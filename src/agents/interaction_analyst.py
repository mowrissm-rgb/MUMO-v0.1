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

It does this with PLIP (Protein-Ligand Interaction Profiler) — the tool used in
published papers — by analysing the docked 3D pose against the protein.

HOW IT WORKS
    1. Take the best docked pose (from Vina's output) + the protein structure
    2. Glue them into one "complex" PDB file (protein + ligand together)
    3. Run PLIP on that complex
    4. Summarise every interaction into a clean dictionary
"""

import os

# ── Resilient imports ────────────────────────────────────────────────────────
# Interaction profiling needs OpenBabel + PLIP. If either is missing (e.g. a
# cloud build hiccup), MUMO must NOT crash — docking still works, we just skip
# the interaction details. INTERACTIONS_AVAILABLE tells the rest of the app.
INTERACTIONS_AVAILABLE = True
_IMPORT_ERROR = ""
try:
    import openbabel.pybel as pybel

    # Compatibility shim: some OpenBabel builds lack InChI, but PLIP asks for an
    # 'inchikey' (just a label). RDKit has InChI, so we redirect those calls.
    _orig_write = pybel.Molecule.write
    def _write_with_rdkit_inchi(self, format="smi", filename=None, *args, **kwargs):
        if format in ("inchikey", "inchi") and filename is None:
            try:
                from rdkit import Chem
                molblock = _orig_write(self, "mol")
                m = Chem.MolFromMolBlock(molblock, sanitize=False)
                if m is not None:
                    return Chem.MolToInchiKey(m) if format == "inchikey" else Chem.MolToInchi(m)
            except Exception:
                pass
            return "NOINCHIKEY"
        return _orig_write(self, format, filename, *args, **kwargs)
    pybel.Molecule.write = _write_with_rdkit_inchi

    from plip.structure.preparation import PDBComplex
except Exception as _e:                      # pragma: no cover
    INTERACTIONS_AVAILABLE = False
    _IMPORT_ERROR = f"{type(_e).__name__}: {_e}"


def _empty_result(note):
    """A zeroed interaction result so the app keeps working when PLIP is absent."""
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


def _ligand_pose_to_pdb_block(ligand_pdbqt):
    """
    Take the FIRST (best) pose from Vina's output .pdbqt and turn it into PDB
    lines, marked as HETATM residue 'LIG' on chain Z so PLIP treats it as the
    ligand (not part of the protein).
    """
    mol = next(pybel.readfile("pdbqt", ligand_pdbqt))   # first pose = best pose
    pdb_text = mol.write("pdb")

    fixed = []
    for line in pdb_text.splitlines():
        if line.startswith(("ATOM", "HETATM")):
            line = "HETATM" + line[6:]            # force HETATM
            line = line[:17] + "LIG" + line[20:]  # residue name -> LIG
            line = line[:21] + "Z" + line[22:]    # chain -> Z
            fixed.append(line)
    return "\n".join(fixed)


def build_complex(receptor_pdb, ligand_pdbqt, out_complex_pdb):
    """Glue protein + best ligand pose into one complex PDB file for PLIP."""
    with open(receptor_pdb) as f:
        protein_lines = [ln.rstrip("\n") for ln in f
                         if ln.startswith(("ATOM", "TER"))]
    ligand_block = _ligand_pose_to_pdb_block(ligand_pdbqt)

    with open(out_complex_pdb, "w") as f:
        f.write("\n".join(protein_lines) + "\n")
        f.write("TER\n")
        f.write(ligand_block + "\n")
        f.write("END\n")
    return out_complex_pdb


def _residue_tag(i):
    """Make a readable residue label like 'ASP110(A)' from a PLIP interaction."""
    return f"{i.restype}{i.resnr}({i.reschain})"


# One colour per interaction type — used by the 3D lines AND the 2D diagram so
# they always agree.
_COLORS = {
    "H-bond": "blue", "Hydrophobic": "grey", "Pi-stack": "green",
    "Salt bridge": "orange", "Halogen": "cyan", "Pi-cation": "purple",
}


def _pt(obj):
    """Best-effort (x,y,z) for a pybel atom (.coords), a ring/charge centre
    (.center), or a halogen sub-atom (.x/.o). Returns None if nothing usable."""
    if obj is None:
        return None
    if hasattr(obj, "coords"):
        try:
            return tuple(obj.coords)
        except Exception:
            pass
    if hasattr(obj, "center"):
        try:
            return tuple(obj.center)
        except Exception:
            pass
    for sub in ("x", "o"):
        s = getattr(obj, sub, None)
        if s is not None and hasattr(s, "coords"):
            try:
                return tuple(s.coords)
            except Exception:
                pass
    return None


def _collect_interactions(site):
    """
    THE single source of truth. Walk every interaction PLIP found for this binding
    site and return one flat list of records — each with its type, residue, the
    ligand-side and protein-side 3D points, the measured distance, and a colour.
    The CSV counts, the 2D diagram and the 3D lines are ALL derived from this list,
    so they can never disagree. Interactions whose 3D points can't be resolved are
    dropped (so a counted interaction is always a drawable one).
    """
    recs = []

    def add(itype, obj, lig, prot, dist):
        lp, pp = _pt(lig), _pt(prot)
        if lp is None or pp is None:
            return
        recs.append({
            "type": itype, "restype": obj.restype, "resnr": int(obj.resnr),
            "reschain": obj.reschain, "tag": f"{obj.restype}{obj.resnr}({obj.reschain})",
            "lig_xyz": lp, "prot_xyz": pp,
            "distance": float(dist) if dist else 0.0, "color": _COLORS[itype],
        })

    for b in list(site.hbonds_ldon) + list(site.hbonds_pdon):
        lig, prot = (b.a, b.d) if b.protisdon else (b.d, b.a)   # ligand = acceptor if protein donates
        add("H-bond", b, lig, prot, getattr(b, "distance_ad", getattr(b, "distance", 0)))
    for c in site.hydrophobic_contacts:
        add("Hydrophobic", c, c.ligatom, c.bsatom, getattr(c, "distance", 0))
    for p in site.pistacking:
        add("Pi-stack", p, p.ligandring, p.proteinring, getattr(p, "distance", 0))
    for s in list(site.saltbridge_lneg) + list(site.saltbridge_pneg):
        lig, prot = (s.negative, s.positive) if s.protispos else (s.positive, s.negative)
        add("Salt bridge", s, lig, prot, getattr(s, "distance", 0))
    for x in site.halogen_bonds:
        add("Halogen", x, getattr(x, "don", None), getattr(x, "acc", None), getattr(x, "distance", 0))
    for p in site.pication_laro:                                # ligand provides the ring
        add("Pi-cation", p, getattr(p, "ring", None), getattr(p, "charge", None), getattr(p, "distance", 0))
    for p in site.pication_paro:                                # ligand provides the charge
        add("Pi-cation", p, getattr(p, "charge", None), getattr(p, "ring", None), getattr(p, "distance", 0))
    return recs


def analyze_interactions(receptor_pdb, ligand_pdbqt, out_complex_pdb):
    """
    Full analysis. Returns a dictionary of interaction details for the docked pose.
    Never raises — if PLIP is unavailable or analysis fails, returns zeros so the
    rest of MUMO (docking, scores, 3D view) keeps working.
    """
    if not INTERACTIONS_AVAILABLE:
        return _empty_result(f"Interaction profiling unavailable ({_IMPORT_ERROR}).")

    try:
        return _run_plip(receptor_pdb, ligand_pdbqt, out_complex_pdb)
    except Exception as e:
        return _empty_result(f"Interaction analysis skipped: {e}")


def _run_plip(receptor_pdb, ligand_pdbqt, out_complex_pdb):
    build_complex(receptor_pdb, ligand_pdbqt, out_complex_pdb)

    complex_mol = PDBComplex()
    complex_mol.load_pdb(out_complex_pdb)
    complex_mol.analyze()

    if not complex_mol.interaction_sets:
        raise RuntimeError("PLIP found no ligand binding site in the complex.")

    # Pick the binding site with the most interactions (our docked ligand).
    def total(site):
        return (len(site.hbonds_ldon) + len(site.hbonds_pdon) +
                len(site.hydrophobic_contacts) + len(site.pistacking) +
                len(site.saltbridge_lneg) + len(site.saltbridge_pneg) +
                len(site.halogen_bonds) + len(site.pication_laro) +
                len(site.pication_paro))

    site = max(complex_mol.interaction_sets.values(), key=total)

    # ── everything below derives from ONE canonical list, so CSV == 2D == 3D ──
    recs = _collect_interactions(site)

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
        "svg_2d": generate_2d_interaction_svg(out_complex_pdb, recs),
    }


def generate_2d_interaction_svg(complex_pdb_path, records):
    """
    Build a professional 2D ligand-interaction diagram (Maestro / LigPlot style)
    from the SAME canonical interaction list used for the CSV and the 3D view, so
    all three always agree. The ligand is drawn in the centre and every interacting
    residue is a labelled bubble linked by a colour-coded dashed line to the ligand
    atom it touches. Pure RDKit — no extra deps.
    """
    try:
        import math
        from rdkit import Chem
        from rdkit.Chem import rdDepictor
        from rdkit.Chem.Draw import rdMolDraw2D

        COLORS_RGB = {
            "H-bond": (0.15, 0.39, 0.92), "Hydrophobic": (0.42, 0.45, 0.50),
            "Halogen": (0.05, 0.58, 0.53), "Salt bridge": (0.92, 0.35, 0.05),
            "Pi-stack": (0.09, 0.64, 0.29), "Pi-cation": (0.58, 0.20, 0.83),
        }
        COLORS_HEX = {
            "H-bond": "#2563eb", "Hydrophobic": "#6b7280", "Halogen": "#0d9488",
            "Salt bridge": "#ea580c", "Pi-stack": "#16a34a", "Pi-cation": "#9333ea",
        }

        # ── read the ligand (chain Z / resname LIG) out of the complex ──
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
            if idx is None:
                continue
            atom_colors[idx] = COLORS_RGB[r["type"]]
            if idx not in highlight_atoms:
                highlight_atoms.append(idx)
            interactions.append((idx, r["restype"], int(r["resnr"]), r["reschain"], r["type"]))

        # ── draw the ligand, leaving a wide margin for the residue bubbles ──
        rdDepictor.Compute2DCoords(mol)
        W, H = 760, 640
        drawer = rdMolDraw2D.MolDraw2DSVG(W, H)
        opts = drawer.drawOptions()
        opts.setBackgroundColour((1, 1, 1, 1))
        opts.padding = 0.33                      # shrink molecule → room for bubbles
        drawer.DrawMolecule(mol, highlightAtoms=highlight_atoms,
                            highlightAtomColors=atom_colors)
        drawer.FinishDrawing()
        svg = drawer.GetDrawingText()

        if not interactions:
            return svg

        coords = [drawer.GetDrawCoords(i) for i in range(mol.GetNumAtoms())]

        # one bubble per residue (keep its first interaction)
        seen, order = {}, []
        for idx, restype, resnr, reschain, itype in interactions:
            key = (restype, resnr, reschain)
            if key not in seen:
                seen[key] = (idx, itype)
                order.append(key)

        cx, cy, R = W / 2.0, H / 2.0, min(W, H) * 0.40
        # order residues by their atom's angle, then space evenly (avoids overlap)
        order.sort(key=lambda k: math.atan2(coords[seen[k][0]].y - cy,
                                            coords[seen[k][0]].x - cx))
        extra, n = [], max(len(order), 1)
        for i, key in enumerate(order):
            restype, resnr, reschain = key
            idx, itype = seen[key]
            hexc, ap = COLORS_HEX[itype], coords[idx]
            theta = 2 * math.pi * i / n - math.pi / 2
            nx, ny = cx + R * math.cos(theta), cy + R * math.sin(theta)
            extra.append(
                f'<line x1="{ap.x:.1f}" y1="{ap.y:.1f}" x2="{nx:.1f}" y2="{ny:.1f}" '
                f'stroke="{hexc}" stroke-width="1.7" stroke-dasharray="5,4" opacity="0.85"/>')
            extra.append(
                f'<ellipse cx="{nx:.1f}" cy="{ny:.1f}" rx="41" ry="22" '
                f'fill="#ffffff" stroke="{hexc}" stroke-width="2.2"/>')
            extra.append(
                f'<text x="{nx:.1f}" y="{ny - 3:.1f}" text-anchor="middle" '
                f'font-family="sans-serif" font-size="13" font-weight="700" '
                f'fill="#1f2937">{restype} {resnr}</text>')
            extra.append(
                f'<text x="{nx:.1f}" y="{ny + 12:.1f}" text-anchor="middle" '
                f'font-family="sans-serif" font-size="9" fill="{hexc}">{itype} &#183; {reschain}</text>')
        return svg.replace("</svg>", "\n".join(extra) + "\n</svg>")
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
