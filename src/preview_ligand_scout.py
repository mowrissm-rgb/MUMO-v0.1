"""
MUMO — Ligand Scout PREVIEW (standalone interactive page)
Run with:  .venv\\Scripts\\streamlit.exe run src/preview_ligand_scout.py

This is a playground so Mowriss can try the Ligand Scout agent on any target,
tune how many ligands and how potent, and see results live. Use it to explore
and enhance efficacy before we wire Ligand Scout into the main MUMO app.
"""

import os, sys
import streamlit as st
import pandas as pd

# let this file import the agents/ package next to it
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agents.ligand_scout import find_ligands

st.set_page_config(page_title="MUMO · Ligand Scout", page_icon="🔬", layout="wide")

# ── light dark-theme polish (matches main app accent colour) ──
st.markdown("""
<style>
.stApp { background: linear-gradient(135deg,#0a0f1e,#0d1528); }
h1 { color:#00d4aa !important; }
</style>
""", unsafe_allow_html=True)

st.title("🔬 MUMO · Ligand Scout")
st.caption("Give it a target — it finds the strongest known ligands from ChEMBL (free, no API key).")

# ── controls ──
c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    target = st.text_input("Target (gene / protein name or ChEMBL ID)", value="CFTR",
                           help="e.g. CFTR, EGFR, TNF, ACE2, or a CHEMBL target ID")
with c2:
    n = st.slider("How many ligands", 3, 30, 10)
with c3:
    min_p = st.slider("Min potency (pChEMBL)", 5.0, 9.0, 6.0, 0.5,
                      help="Higher = only stronger binders. 6.0 ≈ 1 µM, 9.0 ≈ 1 nM.")

if st.button("🚀 Scout ligands", use_container_width=True):
    try:
        with st.spinner(f"Searching ChEMBL for the best ligands against {target}..."):
            name, hits = find_ligands(target, limit=n, min_pchembl=min_p)

        if not hits:
            st.warning("No ligands found above that potency. Try lowering the potency slider.")
        else:
            st.success(f"Target matched: **{name}** — found {len(hits)} candidate ligands.")
            df = pd.DataFrame(hits)
            df.index = range(1, len(df) + 1)
            df = df.rename(columns={
                "chembl_id": "ChEMBL ID", "smiles": "SMILES",
                "activity_type": "Assay", "value": "Value",
                "units": "Units", "pchembl": "pChEMBL",
            })
            st.dataframe(df[["ChEMBL ID", "Assay", "Value", "Units", "pChEMBL", "SMILES"]],
                         use_container_width=True)
            st.download_button("⬇ Download as CSV", df.to_csv().encode("utf-8"),
                               file_name=f"MUMO_ligands_{target}.csv", mime="text/csv")
            st.info("Next in MUMO: each SMILES above gets sent to the Docking Engine automatically.")
    except Exception as e:
        st.error(f"Something went wrong: {e}")
