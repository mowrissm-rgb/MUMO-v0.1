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
    Returns None (rather than raising) if the CDN 3Dmol.js load times out."""
    from viz import render_complex_html
    html = render_complex_html(complex_pdb_path, ia, options=options, width=width, height=height)
    page = browser.new_page(viewport={"width": width, "height": height + 20})
    try:
        page.set_content(f"<html><body style='margin:0;'>{html}</body></html>")
        page.wait_for_function("window.__mumoReady === true", timeout=20000)
        page.wait_for_timeout(200)  # let the final zoom/render settle
        return page.locator("#mumoview").screenshot()
    except Exception:
        return None
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
    summary_cols = ["Ligand", "Best affinity (kcal/mol)", "Vinardo (kcal/mol)", "Consensus",
                     "Pose consistency", "Confidence", "Total interactions", "H-bonds"]
    cols = [c for c in summary_cols if c in rdf.columns]
    summary = rdf[cols].reset_index().rename(columns={"index": "Rank"})
    _add_df_table(doc, summary)

    pw = browser = None
    try:
        pw, browser = new_browser()
    except Exception:
        pass

    try:
        for rank, row in rdf.iterrows():
            label = row["Ligand"]
            doc.add_page_break()
            doc.add_heading(f"#{rank} — {label}", level=1)
            if str(row["Best affinity (kcal/mol)"]) == "FAILED":
                doc.add_paragraph(f"Docking failed for this ligand: {row.get('Total interactions', '')}")
                continue

            _add_kv_table(doc, [(c, row[c]) for c in cols if c != "Ligand"])

            def _sp(v):
                return [x for x in str(v).split("; ") if x and x != "-"]

            writeup = write_report({
                "target": meta.get("gene"), "ligand": label,
                "affinity": float(row["Best affinity (kcal/mol)"]),
                "total_interactions": row.get("Total interactions"),
                "n_hbonds": int(row.get("H-bonds", 0) or 0),
                "hbond_residues": _sp(row.get("H-bond residues", "")),
                "n_hydrophobic": int(row.get("Hydrophobic", 0) or 0),
                "interacting_residues": _sp(row.get("All interacting residues", "")),
            }, llm, r.get("tier", "Standard"))
            doc.add_heading("Interpretation", level=2)
            _add_markdown(doc, writeup)

            entry = viz.get(label)
            if entry and browser:
                svg = entry["ia"].get("svg_2d")
                if svg:
                    doc.add_heading("2D interaction diagram", level=2)
                    try:
                        png = svg_to_png(svg, browser)
                        doc.add_picture(io.BytesIO(png), width=Inches(5.5))
                    except Exception:
                        doc.add_paragraph("(2D diagram could not be rendered.)")

                doc.add_heading("3D pose", level=2)
                try:
                    png3d = png_from_3d(entry["complex"], entry["ia"], browser)
                    if png3d:
                        doc.add_picture(io.BytesIO(png3d), width=Inches(5.5))
                    else:
                        doc.add_paragraph("(3D pose could not be rendered.)")
                except Exception:
                    doc.add_paragraph("(3D pose could not be rendered.)")
    finally:
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
        try:
            pw, browser = new_browser()
            try:
                png = svg_to_png(svg, browser, width=900, height=700)
                doc.add_picture(io.BytesIO(png), width=Inches(6.0))
            finally:
                browser.close()
                pw.stop()
        except Exception:
            doc.add_paragraph("(Network image could not be rendered.)")

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
