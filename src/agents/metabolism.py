"""
MUMO — Metabolism agent (phase I / phase II biotransformation prediction)
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

WHY THIS IS OUR OWN IMPLEMENTATION
----------------------------------
The obvious library here is SyGMa, and it is a good one — but it is licensed
GPL-3.0, which is copyleft. MUMO deliberately carries no copyleft dependency
(OpenBabel and PLIP were removed for exactly this reason), so linking it is not
an option on a commercial track.

What SyGMa implements, however, is not SyGMa's invention: the rules come from
Ridder & Wagener, "SyGMa: Combining Expert Knowledge and Empirical Scoring in
the Prediction of Metabolites", ChemMedChem 2008, 3(5):821-32. Published
reaction rules are science, not software — SyGMa's own README describes itself
as "a reimplementation of the metabolic rules outlined in" that paper. This
module does the same thing from the same literature, in our own code, on RDKit
(BSD). The science is cited; no code is borrowed.

HOW IT WORKS
------------
Each biotransformation is an RDKit reaction SMARTS plus an empirical
probability — roughly how often that transformation is actually observed for a
matching substructure. Rules are applied to the parent, then to the products,
up to `depth` generations, so a phase I oxidation can be followed by a phase II
conjugation the way real metabolism proceeds.

Every metabolite carries the PATH that produced it, because for a pharmacy
student the interesting output is not a list of structures — it is "this ester
is hydrolysed, and the resulting alcohol is then glucuronidated".

Scores multiply along a path and are relative, not absolute: they rank which
metabolites are most likely, they are NOT a quantitative prediction of how much
of each is formed. Anything here is a hypothesis to test, never a measurement.
"""

# ── phase I: functionalisation ────────────────────────────────────────────
# (name, SMARTS, probability, note). Probabilities follow the published
# occurrence ratios in Ridder & Wagener 2008; they are relative weights used
# for ranking, not measured yields.
PHASE_I = [
    ("Aromatic hydroxylation",
     "[cH:1]>>[c:1][OX2H]", 0.30,
     "A CYP enzyme adds -OH to an aromatic ring, the commonest phase I step."),
    ("Aliphatic hydroxylation",
     "[CX4H2:1]>>[CX4H1:1][OX2H]", 0.22,
     "Oxidation of a saturated carbon to an alcohol."),
    ("N-dealkylation",
     "[NX3:1]-[CH3]>>[NX3H:1]", 0.28,
     "A methyl group is removed from nitrogen, releasing formaldehyde."),
    ("O-demethylation",
     "[c,C:1]-[OX2]-[CH3]>>[c,C:1]-[OX2H]", 0.26,
     "A methyl ether is cleaved to the free phenol or alcohol."),
    ("S-oxidation",
     "[SX2:1]>>[SX3:1]=O", 0.20,
     "Sulfur is oxidised to a sulfoxide."),
    ("N-oxidation",
     "[NX3;H0;!$(N-[!#6]):1]>>[NX4:1]=O", 0.12,
     "A tertiary amine is oxidised to an N-oxide."),
    ("Primary alcohol to aldehyde",
     "[CX4H2:1][OX2H]>>[CX3H1:1]=O", 0.16,
     "Alcohol dehydrogenase oxidises a primary alcohol."),
    ("Aldehyde to carboxylic acid",
     "[CX3H1:1]=O>>[CX3:1](=O)[OX2H]", 0.24,
     "Aldehyde dehydrogenase completes the oxidation to an acid."),
    ("Ester hydrolysis",
     "[CX3:1](=O)[OX2][#6:2]>>[CX3:1](=O)[OX2H].[#6:2][OX2H]", 0.34,
     "An esterase splits the ester into an acid and an alcohol."),
    ("Amide hydrolysis",
     "[CX3:1](=O)[NX3:2]>>[CX3:1](=O)[OX2H].[NX3H:2]", 0.15,
     "An amidase splits the amide into an acid and an amine."),
    # NB: RDKit canonicalises a nitro group to the CHARGE-SEPARATED form
    # ([N+](=O)[O-]), so the neutral pentavalent pattern never matches and the
    # rule silently does nothing. Match what RDKit actually stores.
    ("Nitro reduction",
     "[#6:1][N+](=O)[O-]>>[#6:1][NX3H2]", 0.14,
     "A nitro group is reduced to an amine."),
    ("Epoxidation of alkene",
     "[CX3:1]=[CX3:2]>>[C:1]1[O][C:2]1", 0.10,
     "A double bond becomes an epoxide — often the reactive, toxic step."),
    ("Aromatic ring dihydrodiol",
     "[cH:1][cH:2]>>[C:1]([OX2H])[C:2][OX2H]", 0.05,
     "Ring oxidation to a dihydrodiol, via the epoxide."),
]

# ── phase II: conjugation ─────────────────────────────────────────────────
# These attach a large polar group, which is what actually makes a compound
# excretable. They act on the handles phase I creates.
PHASE_II = [
    ("O-glucuronidation",
     "[OX2H:1]>>[OX2:1]C1OC(C(=O)[OX2H])C(O)C(O)C1O", 0.40,
     "UGT attaches glucuronic acid to a hydroxyl — the main clearance route."),
    ("N-glucuronidation",
     "[NX3H1:1]>>[NX3:1]C1OC(C(=O)[OX2H])C(O)C(O)C1O", 0.18,
     "Glucuronic acid attached to nitrogen instead."),
    ("Sulfation",
     "[OX2H:1]>>[OX2:1]S(=O)(=O)[OX2H]", 0.30,
     "SULT attaches sulfate; competes with glucuronidation, saturates sooner."),
    ("Glycine conjugation",
     "[CX3:1](=O)[OX2H]>>[CX3:1](=O)NCC(=O)[OX2H]", 0.20,
     "A carboxylic acid is conjugated with glycine."),
    ("N-acetylation",
     "[NX3H2:1]>>[NX3:1]C(=O)C", 0.24,
     "NAT acetylates an amine — the step with the fast/slow acetylator polymorphism."),
    ("Methylation",
     "[OX2H:1][c:2]>>[OX2:1]([CH3])[c:2]", 0.12,
     "COMT methylates a phenol, notably on catechols."),
    ("Glutathione conjugation",
     "[C:1]1[O][C:2]1>>[C:1]([OX2H])[C:2]SCC(N)C(=O)O", 0.35,
     "GSH traps a reactive epoxide — the body's detox response."),
]

ALL_RULES = [(n, s, p, note, "I") for n, s, p, note in PHASE_I] + \
            [(n, s, p, note, "II") for n, s, p, note in PHASE_II]

MAX_METABOLITES = 400          # a hard ceiling; combinatorics explode fast
CITATION = ("Rule set adapted from Ridder, L. & Wagener, M. SyGMa: Combining "
            "Expert Knowledge and Empirical Scoring in the Prediction of "
            "Metabolites. ChemMedChem 2008, 3(5), 821-832.")


def _canonical(mol):
    from rdkit import Chem
    try:
        return Chem.MolToSmiles(mol)
    except Exception:
        return None


def _sanitize(mol):
    """Return a clean mol, or None if the transformation produced nonsense.

    Reaction SMARTS routinely emit chemically invalid products; silently
    discarding those is the difference between a useful prediction list and a
    list padded with molecules that cannot exist.
    """
    from rdkit import Chem
    try:
        Chem.SanitizeMol(mol)
        return mol
    except Exception:
        return None


def _apply_rule(mol, smarts):
    """All distinct products of one rule on one molecule."""
    from rdkit import Chem
    from rdkit.Chem import AllChem
    out = []
    try:
        rxn = AllChem.ReactionFromSmarts(smarts)
        if rxn is None:
            return out
        for products in rxn.RunReactants((mol,)):
            for p in products:
                p = _sanitize(p)
                if p is None:
                    continue
                smi = _canonical(p)
                # a rule that "fires" but changes nothing is noise
                if smi and smi != _canonical(mol):
                    out.append((smi, p))
    except Exception:
        pass
    return out


def predict_metabolites(smiles, depth=2, min_score=0.01, max_results=40):
    """Predict the phase I and phase II metabolites of a compound.

    `depth` is how many successive transformations to allow — 2 is the useful
    default, because it covers the real pattern of a phase I step creating the
    handle that a phase II conjugation then uses.

    Returns a dict:
        {"parent": <canonical SMILES>, "n_generated": int,
         "metabolites": [{smiles, name, phase, note, parent, generation,
                          score, pathway}],
         "citation": str}
    or {"_error": "..."} — never raises.
    """
    try:
        from rdkit import Chem, RDLogger
        RDLogger.DisableLog("rdApp.*")   # invalid intermediates are expected
    except Exception as e:
        return {"_error": f"RDKit unavailable: {e}"}

    parent = Chem.MolFromSmiles(str(smiles or "").strip())
    if parent is None:
        return {"_error": "Couldn't read that structure — check the SMILES."}

    parent_smi = _canonical(parent)
    seen = {parent_smi}
    results = {}
    frontier = [(parent_smi, parent, 1.0, [])]

    for generation in range(1, max(1, int(depth)) + 1):
        next_frontier = []
        for smi, mol, score, path in frontier:
            # The ceiling has to be enforced at EVERY loop level. Checking it
            # only between generations lets one generation of a large, heavily
            # substituted molecule blow straight past it — measured at 930
            # against a 400 cap, which is minutes of wasted RDKit work.
            if len(results) >= MAX_METABOLITES:
                break
            for name, smarts, prob, note, phase in ALL_RULES:
                if len(results) >= MAX_METABOLITES:
                    break
                for prod_smi, prod_mol in _apply_rule(mol, smarts):
                    new_score = score * prob
                    if new_score < min_score:
                        continue
                    step = f"{name} (phase {phase})"
                    if prod_smi in seen:
                        # same metabolite by a different route — keep the more
                        # likely explanation rather than the first one found
                        prev = results.get(prod_smi)
                        if prev and new_score > prev["score"]:
                            prev.update(score=round(new_score, 4),
                                        name=name, phase=phase, note=note,
                                        parent=smi, generation=generation,
                                        pathway=path + [step])
                        continue
                    seen.add(prod_smi)
                    results[prod_smi] = {
                        "smiles": prod_smi, "name": name, "phase": phase,
                        "note": note, "parent": smi, "generation": generation,
                        "score": round(new_score, 4), "pathway": path + [step]}
                    next_frontier.append((prod_smi, prod_mol, new_score,
                                          path + [step]))
                    if len(results) >= MAX_METABOLITES:
                        break
        if len(results) >= MAX_METABOLITES:
            break
        frontier = next_frontier

    ranked = sorted(results.values(), key=lambda m: -m["score"])[:max_results]
    return {"parent": parent_smi, "n_generated": len(results),
            "metabolites": ranked, "citation": CITATION}


def route_to_root(pred, metabolite):
    """The full chain of structures from the parent drug to this metabolite.

    A metabolite record only stores its IMMEDIATE parent, so a two-step route
    has to be walked backwards to recover the intermediate. Returns
    [(smiles, step_name_or_None), …] starting at the parent drug, which is what
    a pathway drawing needs — the point is to see the molecule change at each
    step, not to read the transformation's name.
    """
    if not pred or not metabolite:
        return []
    by_smiles = {m["smiles"]: m for m in (pred.get("metabolites") or [])}
    root = pred.get("parent")
    chain, node, guard = [], metabolite, 0
    while node is not None and guard < 12:
        guard += 1
        chain.append((node["smiles"], node.get("name")))
        parent_smi = node.get("parent")
        if not parent_smi or parent_smi == root:
            chain.append((root, None))
            break
        nxt = by_smiles.get(parent_smi)
        if nxt is None:
            # The intermediate isn't in the returned list (it can be ranked out
            # if the caller trimmed the results). Anchor to the parent drug and
            # keep the route drawable — a partial route is still informative;
            # silently returning nothing would just erase the row.
            chain.append((parent_smi, None))
            if parent_smi != root:
                chain.append((root, None))
            break
        node = nxt
    return list(reversed(chain))


def _mol_svg_inner(smiles, width, height, highlight_changed=None):
    """One molecule as SVG body (no outer <svg>), ready to place in a layout."""
    import re
    from rdkit import Chem
    from rdkit.Chem.Draw import rdMolDraw2D
    mol = Chem.MolFromSmiles(str(smiles or ""))
    if mol is None:
        return ""
    try:
        from rdkit.Chem import AllChem
        AllChem.Compute2DCoords(mol)
        d = rdMolDraw2D.MolDraw2DSVG(width, height)
        opts = d.drawOptions()
        opts.clearBackground = False
        opts.bondLineWidth = 1
        rdMolDraw2D.PrepareAndDrawMolecule(d, mol)
        d.FinishDrawing()
        svg = d.GetDrawingText()
    except Exception:
        return ""
    # strip the XML prolog and the outer <svg …> wrapper so the body can be
    # translated into position inside a bigger drawing
    svg = re.sub(r"<\?xml[^>]*\?>", "", svg)
    svg = re.sub(r"<!DOCTYPE[^>]*>", "", svg)
    m = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.DOTALL)
    return m.group(1) if m else ""


def pathway_svg(pred, max_routes=6, cell_w=210, cell_h=170):
    """Draw the metabolic routes as STRUCTURES, not text.

    Each row is one route read left to right — parent drug, arrow labelled with
    the transformation, the molecule that results, and so on for a second step.
    Naming a transformation is useless to a chemist without the structure beside
    it; this is the figure that makes the prediction checkable.

    Returns an SVG string, or "" if nothing can be drawn.
    """
    mets = (pred or {}).get("metabolites") or []
    if not mets:
        return ""
    routes = [route_to_root(pred, m) for m in mets[:max_routes]]
    routes = [r for r in routes if len(r) >= 2]
    if not routes:
        return ""

    ARROW = 96
    widest = max(len(r) for r in routes)
    width = 40 + widest * cell_w + (widest - 1) * ARROW
    height = 54 + len(routes) * cell_h
    INK, MUTED, LINE = "#0b0b0b", "#52514e", "#c3c2b7"
    font = ('-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, '
            'Roboto, Helvetica, Arial, sans-serif')

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
           f'height="{height}" viewBox="0 0 {width} {height}" '
           f"font-family='{font}'>",
           f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
           f'<text x="24" y="30" font-size="15" font-weight="600" fill="{INK}">'
           f'Predicted metabolic routes</text>']

    for i, route in enumerate(routes):
        y = 54 + i * cell_h
        x = 24
        for j, (smi, step) in enumerate(route):
            inner = _mol_svg_inner(smi, cell_w, cell_h - 30)
            if inner:
                out.append(f'<g transform="translate({x},{y})">{inner}</g>')
            # the compound's own line, so a structure is never unlabelled. The
            # middle of a two-step route is an INTERMEDIATE, not the product —
            # calling both "metabolite" misreads the route.
            if j == 0:
                label = "parent drug"
            elif j == len(route) - 1:
                label = f"metabolite {i + 1}"
            else:
                label = "intermediate"
            out.append(f'<text x="{x + cell_w / 2:.0f}" y="{y + cell_h - 16}" '
                       f'font-size="10.5" fill="{MUTED}" text-anchor="middle">'
                       f'{label}</text>')
            if j < len(route) - 1:
                ax = x + cell_w
                ay = y + (cell_h - 30) / 2
                nxt = route[j + 1][1] or ""
                out.append(f'<line x1="{ax + 8}" y1="{ay}" x2="{ax + ARROW - 12}" '
                           f'y2="{ay}" stroke="{LINE}" stroke-width="1.5"/>')
                out.append(f'<path d="M{ax + ARROW - 12},{ay} l-7,-4 l0,8 Z" '
                           f'fill="{LINE}"/>')
                # the transformation name rides ABOVE its arrow, wrapped so a
                # long name like "Glutathione conjugation" doesn't overrun
                words, line1, line2 = nxt.split(), "", ""
                for w in words:
                    if len(line1) + len(w) <= 14:
                        line1 = (line1 + " " + w).strip()
                    else:
                        line2 = (line2 + " " + w).strip()
                out.append(f'<text x="{ax + ARROW / 2:.0f}" y="{ay - 14}" '
                           f'font-size="9.5" fill="{INK}" text-anchor="middle">'
                           f'{_esc_svg(line1)}</text>')
                if line2:
                    out.append(f'<text x="{ax + ARROW / 2:.0f}" y="{ay - 3}" '
                               f'font-size="9.5" fill="{INK}" text-anchor="middle">'
                               f'{_esc_svg(line2)}</text>')
                x = ax + ARROW
    out.append("</svg>")
    return "\n".join(out)


def _esc_svg(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def summarize(pred):
    """A short factual summary used to prompt the narrative writer."""
    if not pred or pred.get("_error"):
        return ""
    mets = pred.get("metabolites") or []
    n1 = sum(1 for m in mets if m["phase"] == "I")
    n2 = sum(1 for m in mets if m["phase"] == "II")
    lines = [f"Parent: {pred.get('parent')}",
             f"{len(mets)} metabolites shown ({n1} phase I, {n2} phase II) "
             f"of {pred.get('n_generated')} generated."]
    for m in mets[:12]:
        lines.append(f"- {m['smiles']} | {m['name']} (phase {m['phase']}) "
                     f"| score {m['score']} | route: {' -> '.join(m['pathway'])}")
    return "\n".join(lines)
