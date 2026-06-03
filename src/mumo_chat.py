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
import json as _json
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


def say(text):
    ss.messages.append({"role": "assistant", "content": text})


# ── LLM-driven conversation — the brain reads every reply IN CONTEXT ──
CONV_SYSTEM = (
    "You are MUMO, a warm, intelligent drug-discovery assistant. Your job is to dock a "
    "ligand into a protein target and report the result. To run a docking you need:\n"
    "• TARGET: a gene/protein name (CFTR, EGFR…) or a 4-character PDB ID (6LU7, 1NFK…), "
    "OR a DISEASE (you derive the target from it).\n"
    "• LIGAND (optional): a drug name (aspirin, lupeol…) or a SMILES string. If the user "
    "has none, you scout candidates automatically.\n"
    "• TIER: report style — Simple, Standard, or Ambitious.\n\n"
    "Act like a smart human assistant:\n"
    "• Read each message IN CONTEXT of the conversation and what is already known.\n"
    "• If a message is off-topic, vague or random (e.g. 'hi', 'ok', 'm', 'thanks', 'lol'), "
    "reply warmly and gently RE-ASK for the next thing you need. NEVER invent or assume "
    "values the user did not actually give, and NEVER move forward on nonsense.\n"
    "• Fix obvious gene typos (CTRF→CFTR, EGRF→EGFR) and recognise drug names.\n"
    "• Ask for what's missing one item at a time, briefly and naturally.\n"
    "• Set ready_to_dock=true ONLY when you have (a target OR a disease) AND a tier.\n"
    "• Set analyze_only=true if the user only wants a molecule's drug-likeness, no docking.\n\n"
    "Reply with ONLY a JSON object and nothing else:\n"
    '{"disease": <string|null>, "target": <gene or 4-char PDB ID|null>, '
    '"ligand": <drug name or SMILES the user gave|null>, '
    '"tier": <"Simple"|"Standard"|"Ambitious"|null>, '
    '"reply": "<your short friendly message>", '
    '"ready_to_dock": <true|false>, "analyze_only": <true|false>}'
)


def _history_text(n=10):
    return "\n".join(f'{m["role"]}: {m["content"]}' for m in ss.messages[-n:])


def converse(msg):
    """One conversational turn, driven by the LLM (with a minimal no-key fallback)."""
    ss.messages.append({"role": "user", "content": msg})
    c = ss.convo

    # ── no LLM key: minimal rule-based fallback ──
    if _llm is None:
        intent = parse_intent(msg, None)["intent"]
        if intent["target"] or intent["disease"]:
            c.update({"target": intent["target"], "disease": intent["disease"], "tier": "Standard"})
            if intent["ligand"]:
                smi, label = resolve_ligand(intent["ligand"])
                if smi:
                    c["ligand_smiles"], c["ligand_label"] = smi, label
            say("Running it now (basic mode — add an LLM key for full conversation). Results below. ⚙️")
            ss.run_now = True
        else:
            say("Tell me a target and a ligand, e.g. *“dock 6LU7 with aspirin”*. "
                "(Add an LLM key in secrets for smart conversation.)")
        return

    # ── LLM-driven turn ──
    known = {k: c.get(k) for k in ("disease", "target", "ligand", "tier")}
    prompt = (f"Known so far: {_json.dumps(known)}\n\n"
              f"Conversation:\n{_history_text()}\n\n"
              f'The user just said: "{msg}"\n\nReturn the JSON.')
    try:
        with st.spinner("Thinking…"):
            raw = _llm.chat(CONV_SYSTEM, prompt, temperature=0.3, max_tokens=400)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        data = _json.loads(match.group(0))
    except Exception:
        say("Sorry — my brain hiccupped just now. Could you say that again?")
        return

    for k in ("disease", "target", "ligand", "tier"):
        if data.get(k):
            c[k] = data[k]
    say(data.get("reply") or "Okay.")

    # analyze-only → drug-likeness, no docking
    if data.get("analyze_only") and c.get("ligand"):
        smi, label = resolve_ligand(str(c["ligand"]))
        if smi:
            ss.results = {"druglikeness": druglikeness(smi), "lig_label": label, "lig_smiles": smi}
        return

    if data.get("ready_to_dock"):
        # always resolve the CURRENT ligand fresh (don't reuse a previous one)
        if c.get("ligand"):
            smi, label = resolve_ligand(str(c["ligand"]))
            c["ligand_smiles"], c["ligand_label"] = (smi, label) if smi else (None, None)
        else:
            c["ligand_smiles"] = None
        c["tier"] = c.get("tier") or "Standard"
        ss.run_now = True


def build_target(c):
    """Turn the chosen target string into a dockable target dict (gene or PDB ID)."""
    t = c["target"]
    if re.match(r"^[1-9][A-Za-z0-9]{3}$", t):       # PDB ID — fetch from RCSB (with retries)
        content = None
        for attempt in range(3):
            try:
                r = requests.get(f"https://files.rcsb.org/download/{t}.pdb", timeout=45)
                if r.status_code == 200 and r.content:
                    content = r.content
                    break
            except Exception:
                pass
        if content is None:
            raise RuntimeError(f"Couldn't download {t} from RCSB (network was slow). Please try again.")
        raw = os.path.join(DATA, f"{t}_chat.pdb")
        with open(raw, "wb") as f:
            f.write(content)
        center, size, pocket = auto_grid_from_pdb(raw)
        return {"gene": t, "pdb_path": raw, "center": center, "size": size, "source": f"PDB {t} · {pocket}"}
    return {"gene": t, "pdb_path": None, "center": None, "size": None, "source": "gene (AlphaFold)"}


def run_pipeline(status_area):
    c = ss.convo
    # resolve a disease into its top target (Open Targets) if we don't have one
    if not c.get("target") and c.get("disease"):
        status_area.write(f"🔎 Finding the top target for {c['disease']}…")
        try:
            _, tl = find_targets(c["disease"], 5)
            if tl:
                c["target"] = tl[0]["symbol"]
        except Exception:
            pass
    if not c.get("target"):
        say("I couldn't pin down a target — tell me a gene, PDB ID, or disease.")
        return

    tgt = build_target(c)
    if c.get("ligand_smiles"):
        ligands = [{"label": c["ligand_label"], "smiles": c["ligand_smiles"]}]
    else:
        n = c.get("n_ligands") or 3
        status_area.write(f"🔬 Scouting {n} ligands for {tgt['gene']}…")
        try:
            _, ligs = find_ligands(tgt["gene"], limit=n)
        except Exception:
            ligs = []
        ligands = [{"label": l["chembl_id"], "smiles": l["smiles"]} for l in ligs]

    # guard: nothing to dock (e.g. scouting a raw PDB ID returns nothing)
    if not ligands:
        say(f"⚠️ I couldn't find ligands to dock against **{tgt['gene']}**. "
            f"Scouting works for gene/protein targets, not raw PDB IDs — "
            f"tell me a specific ligand, e.g. *“dock {tgt['gene']} with aspirin”*.")
        ss.stage = "start"
        return

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
            f"kcal/mol** against {meta['gene']}. Full results & 3D pose are below.\n\n{rep}")
    else:
        say("The docking didn't produce a valid pose — see the results below.")
    ss.convo = {}   # reset for the next, independent request


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
    converse(user_input.strip())

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

                pocket_only = st.checkbox("Pocket only (lighter view)", value=False, key="v_pocket")

            opts = {"protein_style": protein_style, "protein_color": protein_color,
                    "cartoon_style": cartoon_style, "protein_opacity": protein_opacity,
                    "surface_color": surface_color, "surface_opacity": surface_opacity,
                    "ligand_style": ligand_style, "ligand_carbon": ligand_carbon,
                    "ligand_radius": ligand_radius, "zoom": zoom,
                    "show_residues": show_residues, "show_interactions": show_interactions,
                    "show_labels": show_labels, "label_size": label_size, "spin": spin,
                    "pocket_only": pocket_only,
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
