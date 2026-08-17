"""
MUMO Agent — Interaction Analyst
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

WHAT THIS AGENT DOES (plain English)
------------------------------------
AutoDock Vina only tells us HOW STRONG the binding is (the affinity number).
It does NOT tell us WHY. This agent answers the "why":
    - How many total interactions hold the drug in place?
    - How many hydrogen bonds (the strongest, most specific 'handshakes')?
    - WHICH protein residues form those H-bonds?
    - How many hydrophobic contacts, pi-stacking, salt bridges, halogen bonds?

It does this with ProLIF (Protein-Ligand Interaction Fingerprints) + RDKit,
all permissive/Apache-2.0 (this replaced the GPL PLIP + OpenBabel path so MUMO
stays patent-safe for commercial use).

HOW IT WORKS
    1. Read the best docked pose (Vina's PDBQT) into an RDKit molecule via meeko
       — correct bond orders, no OpenBabel.
    2. Prepare the receptor: physiological formal charges on ionizable residues
       (so ProLIF's charged-interaction detectors fire) + explicit hydrogens.
    3. Run a ProLIF fingerprint of the ligand against the protein.
    4. Flatten every interaction into one canonical record list (type, residue,
       ligand/protein 3D points, distance) that drives the CSV, 2D diagram and
       3D lines — so all three always agree.
"""

import math
import os
import re

# ── Resilient imports ────────────────────────────────────────────────────────
# Interaction profiling needs RDKit + ProLIF. If either is missing (e.g. a cloud
# build hiccup), MUMO must NOT crash — docking still works, we just skip the
# interaction details. INTERACTIONS_AVAILABLE tells the rest of the app.
INTERACTIONS_AVAILABLE = True
_IMPORT_ERROR = ""
try:
    from rdkit import Chem
    from rdkit.Chem import AllChem  # noqa: F401  (used in the ligand fallback)
    import prolif as plf
except Exception as _e:                      # pragma: no cover
    INTERACTIONS_AVAILABLE = False
    _IMPORT_ERROR = f"{type(_e).__name__}: {_e}"


# One colour per interaction type — used by the 3D lines AND the 2D diagram so
# they always agree.
_COLORS = {
    "H-bond": "blue", "Hydrophobic": "grey", "Pi-stack": "green",
    "Salt bridge": "orange", "Halogen": "cyan", "Pi-cation": "purple",
}

# ProLIF interaction name → MUMO's interaction type.
_PROLIF_MAP = {
    "HBDonor": "H-bond", "HBAcceptor": "H-bond",
    "Hydrophobic": "Hydrophobic",
    "PiStacking": "Pi-stack", "FaceToFace": "Pi-stack", "EdgeToFace": "Pi-stack",
    "Anionic": "Salt bridge", "Cationic": "Salt bridge",
    "CationPi": "Pi-cation", "PiCation": "Pi-cation",
    "XBAcceptor": "Halogen", "XBDonor": "Halogen",
}
_PROLIF_INTERACTIONS = ["Hydrophobic", "HBDonor", "HBAcceptor", "PiStacking",
                        "Anionic", "Cationic", "CationPi", "PiCation",
                        "XBAcceptor", "XBDonor"]

# Physiological formal charges (pH ~7.4) for ionizable protein atoms. RDKit reads
# a raw PDB with NO charges, so without this ProLIF's Anionic/Cationic detectors
# never fire (no salt bridges). Lightweight residue-template approach — no heavy
# PDBFixer/OpenMM needed. One oxygen per carboxylate carries the −1 (the other is
# the C=O); one nitrogen per basic group carries the +1.
_RES_CHARGES = {
    ("ASP", "OD2"): -1, ("GLU", "OE2"): -1,     # carboxylate side chains
    ("LYS", "NZ"): 1, ("ARG", "NH2"): 1,        # ammonium / guanidinium
    ("HIP", "NE2"): 1,                          # protonated histidine (if present)
}


def _empty_result(note):
    """A zeroed interaction result so the app keeps working when ProLIF is absent."""
    return {
        "total_interactions": 0, "n_hbonds": 0, "hbond_residues": [],
        "n_hydrophobic": 0, "hydrophobic_residues": [],
        "n_pistacking": 0, "pistacking_residues": [],
        "n_saltbridges": 0, "saltbridge_residues": [],
        "n_halogen": 0, "n_pication": 0, "n_waterbridges": 0,
        "interacting_residues": [], "lines": [], "residue_numbers": [],
        "residues": [],
        "note": note,
        "svg_2d": "",
    }


def _keep_best_conformer(mol):
    """Reduce a multi-pose molecule to its single best pose.

    A docked PDBQT holds EVERY mode Vina found, and meeko faithfully returns
    them as multiple conformers on one molecule. Left alone they all travel
    downstream together: RDKit's PDB writer emits one MODEL per conformer, and
    since the complex builder keeps only ATOM/HETATM lines the MODEL separators
    are stripped — so all six poses land in the complex as one flat atom list
    and the 3D viewer draws them superimposed, bonding between poses. Vina ranks
    its output, so conformer 0 is the best pose; keeping only that is what makes
    the 3D view, the 2D diagram, the metrics and the structure export describe
    the SAME pose.
    """
    if mol is None or mol.GetNumConformers() <= 1:
        return mol
    best = Chem.Conformer(mol.GetConformer(0))
    mol.RemoveAllConformers()
    mol.AddConformer(best, assignId=True)
    return mol


def _ligand_mol_from_pose(ligand_pdbqt, smiles=None):
    """Read the best docked pose (Vina PDBQT) into an RDKit mol with correct bond
    orders — via meeko (permissive), which reconstructs the molecule meeko itself
    wrote during ligand prep. Falls back to reading the raw coordinates and
    assigning bond orders from `smiles`. Returns an RDKit mol (no explicit Hs)
    carrying exactly ONE conformer: the top-ranked pose."""
    try:
        from meeko import PDBQTMolecule, RDKitMolCreate
        pmol = PDBQTMolecule.from_file(ligand_pdbqt, skip_typing=True)
        mols = RDKitMolCreate.from_pdbqt_mol(pmol)
        if mols and mols[0] is not None:
            return _keep_best_conformer(mols[0])
    except Exception:
        pass
    # fallback: raw atoms from the PDBQT text + bond orders from the known SMILES
    try:
        lines = []
        for ln in open(ligand_pdbqt):
            if ln.startswith("MODEL") and lines:
                break
            if ln.startswith(("ATOM", "HETATM")):
                lines.append(ln[:66] + "\n")   # PDB portion only (drop PDBQT columns)
        mol = Chem.MolFromPDBBlock("".join(lines), sanitize=False, removeHs=False)
        if mol is None:
            return None
        if smiles:
            tmpl = Chem.MolFromSmiles(smiles)
            if tmpl is not None:
                mol = AllChem.AssignBondOrdersFromTemplate(tmpl, mol)
        return mol
    except Exception:
        return None


def _ligand_pdb_block(lig_mol, start_serial=1):
    """Heavy-atom PDB lines for the ligand, forced to HETATM residue 'LIG' on
    chain Z so the 2D diagram + 3D viewer treat it as the ligand.

    `start_serial` renumbers the atoms so they can continue after a receptor's
    serials instead of restarting at 1 — see build_complex for why that matters.
    """
    try:
        heavy = Chem.RemoveHs(lig_mol)
    except Exception:
        heavy = lig_mol
    # confId is explicit on purpose: the default (-1) makes RDKit write EVERY
    # conformer as its own MODEL, and the ATOM/HETATM filter below would strip
    # the MODEL separators and silently fuse the poses into one blob. Read the
    # real id of the first conformer rather than assuming it is 0.
    try:
        conf_id = heavy.GetConformer().GetId()
    except Exception:
        conf_id = 0
    fixed = []
    for line in Chem.MolToPDBBlock(heavy, confId=conf_id).splitlines():
        if line.startswith(("ATOM", "HETATM")):
            line = "HETATM" + line[6:]            # force HETATM
            line = line[:6] + f"{start_serial + len(fixed):>5}" + line[11:]  # renumber
            line = line[:17] + "LIG" + line[20:]  # residue name -> LIG
            line = line[:21] + "Z" + line[22:]    # chain -> Z
            fixed.append(line)
    return "\n".join(fixed)


def build_complex(receptor_pdb, lig_mol, out_complex_pdb):
    """Glue protein + best ligand pose into one complex PDB (protein + ligand),
    used by the 2D diagram, the 3D viewer and the structure export.

    The ligand's atom serials continue after the receptor's rather than
    restarting at 1. A PDB serial is the identity a viewer resolves CONECT
    records against, so duplicates are not cosmetic: with the ligand numbered
    1..N over a protein that already owns those serials, every ligand CONECT
    record points at a PROTEIN atom. Discovery Studio then cannot perceive the
    ligand as its own molecule and reports no ligand at all.
    """
    with open(receptor_pdb) as f:
        protein_lines = [ln.rstrip("\n") for ln in f
                         if ln.startswith(("ATOM", "TER"))]
    max_serial = 0
    for ln in protein_lines:
        if ln.startswith("ATOM"):
            try:
                max_serial = max(max_serial, int(ln[6:11]))
            except ValueError:
                pass
    ligand_block = _ligand_pdb_block(lig_mol, start_serial=max_serial + 1)

    with open(out_complex_pdb, "w") as f:
        f.write("\n".join(protein_lines) + "\n")
        f.write("TER\n")
        f.write(ligand_block + "\n")
        f.write("END\n")
    return out_complex_pdb


def _protonate_protein(receptor_pdb):
    """Load the receptor and give ionizable residues their physiological formal
    charges, then add explicit hydrogens — the preparation ProLIF needs to detect
    salt bridges and hydrogen bonds. Returns an RDKit mol (with Hs) or None."""
    mol = Chem.MolFromPDBFile(receptor_pdb, sanitize=True, removeHs=False)
    if mol is None:
        mol = Chem.MolFromPDBFile(receptor_pdb, sanitize=False, removeHs=False)
    if mol is None:
        return None
    for atom in mol.GetAtoms():
        info = atom.GetPDBResidueInfo()
        if not info:
            continue
        resn, name = info.GetResidueName().strip(), info.GetName().strip()
        chg = -1 if name == "OXT" else _RES_CHARGES.get((resn, name))   # OXT = C-terminus
        if chg is not None:
            atom.SetFormalCharge(chg)
            atom.SetNoImplicit(True)
            atom.SetNumExplicitHs(0)
    try:
        Chem.SanitizeMol(mol)
    except Exception:
        pass
    try:
        mol = Chem.AddHs(mol, addCoords=True)
    except Exception:
        pass
    return mol


def _centroid(conf, idxs):
    """Average (x,y,z) of the given atom indices in a conformer, or None."""
    idxs = [int(i) for i in (idxs or []) if i is not None]
    if not idxs:
        return None
    ps = [conf.GetAtomPosition(i) for i in idxs]
    n = len(ps)
    return (sum(p.x for p in ps) / n, sum(p.y for p in ps) / n, sum(p.z for p in ps) / n)


def _collect_interactions(ifp, lig_conf, prot_conf):
    """
    THE single source of truth. Walk every interaction ProLIF found and return one
    flat list of records — each with its type, residue, the ligand-side and
    protein-side 3D points, the measured distance, and a colour. The CSV counts,
    the 2D diagram and the 3D lines are ALL derived from this list, so they can
    never disagree. Interactions whose 3D points can't be resolved are dropped.
    """
    recs = []
    for pair, inters in ifp.items():
        prot_res = pair[1]
        chain = prot_res.chain or "A"
        for iname, metas in inters.items():
            itype = _PROLIF_MAP.get(iname)
            if not itype:
                continue
            for m in metas:
                pidx = m.get("parent_indices") or m.get("indices") or {}
                lig_xyz = _centroid(lig_conf, pidx.get("ligand"))
                prot_xyz = _centroid(prot_conf, pidx.get("protein"))
                if lig_xyz is None or prot_xyz is None:
                    continue
                recs.append({
                    "type": itype, "restype": prot_res.name, "resnr": int(prot_res.number),
                    "reschain": chain, "tag": f"{prot_res.name}{prot_res.number}({chain})",
                    "lig_xyz": lig_xyz, "prot_xyz": prot_xyz,
                    "distance": float(m.get("distance", 0) or 0), "color": _COLORS[itype],
                })
    return recs


def _polar_protein_atoms(prot_mol, conf):
    """Every N/O in the protein, with the residue identity needed to report it.

    Precomputed once per receptor because a batch of ligands re-uses it.
    """
    out = []
    for atom in prot_mol.GetAtoms():
        if atom.GetSymbol() not in ("N", "O"):
            continue
        info = atom.GetPDBResidueInfo()
        if not info:
            continue
        resn = info.GetResidueName().strip()
        if resn in ("HOH", "WAT", "DOD"):
            continue
        p = conf.GetAtomPosition(atom.GetIdx())
        out.append({"resn": resn, "resi": int(info.GetResidueNumber()),
                    "chain": (info.GetChainId() or "A").strip() or "A",
                    "name": info.GetName().strip(),
                    "charge": atom.GetFormalCharge(),
                    "xyz": (p.x, p.y, p.z)})
    return out


def _geometric_hbonds(lig_mol, polar_atoms, existing, cutoff=3.5):
    """Hydrogen bonds found by DONOR–ACCEPTOR HEAVY-ATOM distance.

    WHY THIS EXISTS
    ---------------
    ProLIF decides an H-bond using the D–H···A angle, which needs the hydrogen
    to be in the right place. Ours are not: the receptor is protonated with
    RDKit's AddHs, which sets a chemically valid but ARBITRARY torsion for every
    rotatable donor — Ser/Thr/Tyr hydroxyls, Lys ammonium. Their hydrogens end
    up pointing in whatever direction the geometry code chose, so genuine bonds
    fail the angle test and vanish.

    That is not a hypothetical. On a real trypsin pose, aspirin sat with its
    carbonyl oxygen 2.70 Å from Ser195 OG and 2.72 Å from Cys191 O — eleven
    polar pairs inside 3.5 Å — and MUMO reported ZERO hydrogen bonds, while
    Discovery Studio reported several. Discovery Studio was right.

    Optimising those hydrogens properly needs Reduce or PDBFixer/OpenMM, which
    is a heavy dependency this deployment deliberately keeps isolated. The
    standard alternative, and what Discovery Studio effectively does, is the
    heavy-atom criterion: a donor/acceptor pair within ~3.5 Å is a hydrogen
    bond. For a rotatable hydroxyl that is the more honest test anyway, because
    the crystal structure never determined where that hydrogen points.

    Kept conservative: same-sign charged pairs are skipped (two cations close
    together is a clash, not a bond), and anything ProLIF already reported for
    that residue and ligand atom is skipped, so nothing is counted twice.
    """
    conf = lig_mol.GetConformer()
    seen = [(r["resnr"], r["reschain"], r["lig_xyz"]) for r in existing]
    found = []
    for atom in lig_mol.GetAtoms():
        if atom.GetSymbol() not in ("N", "O"):
            continue
        lp = conf.GetAtomPosition(atom.GetIdx())
        lxyz = (lp.x, lp.y, lp.z)
        lchg = atom.GetFormalCharge()
        for pa in polar_atoms:
            px, py, pz = pa["xyz"]
            d = math.sqrt((lxyz[0] - px) ** 2 + (lxyz[1] - py) ** 2 + (lxyz[2] - pz) ** 2)
            if d > cutoff or d < 2.2:          # < 2.2 Å is a clash, not a bond
                continue
            if lchg and pa["charge"] and (lchg > 0) == (pa["charge"] > 0):
                continue                        # like charges: not a hydrogen bond
            dup = False
            for resnr, chain, xyz in seen:
                if resnr == pa["resi"] and chain == pa["chain"] and xyz:
                    if ((lxyz[0] - xyz[0]) ** 2 + (lxyz[1] - xyz[1]) ** 2
                            + (lxyz[2] - xyz[2]) ** 2) < 0.36:      # within 0.6 Å
                        dup = True
                        break
            if dup:
                continue
            seen.append((pa["resi"], pa["chain"], lxyz))
            found.append({
                "type": "H-bond", "restype": pa["resn"], "resnr": pa["resi"],
                "reschain": pa["chain"],
                "tag": f'{pa["resn"]}{pa["resi"]}({pa["chain"]})',
                "lig_xyz": lxyz, "prot_xyz": (px, py, pz),
                "distance": float(d), "color": _COLORS["H-bond"],
            })
    return found


def prepare_receptor_context(receptor_pdb):
    """Protonate + charge the receptor and build the ProLIF fingerprint ONCE, so a
    batch of ligands can reuse it instead of re-preparing the whole protein for
    every ligand. This is the main multi-ligand speed + memory win (re-protonating
    a full protein per ligand was the bottleneck, and its failures under batch load
    left ligands with no interaction data → missing 2D/3D and an incomplete zip).
    Returns a context dict, or None if unavailable (callers fall back per-ligand)."""
    if not INTERACTIONS_AVAILABLE:
        return None
    try:
        prot_h = _protonate_protein(receptor_pdb)
        if prot_h is None:
            return None
        conf = prot_h.GetConformer()
        return {"prot_plf": plf.Molecule.from_rdkit(prot_h),
                "prot_conf": conf,
                # precomputed once per receptor: the polar atoms the geometric
                # H-bond pass needs, so a batch of ligands doesn't rescan the
                # whole protein each time
                "polar": _polar_protein_atoms(prot_h, conf),
                "fp": plf.Fingerprint(_PROLIF_INTERACTIONS)}
    except Exception:
        return None


def analyze_interactions(receptor_pdb, ligand_pdbqt, out_complex_pdb, ligand_smiles=None,
                         receptor_ctx=None):
    """
    Full analysis. Returns a dictionary of interaction details for the docked pose.
    Never raises — if ProLIF is unavailable or analysis fails, returns zeros so the
    rest of MUMO (docking, scores, 3D view) keeps working.

    `receptor_ctx` (from prepare_receptor_context) lets a multi-ligand run reuse one
    prepared receptor instead of re-protonating the protein for every ligand.
    """
    if not INTERACTIONS_AVAILABLE:
        return _empty_result(f"Interaction profiling unavailable ({_IMPORT_ERROR}).")

    try:
        return _run_prolif(receptor_pdb, ligand_pdbqt, out_complex_pdb, ligand_smiles, receptor_ctx)
    except Exception as e:
        return _empty_result(f"Interaction analysis skipped: {e}")


def _run_prolif(receptor_pdb, ligand_pdbqt, out_complex_pdb, ligand_smiles=None, receptor_ctx=None):
    lig_mol = _ligand_mol_from_pose(ligand_pdbqt, ligand_smiles)
    if lig_mol is None:
        raise RuntimeError("Could not read the docked ligand pose.")

    # write the complex (heavy-atom ligand) that the 2D diagram + 3D viewer read
    build_complex(receptor_pdb, lig_mol, out_complex_pdb)

    # ProLIF needs explicit Hs on the ligand. Heavy-atom coords are unchanged by
    # AddHs, so the coordinates in `recs` stay consistent with the complex PDB above.
    lig_h = Chem.AddHs(lig_mol, addCoords=True)

    # Reuse the prepared receptor (protonated protein + fingerprint) if given —
    # otherwise prepare it just for this ligand (single-ligand path).
    ctx = receptor_ctx or prepare_receptor_context(receptor_pdb)
    if ctx is None:
        raise RuntimeError("Could not prepare the receptor for interaction analysis.")
    prot_plf, prot_conf, fp = ctx["prot_plf"], ctx["prot_conf"], ctx["fp"]

    lig_plf = plf.Molecule.from_rdkit(lig_h)
    ifp = fp.generate(lig_plf, prot_plf, metadata=True)

    # ── everything below derives from ONE canonical list, so CSV == 2D == 3D ──
    recs = _collect_interactions(ifp, lig_h.GetConformer(), prot_conf)
    # Supplement ProLIF's angle-based H-bonds with the heavy-atom criterion —
    # see _geometric_hbonds for why the angle test under-reports here.
    if ctx.get("polar"):
        recs = recs + _geometric_hbonds(lig_h, ctx["polar"], recs)

    def _by(t):
        return [r for r in recs if r["type"] == t]

    def _tags(rs):
        seen = []
        for r in rs:
            if r["tag"] not in seen:
                seen.append(r["tag"])
        return seen

    hb, hy, pi = _by("H-bond"), _by("Hydrophobic"), _by("Pi-stack")
    sb, hal, pc = _by("Salt bridge"), _by("Halogen"), _by("Pi-cation")

    lines = [{"type": r["type"], "p1": r["lig_xyz"], "p2": r["prot_xyz"],
              "color": r["color"],
              "label": (f'{r["tag"]} · {r["distance"]:.2f} Å'
                        if r["distance"] else r["tag"])} for r in recs]

    residues, seen_res = [], set()
    for r in recs:
        k = (r["reschain"], r["resnr"])
        if k not in seen_res:
            seen_res.add(k)
            residues.append({"chain": r["reschain"], "resi": r["resnr"]})

    return {
        "total_interactions": len(recs),
        "n_hbonds": len(hb), "hbond_residues": _tags(hb),
        "n_hydrophobic": len(hy), "hydrophobic_residues": _tags(hy),
        "n_pistacking": len(pi), "pistacking_residues": _tags(pi),
        "n_saltbridges": len(sb), "saltbridge_residues": _tags(sb),
        "n_halogen": len(hal), "n_pication": len(pc), "n_waterbridges": 0,
        "interacting_residues": sorted({r["tag"] for r in recs}),
        "lines": lines,                       # 3D dashed lines (with distances)
        "residue_numbers": sorted({r["resnr"] for r in recs}),
        "residues": residues,                 # chain-aware (fixes wrong-residue highlight)
        "svg_2d": generate_2d_interaction_svg(out_complex_pdb, recs, lig_mol=lig_mol),
    }


def generate_2d_interaction_svg(complex_pdb_path, records, lig_mol=None):
    """
    Build a Discovery-Studio-style 2D ligand-interaction diagram from the SAME
    canonical interaction list used for the CSV and the 3D view, so all three
    always agree. The ligand is drawn in the centre (RDKit); each interacting
    residue is a filled, colour-coded circle with a soft halo glow, linked to the
    ligand atom it touches by a colour-matched line. Pure RDKit + SVG — no deps.

    `lig_mol` (preferred): the RDKit ligand with CORRECT bonds + the pose conformer.
    Using it avoids re-perceiving bonds from the folded 3D pose, which invents
    spurious cross-bonds for big flexible molecules and turns the drawing into an
    unreadable tangle. Falls back to reading the ligand from the complex PDB.
    """
    try:
        import math
        from rdkit import Chem
        from rdkit.Chem import rdDepictor
        from rdkit.Chem.Draw import rdMolDraw2D

        # Discovery-Studio-like palette per interaction: line / circle-fill / glow
        STYLE = {
            "H-bond":      {"line": "#2e8b3d", "fill": "#8fd39a", "glow": "#43ad5b"},
            "Hydrophobic": {"line": "#c665a6", "fill": "#f1b9dc", "glow": "#e07bb5"},
            "Pi-stack":    {"line": "#7a5cc0", "fill": "#c6b4ea", "glow": "#9070cc"},
            "Pi-cation":   {"line": "#d5811f", "fill": "#f6cf97", "glow": "#e8971f"},
            "Salt bridge": {"line": "#cf4a2e", "fill": "#f4ab99", "glow": "#e0593a"},
            "Halogen":     {"line": "#1f93a6", "fill": "#a3dde5", "glow": "#33b5c4"},
        }
        # soft atom-highlight tints on the ligand (0-1 RGB), matched to interaction
        HL_RGB = {
            "H-bond": (0.72, 0.90, 0.75), "Hydrophobic": (0.95, 0.80, 0.90),
            "Pi-stack": (0.85, 0.80, 0.95), "Pi-cation": (0.97, 0.88, 0.70),
            "Salt bridge": (0.96, 0.78, 0.72), "Halogen": (0.72, 0.89, 0.93),
        }

        # ── get the ligand: prefer the correct-bond mol; else read from the complex ──
        mol = None
        if lig_mol is not None:
            try:
                mol = Chem.RemoveHs(lig_mol)          # heavy atoms, correct connectivity
            except Exception:
                mol = lig_mol
        if mol is None:
            lig_lines = [ln for ln in open(complex_pdb_path)
                         if "LIG" in ln and ln.startswith(("HETATM", "ATOM"))]
            if not lig_lines:
                return ""
            mol = Chem.MolFromPDBBlock("".join(lig_lines), sanitize=False)
        if mol is None or mol.GetNumConformers() == 0:
            return ""

        # Match each interaction's ligand-side point to the nearest RDKit atom by 3D
        # coordinate (read BEFORE Compute2DCoords overwrites the conformer).
        conf = mol.GetConformer()
        rd_pos = [conf.GetAtomPosition(i) for i in range(mol.GetNumAtoms())]

        def _nearest(xyz):
            if xyz is None:
                return None
            bi, best = None, 1e18
            for i, p in enumerate(rd_pos):
                d = (p.x - xyz[0]) ** 2 + (p.y - xyz[1]) ** 2 + (p.z - xyz[2]) ** 2
                if d < best:
                    best, bi = d, i
            return bi

        # ── collect interactions FROM THE CANONICAL LIST: (idx, res…, itype) ──
        interactions, highlight_atoms, atom_colors = [], [], {}
        for r in records:
            idx = _nearest(r.get("lig_xyz"))
            if idx is None or r["type"] not in STYLE:
                continue
            atom_colors[idx] = HL_RGB[r["type"]]
            if idx not in highlight_atoms:
                highlight_atoms.append(idx)
            interactions.append((idx, r["restype"], int(r["resnr"]), r["reschain"], r["type"]))

        # ── draw the ligand, shrunk to leave room for the residue ring ──
        rdDepictor.Compute2DCoords(mol)
        # scale the canvas up for large ligands so a big molecule stays legible
        # instead of being crushed into the centre (1x for typical drugs, up to ~1.8x)
        _n = mol.GetNumAtoms()
        _s = min(1.8, max(1.0, (_n / 28.0) ** 0.5))
        W, H = int(800 * _s), int(720 * _s)
        drawer = rdMolDraw2D.MolDraw2DSVG(W, H)
        opts = drawer.drawOptions()
        opts.setBackgroundColour((1, 1, 1, 1))
        # Leave room for the residue ring, but not so much that the structure
        # itself becomes a small mark in the middle of the page — the canvas is
        # cropped to the real content at the end anyway.
        opts.padding = 0.22
        opts.bondLineWidth = 2
        drawer.DrawMolecule(mol, highlightAtoms=highlight_atoms,
                            highlightAtomColors=atom_colors)
        drawer.FinishDrawing()
        svg = drawer.GetDrawingText()

        if not interactions:
            return svg

        coords = [drawer.GetDrawCoords(i) for i in range(mol.GetNumAtoms())]

        # A residue often makes MORE THAN ONE kind of contact — Trp215 can stack
        # with a ring and also touch it hydrophobically; Asp189 can both salt-
        # bridge and H-bond. The old drawing kept whichever came first and
        # silently discarded the rest, so the figure disagreed with the
        # interaction table printed beside it. Every type is kept now: the disc
        # takes the strongest, the others appear as small dots beneath it.
        PRIORITY = ["Salt bridge", "H-bond", "Pi-cation", "Pi-stack",
                    "Halogen", "Hydrophobic"]
        res_types, res_atom, order = {}, {}, []
        for idx, restype, resnr, reschain, itype in interactions:
            key = (restype, resnr, reschain)
            if key not in res_types:
                res_types[key], res_atom[key] = [], idx
                order.append(key)
            if itype not in res_types[key]:
                res_types[key].append(itype)

        DISC_R = 26.0
        cx, cy = W / 2.0, H / 2.0
        # Put the ring OUTSIDE the drawn structure instead of at a fixed fraction
        # of the canvas: at a fixed radius, a large ligand had residue discs
        # landing on top of its own atoms.
        reach = max((math.hypot(p.x - cx, p.y - cy) for p in coords), default=0.0)
        # Deliberately NOT clamped to the RDKit canvas. Clamping is what made
        # discs land on top of the structure: the ring was forced inward to stay
        # on a page that gets cropped away at the end anyway. The crop below is
        # computed FROM these positions, so the ring defines the page rather
        # than the page constraining the ring.
        # The +60 is clearance for RDKit's ATOM LABELS: `reach` measures atom
        # CENTRES, but a drawn "NH2" or "OH" extends well past its centre, so a
        # ring sized to the centres lands discs on top of the lettering.
        R = max(min(W, H) * 0.30, reach + DISC_R + 60)

        # place each residue in the DIRECTION of the atom it touches (natural,
        # Discovery-Studio-like), then relax any that sit too close together
        placed = []
        for key in order:
            ap = coords[res_atom[key]]
            placed.append([key, res_atom[key], math.atan2(ap.y - cy, ap.x - cx)])
        placed.sort(key=lambda z: z[2])
        n = len(placed)
        # neighbouring discs must not touch; the angle needed shrinks as R grows.
        # 2.8x rather than 2x the disc radius because the "A:189" line under a
        # label is wider than the disc itself.
        min_gap = min(2 * math.pi / max(n, 1), 2.8 * DISC_R / max(R, 1.0))
        for _ in range(160):                                 # nudge neighbours apart
            for i in range(n):
                if n < 2:
                    break
                gap = (placed[(i + 1) % n][2] - placed[i][2]) % (2 * math.pi)
                # `gap < min_gap`, NOT `0 < gap < min_gap`. Two residues that
                # contact the SAME ligand atom get the SAME angle, so their gap
                # is exactly 0 — and the old strict `0 <` skipped precisely that
                # case, leaving the two discs stacked on top of each other with
                # their labels overprinted. A real docking hit this immediately
                # (Asp189 and Gly219 both bind the amidine nitrogen); the
                # synthetic test never did, because it gave every residue its
                # own atom.
                if gap < min_gap:
                    push = (min_gap - gap) / 2.0
                    placed[i][2] -= push
                    placed[(i + 1) % n][2] += push

        def _solid(t):
            """Solid = directional polar contact, dashed = everything else —
            the convention these diagrams are read with."""
            return t in ("H-bond", "Salt bridge")

        circles, lines, labels, dots, disc_xy = [], [], [], [], []
        for key, idx, ang in placed:
            restype, resnr, reschain = key
            types = sorted(res_types[key],
                           key=lambda t: PRIORITY.index(t) if t in PRIORITY else 99)
            primary = types[0]
            s = STYLE[primary]
            ap = coords[idx]
            rx, ry = cx + R * math.cos(ang), cy + R * math.sin(ang)
            disc_xy.append((rx, ry))

            # stop the connector at the disc EDGE: a line running under a filled
            # circle and out the far side reads as a drawing mistake
            dx, dy = rx - ap.x, ry - ap.y
            dist = math.hypot(dx, dy) or 1.0
            ex, ey = rx - dx / dist * DISC_R, ry - dy / dist * DISC_R
            dash = '' if _solid(primary) else ' stroke-dasharray="6,4"'
            lines.append(
                f'<line x1="{ap.x:.1f}" y1="{ap.y:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" '
                f'stroke="{s["line"]}" stroke-width="1.8"{dash} opacity="0.85"/>')
            # A flat disc with a crisp ring. The soft radial "glow" halo this
            # replaces is the single thing that made the old figure read as a
            # slide graphic rather than something from a paper.
            circles.append(
                f'<circle cx="{rx:.1f}" cy="{ry:.1f}" r="{DISC_R}" fill="{s["fill"]}" '
                f'stroke="{s["line"]}" stroke-width="1.8"/>')
            labels.append(
                f'<text x="{rx:.1f}" y="{ry - 1:.1f}" text-anchor="middle" '
                f'font-family="Helvetica, Arial, sans-serif" font-size="13" '
                f'font-weight="700" fill="#16202b">{restype}</text>'
                f'<text x="{rx:.1f}" y="{ry + 12:.1f}" text-anchor="middle" '
                f'font-family="Helvetica, Arial, sans-serif" font-size="10.5" '
                f'fill="#44515f">{reschain}:{resnr}</text>')
            for j, extra in enumerate(types[1:]):
                ox = rx - (len(types) - 2) * 4.5 + j * 9.0
                dots.append(f'<circle cx="{ox:.1f}" cy="{ry + DISC_R - 4.5:.1f}" r="3.2" '
                            f'fill="{STYLE[extra]["line"]}" stroke="#ffffff" '
                            f'stroke-width="1"/>')

        # ── crop to what was actually drawn ──
        # The RDKit canvas is sized for the worst case, so the ring of residues
        # leaves a wide band of empty white — which in a report reads as a
        # broken image rather than as spacing. Measure the real extent of the
        # structure plus the discs and trim the page to it.
        MARGIN = 22.0
        xs = [p.x for p in coords] + [rx for rx, _ in disc_xy]
        ys = [p.y for p in coords] + [ry for _, ry in disc_xy]
        left = min(xs) - DISC_R - 4
        right = max(xs) + DISC_R + 4
        top = min(ys) - DISC_R - 6
        bot = max(ys) + DISC_R + 16          # +16 clears the chain:number line
        outW = (right - left) + 2 * MARGIN
        bodyH = (bot - top) + 2 * MARGIN
        dx, dy = MARGIN - left, MARGIN - top

        # ── legend ── only the types actually present, so nothing is unexplained.
        # Without this the reader cannot tell what green versus pink means, which
        # is the difference between a figure and a decoration.
        present = [t for t in PRIORITY if any(t in v for v in res_types.values())]
        LEG_H = 56 if present else 0
        leg = []
        if present:
            leg.append(f'<line x1="26" y1="{bodyH:.0f}" x2="{outW - 26:.0f}" '
                       f'y2="{bodyH:.0f}" stroke="#dde2e8" stroke-width="1"/>')
            step = (outW - 60) / max(len(present), 1)
            for i, t in enumerate(present):
                s = STYLE[t]
                lx, ly = 34 + i * step, bodyH + 26
                leg.append(f'<line x1="{lx:.0f}" y1="{ly:.0f}" x2="{lx + 20:.0f}" '
                           f'y2="{ly:.0f}" stroke="{s["line"]}" stroke-width="2.2"'
                           + ('' if _solid(t) else ' stroke-dasharray="5,3"') + '/>')
                leg.append(f'<circle cx="{lx + 30:.0f}" cy="{ly:.0f}" r="6.5" '
                           f'fill="{s["fill"]}" stroke="{s["line"]}" stroke-width="1.6"/>')
                leg.append(f'<text x="{lx + 42:.0f}" y="{ly + 4:.0f}" '
                           f'font-family="Helvetica, Arial, sans-serif" font-size="12" '
                           f'fill="#2b3642">{t}</text>')

        newH = bodyH + LEG_H
        # The molecule and the ring are shifted together so their coordinates stay
        # consistent with each other; the legend is placed in the trimmed page's
        # own coordinates, outside that group.
        body = ("".join(lines) + "".join(circles) + "".join(labels) + "".join(dots))
        svg = re.sub(r"(<svg[^>]*?)width='[\d.]+(px)?'", rf"\1width='{outW:.0f}px'", svg, count=1)
        svg = re.sub(r'(<svg[^>]*?)width="[\d.]+(px)?"', rf'\1width="{outW:.0f}px"', svg, count=1)
        svg = re.sub(r"(<svg[^>]*?)height='[\d.]+(px)?'", rf"\1height='{newH:.0f}px'", svg, count=1)
        svg = re.sub(r'(<svg[^>]*?)height="[\d.]+(px)?"', rf'\1height="{newH:.0f}px"', svg, count=1)
        svg = re.sub(r"viewBox='0 0 [\d.]+ [\d.]+'",
                     f"viewBox='0 0 {outW:.0f} {newH:.0f}'", svg, count=1)
        svg = re.sub(r'viewBox="0 0 [\d.]+ [\d.]+"',
                     f'viewBox="0 0 {outW:.0f} {newH:.0f}"', svg, count=1)
        # open a translate group right after the <svg ...> tag
        m = re.search(r"<svg[^>]*>", svg)
        svg = (svg[:m.end()] + f'<g transform="translate({dx:.1f},{dy:.1f})">'
               + svg[m.end():])
        return svg.replace("</svg>", body + "</g>" + "".join(leg) + "</svg>")
    except Exception as e:
        print(f"Error generating 2D SVG: {e}")
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# DEMO — analyse the CFTR complex we already docked earlier
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    DATA = os.path.join(PROJECT, "data")
    receptor = os.path.join(DATA, "chain_cleaned.pdb")
    ligand   = os.path.join(DATA, "chain_out.pdbqt")
    complexf = os.path.join(DATA, "chain_complex.pdb")

    print("=" * 60)
    print("MUMO INTERACTION ANALYST — CFTR docked complex")
    print("=" * 60)
    res = analyze_interactions(receptor, ligand, complexf)
    print(f"Total interactions : {res['total_interactions']}")
    print(f"Hydrogen bonds     : {res['n_hbonds']}  -> {res['hbond_residues']}")
    print(f"Hydrophobic        : {res['n_hydrophobic']} -> {res['hydrophobic_residues']}")
    print(f"Pi-stacking        : {res['n_pistacking']} -> {res['pistacking_residues']}")
    print(f"Salt bridges       : {res['n_saltbridges']} -> {res['saltbridge_residues']}")
    print(f"Halogen bonds      : {res['n_halogen']}")
    print(f"Water bridges      : {res['n_waterbridges']}")
    print(f"All residues       : {res['interacting_residues']}")
