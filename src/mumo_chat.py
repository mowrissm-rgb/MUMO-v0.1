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

st.set_page_config(page_title="MUMO", page_icon="⚛️", layout="centered")

# ── MUMO product theme (dark, gradient logo, teal accent) ──
st.markdown("""
<style>
.stApp {
    background:
      radial-gradient(1200px 600px at 80% -10%, rgba(45,212,191,0.08), transparent 60%),
      radial-gradient(900px 500px at 0% 110%, rgba(99,102,241,0.10), transparent 55%),
      #0a0e1a;
}
.block-container { padding-top: 2.5rem; max-width: 840px; }

/* Sidebar */
[data-testid="stSidebar"] {
    background: #0c1120;
    border-right: 1px solid rgba(148,163,184,0.08);
}
[data-testid="stSidebar"] .stButton button {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(148,163,184,0.12);
    color: #cbd5e1; border-radius: 10px;
    text-align: left; justify-content: flex-start; font-weight: 500;
}
[data-testid="stSidebar"] .stButton button:hover {
    border-color: rgba(45,212,191,0.5); color: #fff;
    background: rgba(45,212,191,0.06);
}
.mumo-brand { display:flex; align-items:center; gap:.55rem; margin:.2rem 0 1rem .1rem; }
.mumo-brand .wm {
    font-size:1.5rem; font-weight:800; letter-spacing:.5px;
    background: linear-gradient(90deg,#818cf8,#22d3ee,#34d399);
    -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent;
}
.mumo-hero-logo { display:flex; align-items:center; justify-content:center; gap:16px; margin-bottom:.2rem; }

/* Chat bubbles + input */
[data-testid="stChatMessage"] {
    background: rgba(255,255,255,0.025);
    border: 1px solid rgba(148,163,184,0.10);
    border-radius: 14px; padding:.4rem .6rem;
}
[data-testid^="stChatMessageAvatar"] { display:none !important; }
[data-testid="stChatMessageContent"] { margin-left:0 !important; }
[data-testid="stChatInput"] {
    border: 1px solid rgba(148,163,184,0.15) !important;
    border-radius: 16px !important; background: #0f1626 !important;
}

/* Welcome hero */
.mumo-hero {
    text-align:center; margin: 9vh auto 0; padding: 3rem 2rem;
    max-width: 680px;
    display:flex; flex-direction:column; align-items:center; justify-content:center;
    border-radius: 24px;
    background: linear-gradient(180deg, rgba(255,255,255,0.035), rgba(255,255,255,0.008));
    border: 1px solid rgba(148,163,184,0.10);
}
.mumo-hero-title {
    font-size: 4.6rem; font-weight: 900; line-height:1; letter-spacing:1px; margin:0;
    background: linear-gradient(90deg,#818cf8,#22d3ee,#34d399);
    -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent;
}
.mumo-hero-sub {
    margin: 1.3rem auto 0; max-width: 580px;
    font-size: 1.4rem; font-weight: 600; color:#e6edf6; line-height:1.45;
}
.mumo-pills {
    display:flex; gap:1.7rem; justify-content:center; flex-wrap:wrap;
    margin-top: 1.7rem; color: rgba(148,163,184,0.75); font-size:.92rem;
}
.mumo-pills span { white-space:nowrap; }
</style>
""", unsafe_allow_html=True)

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


def mol_logo(size=28, gid="mg"):
    """Inline SVG of a clean hexagonal molecule — MUMO's professional brand mark."""
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 64 64" '
        'xmlns="http://www.w3.org/2000/svg" style="vertical-align:middle;">'
        f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="64" y2="64" '
        'gradientUnits="userSpaceOnUse">'
        '<stop offset="0" stop-color="#818cf8"/><stop offset="0.5" stop-color="#22d3ee"/>'
        '<stop offset="1" stop-color="#34d399"/></linearGradient></defs>'
        f'<g stroke="url(#{gid})" stroke-width="2.6" stroke-linecap="round" '
        'stroke-linejoin="round" fill="none">'
        '<polygon points="32,12 48,21 48,39 32,48 16,39 16,21"/>'
        '<line x1="48" y1="21" x2="58" y2="15"/><line x1="16" y1="39" x2="6" y2="45"/>'
        '<line x1="32" y1="48" x2="32" y2="59"/></g>'
        f'<g fill="url(#{gid})">'
        '<circle cx="32" cy="12" r="3.4"/><circle cx="48" cy="21" r="3.4"/>'
        '<circle cx="48" cy="39" r="3.4"/><circle cx="32" cy="48" r="3.4"/>'
        '<circle cx="16" cy="39" r="3.4"/><circle cx="16" cy="21" r="3.4"/>'
        '<circle cx="58" cy="15" r="3"/><circle cx="6" cy="45" r="3"/>'
        '<circle cx="32" cy="59" r="3"/></g></svg>'
    )


# ── LLM-driven conversation — the brain reads every reply IN CONTEXT ──
CONV_SYSTEM = (
    "You are MUMO — a warm, brilliant drug-discovery partner: part pharmacologist, part "
    "computational chemist, part toxicologist, and a patient TUTOR. You talk like a smart, "
    "kind expert helping a curious student.\n\n"
    "WHAT YOU CAN DO:\n"
    "1) ANSWER any drug-discovery / pharmacology / chemistry / biology question (what is "
    "CFTR, what is molecular docking, what is a good binding score, what is ADMET…).\n"
    "2) TEACH step by step. If the user is unsure, doesn't know a term, or asks "
    "'how / why / what', walk them through the procedure step by step: say WHAT each step "
    "does and WHY it matters, define EVERY piece of jargon in plain words, and give the "
    "background knowledge they need before moving on. Never assume prior knowledge.\n"
    "3) EXPLAIN RESULTS. When docking results are provided below, use the ACTUAL numbers to "
    "answer ('is this score good?', 'which ligand is best and why?', 'explain these "
    "interactions'). Read affinity as: about -7 kcal/mol or lower = strong, -5 to -7 = "
    "moderate, above -5 = weak.\n"
    "4) RUN DOCKING. To dock you need a TARGET (gene/protein like CFTR or EGFR, or a "
    "4-char PDB ID like 6LU7) OR a DISEASE (you derive the target). A LIGAND is optional "
    "(a drug name like aspirin, a SMILES, or SEVERAL for a comparison); if none is given "
    "you scout candidates automatically. Report TIER defaults to Standard — don't pester "
    "for it.\n\n"
    "HOW TO BEHAVE:\n"
    "• Read every message IN CONTEXT of the whole conversation and what is already known. "
    "Remember what the user already told you; never re-ask it.\n"
    "• Understand messy, vague or multi-part requests. For a comparison "
    "('compare aspirin and ibuprofen on EGFR') return ligand as a LIST.\n"
    "• Fix obvious gene typos (CTRF→CFTR, EGRF→EGFR); map plain descriptions to genes "
    "('lung mucus protein'→MUC5B).\n"
    "• If a message is random/off-topic ('hi','ok','m'), reply warmly and gently steer "
    "back. NEVER invent values the user did not give.\n"
    "• NEVER use emojis. Keep a clean, professional tone in every reply.\n"
    "• Choose ACTION each turn:\n"
    "   - 'dock'    : you have a target OR disease and the user wants to run it.\n"
    "   - 'analyze' : the user only wants a molecule's drug-likeness, no docking.\n"
    "   - 'chat'    : everything else — answering, teaching, explaining results, or asking "
    "ONE clarifying question. When unsure, use 'chat'.\n\n"
    "Reply with ONLY a JSON object, nothing else:\n"
    '{"action": "chat"|"dock"|"analyze", '
    '"disease": <string|null>, "target": <gene or 4-char PDB ID|null>, '
    '"ligand": <drug name, SMILES, or a LIST of them|null>, '
    '"tier": <"Simple"|"Standard"|"Ambitious"|null>, '
    '"reply": "<your message — a full helpful/teaching answer, an explanation of the '
    'results, a short clarifying question, or a brief \'running it now\' note>"}'
)


def _history_text(n=10):
    return "\n".join(f'{m["role"]}: {m["content"]}' for m in ss.messages[-n:])


def _resolve_ligands(lig):
    """Resolve a ligand (name/SMILES) OR a list of them into [{label, smiles}]."""
    if not lig:
        return []
    items = lig if isinstance(lig, list) else [lig]
    out = []
    for x in items:
        smi, label = resolve_ligand(str(x))
        if smi:
            out.append({"label": label, "smiles": smi})
    return out


def _results_context():
    """Summarise the latest results so the brain can discuss them with real numbers."""
    r = ss.results
    if not r:
        return "Docking results so far: none yet."
    if "druglikeness" in r:
        return (f"Latest analysis — drug-likeness of {r['lig_label']} "
                f"({r['lig_smiles']}): {_json.dumps(r['druglikeness'])}")
    rdf = r["rdf"]
    rows = []
    for _, row in rdf.head(5).iterrows():
        rows.append(f"- {row['Ligand']}: {row['Best affinity (kcal/mol)']} kcal/mol, "
                    f"{row['H-bonds']} H-bonds, {row['Total interactions']} total interactions; "
                    f"residues: {row['All interacting residues']}")
    return (f"Latest docking results — target {r['meta']['gene']} "
            f"(more negative kcal/mol = stronger binding):\n" + "\n".join(rows))


def converse(msg):
    """One conversational turn — MUMO can teach, answer, explain results, or dock."""
    ss.messages.append({"role": "user", "content": msg})
    c = ss.convo

    # ── no LLM key: minimal rule-based fallback (dock-only) ──
    if _llm is None:
        intent = parse_intent(msg, None)["intent"]
        if intent["target"] or intent["disease"]:
            c.update({"target": intent["target"], "disease": intent["disease"], "tier": "Standard"})
            if intent["ligand"]:
                c["ligand"] = intent["ligand"]
            c["ligand_objs"] = _resolve_ligands(c.get("ligand"))
            say("Running it now (basic mode — add an LLM key to unlock questions, "
                "teaching and result explanations). Results below.")
            ss.run_now = True
        else:
            say("Tell me a target and a ligand, e.g. *“dock 6LU7 with aspirin”*. "
                "(Add an LLM key in secrets to unlock questions, teaching and smart chat.)")
        return

    # ── LLM-driven turn (full context: known slots + latest results + history) ──
    known = {k: c.get(k) for k in ("disease", "target", "ligand", "tier")}
    prompt = (f"Known so far: {_json.dumps(known)}\n"
              f"{_results_context()}\n\n"
              f"Conversation:\n{_history_text(14)}\n\n"
              f'The user just said: "{msg}"\n\nReturn the JSON.')
    try:
        with st.spinner("Thinking…"):
            raw = _llm.chat(CONV_SYSTEM, prompt, temperature=0.3, max_tokens=900)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        data = _json.loads(match.group(0))
    except Exception:
        say("Sorry — my brain hiccupped just now. Could you say that again?")
        return

    for k in ("disease", "target", "tier"):
        if data.get(k):
            c[k] = data[k]
    if data.get("ligand"):
        c["ligand"] = data["ligand"]
    say(data.get("reply") or "Okay.")

    action = (data.get("action") or "chat").lower()

    # analyze-only → drug-likeness, no docking
    if action == "analyze" and c.get("ligand"):
        one = c["ligand"][0] if isinstance(c["ligand"], list) else c["ligand"]
        smi, label = resolve_ligand(str(one))
        if smi:
            ss.results = {"druglikeness": druglikeness(smi), "lig_label": label, "lig_smiles": smi}
        return

    if action == "dock":
        # resolve the CURRENT ligand(s) fresh (supports a single name OR a comparison list)
        c["ligand_objs"] = _resolve_ligands(c.get("ligand"))
        c["tier"] = c.get("tier") or "Standard"
        ss.run_now = True
    # action == "chat" → the reply IS the whole answer; nothing more to run


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
        status_area.write(f"Finding the top target for {c['disease']}…")
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
    if c.get("ligand_objs"):
        ligands = c["ligand_objs"]
    else:
        n = c.get("n_ligands") or 3
        status_area.write(f"Scouting {n} ligands for {tgt['gene']}…")
        try:
            _, ligs = find_ligands(tgt["gene"], limit=n)
        except Exception:
            ligs = []
        ligands = [{"label": l["chembl_id"], "smiles": l["smiles"]} for l in ligs]

    # guard: nothing to dock (e.g. scouting a raw PDB ID returns nothing)
    if not ligands:
        say(f"I couldn't find ligands to dock against **{tgt['gene']}**. "
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
        msd = top.get("Mean ± SD (kcal/mol)", "—")
        rep_note = (f" (mean ± SD {msd}, confidence {top.get('Confidence','—')})"
                    if msd and msd != "—" else "")
        val = meta.get("validation")
        val_note = ""
        if val:
            verdict = "<2 Å — setup validated" if val["passed"] else ">2 Å — interpret with care"
            val_note = (f" Setup validation: native ligand {val['resname']} redocked to "
                        f"{val['rmsd']} Å RMSD ({verdict}).")
        say(f"Done. Best hit **{top['Ligand']}** at **{top['Best affinity (kcal/mol)']} "
            f"kcal/mol**{rep_note} against {meta['gene']} "
            f"[exhaustiveness {meta.get('exhaustiveness','?')}, {meta.get('replicas','?')} replica(s)].{val_note} "
            f"Full results & 3D pose are below.\n\n{rep}")
    else:
        say("The docking didn't produce a valid pose — see the results below.")
    ss.convo = {}   # reset for the next, independent request


# ════════════════════════════════════════════════════════════════════════════
# LAYOUT
# ════════════════════════════════════════════════════════════════════════════

# ── left sidebar: history ──
with st.sidebar:
    st.markdown(f"<div class='mumo-brand'>{mol_logo(26, 'mgSide')}<span class='wm'>MUMO</span></div>",
                unsafe_allow_html=True)
    if st.button("New chat", use_container_width=True):
        if ss.messages:
            title = next((m["content"] for m in ss.messages if m["role"] == "user"), "Chat")
            ss.history.insert(0, {"title": title[:40], "messages": ss.messages, "results": ss.results})
        ss.messages, ss.stage, ss.convo, ss.results, ss.run_now = [], "start", {}, None, False
        st.rerun()

    st.markdown("---")
    st.caption("History")
    for i, h in enumerate(ss.history[:15]):
        if st.button(f"{h['title']}", key=f"h{i}", use_container_width=True):
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
            status_area.update(label="Done", state="complete")
            ss.panel_open = True
        except Exception as e:
            say(f"The run hit a snag: {e}")
            status_area.update(label="Failed", state="error")
    st.rerun()


def render_results():
    r = ss.results
    if "druglikeness" in r:
        st.markdown(f"#### Drug-likeness — {r['lig_label']}")
        st.caption(f"`{r['lig_smiles']}`")
        st.table(pd.DataFrame(list(r["druglikeness"].items()), columns=["Property", "Value"]))
    else:
        rdf = r["rdf"]
        st.markdown(f"#### Docking results — {r['meta']['gene']}")
        st.dataframe(rdf, use_container_width=True, height=200)
        st.download_button("Download CSV", rdf.to_csv(index_label="Rank").encode("utf-8"),
                           file_name=f"MUMO_{r['meta']['gene']}.csv", mime="text/csv")
        if r.get("viz"):
            st.markdown("##### Pose & Interaction Views")
            choice = st.selectbox("Ligand", list(r["viz"].keys()), label_visibility="collapsed")
            entry = r["viz"][choice]

            tab_3d, tab_2d = st.tabs(["3D Pose", "2D Interactions"])

            with tab_2d:
                svg_content = entry["ia"].get("svg_2d", "")
                if svg_content:
                    st.markdown(
                        f'<div style="background-color: white; padding: 16px; border-radius: 12px; border: 1px solid rgba(0,212,170,0.2); box-shadow: 0 4px 12px rgba(0,0,0,0.15); display: flex; justify-content: center; align-items: center; max-width: 760px; margin: 1.5rem auto 0.5rem auto;">{svg_content}</div>',
                        unsafe_allow_html=True
                    )
                    def _sw(color, label):
                        return (f"<span style='display:inline-block;width:11px;height:11px;"
                                f"border-radius:50%;background:{color};margin:0 5px -1px 12px;'></span>{label}")
                    st.markdown(
                        "<div style='text-align:center; color:rgba(226,232,240,0.7); font-size:0.82rem; margin-top:0.3rem;'>"
                        + _sw("#2563eb", "H-bond") + _sw("#6b7280", "Hydrophobic")
                        + _sw("#ea580c", "Salt bridge") + _sw("#16a34a", "Pi-stack")
                        + _sw("#9333ea", "Pi-cation") + _sw("#0d9488", "Halogen")
                        + "<br><span style='opacity:0.7;'>Each residue bubble is linked by a dashed line "
                          "to the ligand atom it interacts with.</span></div>",
                        unsafe_allow_html=True
                    )
                else:
                    st.info("No 2D interaction diagram available.")

            with tab_3d:
                with st.expander("Visualization settings", expanded=False):
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
                try:
                    components.html(render_complex_html(entry["complex"], entry["ia"],
                                    options=opts, height=520), height=540)
                except Exception as e:
                    st.caption(f"(3D view unavailable: {e})")


def render_chat():
    if not ss.messages:
        st.markdown(
            "<div class='mumo-hero'>"
            f"<div class='mumo-hero-logo'>{mol_logo(58, 'mgHero')}"
            "<span class='mumo-hero-title'>MUMO</span></div>"
            "<p class='mumo-hero-sub'>Tell me what to work on — a disease, a target, "
            "or a molecule. I'll ask what I need, then dock it.</p>"
            "<div class='mumo-pills'><span>Disease, Target, or Molecule</span>"
            "<span>Analysis &amp; Design</span><span>Docking Results</span></div>"
            "</div>", unsafe_allow_html=True)
    for m in ss.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])


# ── chat (full width) ──
render_chat()

# ── results, as usual, at the bottom (full width, below the conversation) ──
if ss.results:
    st.divider()
    render_results()
