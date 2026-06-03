"""
MUMO — Unified Interface (preview)
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

Run with:  .venv\\Scripts\\streamlit.exe run src/preview_pipeline.py

This is the "One interface" from the brief. It handles ANY entry point:
    TARGET:  find from a disease  |  type my own gene/protein  |  upload my own PDB
    LIGAND:  let MUMO scout it    |  paste my own SMILES (one or many)
Then it docks every ligand against the target, profiles interactions (PLIP),
shows a results table, and lets you download it as CSV.
"""

import os, sys, io, re
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agents.target_finder import find_targets
from agents.ligand_scout import find_ligands
from agents.target_analyst import analyze_target, auto_grid_from_pdb
from agents.interaction_analyst import analyze_interactions
from agents.admet import resolve_ligand, druglikeness
from viz import render_complex_html
from setup_env import ensure_vina
from llm_client import get_llm
from brain import parse_intent, write_report
from docking_engine import (clean_protein_pdb, prepare_receptor,
                            prepare_ligand, run_docking, parse_docking_results)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data"); os.makedirs(DATA, exist_ok=True)
# venv scripts dir is Windows-only; on Linux the tools are on PATH (resolved in engine).
VENV = os.path.join(BASE, ".venv", "Scripts" if os.name == "nt" else "bin")
VINA = ensure_vina()

st.set_page_config(page_title="MUMO", page_icon="🧬", layout="wide")
# No forced colors — the UI follows the user's theme (light → dark text, dark → light text).
st.title("🧬 MUMO — Unified Drug Discovery Interface")
st.caption("Start from anything: a disease, your own target, or your own ligand. MUMO does the rest.")

# session memory
ss = st.session_state
ss.setdefault("target", None)     # dict: {gene, pdb_path, center, size, source}
ss.setdefault("ligands", None)    # list of {label, smiles}


# ─────────────────────────────────────────────────────────────────────────────
# SHARED PIPELINE — used by both the chat ("run it all") and the Section 3 button
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_receptor(tgt):
    """Get (pdb_path, center, size, pocket) for a target: user PDB or gene→AlphaFold."""
    if tgt.get("pdb_path"):
        return tgt["pdb_path"], tgt["center"], tgt["size"], tgt.get("source", "user PDB")
    info = analyze_target(tgt["gene"], DATA)
    return info["pdb_path"], info["center"], info["size"], info["pocket_source"]


def run_full_dock(tgt, ligands):
    """Prepare the receptor once, dock every ligand, store results + viz in session."""
    pdb_path, center, size, pocket = _resolve_receptor(tgt)
    cleaned = os.path.join(DATA, "u_cleaned.pdb")
    receptor = os.path.join(DATA, "u_receptor.pdbqt")
    clean_protein_pdb(pdb_path, cleaned)
    prepare_receptor(cleaned, receptor, VENV)
    st.caption(f"Receptor ready · box center {center} · {pocket}")

    rows, viz = [], {}
    prog = st.progress(0.0)
    for k, lig in enumerate(ligands):
        label = lig["label"]
        with st.spinner(f"Docking {label} ({k+1}/{len(ligands)})..."):
            try:
                ligf = os.path.join(DATA, f"u_lig_{k}.pdbqt")
                outp = os.path.join(DATA, f"u_out_{k}.pdbqt")
                cfg  = os.path.join(DATA, f"u_cfg_{k}.txt")
                cmplx = os.path.join(DATA, f"u_complex_{k}.pdb")
                prepare_ligand(lig["smiles"], ligf)
                logp = run_docking(VINA, receptor, ligf, outp, cfg, center, size)
                best, modes = parse_docking_results(logp)
                ia = analyze_interactions(cleaned, outp, cmplx)
                rows.append({
                    "Ligand": label, "SMILES": lig["smiles"],
                    "Best affinity (kcal/mol)": best, "Poses": len(modes),
                    "Total interactions": ia["total_interactions"], "H-bonds": ia["n_hbonds"],
                    "H-bond residues": "; ".join(ia["hbond_residues"]) or "-",
                    "Hydrophobic": ia["n_hydrophobic"], "Pi-stack": ia["n_pistacking"],
                    "Salt bridges": ia["n_saltbridges"], "Halogen": ia["n_halogen"],
                    "All interacting residues": "; ".join(ia["interacting_residues"]) or "-",
                })
                viz[label] = {"complex": cmplx,
                              "ia": {"lines": ia["lines"], "residue_numbers": ia["residue_numbers"]}}
            except Exception as le:
                rows.append({"Ligand": label, "SMILES": lig["smiles"],
                             "Best affinity (kcal/mol)": "FAILED", "Poses": 0,
                             "Total interactions": str(le)[:40]})
        prog.progress((k + 1) / len(ligands))

    rdf = pd.DataFrame(rows)
    num = pd.to_numeric(rdf["Best affinity (kcal/mol)"], errors="coerce")
    rdf = rdf.assign(_s=num).sort_values("_s").drop(columns="_s").reset_index(drop=True)
    rdf.index = range(1, len(rdf) + 1)
    ss["results_df"] = rdf
    ss["viz"] = viz
    ss["results_gene"] = tgt["gene"]
    return rdf


# ─────────────────────────────────────────────────────────────────────────────
# 💬 TALK TO MUMO — the conversational brain (fills the form below from English)
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("## 💬 Talk to MUMO")
_llm = get_llm()
if _llm:
    st.caption(f"🧠 LLM brain active — {_llm.provider} · {_llm.model}. Ask in plain English.")
else:
    st.caption("🧠 Free rule-based brain (no API key). Understands targets, SMILES, PDB IDs "
               "and diseases. Add an LLM key in secrets to unlock full natural language.")

with st.form("chat_form"):
    user_msg = st.text_input("Tell MUMO what you want",
        placeholder="e.g. 'I have a CFTR target, find me a drug and dock it'")
    fc1, fc2 = st.columns([1, 2])
    run_it = fc1.checkbox("🚀 Run it end-to-end", value=True,
                          help="MUMO scouts ligands if needed, then docks and analyses automatically.")
    n_auto = fc2.slider("If scouting: how many ligands to dock", 1, 5, 2)
    submitted = st.form_submit_button("🧠 Ask MUMO")

if submitted and user_msg.strip():
    res = parse_intent(user_msg, _llm)
    it = res["intent"]
    st.info(f"**MUMO understood** → disease: `{it['disease'] or '—'}` · "
            f"target: `{it['target'] or '—'}` · ligand: `{'given' if it['ligand'] else '—'}`\n\n"
            f"**Plan:** {res['reason']}")
    try:
        # normalize the ligand: accept a SMILES OR a drug name (e.g. "aspirin")
        if it["ligand"]:
            with st.spinner("Resolving your ligand..."):
                smi, label = resolve_ligand(it["ligand"])
            if smi:
                ss["ligands"] = [{"label": label, "smiles": smi}]
            else:
                st.warning(f"Couldn't recognise the ligand '{it['ligand']}'. "
                           "Give me a valid SMILES or a known drug name.")
        if it["target"]:
            tgt = it["target"]
            if re.match(r"^[1-9][A-Za-z0-9]{3}$", tgt):          # a PDB ID
                with st.spinner(f"Fetching {tgt} + detecting pocket..."):
                    r = requests.get(f"https://files.rcsb.org/download/{tgt}.pdb", timeout=30)
                    if r.status_code == 200:
                        raw = os.path.join(DATA, f"{tgt}_chat.pdb")
                        with open(raw, "wb") as f:
                            f.write(r.content)
                        c, s, pk = auto_grid_from_pdb(raw)
                        ss["target"] = {"gene": tgt, "source": f"chat · PDB {tgt} · {pk}",
                                        "pdb_path": raw, "center": c, "size": s}
            else:                                                 # a gene symbol
                ss["target"] = {"gene": tgt, "source": "chat · gene (AlphaFold)",
                                "pdb_path": None, "center": None, "size": None}
        elif it["disease"]:
            with st.spinner(f"Finding the top target for {it['disease']}..."):
                _, tlist = find_targets(it["disease"], limit=1)
            if tlist:
                ss["target"] = {"gene": tlist[0]["symbol"],
                                "source": f"chat · disease {it['disease']} → {tlist[0]['symbol']}",
                                "pdb_path": None, "center": None, "size": None}

        # ── Decide what to run — every combination handled ──
        if run_it and ss["target"]:
            # TARGET (+ optional ligand): scout if no ligand, then dock everything.
            if not ss["ligands"]:
                with st.spinner(f"Ligand Scout: fetching ligands for {ss['target']['gene']}..."):
                    _, ligs = find_ligands(ss["target"]["gene"], limit=int(n_auto))
                ss["ligands"] = [{"label": l["chembl_id"], "smiles": l["smiles"]} for l in ligs]
            st.info(f"🚀 Running the full pipeline: docking {len(ss['ligands'])} ligand(s) "
                    f"against {ss['target']['gene']}...")
            run_full_dock(ss["target"], ss["ligands"])
            st.success("✅ Done! Results, CSV, report, and the 3D view are below. 🎈")
            st.balloons()
        elif run_it and ss["ligands"]:
            # LIGAND ONLY (no target): can't dock — show its drug-likeness instead.
            lig = ss["ligands"][0]
            st.markdown(f"#### 💊 Drug-likeness of **{lig['label']}**")
            st.caption(f"SMILES: `{lig['smiles']}`")
            dl = druglikeness(lig["smiles"])
            st.table(pd.DataFrame(list(dl.items()), columns=["Property", "Value"]))
            st.info("📌 To **dock** this molecule, also give me a target or disease "
                    "(e.g. *“dock this against CFTR”*).")
        elif ss["target"] or ss["ligands"]:
            st.success("✅ Filled in the sections below — scroll down, adjust, and hit **Run docking**.")
        else:
            st.warning("I couldn't pin down a target or ligand. Try naming a gene, PDB ID, "
                       "disease, drug name, or SMILES.")
    except Exception as e:
        st.warning(f"Understood your request, but the run hit a snag: {e}")

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 — YOUR TARGET
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("## 1 · Your Target")
tmode = st.radio("How do you want to give MUMO the target?",
                 ["🔎 Find it from a disease", "🆔 Enter a PDB ID", "📁 Upload my own PDB"],
                 horizontal=True)
st.caption("ℹ️ Coming with the LLM upgrade: just type a target name and MUMO will fetch "
           "the AlphaFold structure and ask you to confirm before using it.")


def _lock_pdb_target(name, pdb_path, source):
    """Auto-detect the grid box for a PDB and lock it in as the target."""
    center, size, pocket = auto_grid_from_pdb(pdb_path)
    ss["target"] = {"gene": name, "source": f"{source} · {pocket}",
                    "pdb_path": pdb_path, "center": center, "size": size}


# --- 1a. disease -> target ---
if tmode.startswith("🔎"):
    c1, c2 = st.columns([3, 1])
    disease = c1.text_input("Disease", value="cystic fibrosis")
    nT = c2.number_input("Top N", 3, 20, 8)
    if st.button("Find targets"):
        try:
            with st.spinner("Target Finder querying Open Targets..."):
                dname, targets = find_targets(disease, limit=int(nT))
            ss["_disease_targets"] = targets
            ss["_disease_name"] = dname
        except Exception as e:
            st.error(f"Target Finder failed: {e}")
    if ss.get("_disease_targets"):
        tdf = pd.DataFrame(ss["_disease_targets"])
        tdf.index = range(1, len(tdf) + 1)
        st.dataframe(tdf.rename(columns={"symbol": "Gene", "score": "Evidence",
                     "name": "Full name", "ensembl_id": "Ensembl"}), use_container_width=True)
        genes = [t["symbol"] for t in ss["_disease_targets"]]
        gpick = st.selectbox("Choose the target to use", genes)
        if st.button(f"✅ Use {gpick} as my target"):
            ss["target"] = {"gene": gpick, "source": f"disease:{ss['_disease_name']}",
                            "pdb_path": None, "center": None, "size": None}

# --- 1b. fetch by PDB ID (auto grid) ---
elif tmode.startswith("🆔"):
    pid = st.text_input("PDB ID (4-letter code from rcsb.org)", value="6LU7").strip().upper()
    st.caption("MUMO fetches the structure from RCSB and auto-detects the binding pocket.")
    if st.button(f"✅ Fetch & use {pid}"):
        if len(pid) != 4:
            st.error("A PDB ID is exactly 4 characters, e.g. 6LU7.")
        else:
            try:
                with st.spinner(f"Fetching {pid} from RCSB + detecting pocket..."):
                    r = requests.get(f"https://files.rcsb.org/download/{pid}.pdb", timeout=30)
                    if r.status_code != 200:
                        raise ValueError(f"PDB ID '{pid}' not found on RCSB.")
                    raw = os.path.join(DATA, f"{pid}_fetched.pdb")
                    with open(raw, "wb") as f:
                        f.write(r.content)
                    _lock_pdb_target(pid, raw, f"PDB:{pid}")
            except Exception as e:
                st.error(f"Could not fetch {pid}: {e}")

# --- 1c. upload own PDB (auto grid) ---
else:
    up = st.file_uploader("Upload your protein .pdb", type=["pdb"])
    st.caption("MUMO auto-detects the grid box — no manual coordinates needed.")
    if st.button("✅ Use this PDB as my target"):
        if up is None:
            st.error("Please upload a .pdb file first.")
        else:
            raw = os.path.join(DATA, "user_target.pdb")
            with open(raw, "wb") as f:
                f.write(up.read())
            _lock_pdb_target(os.path.splitext(up.name)[0], raw, "uploaded PDB")

if ss["target"]:
    t = ss["target"]
    st.success(f"🎯 Target locked: **{t['gene']}**  ({t['source']})")
    if t.get("center"):
        with st.expander("🔧 Auto-detected grid box (optional: fine-tune)"):
            st.caption("MUMO set these automatically. Adjust only if you want a different pocket.")
            gc = st.columns(3)
            cx = gc[0].number_input("Center X", value=float(t["center"][0]), format="%.3f")
            cy = gc[1].number_input("Center Y", value=float(t["center"][1]), format="%.3f")
            cz = gc[2].number_input("Center Z", value=float(t["center"][2]), format="%.3f")
            gs = st.columns(3)
            sx = gs[0].number_input("Size X", value=float(t["size"][0]))
            sy = gs[1].number_input("Size Y", value=float(t["size"][1]))
            sz = gs[2].number_input("Size Z", value=float(t["size"][2]))
            t["center"], t["size"] = (cx, cy, cz), (sx, sy, sz)

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 — YOUR LIGAND(S)
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("## 2 · Your Ligand(s)")
lmode = st.radio("How do you want to give MUMO the ligand?",
                 ["🔬 Let MUMO scout ligands (ChEMBL)", "💊 I have my own SMILES"], horizontal=True)

if lmode.startswith("🔬"):
    if not ss["target"]:
        st.info("Lock a target above first, then MUMO can scout ligands for it.")
    else:
        nL = st.number_input("How many ligands to fetch", 1, 30, 5)
        if st.button("Scout ligands"):
            try:
                with st.spinner("Ligand Scout querying ChEMBL..."):
                    _, ligs = find_ligands(ss["target"]["gene"], limit=int(nL))
                ss["ligands"] = [{"label": l["chembl_id"], "smiles": l["smiles"]} for l in ligs]
            except Exception as e:
                st.error(f"Ligand Scout failed: {e}")
        if ss["ligands"]:
            st.dataframe(pd.DataFrame(ss["ligands"]), use_container_width=True)
else:
    txt = st.text_area("Paste one SMILES per line",
                       value="CC(=O)Oc1ccccc1C(=O)O", height=100,
                       help="One molecule per line. You can paste several to dock them all.")
    if st.button("✅ Use these SMILES"):
        lines = [s.strip() for s in txt.splitlines() if s.strip()]
        ss["ligands"] = [{"label": f"SMILES_{i+1}", "smiles": s} for i, s in enumerate(lines)]

if ss["ligands"]:
    st.success(f"💊 {len(ss['ligands'])} ligand(s) ready.")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 — DOCK + RESULTS + CSV
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("## 3 · Dock & Results")
if not ss["target"] or not ss["ligands"]:
    st.info("Lock a target (Section 1) and add ligand(s) (Section 2) to enable docking.")
else:
    st.caption(f"Ready to dock {len(ss['ligands'])} ligand(s) against {ss['target']['gene']}. "
               "~1 min per ligand.")
    if st.button("🚀 Run docking"):
        try:
            run_full_dock(ss["target"], ss["ligands"])
            st.balloons()
        except Exception as e:
            st.error(f"Docking run failed: {e}")

# --- results + CSV + 3D viewer (persist across reruns, e.g. when changing the viewer dropdown) ---
if ss.get("results_df") is not None:
    rdf = ss["results_df"]
    st.markdown("### 📊 Docking Results")
    st.dataframe(rdf, use_container_width=True)
    st.download_button("⬇ Download docking results (CSV)",
                       rdf.to_csv(index_label="Rank").encode("utf-8"),
                       file_name=f"MUMO_docking_{ss.get('results_gene','target')}.csv",
                       mime="text/csv")

    # ── 📝 Report Writer agent — narrative summary of the best hit ──
    st.markdown("### 📝 MUMO's Report")
    tier = st.radio("Report style", ["Simple", "Standard", "Ambitious"],
                    horizontal=True, index=1,
                    help="Simple = plain language · Standard = technical · Ambitious = publication-style")
    try:
        top = rdf.iloc[0]
        if str(top["Best affinity (kcal/mol)"]) != "FAILED":
            def _split(v):
                return [x for x in str(v).split("; ") if x and x != "-"]
            report_input = {
                "target": ss.get("results_gene", "target"),
                "ligand": top["Ligand"],
                "affinity": float(top["Best affinity (kcal/mol)"]),
                "total_interactions": top["Total interactions"],
                "n_hbonds": int(top["H-bonds"]),
                "hbond_residues": _split(top["H-bond residues"]),
                "n_hydrophobic": int(top["Hydrophobic"]),
                "interacting_residues": _split(top["All interacting residues"]),
            }
            with st.spinner("Report Writer composing..."):
                st.markdown(write_report(report_input, _llm, tier))
            if not _llm:
                st.caption("ℹ️ Template report (no LLM key). Add a key to get full narrative reports.")
        else:
            st.warning("Top result failed to dock — no report to write.")
    except Exception as e:
        st.caption(f"(Report unavailable: {e})")

    if ss.get("viz"):
        st.markdown("### 🧪 3D Interaction View  (rotate · zoom · screenshot for your paper)")
        choice = st.selectbox("Show pose for ligand", list(ss["viz"].keys()))

        with st.expander("⚙️ Visualization settings", expanded=True):
            r1 = st.columns(4)
            protein_style = r1[0].selectbox("Protein style",
                ["cartoon", "surface", "cartoon+surface", "stick", "line"])
            protein_color = r1[1].selectbox("Protein color",
                ["spectrum", "secondary structure", "grey", "white"])
            ligand_style = r1[2].selectbox("Ligand style",
                ["stick", "ball-and-stick", "sphere", "line"])
            ligand_carbon = r1[3].selectbox("Ligand color",
                ["greenCarbon", "cyanCarbon", "yellowCarbon", "magentaCarbon",
                 "orangeCarbon", "whiteCarbon"])

            r2 = st.columns(4)
            background = r2[0].color_picker("Background", "#0a0f1e")
            surface_opacity = r2[1].slider("Surface opacity", 0.0, 1.0, 0.6, 0.05)
            surface_color = r2[2].selectbox("Surface color", ["white", "grey", "lightblue"])
            spin = r2[3].checkbox("Auto-spin", value=False)

            r3 = st.columns(3)
            show_residues = r3[0].checkbox("Interacting residues", value=True)
            show_interactions = r3[1].checkbox("Interaction lines", value=True)
            show_labels = r3[2].checkbox("Residue labels", value=True)

        opts = {
            "protein_style": protein_style, "protein_color": protein_color,
            "ligand_style": ligand_style, "ligand_carbon": ligand_carbon,
            "background": background, "surface_opacity": surface_opacity,
            "surface_color": surface_color, "spin": spin,
            "show_residues": show_residues, "show_interactions": show_interactions,
            "show_labels": show_labels,
        }
        st.caption("Dashed lines: blue=H-bond · grey=hydrophobic · cyan=halogen · "
                   "green=π-stack · orange=salt bridge. Change any setting and the view updates.")
        entry = ss["viz"][choice]
        try:
            html = render_complex_html(entry["complex"], entry["ia"], options=opts)
            components.html(html, height=580)
        except Exception as e:
            st.warning(f"Could not render 3D view for {choice}: {e}")
