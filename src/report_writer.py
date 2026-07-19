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

    # ── Figures: the two views the per-ligand sections can't give you ──
    # The summary table has every number but no shape; these say which ligands
    # separate from the pack and which residues the whole series converges on.
    # Both are skipped when the data can't support them (see charts.py), so a
    # single-ligand report simply doesn't get a one-bar chart.
    try:
        import charts
        chart_rows = rdf.reset_index(drop=True).to_dict(orient="records")
        figures = [("Binding affinity", charts.affinity_chart_svg(chart_rows)),
                   ("Residue contact frequency", charts.residue_frequency_svg(chart_rows)),
                   ("Ligand × residue contact map", charts.contact_heatmap_svg(chart_rows))]
        drawn = [(cap, svg) for cap, svg in figures if svg]
        if drawn:
            doc.add_heading("Figures", level=1)
            for cap, svg in drawn:
                png, err = _shot("2d", svg)
                if png:
                    doc.add_picture(io.BytesIO(png), width=Inches(6.2))
                else:
                    doc.add_paragraph(f"[{cap} chart unavailable: {err}]")
    except Exception as e:
        # a figure is a nice-to-have; never lose the whole report over one
        doc.add_paragraph(f"[Charts unavailable: {type(e).__name__}: {e}]")

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


def build_metabolism_docx(r):
    """Metabolism report: narrative, the ROUTE DIAGRAM, then the table.

    The diagram is the point. A route written as "Aromatic hydroxylation ->
    O-glucuronidation" tells a chemist almost nothing on its own — they need to
    see which position was hydroxylated and what the conjugate looks like. So
    the structures are rendered and rasterized the same way the docking figures
    are, and the table follows as the precise reference.
    """
    from docx import Document
    from docx.shared import Inches
    import pandas as pd     # local: report_writer takes DataFrames in elsewhere

    pred = r.get("prediction") or {}
    mets = pred.get("metabolites") or []

    doc = Document()
    doc.add_heading(f"MUMO Metabolism Report — {r.get('lig_label', 'compound')}", level=0)
    doc.add_paragraph(f"Parent SMILES: {r.get('lig_smiles', '')}")
    n1 = sum(1 for m in mets if m.get("phase") == "I")
    n2 = sum(1 for m in mets if m.get("phase") == "II")
    doc.add_paragraph(f"{len(mets)} metabolites shown ({n1} phase I, {n2} phase II) "
                      f"of {pred.get('n_generated', 0)} generated.")

    if r.get("narrative"):
        doc.add_heading("Report", level=1)
        _add_markdown(doc, r["narrative"])

    # ── the route diagram ────────────────────────────────────────────────
    try:
        from agents.metabolism import pathway_svg
        svg = pathway_svg(pred, max_routes=6)
        if svg:
            pw = browser = None
            try:
                pw, browser = new_browser()
                png = svg_to_png(svg, browser, width=1500, height=1200)
                doc.add_heading("Predicted routes", level=1)
                doc.add_picture(io.BytesIO(png), width=Inches(6.4))
            finally:
                try:
                    if browser:
                        browser.close()
                    if pw:
                        pw.stop()
                except Exception:
                    pass
    except Exception as e:
        # the tables below still carry the substance — never lose the report
        doc.add_paragraph(f"[Route diagram unavailable: {type(e).__name__}: {e}]")

    if mets:
        doc.add_heading("Predicted metabolites", level=1)
        doc.add_paragraph("Score ranks likelihood; it is not a predicted amount.")
        rows = [{"Rank": i, "Metabolite (SMILES)": m["smiles"],
                 "Transformation": m["name"], "Phase": m["phase"],
                 "Score": m["score"], "Route": " -> ".join(m["pathway"])}
                for i, m in enumerate(mets, 1)]
        _add_df_table(doc, pd.DataFrame(rows))

    doc.add_heading("Method and limitations", level=1)
    doc.add_paragraph(pred.get("citation", ""))
    doc.add_paragraph(
        "Metabolites are generated by applying literature-derived phase I and "
        "phase II reaction rules to the parent structure, then to the products, "
        "so a phase I step can be followed by a phase II conjugation. Scores "
        "multiply along a route and rank relative likelihood only. These are "
        "computational hypotheses for experimental testing, not measurements, "
        "and absence from this list is not evidence a metabolite does not form.")

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


def _corrected_ligand_mol(lig_pdb, smiles=None):
    """RDKit ligand mol from the docked PDB block with bond orders restored from the
    known SMILES (a docked PDB has coordinates but NO bonds). Returns None on failure."""
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
    except Exception:
        return None
    mol = (Chem.MolFromPDBBlock(lig_pdb, sanitize=True, removeHs=False)
           or Chem.MolFromPDBBlock(lig_pdb, sanitize=False, removeHs=False))
    if mol is None:
        return None
    if smiles:
        try:
            tmpl = Chem.MolFromSmiles(smiles)
            if tmpl is not None:
                mol = AllChem.AssignBondOrdersFromTemplate(tmpl, mol)
        except Exception:
            pass
    return mol


def _add_ligand_conect(complex_pdb, lig_mol):
    """Append CONECT records for the ligand's bonds to a complex PDB, so viewers
    draw the ligand with its REAL connectivity instead of guessing bonds from atom
    distances (which tangles folded/large ligands). No-op if the atom counts don't
    line up."""
    if lig_mol is None:
        return complex_pdb
    serials = []
    for ln in complex_pdb.splitlines():
        if ln.startswith("HETATM") and ln[17:20].strip() == "LIG":
            try:
                serials.append(int(ln[6:11]))
            except ValueError:
                return complex_pdb
    if lig_mol.GetNumAtoms() != len(serials):
        return complex_pdb
    conect = [f"CONECT{serials[b.GetBeginAtomIdx()]:>5}{serials[b.GetEndAtomIdx()]:>5}"
              for b in lig_mol.GetBonds()]
    lines = [ln for ln in complex_pdb.splitlines() if ln.strip() != "END"]
    return "\n".join(lines + conect + ["END"]) + "\n"


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
    rank_by = {}
    if rdf is not None:
        for idx, row in rdf.iterrows():
            # A multi-target run keys its viz by "TARGET · ligand" so the same
            # ligand docked against two proteins doesn't overwrite itself, so
            # register BOTH forms — the plain name for a single-target run and
            # the composite for a screen.
            keys = [row.get("Ligand")]
            if row.get("Target"):
                keys.append(f'{row["Target"]} · {row.get("Ligand")}')
            for k in keys:
                smiles_by[k] = row.get("SMILES")
                rank_by[k] = idx                  # rdf is already sorted best→worst

    used_stems = set()

    def _stem(label, fallback_rank):
        """A unique, rank-prefixed filename stem for one ligand.

        Compound names are truncated to keep paths sane, and GC-MS peak lists are
        full of homologs that differ only in a suffix ('…-, methyl ester' vs
        '…-, octadecyl ester') — those collide once truncated, and a zip member
        written twice means the second silently replaces the first on extraction,
        losing a ligand's structures. The rank prefix makes the name unique AND
        lets a file be matched to its row in the results table.
        """
        base = re.sub(r"[^A-Za-z0-9_.-]", "_", str(label))[:40] or "ligand"
        stem = f"{rank_by.get(label, fallback_rank):02d}_{base}"
        if stem in used_stems:                    # belt and braces
            n = 2
            while f"{stem}_{n}" in used_stems:
                n += 1
            stem = f"{stem}_{n}"
        used_stems.add(stem)
        return stem

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
        for i, (label, entry) in enumerate(viz.items(), 1):
            safe = _stem(label, i)
            try:
                with open(entry["complex"]) as f:
                    complex_pdb = f.read()
            except Exception:
                continue
            rec_pdb, lig_pdb = _split_complex_pdb(complex_pdb)
            smi = smiles_by.get(label)
            # correct-bond ligand mol → used to add CONECT records so viewers show
            # the ligand with real bonds (not distance-guessed tangles)
            lig_mol = _corrected_ligand_mol(lig_pdb, smi) if lig_pdb else None
            z.writestr(f"{gene}_{safe}_complex.pdb", _add_ligand_conect(complex_pdb, lig_mol))
            wrote_any = True
            if lig_pdb:
                # ligand.pdb from the corrected mol (RDKit writes CONECT records) so
                # the standalone ligand also opens with correct bonds; else raw block
                lig_pdb_out = lig_pdb
                if lig_mol is not None:
                    try:
                        from rdkit import Chem
                        lig_pdb_out = Chem.MolToPDBBlock(lig_mol)
                    except Exception:
                        pass
                z.writestr(f"{safe}_ligand.pdb", lig_pdb_out)
                sdf = _ligand_sdf(lig_pdb, smi)
                if sdf:
                    z.writestr(f"{safe}_ligand.sdf", sdf)
                mol2 = _ligand_mol2(lig_pdb, smi)
                if mol2:
                    z.writestr(f"{safe}_ligand.mol2", mol2)
            if not receptor_written and rec_pdb:
                z.writestr(f"{gene}_receptor.pdb", rec_pdb)
                receptor_written = True
            readme.append(f"  - [{safe.split('_')[0]}] {label}")
        z.writestr("README.txt", "\n".join(readme) + "\n")

    return buf.getvalue() if wrote_any else None
