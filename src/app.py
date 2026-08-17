"""
MUMO Web Application - Phase 1 POC Interface
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Antigravity AI Partner
"""

import streamlit as st
import sys
import os
import time
import threading
import queue
import io
import requests

# Make sure our src/ folder can be imported by Streamlit
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from docking_engine import (
    clean_protein_pdb,
    prepare_receptor,
    prepare_ligand,
    run_docking,
    parse_docking_results
)

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MUMO | Drug Discovery AI Platform",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# CUSTOM CSS — Premium Dark UI
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

/* ── Main background ── */
.stApp {
    background: linear-gradient(135deg, #0a0f1e 0%, #0d1528 50%, #0a1520 100%);
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0d1528 0%, #111827 100%);
    border-right: 1px solid rgba(0, 212, 170, 0.15);
}

/* ── Header banner ── */
.mumo-header {
    background: linear-gradient(135deg, rgba(0,212,170,0.08) 0%, rgba(0,100,200,0.08) 100%);
    border: 1px solid rgba(0, 212, 170, 0.2);
    border-radius: 16px;
    padding: 2rem 2.5rem;
    margin-bottom: 2rem;
    position: relative;
    overflow: hidden;
}
.mumo-header::before {
    content: '';
    position: absolute;
    top: -50%;
    left: -50%;
    width: 200%;
    height: 200%;
    background: radial-gradient(circle, rgba(0,212,170,0.03) 0%, transparent 60%);
    animation: pulse 4s ease-in-out infinite;
}
@keyframes pulse {
    0%, 100% { transform: scale(1); opacity: 1; }
    50% { transform: scale(1.05); opacity: 0.7; }
}
.mumo-title {
    font-size: 2.8rem;
    font-weight: 700;
    background: linear-gradient(135deg, #00d4aa, #0099ff);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin: 0;
    letter-spacing: -1px;
}
.mumo-subtitle {
    color: rgba(226,232,240,0.6);
    font-size: 0.95rem;
    margin-top: 0.4rem;
    font-weight: 300;
    letter-spacing: 0.5px;
}

/* ── Section cards ── */
.mumo-card {
    background: rgba(17, 24, 39, 0.8);
    border: 1px solid rgba(0, 212, 170, 0.12);
    border-radius: 12px;
    padding: 1.5rem;
    margin-bottom: 1rem;
    backdrop-filter: blur(10px);
    transition: border-color 0.3s ease;
}
.mumo-card:hover {
    border-color: rgba(0, 212, 170, 0.3);
}

/* ── Section label ── */
.section-label {
    color: #00d4aa;
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 2px;
    margin-bottom: 0.5rem;
}

/* ── Result score card ── */
.score-card {
    background: linear-gradient(135deg, rgba(0,212,170,0.1), rgba(0,100,200,0.1));
    border: 1px solid rgba(0,212,170,0.4);
    border-radius: 16px;
    padding: 2rem;
    text-align: center;
}
.score-value {
    font-size: 3.5rem;
    font-weight: 700;
    font-family: 'JetBrains Mono', monospace;
    color: #00d4aa;
    line-height: 1;
}
.score-unit {
    color: rgba(226,232,240,0.5);
    font-size: 0.85rem;
    margin-top: 0.3rem;
}
.score-label {
    color: rgba(226,232,240,0.7);
    font-size: 0.9rem;
    margin-top: 0.5rem;
}

/* ── Log console ── */
.log-console {
    background: #050a14;
    border: 1px solid rgba(0,212,170,0.15);
    border-radius: 10px;
    padding: 1rem 1.2rem;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.75rem;
    color: #7fdbca;
    max-height: 300px;
    overflow-y: auto;
    line-height: 1.8;
}

/* ── Status badges ── */
.badge-success {
    background: rgba(0,212,170,0.15);
    color: #00d4aa;
    border: 1px solid rgba(0,212,170,0.3);
    border-radius: 20px;
    padding: 0.25rem 0.8rem;
    font-size: 0.75rem;
    font-weight: 600;
}
.badge-warning {
    background: rgba(255,165,0,0.15);
    color: #ffa500;
    border: 1px solid rgba(255,165,0,0.3);
    border-radius: 20px;
    padding: 0.25rem 0.8rem;
    font-size: 0.75rem;
    font-weight: 600;
}

/* ── Buttons ── */
.stButton > button {
    background: linear-gradient(135deg, #00d4aa, #0077cc);
    color: white;
    border: none;
    border-radius: 10px;
    padding: 0.7rem 2rem;
    font-weight: 600;
    font-size: 1rem;
    width: 100%;
    transition: all 0.3s ease;
    letter-spacing: 0.5px;
}
.stButton > button:hover {
    background: linear-gradient(135deg, #00e8bb, #0088ee);
    transform: translateY(-2px);
    box-shadow: 0 8px 25px rgba(0,212,170,0.3);
}

/* ── Divider ── */
hr {
    border: none;
    border-top: 1px solid rgba(0,212,170,0.12);
    margin: 1.5rem 0;
}

/* ── Input labels ── */
.stTextInput label, .stNumberInput label, .stSelectbox label, .stTextArea label {
    color: rgba(226,232,240,0.8) !important;
    font-size: 0.85rem !important;
    font-weight: 500 !important;
}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="mumo-header">
    <p class="mumo-title">🧬 MUMO</p>
    <p class="mumo-subtitle">Multi-Agent Drug Discovery & Development AI Platform &nbsp;·&nbsp; Phase 1 Docking Engine &nbsp;·&nbsp; Built by Mowriss</p>
</div>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# PATH CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR     = os.path.join(BASE_DIR, "data")
BIN_DIR      = os.path.join(BASE_DIR, "bin")
VENV_SCRIPTS = os.path.join(BASE_DIR, ".venv", "Scripts")
VINA_PATH    = os.path.join(BIN_DIR, "vina.exe")
os.makedirs(DATA_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR — INPUTS
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<p class="section-label">⚙ Configuration</p>', unsafe_allow_html=True)

    # ── Target Protein ──────────────────────────────────────────────────────
    st.markdown("### 🎯 Target Protein")
    protein_source = st.radio(
        "Protein source",
        options=["Fetch from PDB (by ID)", "Upload local .pdb file"],
        index=0
    )

    pdb_id_input  = ""
    uploaded_file = None

    if protein_source == "Fetch from PDB (by ID)":
        pdb_id_input = st.text_input(
            "PDB ID",
            value="6LU7",
            placeholder="e.g. 6LU7, 1HTQ, 2V92",
            help="A 4-letter code from the RCSB Protein Data Bank (rcsb.org)"
        ).strip().upper()
    else:
        uploaded_file = st.file_uploader("Upload .pdb file", type=["pdb"])

    st.markdown("---")

    # ── Ligand ──────────────────────────────────────────────────────────────
    st.markdown("### 💊 Drug Candidate (Ligand)")

    preset_smiles = {
        "Custom / Paste your own": "",
        "Aspirin": "CC(=O)Oc1ccccc1C(=O)O",
        "Ibuprofen": "CC(C)Cc1ccc(cc1)C(C)C(=O)O",
        "Caffeine": "Cn1cnc2c1c(=O)n(c(=O)n2C)C",
        "Paracetamol": "CC(=O)Nc1ccc(O)cc1",
        "Quercetin": "O=c1c(O)c(-c2ccc(O)c(O)c2)oc2cc(O)cc(O)c12",
    }

    ligand_preset = st.selectbox(
        "Quick pick (or enter your own below)",
        options=list(preset_smiles.keys())
    )

    default_smiles = preset_smiles[ligand_preset]
    smiles_input = st.text_area(
        "SMILES String",
        value=default_smiles,
        placeholder="Paste SMILES here, e.g. CC(=O)Oc1ccccc1C(=O)O",
        height=80,
        help="SMILES (Simplified Molecular Input Line Entry System) is a text-based representation of a chemical structure."
    ).strip()

    st.markdown("---")

    # ── Grid Box ─────────────────────────────────────────────────────────────
    st.markdown("### 📦 Docking Grid Box")
    st.caption("Define the active site search space on the protein.")

    col_cx, col_cy, col_cz = st.columns(3)
    with col_cx:
        center_x = st.number_input("Center X", value=-10.807, format="%.3f")
    with col_cy:
        center_y = st.number_input("Center Y", value=12.541, format="%.3f")
    with col_cz:
        center_z = st.number_input("Center Z", value=68.917, format="%.3f")

    col_sx, col_sy, col_sz = st.columns(3)
    with col_sx:
        size_x = st.number_input("Size X (Å)", value=30.0, min_value=5.0, max_value=100.0, format="%.1f")
    with col_sy:
        size_y = st.number_input("Size Y (Å)", value=30.0, min_value=5.0, max_value=100.0, format="%.1f")
    with col_sz:
        size_z = st.number_input("Size Z (Å)", value=30.0, min_value=5.0, max_value=100.0, format="%.1f")

    st.markdown("---")

    # ── Run Button ───────────────────────────────────────────────────────────
    run_btn = st.button("🚀 Run Docking Simulation", use_container_width=True)

# ─────────────────────────────────────────────────────────────────────────────
# MAIN AREA — HOW IT WORKS (default state)
# ─────────────────────────────────────────────────────────────────────────────
if not run_btn:
    st.markdown('<p class="section-label">How MUMO Works</p>', unsafe_allow_html=True)

    col1, col2, col3, col4, col5 = st.columns(5)
    steps = [
        ("🎯", "Target Analyst", "Fetches and cleans the protein structure"),
        ("🔬", "Ligand Scout", "Converts your SMILES into a 3D structure"),
        ("⚙️", "Docking Engine", "Runs AutoDock Vina simulation"),
        ("📊", "Score Analyst", "Extracts binding affinity scores"),
        ("📄", "Report Writer", "Compiles results into a clean report"),
    ]
    for col, (icon, title, desc) in zip([col1, col2, col3, col4, col5], steps):
        with col:
            st.markdown(f"""
            <div class="mumo-card" style="text-align:center; height:160px;">
                <div style="font-size:2rem; margin-bottom:0.5rem;">{icon}</div>
                <div style="font-weight:600; color:#e2e8f0; font-size:0.85rem; margin-bottom:0.4rem;">{title}</div>
                <div style="color:rgba(226,232,240,0.45); font-size:0.72rem; line-height:1.5;">{desc}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("""
    <div class="mumo-card">
        <p class="section-label">Quick Start Guide</p>
        <ol style="color:rgba(226,232,240,0.75); font-size:0.88rem; line-height:2.2;">
            <li>Enter a <b style="color:#00d4aa">PDB ID</b> in the sidebar (e.g. <code>6LU7</code> for SARS-CoV-2 Main Protease)</li>
            <li>Select a <b style="color:#00d4aa">drug candidate</b> from the presets, or paste your own SMILES string</li>
            <li>Set the <b style="color:#00d4aa">grid box</b> to define the active site search space</li>
            <li>Click <b style="color:#00d4aa">Run Docking Simulation</b> and watch the pipeline execute live</li>
            <li>Review the <b style="color:#00d4aa">binding affinity score</b> and all docking poses in the results table</li>
        </ol>
    </div>
    """, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# MAIN AREA — DOCKING EXECUTION
# ─────────────────────────────────────────────────────────────────────────────
if run_btn:
    # ── Validation ────────────────────────────────────────────────────────────
    errors = []
    if protein_source == "Fetch from PDB (by ID)" and len(pdb_id_input) != 4:
        errors.append("PDB ID must be exactly 4 characters (e.g. 6LU7).")
    if protein_source == "Upload local .pdb file" and uploaded_file is None:
        errors.append("Please upload a .pdb file.")
    if not smiles_input:
        errors.append("Please enter a SMILES string for your drug candidate.")

    if errors:
        for e in errors:
            st.error(f"⚠️ {e}")
        st.stop()

    st.markdown('<p class="section-label">🔬 Running Docking Pipeline</p>', unsafe_allow_html=True)
    log_area    = st.empty()
    status_area = st.empty()
    log_lines   = []

    def log(msg):
        icon = "✅" if msg.startswith("[Prep]") or msg.startswith("[Dock]") or msg.startswith("[Results]") else \
               "⚙️" if msg.startswith("[Exec]") else \
               "⚠️" if msg.startswith("[Warning]") else \
               "❌" if msg.startswith("[Error]") else "→"
        log_lines.append(f"{icon}  {msg}")
        log_area.markdown(
            '<div class="log-console">' +
            "<br>".join(log_lines[-18:]) +
            "</div>",
            unsafe_allow_html=True
        )
        time.sleep(0.05)

    try:
        # ── Step 1: Get protein PDB ───────────────────────────────────────────
        protein_name = pdb_id_input if protein_source == "Fetch from PDB (by ID)" else \
                       os.path.splitext(uploaded_file.name)[0]
        raw_pdb_path = os.path.join(DATA_DIR, f"{protein_name}_raw.pdb")

        if protein_source == "Fetch from PDB (by ID)":
            status_area.info(f"🌐 Fetching protein structure **{pdb_id_input}** from RCSB PDB...")
            log(f"[Prep] Fetching {pdb_id_input}.pdb from RCSB Protein Data Bank...")
            url = f"https://files.rcsb.org/download/{pdb_id_input}.pdb"
            resp = requests.get(url, timeout=30)
            if resp.status_code != 200:
                st.error(f"❌ Could not fetch PDB ID `{pdb_id_input}`. Please check the ID and try again.")
                st.stop()
            with open(raw_pdb_path, "wb") as f:
                f.write(resp.content)
            log(f"[Prep] Downloaded {pdb_id_input}.pdb ({len(resp.content)//1024} KB)")
        else:
            log(f"[Prep] Saving uploaded file: {uploaded_file.name}")
            with open(raw_pdb_path, "wb") as f:
                f.write(uploaded_file.read())
            log(f"[Prep] Uploaded PDB saved to data directory.")

        # ── Step 2: Clean protein ─────────────────────────────────────────────
        status_area.info("🧹 Cleaning protein structure...")
        cleaned_pdb    = os.path.join(DATA_DIR, f"{protein_name}_cleaned.pdb")
        receptor_pdbqt = os.path.join(DATA_DIR, f"{protein_name}_prepared.pdbqt")
        ligand_pdbqt   = os.path.join(DATA_DIR, "ligand_prepared.pdbqt")
        output_pdbqt   = os.path.join(DATA_DIR, "docking_output.pdbqt")
        config_path    = os.path.join(DATA_DIR, "vina_config.txt")

        # Redirect print() from docking_engine functions into our log
        import io
        from contextlib import redirect_stdout

        captured = io.StringIO()
        with redirect_stdout(captured):
            clean_protein_pdb(raw_pdb_path, cleaned_pdb)
        for line in captured.getvalue().strip().split("\n"):
            if line.strip():
                log(line.strip())

        # ── Step 3: Prepare receptor ──────────────────────────────────────────
        status_area.info("⚗️ Preparing receptor (adding atom types & charges)...")
        captured = io.StringIO()
        with redirect_stdout(captured):
            prepare_receptor(cleaned_pdb, receptor_pdbqt, VENV_SCRIPTS)
        for line in captured.getvalue().strip().split("\n"):
            if line.strip():
                log(line.strip())

        # ── Step 4: Prepare ligand ────────────────────────────────────────────
        status_area.info("🔗 Generating 3D structure for drug candidate...")
        captured = io.StringIO()
        with redirect_stdout(captured):
            prepare_ligand(smiles_input, ligand_pdbqt)
        for line in captured.getvalue().strip().split("\n"):
            if line.strip():
                log(line.strip())

        # ── Step 5: Run Vina docking ──────────────────────────────────────────
        status_area.info("⚡ Running AutoDock Vina... This may take 30–60 seconds.")
        log("[Dock] Launching AutoDock Vina simulation...")
        captured = io.StringIO()
        with redirect_stdout(captured):
            log_path = run_docking(
                vina_path      = VINA_PATH,
                receptor_pdbqt = receptor_pdbqt,
                ligand_pdbqt   = ligand_pdbqt,
                output_pdbqt   = output_pdbqt,
                config_path    = config_path,
                center         = (center_x, center_y, center_z),
                size           = (size_x, size_y, size_z)
            )
        for line in captured.getvalue().strip().split("\n"):
            if line.strip():
                log(line.strip())

        # ── Step 6: Parse results ─────────────────────────────────────────────
        best_score, all_scores = parse_docking_results(log_path)
        log(f"[Results] Docking complete! Best binding energy: {best_score} kcal/mol")
        status_area.success("✅ Docking simulation completed successfully!")

        # ─────────────────────────────────────────────────────────────────────
        # RESULTS DASHBOARD
        # ─────────────────────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown('<p class="section-label">📊 Docking Results</p>', unsafe_allow_html=True)

        col_score, col_info = st.columns([1, 2])

        with col_score:
            # Interpret the score
            if best_score <= -8.0:
                interpretation = "🟢 Very Strong Binding"
                badge_class    = "badge-success"
            elif best_score <= -6.0:
                interpretation = "🟡 Good Binding"
                badge_class    = "badge-success"
            elif best_score <= -4.0:
                interpretation = "🟠 Moderate Binding"
                badge_class    = "badge-warning"
            else:
                interpretation = "🔴 Weak Binding"
                badge_class    = "badge-warning"

            st.markdown(f"""
            <div class="score-card">
                <div class="score-value">{best_score}</div>
                <div class="score-unit">kcal / mol</div>
                <div class="score-label">Best Binding Affinity</div>
                <div style="margin-top:1rem;">
                    <span class="{badge_class}">{interpretation}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

        with col_info:
            st.markdown('<div class="mumo-card">', unsafe_allow_html=True)
            st.markdown("**📋 Simulation Summary**")
            st.markdown(f"- **Target Protein:** `{protein_name}`")
            st.markdown(f"- **Ligand SMILES:** `{smiles_input}`")
            st.markdown(f"- **Grid Center:** X={center_x}, Y={center_y}, Z={center_z}")
            st.markdown(f"- **Grid Size:** {size_x} × {size_y} × {size_z} Å")
            st.markdown(f"- **Docking Modes Generated:** {len(all_scores)}")
            st.markdown("""
            ---
            > **What does the score mean?**
            > Binding affinity (ΔG) in kcal/mol tells us how strongly the drug candidate binds to the protein.
            > A more **negative** score = **stronger** binding = better drug candidate.
            > Scores below **-7 kcal/mol** are generally considered promising in early screening.
            """)
            st.markdown('</div>', unsafe_allow_html=True)

        # ── Score table ───────────────────────────────────────────────────────
        st.markdown("**📈 All Docking Modes**")
        import pandas as pd
        df = pd.DataFrame(all_scores, columns=["Mode", "Affinity (kcal/mol)"])
        df["Interpretation"] = df["Affinity (kcal/mol)"].apply(
            lambda x: "⭐ Best Pose" if x == best_score else
                      "✅ Strong" if x <= -7.0 else
                      "🟡 Moderate" if x <= -5.0 else "🔴 Weak"
        )
        st.dataframe(df, use_container_width=True, hide_index=True)

        # ── Download buttons ──────────────────────────────────────────────────
        st.markdown("**📥 Download Results**")
        dl_col1, dl_col2 = st.columns(2)

        with dl_col1:
            if os.path.exists(output_pdbqt):
                with open(output_pdbqt, "rb") as f:
                    st.download_button(
                        label     = "⬇ Download Docked Complex (.pdbqt)",
                        data      = f,
                        file_name = f"MUMO_{protein_name}_docked.pdbqt",
                        mime      = "text/plain"
                    )

        with dl_col2:
            if os.path.exists(log_path):
                with open(log_path, "r") as f:
                    st.download_button(
                        label     = "⬇ Download Vina Log (.txt)",
                        data      = f.read(),
                        file_name = f"MUMO_{protein_name}_vina.log",
                        mime      = "text/plain"
                    )

    except Exception as e:
        log(f"[Error] {str(e)}")
        status_area.error(f"❌ An error occurred: {str(e)}")
        st.exception(e)

# ─────────────────────────────────────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("""
<div style="text-align:center; color:rgba(226,232,240,0.3); font-size:0.75rem; padding:1rem 0;">
    <b style="color:rgba(0,212,170,0.5);">MUMO v0.1</b> &nbsp;·&nbsp; Phase 1 Proof of Concept &nbsp;·&nbsp;
    Powered by AutoDock Vina 1.2.5 · RDKit · Meeko &nbsp;·&nbsp;
    Built by <b style="color:rgba(0,212,170,0.5);">Mowriss</b>
</div>
""", unsafe_allow_html=True)
