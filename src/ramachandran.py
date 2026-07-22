"""
MUMO — Ramachandran analysis (backbone geometry validation)
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

WHAT THIS IS FOR
----------------
A Ramachandran plot shows every residue's backbone torsion angles (phi, psi)
against the regions those angles are physically able to occupy. It is the
standard first check on whether a protein STRUCTURE is trustworthy — and in
MUMO's workflow that matters directly: docking into a distorted or poorly
modelled receptor produces confident-looking affinities that mean nothing.
An AlphaFold model of a floppy loop and a 1.5 A crystal structure both dock
fine; only this tells you which one you actually have.

WHY IT'S OUR OWN IMPLEMENTATION
-------------------------------
The angles are pure geometry from backbone coordinates, so this needs numpy
and nothing else. MUMO has twice been taken down by adding heavy native
packages to the shared conda env, so avoiding a new dependency (Biopython,
MDAnalysis) for ~100 lines of vector maths is worth the effort.

HONEST LIMITS — READ BEFORE PUTTING THIS IN A PAPER
---------------------------------------------------
The phi/psi ANGLES computed here are exact: standard IUPAC torsion geometry,
unit-tested against hand-computed values.

The favoured/allowed REGIONS are box approximations of the standard basins,
not MolProbity's Top8000 density contours. Measured against three independent
well-refined crystal structures (1UBQ 1.8 A, 1CRN 0.945 A, 3PTB 1.7 A) this
model reports:

    favoured 90-97%   allowed 3-10%   outliers 0-0.5%

i.e. it runs a few points CONSERVATIVE on "favoured" versus MolProbity (which
would call all three ~96-98%), because a box union clips the smooth edges of
each basin and demotes borderline residues to "allowed".

The practical consequence, and the reason this is still worth having: the
OUTLIER count is the reliable signal and it is clean — good structures come
out at essentially zero, so a structure that reports real outliers genuinely
has something wrong with it. Read "favoured" as a lower bound, not a
MolProbity-equivalent figure. For a number that goes in a paper, validate
that structure in MolProbity and cite THAT; this is a screening aid, and the
report says so wherever these numbers appear.
"""

import math

# ── region model ───────────────────────────────────────────────────────────
# Each region is a list of (phi_min, phi_max, psi_min, psi_max) boxes. Boxes
# rather than smooth contours keeps the membership test, the drawn shading and
# the statistics all derived from ONE definition — a plot whose shading and
# whose percentages came from different models would be quietly inconsistent.
# Glycine has no side chain so it reaches mirror-image regions no other residue
# can; proline's ring locks phi near -60. Scoring all three against one general
# region set is the single most common way these plots are got wrong, so they
# are kept separate here.

_GENERAL_FAVOURED = [
    (-180, -45, 90, 180),     # beta sheet / polyproline II
    (-180, -45, -180, -160),  # beta, wrapped across the psi = +-180 seam
    (-160, -45, -70, -5),     # right-handed alpha helix
    (-125, -45, -10, 45),     # bridge region connecting the beta and alpha
                              # basins — genuinely populated in real proteins,
                              # and omitting it wrongly demoted real residues
                              # to merely "allowed"
    (40, 75, 15, 70),         # left-handed alpha helix
]
_GENERAL_ALLOWED = [
    (-180, -35, 60, 180),
    (-180, -35, -180, -140),
    (-180, -25, -90, 30),
    (30, 95, 0, 95),
]

_GLY_FAVOURED = _GENERAL_FAVOURED + [
    (45, 180, 90, 180),       # glycine's mirror-image regions
    (45, 180, -180, -160),
    (45, 180, 150, 180),
    (-180, -45, 150, 180),
]
_GLY_ALLOWED = _GENERAL_ALLOWED + [
    (30, 180, 60, 180),
    (30, 180, -180, -140),
    (-100, 180, -60, 100),
]

_PRO_FAVOURED = [
    (-100, -45, 110, 180),    # polyproline II
    (-100, -45, -50, 10),     # alpha
]
_PRO_ALLOWED = [
    (-110, -35, 90, 180),
    (-110, -35, -60, 30),
    (-110, -35, -180, -160),
]


def _in_boxes(phi, psi, boxes):
    return any(lo_x <= phi <= hi_x and lo_y <= psi <= hi_y
               for lo_x, hi_x, lo_y, hi_y in boxes)


def classify(phi, psi, resname):
    """'favoured' | 'allowed' | 'outlier' for one residue's torsion pair."""
    rn = (resname or "").upper()
    if rn == "GLY":
        fav, allow = _GLY_FAVOURED, _GLY_ALLOWED
    elif rn == "PRO":
        fav, allow = _PRO_FAVOURED, _PRO_ALLOWED
    else:
        fav, allow = _GENERAL_FAVOURED, _GENERAL_ALLOWED
    if _in_boxes(phi, psi, fav):
        return "favoured"
    if _in_boxes(phi, psi, allow):
        return "allowed"
    return "outlier"


# ── geometry ───────────────────────────────────────────────────────────────

def dihedral(p0, p1, p2, p3):
    """Torsion angle p0-p1-p2-p3 in degrees, in (-180, 180].

    Uses the projection form rather than a naive angle-between-normals: it is
    numerically stable near 0 and 180 degrees, where the cross products of the
    naive version become tiny and the sign flips unpredictably.
    """
    import numpy as np
    p0, p1, p2, p3 = (np.asarray(p, dtype=float) for p in (p0, p1, p2, p3))
    b0 = p0 - p1
    b1 = p2 - p1
    b2 = p3 - p2
    n = np.linalg.norm(b1)
    if n < 1e-8:
        return None
    b1 = b1 / n
    v = b0 - np.dot(b0, b1) * b1        # b0 with its b1 component removed
    w = b2 - np.dot(b2, b1) * b1
    x = float(np.dot(v, w))
    y = float(np.dot(np.cross(b1, v), w))
    if abs(x) < 1e-12 and abs(y) < 1e-12:
        return None                      # collinear — torsion undefined
    return math.degrees(math.atan2(y, x))


# ── PDB parsing ────────────────────────────────────────────────────────────

_BACKBONE = ("N", "CA", "C")


def _parse_backbone(pdb_text):
    """Ordered backbone atoms per residue, straight from PDB column positions.

    Reads fixed columns rather than splitting on whitespace: PDB fields run
    together on wide coordinates (a '-100.000-100.000' pair is one token to
    str.split), so column slicing is the only parse that stays correct on real
    files. HETATM is skipped — modified residues and ligands are not part of
    the protein's Ramachandran statistics.
    """
    residues = []          # ordered, one dict per residue
    index = {}
    for line in (pdb_text or "").splitlines():
        if not line.startswith("ATOM"):
            continue
        name = line[12:16].strip()
        if name not in _BACKBONE:
            continue
        altloc = line[16]
        if altloc not in (" ", "A"):      # keep one conformer only
            continue
        try:
            xyz = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
        except ValueError:
            continue
        key = (line[21], line[22:26].strip(), line[26])   # chain, resseq, icode
        res = index.get(key)
        if res is None:
            res = {"chain": line[21], "resseq": line[22:26].strip(),
                   "icode": line[26].strip(), "resname": line[17:20].strip(),
                   "atoms": {}}
            index[key] = res
            residues.append(res)
        res["atoms"].setdefault(name, xyz)      # first occurrence wins
    return residues


def _bonded(res_a, res_b, cutoff=2.0):
    """True if res_a's C and res_b's N are close enough to be a real peptide
    bond. Consecutive records in a PDB are NOT necessarily bonded — missing
    loops and chain ends leave gaps, and computing a torsion across one
    invents an angle from two unrelated pieces of the protein."""
    c = res_a["atoms"].get("C")
    n = res_b["atoms"].get("N")
    if not c or not n:
        return False
    d2 = sum((a - b) ** 2 for a, b in zip(c, n))
    return d2 <= cutoff * cutoff


def compute(pdb_text):
    """Ramachandran analysis of a protein structure.

    Returns:
        {"points": [{phi, psi, resname, chain, resseq, label, region}, ...],
         "counts": {favoured, allowed, outlier},
         "pct": {favoured, allowed, outlier},
         "n_residues": int, "n_scored": int,
         "outliers": [label, ...],
         "note": str}
    or {"_error": "..."} — never raises.
    """
    try:
        import numpy  # noqa: F401  (dihedral needs it; fail early and clearly)
    except Exception as e:
        return {"_error": f"numpy unavailable: {e}"}

    residues = _parse_backbone(pdb_text)
    if len(residues) < 3:
        return {"_error": "No protein backbone found in that structure."}

    points = []
    for i, res in enumerate(residues):
        prev_r = residues[i - 1] if i > 0 else None
        next_r = residues[i + 1] if i < len(residues) - 1 else None
        # phi needs the PREVIOUS residue's C, psi the NEXT residue's N — so a
        # chain's first residue has no phi and its last has no psi. Those are
        # genuinely undefined, not missing data, and are simply not scored.
        if not (prev_r and next_r):
            continue
        if not (_bonded(prev_r, res) and _bonded(res, next_r)):
            continue
        a = res["atoms"]
        if not all(k in a for k in _BACKBONE):
            continue
        phi = dihedral(prev_r["atoms"]["C"], a["N"], a["CA"], a["C"])
        psi = dihedral(a["N"], a["CA"], a["C"], next_r["atoms"]["N"])
        if phi is None or psi is None:
            continue
        label = f'{res["resname"]}{res["resseq"]}{res["icode"]}({res["chain"]})'
        points.append({"phi": round(phi, 2), "psi": round(psi, 2),
                       "resname": res["resname"], "chain": res["chain"],
                       "resseq": res["resseq"], "label": label,
                       "region": classify(phi, psi, res["resname"])})

    if not points:
        return {"_error": "Backbone found, but no residue had a complete "
                          "phi/psi pair (structure may be badly fragmented)."}

    counts = {k: sum(1 for p in points if p["region"] == k)
              for k in ("favoured", "allowed", "outlier")}
    n = len(points)
    pct = {k: round(100.0 * v / n, 1) for k, v in counts.items()}
    outliers = [p["label"] for p in points if p["region"] == "outlier"]
    return {"points": points, "counts": counts, "pct": pct,
            "n_residues": len(residues), "n_scored": n,
            "outliers": outliers,
            "note": ("Regions are box approximations of the standard basins, not "
                     "MolProbity density contours, so 'favoured' reads a few points "
                     "low (a lower bound); the outlier count is the reliable signal. "
                     "Screen with this, and validate in MolProbity for publication.")}


def plot_svg(result, title=None, width=620):
    """The Ramachandran plot itself, as SVG.

    Hand-written SVG for the same reason as charts.py: the .docx export path
    already rasterizes SVG through headless Chromium, so this needs no
    plotting library and therefore no new dependency.

    The shading is drawn from the SAME box definitions the classifier uses, so
    the background and the statistics come from one model rather than two that
    could drift apart.

    It shades the GENERAL-case regions only, though, while points are scored
    against their own residue type's regions. So a glycine can legitimately
    appear favoured while sitting outside the shading — GLY75 of ubiquitin,
    at phi 120 psi 126, is exactly that: a real mirror-region glycine, which
    is forbidden to any residue carrying a side chain. Shading the union of
    all three region sets instead would be worse, implying those areas are
    open to every residue. The caption states this rather than leaving a
    reader to wonder why a blue point sits on white.

    Point colour marks region membership. Outliers use a status red because
    an outlier IS a problem state, not merely another category; favoured and
    allowed use the standard series blue at two strengths.
    """
    if not result or result.get("_error") or not result.get("points"):
        return ""

    # PAD_B stacks four things under the plot — tick labels, the phi axis
    # title, the legend, then a two-line caption — so it is deliberately deep.
    PAD_L, PAD_T, PAD_R, PAD_B = 62, 66, 20, 100
    size = width - PAD_L - PAD_R          # square plot area
    height = PAD_T + size + PAD_B
    INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
    GRID, AXIS = "#e1e0d9", "#c3c2b7"
    FAV_FILL, ALLOW_FILL = "#dce9fa", "#f0f4f8"
    C_FAV, C_ALLOW, C_OUT = "#2a78d6", "#86b6ef", "#d03b3b"
    FONT = ('-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, '
            'Roboto, Helvetica, Arial, sans-serif')

    def sx(phi):                       # phi: -180..180 -> left..right
        return PAD_L + (phi + 180.0) / 360.0 * size

    def sy(psi):                       # psi: -180..180 -> BOTTOM..top (SVG y is
        return PAD_T + (180.0 - psi) / 360.0 * size      # inverted, so flip)

    pct, counts = result["pct"], result["counts"]
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family=\'{FONT}\'>',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text x="24" y="30" font-size="15" font-weight="600" fill="{INK}">'
        f'{_esc(title or "Ramachandran plot")}</text>',
        f'<text x="24" y="49" font-size="12" fill="{INK2}">'
        f'{result["n_scored"]} residues scored · {pct["favoured"]}% favoured · '
        f'{pct["allowed"]}% allowed · {pct["outlier"]}% outliers</text>',
    ]

    # shaded regions, allowed first so favoured paints over it
    for boxes, fill in ((_GENERAL_ALLOWED, ALLOW_FILL), (_GENERAL_FAVOURED, FAV_FILL)):
        for lo_x, hi_x, lo_y, hi_y in boxes:
            x0, x1 = sx(lo_x), sx(hi_x)
            y0, y1 = sy(hi_y), sy(lo_y)         # hi psi is the TOP edge
            out.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{x1 - x0:.1f}" '
                       f'height="{y1 - y0:.1f}" fill="{fill}"/>')

    # gridlines + ticks every 90 degrees
    for t in (-180, -90, 0, 90, 180):
        x, y = sx(t), sy(t)
        out.append(f'<line x1="{x:.1f}" y1="{PAD_T}" x2="{x:.1f}" '
                   f'y2="{PAD_T + size}" stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{PAD_L + size}" '
                   f'y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{x:.1f}" y="{PAD_T + size + 16}" font-size="10.5" '
                   f'fill="{MUTED}" text-anchor="middle">{t}</text>')
        out.append(f'<text x="{PAD_L - 8}" y="{y + 3.5:.1f}" font-size="10.5" '
                   f'fill="{MUTED}" text-anchor="end">{t}</text>')

    out.append(f'<rect x="{PAD_L}" y="{PAD_T}" width="{size}" height="{size}" '
               f'fill="none" stroke="{AXIS}" stroke-width="1"/>')

    # points — outliers drawn LAST so they are never hidden under the cloud
    order = {"favoured": 0, "allowed": 1, "outlier": 2}
    for p in sorted(result["points"], key=lambda q: order.get(q["region"], 0)):
        colour = {"favoured": C_FAV, "allowed": C_ALLOW}.get(p["region"], C_OUT)
        r_ = 3.4 if p["region"] == "outlier" else 2.2
        out.append(f'<circle cx="{sx(p["phi"]):.1f}" cy="{sy(p["psi"]):.1f}" '
                   f'r="{r_}" fill="{colour}" fill-opacity="0.85"/>')

    # Everything below the plot is positioned relative to the plot's bottom
    # edge, not to `height` — the two were drifting into each other, which is
    # how the legend ended up overlapping the phi axis title.
    bottom = PAD_T + size
    mid = PAD_L + size / 2
    out.append(f'<text x="{mid:.1f}" y="{bottom + 34}" font-size="11.5" '
               f'fill="{INK2}" text-anchor="middle">phi (degrees)</text>')
    out.append(f'<text x="16" y="{PAD_T + size / 2:.1f}" font-size="11.5" '
               f'fill="{INK2}" text-anchor="middle" '
               f'transform="rotate(-90 16 {PAD_T + size / 2:.1f})">psi (degrees)</text>')

    lx, ly = 24, bottom + 56
    for colour, name, n in ((C_FAV, "favoured", counts["favoured"]),
                            (C_ALLOW, "allowed", counts["allowed"]),
                            (C_OUT, "outlier", counts["outlier"])):
        out.append(f'<circle cx="{lx + 4}" cy="{ly - 4}" r="3.4" fill="{colour}"/>')
        out.append(f'<text x="{lx + 13}" y="{ly}" font-size="11" fill="{INK2}">'
                   f'{name} ({n})</text>')
        lx += 26 + len(f"{name} ({n})") * 6.0
    out.append(f'<text x="24" y="{bottom + 76}" font-size="10" fill="{MUTED}">'
               f'Shading shows the general-case regions; glycine and proline are '
               f'scored against their own,</text>')
    out.append(f'<text x="24" y="{bottom + 88}" font-size="10" fill="{MUTED}">'
               f'so a few points may sit outside it. Approximate regions — '
               f'screening aid, not a MolProbity substitute.</text>')
    out.append("</svg>")
    return "\n".join(out)


def _esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def verdict(result):
    """One plain-language line on whether the structure looks trustworthy.

    Thresholds are calibrated to THIS module's region model, not to
    MolProbity's. Applying MolProbity's usual ">98% favoured" bar here would
    mislabel genuinely excellent structures as mediocre, because the box
    regions read a few points low by construction (1UBQ, a 1.8 A structure,
    scores 97.3% here). The outlier fraction carries most of the weight
    instead, since that is the part measured to be reliable.
    """
    if not result or result.get("_error"):
        return ""
    fav, out = result["pct"]["favoured"], result["pct"]["outlier"]
    if fav >= 90 and out <= 0.5:
        return (f"{fav}% of residues sit in favoured regions and {out}% are "
                f"outliers — backbone geometry looks well refined.")
    if fav >= 80 and out <= 2:
        return (f"{fav}% favoured, {out}% outliers — acceptable geometry; the "
                f"outlying residues are worth a look if any sit in the binding site.")
    return (f"Only {fav}% of residues are in favoured regions and {out}% are "
            f"outliers — treat this structure with caution, and check whether "
            f"the distorted residues are near the pocket before trusting a dock.")
