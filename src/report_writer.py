"""
MUMO — Report Writer
Multi-Agent Drug Discovery & Development AI Platform

Turns a pipeline's results (docking / STRING / ADMET) into a downloadable
.docx: tables, write-ups, and static images. 2D/3D/network graphics are
rasterized through a headless Chromium (Playwright) so the exported picture
matches exactly what's shown live in the app (same SVG, same 3Dmol.js pose).

Heavy imports (docx, playwright, pandas, brain) are lazy — this module only
gets touched when a user actually clicks "Generate report".
"""

import io
import re


def normalize_svg_viewbox(svg):
    """Add a viewBox derived from px width/height if missing (STRING's raw SVG
    has none), so the SVG scales instead of clipping when rasterized."""
    m = re.search(r"<svg[^>]*?>", svg)
    if not m:
        return svg
    tag = m.group(0)
    if "viewbox" in tag.lower():
        return svg
    wm = re.search(r'width=["\']([\d.]+)', tag)
    hm = re.search(r'height=["\']([\d.]+)', tag)
    if not (wm and hm):
        return svg
    newtag = re.sub(r"<svg", f'<svg viewBox="0 0 {wm.group(1)} {hm.group(1)}"', tag, count=1)
    return svg.replace(tag, newtag, 1)


def new_browser():
    """Launch one headless Chromium instance to reuse across every screenshot
    in a report (much faster than a fresh browser per image).

    The 3D pose view needs WebGL (3Dmol.js/three.js) — default headless Chromium
    creates a WebGL context but then immediately loses it (no GPU in a headless
    container), which silently renders nothing. These flags force software
    rendering (SwiftShader) so WebGL actually stays alive and draws."""
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.launch(args=[
        "--use-gl=angle", "--use-angle=swiftshader", "--enable-webgl",
        "--ignore-gpu-blocklist", "--enable-unsafe-swiftshader", "--disable-gpu-sandbox",
    ])
    return pw, browser


def svg_to_png(svg, browser, width=760, height=560, pad=16):
    """Rasterize an SVG string to PNG bytes via headless Chromium."""
    svg = normalize_svg_viewbox(svg)
    html = (f'<html><body style="margin:0;background:#fff;">'
            f'<div id="c" style="display:inline-block;padding:{pad}px;background:#fff;">'
            f'{svg}</div></body></html>')
    page = browser.new_page(viewport={"width": width, "height": height})
    try:
        page.set_content(html)
        page.wait_for_timeout(150)
        return page.locator("#c").screenshot()
    finally:
        page.close()


def png_from_3d(complex_pdb_path, ia, browser, options=None, width=900, height=560):
    """Load MUMO's own 3Dmol viewer HTML in headless Chromium and screenshot the
    rendered pose — the same view shown in-app, captured as a static image.
    Raises on failure (e.g. the CDN 3Dmol.js load times out) so the caller can
    report the real reason instead of silently omitting the image."""
    from viz import render_complex_html
    html = render_complex_html(complex_pdb_path, ia, options=options, width=width, height=height)
    page = browser.new_page(viewport={"width": width, "height": height + 20})
    try:
        page.set_content(f"<html><body style='margin:0;'>{html}</body></html>")
        page.wait_for_function("window.__mumoReady === true", timeout=20000)
        page.wait_for_timeout(200)  # let the final zoom/render settle
        return page.locator("#mumoview").screenshot()
    finally:
        page.close()


# ─────────────────────────────────────────────────────────────────────────────
# docx assembly helpers
# ─────────────────────────────────────────────────────────────────────────────

def _add_kv_table(doc, pairs):
    table = doc.add_table(rows=0, cols=2)
    table.style = "Light Grid Accent 1"
    for k, v in pairs:
        cells = table.add_row().cells
        cells[0].text, cells[1].text = str(k), str(v)
    return table


def _add_df_table(doc, df):
    table = doc.add_table(rows=1, cols=len(df.columns))
    table.style = "Light Grid Accent 1"
    for i, col in enumerate(df.columns):
        table.rows[0].cells[i].text = str(col)
    for _, row in df.iterrows():
        cells = table.add_row().cells
        for i, col in enumerate(df.columns):
            cells[i].text = str(row[col])
    return table


def _add_bold_runs(paragraph, text):
    for part in re.split(r"(\*\*.*?\*\*)", text):
        if part.startswith("**") and part.endswith("**"):
            paragraph.add_run(part[2:-2]).bold = True
        elif part:
            paragraph.add_run(part)


def _add_markdown(doc, text):
    """Small markdown -> docx converter: headings, bullet lines, **bold** spans,
    plain paragraphs. Enough to render the LLM's beginner-narrative reports."""
    if not text:
        return
    for line in text.split("\n"):
        line = line.rstrip()
        if not line:
            continue
        if line.startswith("### "):
            doc.add_heading(line[4:], level=3)
        elif line.startswith("## "):
            doc.add_heading(line[3:], level=2)
        elif line.startswith("# "):
            doc.add_heading(line[2:], level=1)
        elif line.startswith(("- ", "* ")):
            _add_bold_runs(doc.add_paragraph(style="List Bullet"), line[2:])
        else:
            _add_bold_runs(doc.add_paragraph(), line)


# ─────────────────────────────────────────────────────────────────────────────
# per-pipeline report builders
# ─────────────────────────────────────────────────────────────────────────────

def build_docking_docx(r, llm=None):
    """Full docking report: method summary, an all-ligands table, then a
    detailed section per ligand (metrics, write-up, 2D diagram, 3D pose)."""
    from docx import Document
    from docx.shared import Inches
    from brain import write_report

    rdf, viz, meta = r["rdf"], r.get("viz", {}), r.get("meta", {})
    doc = Document()
    doc.add_heading(f"MUMO Docking Report — {meta.get('gene', 'target')}", level=0)

    bits = []
    if meta.get("exhaustiveness"):
        bits.append(f"exhaustiveness {meta['exhaustiveness']}")
    if meta.get("replicas"):
        bits.append(f"{meta['replicas']} replica(s)")
    if meta.get("pocket"):
        bits.append(meta["pocket"])
    val = meta.get("validation")
    if val:
        bits.append(f"native redock RMSD {val['rmsd']} Å "
                    f"({'validated' if val['passed'] else '>2 Å'})")
    if bits:
        doc.add_paragraph("Method: " + " · ".join(bits))

    doc.add_heading("Summary — all docked ligands", level=1)
    summary_cols = ["Ligand", "Best affinity (kcal/mol)", "Est. Ki", "Ligand efficiency",
                     "Vinardo (kcal/mol)", "Consensus", "Pose consistency", "Confidence",
                     "Reliability", "Total interactions", "H-bonds"]
    cols = [c for c in summary_cols if c in rdf.columns]
    summary = rdf[cols].reset_index().rename(columns={"index": "Rank"})
    _add_df_table(doc, summary)

    # One shared headless browser for all the screenshots. Rendering many WebGL
    # (3D) scenes in one browser can exhaust memory on a small host and crash it
    # mid-batch — which would fail every remaining ligand. `bh` holds the current
    # browser so `_shot` can restart it once on failure and keep going.
    bh = {"pw": None, "browser": None, "err": None}
    try:
        bh["pw"], bh["browser"] = new_browser()
    except Exception as e:
        bh["err"] = f"{type(e).__name__}: {e}"

    def _shot(kind, *args):
        """Take a 2D/3D screenshot; if the browser died, restart it once and retry.
        Returns (png_bytes, None) or (None, error_string)."""
        for attempt in (0, 1):
            if bh["browser"] is None:
                return None, bh["err"] or "headless browser unavailable"
            try:
                if kind == "2d":
                    return svg_to_png(args[0], bh["browser"]), None
                return png_from_3d(args[0], args[1], bh["browser"]), None
            except Exception as e:
                bh["err"] = f"{type(e).__name__}: {e}"
                if attempt == 0:                       # browser may have crashed — restart once
                    try:
                        bh["browser"].close(); bh["pw"].stop()
                    except Exception:
                        pass
                    try:
                        bh["pw"], bh["browser"] = new_browser()
                    except Exception as e2:
                        bh["browser"] = None
                        return None, f"{type(e2).__name__}: {e2}"
        return None, bh["err"]

    try:
        for pos, (rank, row) in enumerate(rdf.iterrows()):
            label = row["Ligand"]
            # continuous flow — no page break per ligand; a thin spacer between
            # sections keeps them visually separated without forcing new pages
            if pos > 0:
                doc.add_paragraph()
            doc.add_heading(f"#{rank} — {label}", level=1)
            if str(row["Best affinity (kcal/mol)"]) == "FAILED":
                doc.add_paragraph(f"Docking failed for this ligand: {row.get('Total interactions', '')}")
                continue

            _add_kv_table(doc, [(c, row[c]) for c in cols if c != "Ligand"])

            def _sp(v):
                return [x for x in str(v).split("; ") if x and x != "-"]

            _rel = (meta.get("reliability_by") or {}).get(label, {})
            writeup = write_report({
                "target": meta.get("gene"), "ligand": label,
                "affinity": float(row["Best affinity (kcal/mol)"]),
                "estimated_ki": row.get("Est. Ki"),
                "ligand_efficiency": row.get("Ligand efficiency"),
                "reliability": row.get("Reliability"),
                "reliability_reason": _rel.get("reason"),
                "total_interactions": row.get("Total interactions"),
                "n_hbonds": int(row.get("H-bonds", 0) or 0),
                "hbond_residues": _sp(row.get("H-bond residues", "")),
                "n_hydrophobic": int(row.get("Hydrophobic", 0) or 0),
                "interacting_residues": _sp(row.get("All interacting residues", "")),
            }, llm, r.get("tier", "Standard"))
            doc.add_heading("Interpretation", level=2)
            _add_markdown(doc, writeup)

            entry = viz.get(label)
            if not entry:
                doc.add_paragraph("(No pose/interaction data available for this ligand.)")
            elif bh["browser"] is None:
                doc.add_paragraph(f"(2D/3D images unavailable — headless browser failed to "
                                  f"start: {bh['err']})")
            else:
                svg = entry["ia"].get("svg_2d")
                doc.add_heading("2D interaction diagram", level=2)
                if svg:
                    png, err = _shot("2d", svg)
                    if png:
                        doc.add_picture(io.BytesIO(png), width=Inches(5.5))
                    else:
                        doc.add_paragraph(f"(2D diagram could not be rendered: {err})")
                else:
                    doc.add_paragraph("(No 2D interaction diagram available for this ligand.)")

                doc.add_heading("3D pose", level=2)
                png3d, err = _shot("3d", entry["complex"], entry["ia"])
                if png3d:
                    doc.add_picture(io.BytesIO(png3d), width=Inches(5.5))
                else:
                    doc.add_paragraph(f"(3D pose could not be rendered: {err})")
    finally:
        browser = bh["browser"]
        pw = bh["pw"]
        if browser:
            browser.close()
        if pw:
            pw.stop()

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_string_docx(r):
    """STRING interaction network report: network image + narrative + tables."""
    from docx import Document
    from docx.shared import Inches
    import pandas as pd

    names = ", ".join(r.get("input", [])) or "protein"
    doc = Document()
    doc.add_heading(f"MUMO Interaction Network Report — {names}", level=0)
    doc.add_paragraph("STRING protein–protein associations (known + predicted). "
                       "Combined score 0–1 from several evidence channels.")

    svg = r.get("network_svg")
    if svg:
        doc.add_heading("Interaction network", level=1)
        pw = browser = None
        try:
            pw, browser = new_browser()
            png = svg_to_png(svg, browser, width=900, height=700)
            doc.add_picture(io.BytesIO(png), width=Inches(6.0))
        except Exception as e:
            doc.add_paragraph(f"(Network image could not be rendered: {type(e).__name__}: {e})")
        finally:
            if browser:
                browser.close()
            if pw:
                pw.stop()

    narrative = r.get("narrative")
    if narrative:
        doc.add_heading("Report", level=1)
        _add_markdown(doc, narrative)

    partners = r.get("partners") or []
    if partners:
        doc.add_heading("Functional partners", level=1)
        rows = [{"Partner": p.get("preferredName_B", "?"),
                 "Score": round(p.get("score", 0), 3),
                 "Experimental": round(p.get("escore", 0), 3),
                 "Database": round(p.get("dscore", 0), 3),
                 "Text-mining": round(p.get("tscore", 0), 3)} for p in partners]
        _add_df_table(doc, pd.DataFrame(rows))

    enr = r.get("enrichment") or []
    if enr:
        doc.add_heading("Enriched pathways / functions", level=1)
        top = sorted(enr, key=lambda e: e.get("fdr", 1.0))[:12]
        rows = [{"Category": e.get("category", ""), "Term": e.get("description", ""),
                 "FDR": "{:.1e}".format(e.get("fdr", 1.0))} for e in top]
        _add_df_table(doc, pd.DataFrame(rows))

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_admet_docx(r):
    """ADMET / drug-likeness report: tables + beginner narrative (no images)."""
    from docx import Document

    doc = Document()
    doc.add_heading(f"MUMO ADMET Report — {r.get('lig_label', 'ligand')}", level=0)
    doc.add_paragraph(f"SMILES: {r.get('lig_smiles', '')}")

    narrative = r.get("narrative")
    if narrative:
        doc.add_heading("Report", level=1)
        _add_markdown(doc, narrative)

    dl = r.get("druglikeness") or {}
    if dl:
        doc.add_heading("Drug-likeness", level=1)
        _add_kv_table(doc, list(dl.items()))

    adm = r.get("admet_ml") or {}
    if adm and "_error" not in adm:
        doc.add_heading("ADMET-AI predictions", level=1)
        doc.add_paragraph("Pretrained ML models (Therapeutics Data Commons / Chemprop). "
                           "Classifier endpoints are probabilities 0–1; regression endpoints "
                           "are in native units.")
        _add_kv_table(doc, list(adm.items()))

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# structure export: the raw docked geometry in standard formats, so a user can
# open the pose in Discovery Studio / Maestro / BIOVIA / PyMOL / ChimeraX etc.
# Everything is derived from the (persisted) complex PDB, so this works for both
# fresh and reloaded results without needing the original run's temp files.
# ─────────────────────────────────────────────────────────────────────────────

def _split_complex_pdb(pdb_text):
    """Split a docked complex PDB into (receptor_pdb, ligand_pdb). The docked
    ligand is the HETATM group named LIG; everything else is the receptor."""
    receptor, ligand = [], []
    for ln in pdb_text.splitlines():
        rec = ln[:6].strip()
        if rec == "ATOM":
            receptor.append(ln)
        elif rec == "HETATM":
            (ligand if ln[17:20].strip() == "LIG" else receptor).append(ln)
        elif rec in ("TER", "HEADER", "CRYST1", "SEQRES"):
            receptor.append(ln)
    rec_txt = ("\n".join(receptor) + "\nEND\n") if receptor else ""
    lig_txt = ("\n".join(ligand) + "\nEND\n") if ligand else ""
    return rec_txt, lig_txt


def _ligand_sdf(lig_pdb, smiles=None):
    """Ligand PDB block → MDL molblock (.sdf/.mol) text. Uses the known SMILES
    to restore correct bond orders (PDB has none). Returns None on failure."""
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
    except Exception:
        return None
    mol = Chem.MolFromPDBBlock(lig_pdb, sanitize=True, removeHs=False)
    if mol is None:
        mol = Chem.MolFromPDBBlock(lig_pdb, sanitize=False, removeHs=False)
    if mol is None:
        return None
    if smiles:
        try:
            tmpl = Chem.MolFromSmiles(smiles)
            if tmpl is not None:
                mol = AllChem.AssignBondOrdersFromTemplate(tmpl, mol)
        except Exception:
            pass  # keep the perceived-connectivity mol if template matching fails
    try:
        # MolToMolBlock ends at "M  END" (a .mol block); append the SDF record
        # terminator so the .sdf file is valid for strict parsers.
        return Chem.MolToMolBlock(mol).rstrip() + "\n$$$$\n"
    except Exception:
        return None


def _sybyl_type(atom):
    """Minimal SYBYL atom type for a MOL2 file (enough for viewers to read)."""
    from rdkit import Chem
    sym = atom.GetSymbol()
    hyb = atom.GetHybridization()
    if atom.GetIsAromatic() and sym in ("C", "N"):
        return f"{sym}.ar"
    if sym == "C":
        return {Chem.HybridizationType.SP: "C.1", Chem.HybridizationType.SP2: "C.2"}.get(hyb, "C.3")
    if sym == "N":
        return {Chem.HybridizationType.SP: "N.1", Chem.HybridizationType.SP2: "N.2"}.get(hyb, "N.3")
    if sym == "O":
        return "O.2" if hyb == Chem.HybridizationType.SP2 else "O.3"
    if sym == "S":
        return "S.3"
    if sym == "P":
        return "P.3"
    return sym


def _ligand_mol2(lig_pdb, smiles=None):
    """Ligand PDB block → MOL2 (TRIPOS) text via a small RDKit writer — no
    OpenBabel. Bond orders come from `smiles` when given. Returns None on failure."""
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
    except Exception:
        return None
    mol = Chem.MolFromPDBBlock(lig_pdb, sanitize=True, removeHs=False)
    if mol is None:
        mol = Chem.MolFromPDBBlock(lig_pdb, sanitize=False, removeHs=False)
    if mol is None:
        return None
    if smiles:
        try:
            tmpl = Chem.MolFromSmiles(smiles)
            if tmpl is not None:
                mol = AllChem.AssignBondOrdersFromTemplate(tmpl, mol)
        except Exception:
            pass
    try:
        AllChem.ComputeGasteigerCharges(mol)
    except Exception:
        pass
    try:
        conf = mol.GetConformer()
        atom_lines = []
        for i, atom in enumerate(mol.GetAtoms()):
            p = conf.GetAtomPosition(i)
            try:
                q = float(atom.GetProp("_GasteigerCharge"))
                if q != q:      # NaN guard
                    q = 0.0
            except Exception:
                q = 0.0
            atom_lines.append(
                f"{i+1:>7} {atom.GetSymbol()+str(i+1):<8}{p.x:10.4f}{p.y:10.4f}{p.z:10.4f} "
                f"{_sybyl_type(atom):<6}{1:>4} LIG {q:>10.4f}")
        BOND = {Chem.BondType.SINGLE: "1", Chem.BondType.DOUBLE: "2",
                Chem.BondType.TRIPLE: "3", Chem.BondType.AROMATIC: "ar"}
        bond_lines = [f"{j+1:>6} {b.GetBeginAtomIdx()+1:>5} {b.GetEndAtomIdx()+1:>5} "
                      f"{BOND.get(b.GetBondType(), '1'):>2}"
                      for j, b in enumerate(mol.GetBonds())]
        return "\n".join([
            "@<TRIPOS>MOLECULE", "LIG",
            f" {mol.GetNumAtoms()} {mol.GetNumBonds()} 0 0 0", "SMALL", "GASTEIGER", "",
            "@<TRIPOS>ATOM", *atom_lines,
            "@<TRIPOS>BOND", *bond_lines, ""])
    except Exception:
        return None


def build_structure_zip(r):
    """Bundle the docked structures for external viewers. Per ligand: the docked
    complex, ligand, and receptor as PDB, plus ligand SDF (correct bonds) and
    MOL2 (best-effort). Returns zip bytes, or None if there's nothing to export."""
    import os
    import zipfile

    viz = r.get("viz") or {}
    rdf = r.get("rdf")
    meta = r.get("meta") or {}
    gene = re.sub(r"[^A-Za-z0-9_.-]", "_", str(meta.get("gene", "target"))) or "target"

    smiles_by = {}
    if rdf is not None:
        for _, row in rdf.iterrows():
            smiles_by[row.get("Ligand")] = row.get("SMILES")

    buf = io.BytesIO()
    receptor_written = False
    wrote_any = False
    readme = ["MUMO — docked structures", "=" * 25, "",
              f"Target: {meta.get('gene', '?')}",
              f"Pocket: {meta.get('pocket', 'n/a')}", "",
              "Files per ligand:",
              "  *_complex.pdb  — receptor + docked ligand pose (open this to see the pose)",
              "  *_ligand.pdb   — docked ligand only",
              "  *_ligand.sdf   — docked ligand with correct bond orders",
              "  *_ligand.mol2  — docked ligand (if available)",
              f"  {gene}_receptor.pdb — target protein only", "",
              "Open in Discovery Studio, Maestro/BIOLuminate, BIOVIA, PyMOL, ChimeraX, etc.",
              "Note: structures reflect the exact docked pose from this run.", "",
              "Ligands:"]

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for label, entry in viz.items():
            safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(label))[:40] or "ligand"
            try:
                with open(entry["complex"]) as f:
                    complex_pdb = f.read()
            except Exception:
                continue
            rec_pdb, lig_pdb = _split_complex_pdb(complex_pdb)
            z.writestr(f"{gene}_{safe}_complex.pdb", complex_pdb)
            wrote_any = True
            if lig_pdb:
                z.writestr(f"{safe}_ligand.pdb", lig_pdb)
                sdf = _ligand_sdf(lig_pdb, smiles_by.get(label))
                if sdf:
                    z.writestr(f"{safe}_ligand.sdf", sdf)
                mol2 = _ligand_mol2(lig_pdb, smiles_by.get(label))
                if mol2:
                    z.writestr(f"{safe}_ligand.mol2", mol2)
            if not receptor_written and rec_pdb:
                z.writestr(f"{gene}_receptor.pdb", rec_pdb)
                receptor_written = True
            readme.append(f"  - {label}")
        z.writestr("README.txt", "\n".join(readme) + "\n")

    return buf.getvalue() if wrote_any else None
