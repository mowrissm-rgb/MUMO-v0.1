"""
MUMO — Conversational Interface
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

A chat-first MUMO: you talk, MUMO asks clarifying questions (how many ligands?
how many targets? which report style? confirm the target), waits for your
answers, then runs the pipeline and opens the results in the right-hand panel.

Layout:  [ left sidebar = chat history ]  [ chat ]  [ results panel ]
Theme follows the user (light → dark text, dark → light text). No forced colors.
"""

import os, sys, re
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_client import get_llm
from brain import parse_intent, write_report
from agents.target_finder import find_targets
from agents.ligand_scout import find_ligands
from agents.target_analyst import auto_grid_from_pdb
from agents.admet import resolve_ligand, druglikeness
from pipeline import dock_pipeline
from viz import render_complex_html
from setup_env import ensure_vina

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data"); os.makedirs(DATA, exist_ok=True)
VENV = os.path.join(BASE, ".venv", "Scripts" if os.name == "nt" else "bin")
VINA = ensure_vina()

st.set_page_config(page_title="MUMO", page_icon="🧬", layout="centered")

# ── session ──
ss = st.session_state
ss.setdefault("messages", [])     # [{role, content}]
ss.setdefault("stage", "start")
ss.setdefault("convo", {})
ss.setdefault("results", None)    # {rdf, viz, meta}
ss.setdefault("run_now", False)
ss.setdefault("history", [])      # [{title, messages, results}]
ss.setdefault("panel_open", False)  # is the right results drawer open?
_llm = get_llm()


def theme_bg():
    """3D background follows the app theme: dark → black, light → white."""
    try:
        return "#0b0d12" if st.context.theme.type == "dark" else "#ffffff"
    except Exception:
        return "#0b0d12"


# ── tiny helpers ──
def say(text):
    ss.messages.append({"role": "assistant", "content": text})

def parse_int(msg, default):
    m = re.search(r"\d+", msg)
    return max(1, min(20, int(m.group()))) if m else default

def is_yes(msg):
    return any(w in msg.lower() for w in
               ["yes", "yeah", "yep", "sure", "ok", "okay", "proceed", "go ahead",
                "correct", "use it", "do it", "perfect", "right"])

def parse_tier(msg):
    l = msg.lower()
    return "Simple" if "simple" in l else "Ambitious" if "ambit" in l else "Standard"

def pick_target(msg, candidates):
    up = msg.upper()
    for c in candidates:
        if c["symbol"].upper() in up:
            return c["symbol"]
    if is_yes(msg):
        return candidates[0]["symbol"]
    m = re.search(r"[A-Z][A-Z0-9]{1,6}", up)
    return m.group() if m else candidates[0]["symbol"]


# ── conversation flow (asks one question, then waits) ──
def ask_after_target():
    """Once a target is set, ask for ligand count (or skip if ligand given), then tier."""
    c = ss.convo
    if c.get("ligand_smiles"):
        say("Which **report style** would you like — *Simple*, *Standard*, or *Ambitious*? (default Standard)")
        ss.stage = "tier"
    else:
        say(f"How many **ligands** should I scout from ChEMBL for **{c['target']}**? (default 5)")
        ss.stage = "n_ligands"

def handle(msg):
    ss.messages.append({"role": "user", "content": msg})
    stage = ss.stage

    if stage == "start":
        with st.spinner("Thinking…"):
            intent = parse_intent(msg, _llm)["intent"]
        c = ss.convo = {"disease": intent["disease"], "target": intent["target"],
                        "ligand_smiles": None, "ligand_label": None,
                        "n_ligands": None, "tier": None, "candidates": None}
        if intent["ligand"]:
            smi, label = resolve_ligand(intent["ligand"])
            if smi:
                c["ligand_smiles"], c["ligand_label"] = smi, label

        # decide the route — disease first (evidence-based target finding via Open Targets)
        if c["disease"]:
            c["target"] = None   # don't trust the LLM's guess; we'll find it from evidence
            say(f"Got it — a disease: **{c['disease']}**. How many candidate **targets** "
                f"should I consider before picking the best one? (default 5)")
            ss.stage = "n_targets"
        elif c["target"]:
            c["candidates"] = [{"symbol": c["target"]}]
            if c["ligand_label"]:
                lig_phrase = (f" with **{c['ligand_label']}**"
                              if c["ligand_label"] != "your molecule"
                              else " with the molecule you gave")
            else:
                lig_phrase = ""
            say(f"Got it — target **{c['target']}**{lig_phrase}. "
                f"Shall I proceed with this target? (yes / or name another)")
            ss.stage = "confirm_target"
        elif c["ligand_smiles"]:
            say(f"Got it — molecule **{c['ligand_label']}**, but no target given, so I can't dock yet. "
                f"Here's its **drug-likeness** on the right. Give me a target or disease and I'll dock it.")
            ss.results = {"druglikeness": druglikeness(c["ligand_smiles"]),
                          "lig_label": c["ligand_label"], "lig_smiles": c["ligand_smiles"]}
            ss.panel_open = True
            ss.stage = "start"
        else:
            say("I can start from a **disease**, a **target** (gene or PDB ID), or a **ligand** "
                "(drug name or SMILES). What are we working on?")
            ss.stage = "start"

    elif stage == "n_targets":
        c = ss.convo
        n = parse_int(msg, 5)
        with st.spinner(f"Searching Open Targets for {c['disease']}…"):
            _, targets = find_targets(c["disease"], n)
        c["candidates"] = targets
        lst = ", ".join(f"{t['symbol']} ({t['score']})" for t in targets[:n])
        say(f"Top evidence-scored targets: {lst}.\n\nI'd go with **{targets[0]['symbol']}** "
            f"(highest evidence). Use it, or name another from the list?")
        ss.stage = "confirm_target"

    elif stage == "confirm_target":
        c = ss.convo
        c["target"] = pick_target(msg, c["candidates"])
        say(f"Locked target: **{c['target']}**.")
        ask_after_target()

    elif stage == "n_ligands":
        ss.convo["n_ligands"] = parse_int(msg, 5)
        say("Which **report style** — *Simple*, *Standard*, or *Ambitious*? (default Standard)")
        ss.stage = "tier"

    elif stage == "tier":
        ss.convo["tier"] = parse_tier(msg)
        say(f"On it — running the full pipeline now. Watch the right panel. ⚙️")
        ss.stage = "running"
        ss.run_now = True


def build_target(c):
    """Turn the chosen target string into a dockable target dict (gene or PDB ID)."""
    t = c["target"]
    if re.match(r"^[1-9][A-Za-z0-9]{3}$", t):       # PDB ID
        r = requests.get(f"https://files.rcsb.org/download/{t}.pdb", timeout=30)
        raw = os.path.join(DATA, f"{t}_chat.pdb")
        with open(raw, "wb") as f:
            f.write(r.content)
        center, size, pocket = auto_grid_from_pdb(raw)
        return {"gene": t, "pdb_path": raw, "center": center, "size": size, "source": f"PDB {t} · {pocket}"}
    return {"gene": t, "pdb_path": None, "center": None, "size": None, "source": "gene (AlphaFold)"}


def run_pipeline(status_area):
    c = ss.convo
    tgt = build_target(c)
    if c.get("ligand_smiles"):
        ligands = [{"label": c["ligand_label"], "smiles": c["ligand_smiles"]}]
    else:
        status_area.write(f"🔬 Scouting {c['n_ligands']} ligands for {tgt['gene']}…")
        _, ligs = find_ligands(tgt["gene"], limit=c["n_ligands"])
        ligands = [{"label": l["chembl_id"], "smiles": l["smiles"]} for l in ligs]

    rows, viz, meta = dock_pipeline(tgt, ligands, VINA, DATA, VENV,
                                    status=lambda m: status_area.write(m))
    rdf = pd.DataFrame(rows)
    num = pd.to_numeric(rdf["Best affinity (kcal/mol)"], errors="coerce")
    rdf = rdf.assign(_s=num).sort_values("_s").drop(columns="_s").reset_index(drop=True)
    rdf.index = range(1, len(rdf) + 1)
    ss.results = {"rdf": rdf, "viz": viz, "meta": meta, "tier": c["tier"] or "Standard"}

    # narrative report on the best hit
    top = rdf.iloc[0]
    if str(top["Best affinity (kcal/mol)"]) != "FAILED":
        def _sp(v): return [x for x in str(v).split("; ") if x and x != "-"]
        rep = write_report({"target": meta["gene"], "ligand": top["Ligand"],
                            "affinity": float(top["Best affinity (kcal/mol)"]),
                            "total_interactions": top["Total interactions"],
                            "n_hbonds": int(top["H-bonds"]), "hbond_residues": _sp(top["H-bond residues"]),
                            "n_hydrophobic": int(top["Hydrophobic"]),
                            "interacting_residues": _sp(top["All interacting residues"])},
                           _llm, ss.results["tier"])
        say(f"✅ Done! Best hit **{top['Ligand']}** at **{top['Best affinity (kcal/mol)']} "
            f"kcal/mol** against {meta['gene']}. Full results & 3D pose are on the right.\n\n{rep}")
    else:
        say("The docking didn't produce a valid pose — see the right panel.")
    ss.stage = "start"


# ════════════════════════════════════════════════════════════════════════════
# LAYOUT
# ════════════════════════════════════════════════════════════════════════════

# ── left sidebar: history ──
with st.sidebar:
    st.markdown("### 🧬 MUMO")
    if st.button("➕  New chat", use_container_width=True):
        if ss.messages:
            title = next((m["content"] for m in ss.messages if m["role"] == "user"), "Chat")
            ss.history.insert(0, {"title": title[:40], "messages": ss.messages, "results": ss.results})
        ss.messages, ss.stage, ss.convo, ss.results, ss.run_now = [], "start", {}, None, False
        st.rerun()
    st.markdown("---")
    st.caption("History")
    for i, h in enumerate(ss.history[:15]):
        if st.button(f"💬 {h['title']}", key=f"h{i}", use_container_width=True):
            ss.messages, ss.results, ss.stage = h["messages"], h["results"], "start"
            st.rerun()

# ── read chat input (pinned at bottom) ──
user_input = st.chat_input("Message MUMO…  e.g. “find a drug for cystic fibrosis”")
if user_input and user_input.strip():
    handle(user_input.strip())

# ── run the pipeline (full width; opens the panel when done) ──
if ss.run_now:
    ss.run_now = False
    with st.status("Running the pipeline…", expanded=True) as status_area:
        try:
            run_pipeline(status_area)
            status_area.update(label="Done ✅", state="complete")
            ss.panel_open = True
        except Exception as e:
            say(f"⚠️ The run hit a snag: {e}")
            status_area.update(label="Failed", state="error")
    st.rerun()


def render_results():
    r = ss.results
    if "druglikeness" in r:
        st.markdown(f"#### 💊 Drug-likeness — {r['lig_label']}")
        st.caption(f"`{r['lig_smiles']}`")
        st.table(pd.DataFrame(list(r["druglikeness"].items()), columns=["Property", "Value"]))
    else:
        rdf = r["rdf"]
        st.markdown(f"#### 📊 Docking results — {r['meta']['gene']}")
        st.dataframe(rdf, use_container_width=True, height=200)
        st.download_button("⬇ CSV", rdf.to_csv(index_label="Rank").encode("utf-8"),
                           file_name=f"MUMO_{r['meta']['gene']}.csv", mime="text/csv")
        if r.get("viz"):
            st.markdown("##### 🧪 3D pose & interactions")
            choice = st.selectbox("Ligand", list(r["viz"].keys()), label_visibility="collapsed")

            with st.expander("⚙️ Visualization settings", expanded=False):
                a = st.columns(3)
                protein_style = a[0].selectbox("Protein style", ["cartoon", "cartoon+surface",
                                               "surface", "stick", "line"], key="vp_style")
                protein_color = a[1].selectbox("Protein color", ["spectrum",
                                               "secondary structure", "grey", "white"], key="vp_color")
                surface_color = a[2].selectbox("Surface color", ["white", "grey", "lightblue"], key="vp_surfc")

                f = st.columns(3)
                cartoon_style = f[0].selectbox("Ribbon style", ["default", "trace",
                                               "rectangle", "edged"], key="vp_cstyle")
                protein_opacity = f[1].slider("Protein opacity", 0.2, 1.0, 1.0, 0.05, key="vp_op")
                label_size = f[2].slider("Label size", 8, 20, 11, 1, key="v_lsize")

                b = st.columns(3)
                ligand_style = b[0].selectbox("Ligand style", ["stick", "ball-and-stick",
                                              "sphere", "line"], key="vl_style")
                ligand_carbon = b[1].selectbox("Ligand color", ["greenCarbon", "cyanCarbon",
                                               "yellowCarbon", "magentaCarbon", "orangeCarbon",
                                               "whiteCarbon"], key="vl_color")
                ligand_radius = b[2].slider("Ligand thickness", 0.1, 0.4, 0.22, 0.02, key="vl_rad")

                d = st.columns(2)
                surface_opacity = d[0].slider("Surface opacity", 0.0, 1.0, 0.5, 0.05, key="v_surf")
                zoom = d[1].slider("Zoom", 0.3, 1.5, 0.6, 0.05, key="v_zoom")

                e = st.columns(4)
                show_residues = e[0].checkbox("Residues", value=True, key="v_res")
                show_interactions = e[1].checkbox("Interactions", value=True, key="v_int")
                show_labels = e[2].checkbox("Labels", value=True, key="v_lab")
                spin = e[3].checkbox("Spin", value=False, key="v_spin")

            opts = {"protein_style": protein_style, "protein_color": protein_color,
                    "cartoon_style": cartoon_style, "protein_opacity": protein_opacity,
                    "surface_color": surface_color, "surface_opacity": surface_opacity,
                    "ligand_style": ligand_style, "ligand_carbon": ligand_carbon,
                    "ligand_radius": ligand_radius, "zoom": zoom,
                    "show_residues": show_residues, "show_interactions": show_interactions,
                    "show_labels": show_labels, "label_size": label_size, "spin": spin,
                    "background": theme_bg()}   # bg auto-follows the app theme
            entry = r["viz"][choice]
            try:
                components.html(render_complex_html(entry["complex"], entry["ia"],
                                options=opts, height=520), height=540)
            except Exception as e:
                st.caption(f"(3D view unavailable: {e})")


def render_chat():
    if not ss.messages:
        st.markdown("<div style='text-align:center;margin-top:18vh;'>"
                    "<h1>🧬 MUMO</h1>"
                    "<p style='opacity:0.6;'>Tell me what to work on — a disease, a target, or a molecule.<br>"
                    "I'll ask what I need, then dock it.</p></div>", unsafe_allow_html=True)
    for m in ss.messages:
        with st.chat_message(m["role"], avatar="🧬" if m["role"] == "assistant" else "🧑"):
            st.markdown(m["content"])


# ── chat (full width) ──
render_chat()

# ── results, as usual, at the bottom (full width, below the conversation) ──
if ss.results:
    st.divider()
    render_results()
