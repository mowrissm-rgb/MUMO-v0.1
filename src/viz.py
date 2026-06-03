"""
MUMO — 3D Interaction Visualiser (py3Dmol)
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

Turns a docked protein-ligand complex into an INTERACTIVE 3D picture in the
browser — like the pose view in Maestro/PyMOL. Fully customisable: protein style
(cartoon/surface/sticks/lines), ligand style (sticks/ball-and-stick/spheres),
colors, background, surface opacity, and what to show.
"""

import py3Dmol

# Default look — a sensible starting point the user can change in the UI.
DEFAULTS = {
    "protein_style":  "cartoon",      # cartoon | surface | stick | line | cartoon+surface
    "protein_color":  "spectrum",     # spectrum | grey | white | secondary structure
    "cartoon_style":  "default",      # default | trace | rectangle | edged
    "protein_opacity": 1.0,           # cartoon/surface opacity
    "surface_color":  "white",
    "surface_opacity": 0.6,
    "ligand_style":   "stick",        # stick | ball-and-stick | sphere | line
    "ligand_carbon":  "greenCarbon",  # *Carbon color scheme for the ligand
    "ligand_radius":  0.22,           # thickness of the ligand sticks
    "show_residues":  True,
    "show_interactions": True,
    "show_labels":    True,
    "label_size":     11,             # residue label font size
    "zoom":           0.6,            # <1 = wider view, >1 = closer
    "background":     "#0a0f1e",
    "spin":           False,
}


def _hex(c):
    """Turn '#0a0f1e' into the '0x0a0f1e' form 3Dmol expects."""
    return c.replace("#", "0x") if isinstance(c, str) and c.startswith("#") else c


def _protein_color_spec(name):
    if name == "spectrum":               return {"color": "spectrum"}
    if name == "secondary structure":    return {"colorscheme": "ssJmol"}
    return {"color": {"grey": "lightgrey", "white": "white"}.get(name, "lightgrey")}


def render_complex_html(complex_pdb_path, ia, options=None, width=900, height=560):
    """
    complex_pdb_path : protein+ligand 'complex' PDB (ligand = residue 'LIG')
    ia               : dict from analyze_interactions() (has 'lines', 'residue_numbers')
    options          : dict overriding DEFAULTS (the visualisation settings)
    """
    o = dict(DEFAULTS)
    if options:
        o.update(options)

    with open(complex_pdb_path) as f:
        pdb = f.read()

    view = py3Dmol.view(width=width, height=height)
    view.addModel(pdb, "pdb")

    protein = {"resn": "LIG", "invert": True}   # everything that is NOT the ligand
    ligand  = {"resn": "LIG"}

    # ── protein representation ──
    pstyle = o["protein_style"]
    pcolor = _protein_color_spec(o["protein_color"])
    if pstyle in ("cartoon", "cartoon+surface"):
        cartoon = dict(pcolor)
        cartoon.update({"thickness": 0.45, "arrows": True,
                        "opacity": o.get("protein_opacity", 1.0)})   # smoother, Maestro-like ribbons
        if o.get("cartoon_style", "default") != "default":
            cartoon["style"] = o["cartoon_style"]
        view.setStyle(protein, {"cartoon": cartoon})
    elif pstyle == "stick":
        view.setStyle(protein, {"stick": {"radius": 0.12, **({} if "colorscheme" in pcolor else pcolor)}})
    elif pstyle == "line":
        view.setStyle(protein, {"line": {}})
    elif pstyle == "surface":
        view.setStyle(protein, {})   # no cartoon; surface added below
    if pstyle in ("surface", "cartoon+surface"):
        view.addSurface(py3Dmol.VDW,
                        {"opacity": o["surface_opacity"], "color": o["surface_color"]},
                        protein)

    # ── ligand representation ──
    cs = o["ligand_carbon"]
    lstyle = o["ligand_style"]
    lr = o.get("ligand_radius", 0.22)
    if lstyle == "stick":
        view.addStyle(ligand, {"stick": {"colorscheme": cs, "radius": lr}})
    elif lstyle == "ball-and-stick":
        view.addStyle(ligand, {"stick": {"colorscheme": cs, "radius": lr * 0.6}})
        view.addStyle(ligand, {"sphere": {"colorscheme": cs, "scale": 0.32}})
    elif lstyle == "sphere":
        view.addStyle(ligand, {"sphere": {"colorscheme": cs}})
    elif lstyle == "line":
        view.addStyle(ligand, {"line": {}})

    # ── interacting residues (cyan sticks) ──
    if o["show_residues"]:
        resi_list = [str(r) for r in ia.get("residue_numbers", [])]
        if resi_list:
            view.addStyle({"resi": resi_list},
                          {"stick": {"colorscheme": "cyanCarbon", "radius": 0.15}})

    # ── interaction lines + residue labels ──
    if o["show_interactions"]:
        seen = set()
        for ln in ia.get("lines", []):
            p1, p2 = ln["p1"], ln["p2"]
            view.addCylinder({
                "start": {"x": p1[0], "y": p1[1], "z": p1[2]},
                "end":   {"x": p2[0], "y": p2[1], "z": p2[2]},
                "radius": 0.08, "dashed": True, "fromCap": 1, "toCap": 1,
                "color": ln["color"],
            })
            if o["show_labels"] and ln["label"] not in seen:
                seen.add(ln["label"])
                view.addLabel(ln["label"], {
                    "position": {"x": p2[0], "y": p2[1], "z": p2[2]},
                    "fontSize": o.get("label_size", 11), "fontColor": "white",
                    "backgroundColor": "0x111827", "backgroundOpacity": 0.7,
                })

    view.setBackgroundColor(_hex(o["background"]))
    view.zoomTo({"resn": "LIG"})
    view.zoom(o.get("zoom", 0.6))
    if o["spin"]:
        view.spin(True)
    return view._make_html()
