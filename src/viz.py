"""
MUMO — 3D Interaction Visualiser (py3Dmol)
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

Turns a docked protein-ligand complex into an INTERACTIVE 3D picture in the
browser — like the pose view in Maestro/PyMOL. Fully customisable: protein style
(cartoon/surface/sticks/lines), ligand style (sticks/ball-and-stick/spheres),
colors, background, surface opacity, and what to show.
"""

import json as _json   # only the lightweight CDN viewer is used now (no py3Dmol embed)

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
    "zoom":           0.45,           # <1 = wider view, >1 = closer (pocket-focused)
    "background":     "#ffffff",      # clean white "figure panel" look (like a journal figure)
    "spin":           False,
    "pocket_only":    False,          # False = whole protein; True = binding-site crop (lighter)
}


def _hex(c):
    """Turn '#0a0f1e' into the '0x0a0f1e' form 3Dmol expects."""
    return c.replace("#", "0x") if isinstance(c, str) and c.startswith("#") else c


def _protein_color_spec(name):
    if name == "spectrum":               return {"color": "spectrum"}
    if name == "secondary structure":    return {"colorscheme": "ssJmol"}
    return {"color": {"grey": "lightgrey", "white": "white"}.get(name, "lightgrey")}


def _crop_to_pocket(pdb_text, cutoff=14.0):
    """
    Keep only the binding-site region: protein residues with any atom within
    `cutoff` Å of the ligand, plus the ligand. Drops the rest of the protein so
    the viewer payload stays tiny regardless of protein size (cloud-friendly),
    and gives a clean pocket close-up. Falls back to the full PDB if no ligand.
    """
    lines = pdb_text.splitlines()
    lig = []
    for ln in lines:
        if ln.startswith("HETATM") and ln[17:20].strip() == "LIG":
            try:
                lig.append((float(ln[30:38]), float(ln[38:46]), float(ln[46:54])))
            except ValueError:
                pass
    if not lig:
        return pdb_text

    res_lines, res_coords, hetatm = {}, {}, []
    for ln in lines:
        if ln.startswith("ATOM"):
            key = (ln[21], ln[22:26])
            res_lines.setdefault(key, []).append(ln)
            try:
                res_coords.setdefault(key, []).append(
                    (float(ln[30:38]), float(ln[38:46]), float(ln[46:54])))
            except ValueError:
                pass
        elif ln.startswith("HETATM") or ln.startswith("END"):
            hetatm.append(ln)

    cut2 = cutoff * cutoff
    kept = []
    for key, coords in res_coords.items():
        near = any((x-lx)**2 + (y-ly)**2 + (z-lz)**2 <= cut2
                   for (x, y, z) in coords for (lx, ly, lz) in lig)
        if near:
            kept.extend(res_lines[key])
    return "\n".join(kept + ["TER"] + hetatm) + "\n"


# ── persistence: the in-memory `viz` dict points at complex PDB files on disk,
#    which don't survive a page reload / container restart. serialize_viz turns
#    it into a self-contained, JSON-storable form (2D SVG + interaction data +
#    the pocket-cropped complex text) so a reloaded conversation can rebuild the
#    full docking report — 2D diagram AND 3D pose — from the database alone. ──
def serialize_viz(viz, crop=True):
    """viz (label -> {"complex": path, "ia": {...}}) → JSON-safe dict for storage.
    Reads each complex PDB from disk and (by default) crops it to the binding
    pocket, keeping the stored payload small (cloud/free-tier friendly)."""
    out = {}
    for label, entry in (viz or {}).items():
        pdb_text = None
        try:
            with open(entry["complex"]) as f:
                pdb_text = f.read()
            if crop:
                pdb_text = _crop_to_pocket(pdb_text)
        except Exception:
            pdb_text = None
        out[label] = {"pdb": pdb_text, "ia": entry.get("ia", {})}
    return out


def rehydrate_viz(stored_viz, data_dir):
    """Inverse of serialize_viz: write each stored PDB back to a file under
    data_dir and rebuild the viz dict the report builder / 3D viewer expect.
    Ligands whose PDB failed to store are skipped (their section will show the
    'no pose data' note rather than a broken image)."""
    import os
    import re as _re
    out = {}
    for i, (label, v) in enumerate((stored_viz or {}).items()):
        pdb_text = v.get("pdb")
        if not pdb_text:
            continue
        safe = _re.sub(r"[^A-Za-z0-9_.-]", "_", str(label))[:40] or f"lig{i}"
        path = os.path.join(data_dir, f"reload_{i}_{safe}.pdb")
        try:
            with open(path, "w") as f:
                f.write(pdb_text)
            out[label] = {"complex": path, "ia": v.get("ia", {})}
        except Exception:
            continue
    return out


def render_complex_html(complex_pdb_path, ia, options=None, width=900, height=560):
    """
    Build a LIGHTWEIGHT interactive 3D viewer.

    Instead of py3Dmol embedding the whole ~800KB 3Dmol.js library inside every
    render (which exhausts memory on the small Streamlit Cloud tier), we load the
    library ONCE from a CDN and emit only a few KB of our own JS. Same visuals,
    a fraction of the weight — so the cloud stays responsive across many dockings.
    """
    o = dict(DEFAULTS)
    if options:
        o.update(options)

    with open(complex_pdb_path) as f:
        pdb = f.read()
    if o.get("pocket_only"):
        pdb = _crop_to_pocket(pdb)   # optional: lighter binding-site-only view

    pstyle = o["protein_style"]
    pcolor = _protein_color_spec(o["protein_color"])    # {"color":...} or {"colorscheme":...}
    js = []

    # ── protein representation ──
    if pstyle in ("cartoon", "cartoon+surface"):
        cartoon = dict(pcolor)
        # thicker, smoother ribbons with strand arrows = publication-quality look
        cartoon.update({"thickness": 0.7, "arrows": True, "tubes": False,
                        "opacity": o.get("protein_opacity", 1.0)})
        if o.get("cartoon_style", "default") != "default":
            cartoon["style"] = o["cartoon_style"]
        js.append(f'v.setStyle({{}}, {{cartoon:{_json.dumps(cartoon)}}});')
    elif pstyle == "stick":
        js.append('v.setStyle({}, {stick:{radius:0.12}});')
    elif pstyle == "line":
        js.append('v.setStyle({}, {line:{}});')
    else:  # surface only
        js.append('v.setStyle({}, {});')
    if pstyle in ("surface", "cartoon+surface"):
        js.append(f'v.addSurface($3Dmol.SurfaceType.VDW, '
                  f'{{opacity:{o["surface_opacity"]}, color:"{o["surface_color"]}"}}, '
                  f'{{resn:"LIG", invert:true}});')

    # ── ligand representation ──
    cs = o["ligand_carbon"]; lr = o.get("ligand_radius", 0.22); lstyle = o["ligand_style"]
    if lstyle == "stick":
        js.append(f'v.setStyle({{resn:"LIG"}}, {{stick:{{colorscheme:"{cs}", radius:{lr}}}}});')
    elif lstyle == "ball-and-stick":
        js.append(f'v.setStyle({{resn:"LIG"}}, {{stick:{{colorscheme:"{cs}", radius:{lr*0.6}}}, '
                  f'sphere:{{colorscheme:"{cs}", scale:0.32}}}});')
    elif lstyle == "sphere":
        js.append(f'v.setStyle({{resn:"LIG"}}, {{sphere:{{colorscheme:"{cs}"}}}});')
    elif lstyle == "line":
        js.append('v.setStyle({resn:"LIG"}, {line:{}});')

    # ── interacting residues ──
    if o["show_residues"]:
        residues = ia.get("residues")
        if residues:                       # chain-aware: highlight the EXACT residue
            for rr in residues:
                js.append(f'v.addStyle({{chain:{_json.dumps(rr["chain"])}, resi:{rr["resi"]}}}, '
                          f'{{stick:{{colorscheme:"cyanCarbon", radius:0.15}}}});')
        else:                              # fallback (older results without chain)
            resi = [str(r) for r in ia.get("residue_numbers", [])]
            if resi:
                js.append(f'v.addStyle({{resi:{_json.dumps(resi)}}}, '
                          f'{{stick:{{colorscheme:"cyanCarbon", radius:0.15}}}});')

    # ── interaction lines + labels ──
    if o["show_interactions"]:
        seen = set()
        for ln in ia.get("lines", []):
            p1, p2 = ln["p1"], ln["p2"]
            js.append(f'v.addCylinder({{start:{{x:{p1[0]},y:{p1[1]},z:{p1[2]}}}, '
                      f'end:{{x:{p2[0]},y:{p2[1]},z:{p2[2]}}}, radius:0.08, dashed:true, '
                      f'fromCap:1, toCap:1, color:"{ln["color"]}"}});')
            if o["show_labels"] and ln["label"] not in seen:
                seen.add(ln["label"])
                js.append(f'v.addLabel({_json.dumps(ln["label"])}, '
                          f'{{position:{{x:{p2[0]},y:{p2[1]},z:{p2[2]}}}, '
                          f'fontSize:{o.get("label_size", 11)}, fontColor:"white", '
                          f'backgroundColor:"#111827", backgroundOpacity:0.7}});')

    js.append('v.zoomTo({resn:"LIG"});')           # focus the binding pocket so interactions are visible
    js.append(f'v.zoom({o.get("zoom", 0.45)});')   # slightly wide → pocket + interacting residues + bonds
    if o["spin"]:
        js.append('v.spin(true);')
    js.append('v.render();')
    js.append('window.__mumoReady = true;')  # lets a headless screenshotter (report export) know the scene is drawn

    return f"""<div id="mumoview" style="width:100%;height:{height}px;position:relative;
         border-radius:14px;border:1px solid rgba(0,0,0,0.10);overflow:hidden;
         box-shadow:0 4px 14px rgba(0,0,0,0.18);"></div>
<script src="https://3dmol.org/build/3Dmol-min.js"></script>
<script>
(function(){{
  function go(){{
    if(!window.$3Dmol){{ setTimeout(go, 60); return; }}
    var v = $3Dmol.createViewer(document.getElementById("mumoview"),
                                {{backgroundColor:"{o['background']}"}});
    v.addModel({_json.dumps(pdb)}, "pdb");
    {chr(10) + "    ".join(js)}
  }}
  go();
}})();
</script>"""
