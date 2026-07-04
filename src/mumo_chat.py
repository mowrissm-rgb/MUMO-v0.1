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
import auth_store as authdb

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data"); os.makedirs(DATA, exist_ok=True)
VENV = os.path.join(BASE, ".venv", "Scripts" if os.name == "nt" else "bin")
VINA = ensure_vina()

st.set_page_config(page_title="MUMO", page_icon="⚛️", layout="wide")

ACCENT = "#0f9aad"  # slightly deeper teal — reads better on a light canvas than the dark-theme cyan

# ── MUMO product theme — clean true light theme, same structure/accent ──
st.markdown(f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;0,8..60,700;1,8..60,500;1,8..60,600&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root {{ --accent: {ACCENT}; }}
html, body {{ background: #f7f8fa; }}
.stApp {{ background: #f7f8fa !important; }}
.block-container {{ padding-top: 1.6rem; max-width: 900px; }}
html, body, [class*="css"] {{ font-family:'Inter', system-ui, sans-serif; color: #1a1f26;
    -webkit-font-smoothing: antialiased; }}
::selection {{ background: rgba(15,154,173,0.18); }}
::-webkit-scrollbar {{ width:9px; }}
::-webkit-scrollbar-thumb {{ background: rgba(0,0,0,0.14); border-radius:6px; }}
::-webkit-scrollbar-track {{ background:transparent; }}
/* soft glass surface */
.liquid {{ background: rgba(255,255,255,0.7); backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px); border:1px solid rgba(0,0,0,0.06);
    box-shadow: 0 1px 2px rgba(16,24,32,0.04); }}
/* Sidebar — light */
[data-testid="stSidebar"] {{
    background: #ffffff !important; border-right: 1px solid rgba(0,0,0,0.07);
}}
[data-testid="stSidebar"] .stButton button {{
    background: #f7f8fa;
    border: 1px solid rgba(0,0,0,0.08);
    color: #3a4048; border-radius: 12px;
    text-align: left; justify-content: flex-start; font-weight: 600; font-size: 13px;
}}
[data-testid="stSidebar"] .stButton button:hover {{
    border-color: var(--accent); color: #10151b;
    background: rgba(15,154,173,0.07);
}}
.mumo-brand {{ display:flex; align-items:center; gap:.5rem; margin:.2rem 0 1rem .1rem; }}
.mumo-brand .wm {{
    font-family:'Source Serif 4',serif; font-style:italic; font-weight:600;
    font-size:1.35rem; color: #10151b;
}}
.mumo-hero-logo {{ display:flex; align-items:center; justify-content:center; gap:14px; margin-bottom:.2rem; }}
.mumo-session {{
    padding:11px 12px; border-radius:11px; border-left:2px solid rgba(0,0,0,0.08);
    color: #6b7178; font-size:11px; margin:2px 0 8px;
}}
/* Chat bubbles */
.mumo-msg-user {{ display:flex; justify-content:flex-end; margin:10px 0; }}
.mumo-msg-user .bubble {{
    max-width:78%; background: var(--accent); color: #ffffff;
    border-radius:18px 18px 4px 18px; padding:13px 18px;
    font:15px/1.55 'Inter',sans-serif; font-weight:500; box-shadow:0 8px 20px -10px rgba(15,154,173,.35);
}}
.mumo-msg-assistant {{ max-width:88%; margin:14px 0; }}
.mumo-msg-assistant .label {{
    font:600 11px 'Inter',sans-serif; letter-spacing:.8px; color: var(--accent);
    margin-bottom:6px; text-transform:uppercase;
}}
.mumo-msg-assistant .body {{
    font:17px/1.65 'Source Serif 4',serif; color: #1a1f26;
}}
.mumo-msg-assistant .body p {{ margin: 0 0 .6em; }}
[data-testid="stChatInput"] {{
    border: 1px solid rgba(0,0,0,0.10) !important;
    border-radius: 14px !important; background: #ffffff !important;
}}
/* Welcome hero */
.mumo-hero {{
    text-align:center; margin: 8vh auto 0; padding: 2rem;
    max-width: 680px;
    display:flex; flex-direction:column; align-items:center; justify-content:center;
    gap: 14px;
}}
.mumo-hero-title {{
    font-family:'Source Serif 4',serif; font-style:italic; font-weight:600;
    font-size: 3.2rem; line-height:1; color: #10151b;
}}
.mumo-hero-sub {{
    margin: 0 auto; max-width: 460px;
    font-size: 1.05rem; font-weight:400; color: #5c636b; line-height:1.6;
}}
/* Results panel */
.mumo-panel-header {{
    font-family:'Source Serif 4',serif; font-style:italic; font-weight:600;
    font-size:19px; color: #10151b;
}}
.mumo-panel-sub {{ font:12.5px 'Inter',sans-serif; color: #6b7178; margin-bottom:14px; }}
</style>
""", unsafe_allow_html=True)

# ── session ──
ss = st.session_state
ss.setdefault("messages", [])     # [{role, content}]
ss.setdefault("stage", "start")
ss.setdefault("convo", {})
ss.setdefault("results", None)    # {rdf, viz, meta}
ss.setdefault("run_now", False)
ss.setdefault("history", [])      # [{title, messages, results}] — local fallback, no login
ss.setdefault("panel_open", False)  # is the right results drawer open?
ss.setdefault("active_conversation_id", None)  # Supabase conversation row, once logged in
_llm = get_llm()


def theme_bg():
    """3D background follows the app theme: dark → black, light → white."""
    try:
        return "#0b0d12" if st.context.theme.type == "dark" else "#ffffff"
    except Exception:
        return "#0b0d12"


def _persist(role, content):
    """Mirror a message to Supabase (no-op if not logged in / not configured).
    Creates the conversation row lazily on the first message of a session."""
    user = authdb.current_user()
    if not user:
        return
    try:
        if not ss.active_conversation_id:
            title = content if role == "user" else "New session"
            ss.active_conversation_id = authdb.create_conversation(user["id"], title)
        authdb.save_message(ss.active_conversation_id, user["id"], role, content)
        authdb.touch_conversation(ss.active_conversation_id)
    except Exception:
        pass  # cloud storage is best-effort — never break the chat over it


def say(text):
    ss.messages.append({"role": "assistant", "content": text})
    _persist("assistant", text)


def mol_logo(width=20, height=26, gid="mg"):
    """MUMO's swirl brand mark — two interleaved strokes in the accent color."""
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 40 64" '
        'xmlns="http://www.w3.org/2000/svg" style="vertical-align:middle;">'
        f'<path d="M8 4C8 20 32 20 32 32C32 44 8 44 8 60" fill="none" stroke="{ACCENT}" stroke-width="4"/>'
        f'<path d="M32 4C32 20 8 20 8 32C8 44 32 44 32 60" fill="none" stroke="{ACCENT}" '
        'stroke-width="4" opacity="0.55"/></svg>'
    )


# ════════════════════════════════════════════════════════════════════════════
# LOGIN GATE — only enforced if Supabase secrets are configured; otherwise the
# app runs exactly as before, local-only (no login, no cross-device history).
# ════════════════════════════════════════════════════════════════════════════
authdb.restore_session()


def render_login_gate():
    st.markdown(f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fustat:wght@400;500;600;700;800&family=Schibsted+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
[data-testid="stHeader"] {{ background: transparent !important; }}
.block-container {{ position: relative; z-index: 2; max-width: 900px; padding-top: 1.4rem; }}
/* top bar */
.mumo-nav {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 44px; }}
.mumo-nav .brand {{ display: flex; align-items: center; gap: 9px; }}
.mumo-nav .brand span {{ font-family: 'Schibsted Grotesk', sans-serif; font-weight: 600;
    font-size: 22px; letter-spacing: -1.2px; color: #10151b; }}
.mumo-nav .links {{ display: flex; gap: 26px; font-family: 'Schibsted Grotesk', sans-serif;
    font-weight: 500; font-size: 15px; letter-spacing: -0.2px; color: rgba(16,21,27,0.55); }}
/* hero */
.mumo-vhero {{ text-align: center; }}
.mumo-badge {{ display: inline-flex; align-items: center; gap: 9px; margin-bottom: 26px;
    padding: 6px 6px 6px 7px; border-radius: 999px; background: #ffffff;
    border: 1px solid rgba(16,21,27,0.08); box-shadow: 0 1px 2px rgba(16,21,27,0.05);
    font-family: 'Inter', sans-serif; font-size: 14px; color: #10151b; }}
.mumo-badge .chip {{ display: inline-flex; align-items: center; gap: 5px; padding: 3px 10px;
    border-radius: 999px; background: #10151b; color: #fff; font-weight: 600; font-size: 12px; }}
.mumo-badge .chip .star {{ color: {ACCENT}; }}
.mumo-vtitle {{ font-family: 'Fustat', sans-serif !important; font-weight: 800 !important; font-size: 76px !important;
    letter-spacing: -4.2px; line-height: 0.98; color: #10151b !important; margin: 0 0 26px; }}
.mumo-vtitle .accent {{ color: {ACCENT} !important; }}
.mumo-vsub {{ font-family: 'Fustat', sans-serif; font-weight: 500; font-size: 20px;
    letter-spacing: -0.4px; color: #565d66; max-width: 620px; margin: 0 auto 6px; line-height: 1.5; }}
/* the tabs container becomes the login card */
[data-testid="stTabs"] {{ max-width: 440px; margin: 40px auto 0;
    background: #ffffff; border: 1px solid rgba(16,21,27,0.07); border-radius: 20px;
    padding: 6px 24px 24px; box-shadow: 0 24px 60px -28px rgba(16,21,27,0.18); }}
[data-baseweb="tab-list"] {{ background: transparent !important; gap: 6px; justify-content: center; }}
button[data-baseweb="tab"] {{ color: rgba(16,21,27,0.45) !important;
    font-family: 'Schibsted Grotesk', sans-serif !important; font-weight: 600 !important; }}
button[data-baseweb="tab"][aria-selected="true"] {{ color: #10151b !important; }}
[data-baseweb="tab-highlight"] {{ background: {ACCENT} !important; }}
.stTextInput label {{ color: rgba(16,21,27,0.7) !important;
    font-family: 'Inter', sans-serif !important; font-size: 13px !important; }}
.stTextInput input {{ background: #f7f8fa !important;
    border: 1px solid rgba(16,21,27,0.12) !important; color: #10151b !important;
    border-radius: 12px !important; }}
.stTextInput input:focus {{ border-color: {ACCENT} !important; box-shadow: 0 0 0 1px {ACCENT} !important; }}
[data-testid="stForm"] {{ border: none !important; padding: 6px 0 0 !important; }}
[data-testid="stFormSubmitButton"] button {{ background: {ACCENT} !important; color: #ffffff !important;
    border: none !important; border-radius: 12px !important; font-weight: 700 !important;
    font-family: 'Schibsted Grotesk', sans-serif !important; box-shadow: 0 10px 24px -10px {ACCENT}; }}
[data-testid="stFormSubmitButton"] button:hover {{ filter: brightness(1.1); }}
/* mobile */
@media (max-width: 680px) {{
    .block-container {{ padding-left: 1rem !important; padding-right: 1rem !important; }}
    .mumo-nav .links {{ display: none; }}
    .mumo-nav {{ margin-bottom: 30px; }}
    .mumo-vtitle {{ font-size: 44px; letter-spacing: -2px; margin-bottom: 20px; }}
    .mumo-vsub {{ font-size: 16px; padding: 0 6px; }}
    .mumo-badge {{ margin-bottom: 20px; font-size: 13px; }}
    [data-testid="stTabs"] {{ margin-top: 26px; padding: 6px 16px 20px; }}
}}
</style>
<div class="mumo-nav">
  <div class="brand">{mol_logo(20, 26, 'mgNav')}<span>mumo</span></div>
  <div class="links"><span>Platform</span><span>Docking</span><span>Reports</span><span>Contact</span></div>
</div>
<div class="mumo-vhero">
  <div class="mumo-badge"><span class="chip"><span class="star">✦</span> New</span> From disease to docked molecule</div>
  <h1 class="mumo-vtitle">From disease<br>to <span class="accent">drug.</span></h1>
  <p class="mumo-vsub">MUMO's multi-agent AI pinpoints the target, scouts the strongest ligands, and runs real molecular docking — from a single sentence to a full report.</p>
</div>
""", unsafe_allow_html=True)

    tab_in, tab_up = st.tabs(["Log in", "Sign up"])
    with tab_in:
        with st.form("login_form"):
            email = st.text_input("Email", key="li_email")
            pw = st.text_input("Password", type="password", key="li_pw")
            if st.form_submit_button("Log in", use_container_width=True):
                try:
                    authdb.sign_in(email.strip(), pw)
                    st.rerun()
                except Exception as e:
                    st.error(f"Couldn't log in: {e}")
    with tab_up:
        with st.form("signup_form"):
            email2 = st.text_input("Email", key="su_email")
            pw2 = st.text_input("Password", type="password", key="su_pw", help="At least 6 characters.")
            if st.form_submit_button("Create account", use_container_width=True):
                try:
                    authdb.sign_up(email2.strip(), pw2)
                    st.success("Account created — check your email to confirm, then log in.")
                except Exception as e:
                    st.error(f"Couldn't sign up: {e}")


if authdb.is_configured() and not authdb.current_user():
    render_login_gate()
    st.stop()


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


def _personalization_context():
    """A short recall of what THIS logged-in user has asked before, across all
    their past sessions — lets MUMO notice recurring interests instead of
    treating every conversation as a blank slate."""
    user = authdb.current_user()
    if not user:
        return ""
    try:
        topics = authdb.recent_user_topics(user["id"], limit=40)
    except Exception:
        return ""
    topics = [t for t in topics if t and t not in ss.messages[-1:]][:25]
    if not topics:
        return ""
    return ("This user's past questions across earlier sessions (for context only — "
            "don't repeat them back verbatim, just notice patterns like a target or "
            "disease they keep returning to):\n- " + "\n- ".join(topics))


def converse(msg):
    """One conversational turn — MUMO can teach, answer, explain results, or dock."""
    ss.messages.append({"role": "user", "content": msg})
    _persist("user", msg)
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
              f"{_personalization_context()}\n\n"
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
    if ss.active_conversation_id:
        try:
            authdb.save_results(ss.active_conversation_id,
                                 {"gene": meta.get("gene"), "rows": rdf.to_dict(orient="records")})
        except Exception:
            pass

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
_user = authdb.current_user()
with st.sidebar:
    st.markdown(f"<div class='mumo-brand'>{mol_logo(20, 26, 'mgSide')}<span class='wm'>mumo</span></div>",
                unsafe_allow_html=True)
    if st.button("+ New session", use_container_width=True):
        if not _user and ss.messages:
            title = next((m["content"] for m in ss.messages if m["role"] == "user"), "Chat")
            ss.history.insert(0, {"title": title[:40], "messages": ss.messages, "results": ss.results})
        ss.messages, ss.stage, ss.convo, ss.results, ss.run_now, ss.panel_open = [], "start", {}, None, False, False
        ss.active_conversation_id = None
        st.rerun()

    st.markdown(
        "<div style='font:600 11px \"Inter\",sans-serif;letter-spacing:1.2px;"
        "color:#6b7178;margin:14px 0 4px;'>RECENT</div>",
        unsafe_allow_html=True,
    )

    if _user:
        # cloud-backed history — survives logout, refresh, new device
        try:
            convos = authdb.list_conversations(_user["id"])
        except Exception:
            convos = []
        for h in convos:
            if st.button(h["title"] or "Chat", key=f"h{h['id']}", use_container_width=True):
                ss.messages = authdb.load_messages(h["id"])
                stored = None
                try:
                    stored = authdb.load_results(h["id"])
                except Exception:
                    pass
                if stored:
                    rdf = pd.DataFrame(stored["rows"])
                    ss.results = {"rdf": rdf, "viz": {}, "meta": {"gene": stored.get("gene")}, "tier": "Standard"}
                else:
                    ss.results = None
                ss.stage, ss.active_conversation_id = "start", h["id"]
                ss.panel_open = bool(ss.results)
                st.rerun()
    else:
        # not logged in / Supabase not configured — local-only history for this session
        for i, h in enumerate(ss.history[:15]):
            if st.button(f"{h['title']}", key=f"h{i}", use_container_width=True):
                ss.messages, ss.results, ss.stage = h["messages"], h["results"], "start"
                ss.panel_open = bool(h["results"])
                st.rerun()

    if _user:
        st.markdown("---")
        st.caption(_user["email"])
        if st.button("Log out", use_container_width=True):
            authdb.sign_out()
            ss.messages, ss.results, ss.active_conversation_id = [], None, None
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
        meta = r.get("meta", {})
        st.markdown(f"<div class='mumo-panel-sub'>Target: {meta.get('gene', 'target')}</div>",
                    unsafe_allow_html=True)

        # ── best-hit summary (clean, presentation-ready) ──
        top = rdf.iloc[0]
        if str(top["Best affinity (kcal/mol)"]) != "FAILED":
            # Custom compact metrics instead of st.metric — st.metric's fixed
            # 36px value font doesn't fit this panel's width at normal window
            # sizes (it truncated no matter how the st.columns were split).
            # A flex-wrap row sized to the actual panel scales properly and
            # wraps onto a second line instead of cutting text off.
            metrics = [
                ("Best affinity", f"{top['Best affinity (kcal/mol)']} kcal/mol"),
                ("Confidence", str(top.get("Confidence", "—"))),
                ("Total interactions", str(int(top["Total interactions"]))),
                ("H-bonds", str(int(top["H-bonds"]))),
            ]
            cells = "".join(
                f"<div style='min-width:110px;'>"
                f"<div style='font:10.5px \"Inter\",sans-serif;color:#6b7178;"
                f"margin-bottom:4px;'>{label}</div>"
                f"<div style='font:600 20px \"Source Serif 4\",serif;color:#10151b;'>{value}</div>"
                f"</div>"
                for label, value in metrics
            )
            st.markdown(
                f"<div style='display:flex;flex-wrap:wrap;gap:18px;margin:12px 0 18px;'>{cells}</div>",
                unsafe_allow_html=True,
            )
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
            st.caption("Method: " + " · ".join(bits))

        # size to the real row count (35px/row + header) instead of a fixed
        # 200px, which left blank empty rows padded in below short results
        table_height = min(35 * (len(rdf) + 1) + 3, 200)
        st.dataframe(rdf, use_container_width=True, height=table_height)
        st.download_button("Download CSV", rdf.to_csv(index_label="Rank").encode("utf-8"),
                           file_name=f"MUMO_{meta.get('gene', 'target')}.csv", mime="text/csv")
        if r.get("viz"):
            st.markdown("##### Pose & Interaction Views")
            st.caption("The 2D map and the 3D pose show the SAME interactions from one analysis — "
                       "the residues, counts and bonds match the results table above.")
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

                    d = st.columns(3)
                    surface_opacity = d[0].slider("Surface opacity", 0.0, 1.0, 0.5, 0.05, key="v_surf")
                    zoom = d[1].slider("Zoom", 0.3, 1.5, 0.45, 0.05, key="v_zoom")
                    background = d[2].color_picker("Background", "#ffffff", key="v_bg")

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
                        "background": background}   # white "figure panel" by default
                try:
                    components.html(render_complex_html(entry["complex"], entry["ia"],
                                    options=opts, height=520), height=540)
                except Exception as e:
                    st.caption(f"(3D view unavailable: {e})")


def render_chat():
    if not ss.messages:
        st.markdown(
            "<div class='mumo-hero'>"
            f"<div class='mumo-hero-logo'>{mol_logo(40, 52, 'mgHero')}"
            "<span class='mumo-hero-title'>mumo</span></div>"
            "<p class='mumo-hero-sub'>Tell me what to work on — a disease, a target, "
            "or a molecule. I'll ask what I need, then dock it.</p>"
            "</div>", unsafe_allow_html=True)
    for m in ss.messages:
        if m["role"] == "user":
            st.markdown(
                f"<div class='mumo-msg-user'><div class='bubble'>{m['content']}</div></div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div class='mumo-msg-assistant'><div class='label'>MUMO</div>"
                f"<div class='body'>{m['content']}</div></div>",
                unsafe_allow_html=True,
            )


# ── chat: always full width, never resizes ──
# ── docking report: a fixed-width overlay drawer on the right, so it never
#    steals space from the chat column (previously an st.columns([3,2])
#    split, which squeezed/congested the chat every time the panel opened) ──
PANEL_WIDTH = 420
panel_showing = bool(ss.results and ss.panel_open)

st.markdown(f"""
<style>
.block-container {{ transition: padding-right .25s ease; }}
{f'.block-container {{ padding-right: {PANEL_WIDTH + 24}px; }}' if panel_showing else ''}
@media (max-width: 900px) {{ .block-container {{ padding-right: 1rem !important; }} }}
</style>
""", unsafe_allow_html=True)

render_chat()

if panel_showing:
    with st.container(key="mumo_panel"):
        st.markdown(f"""
<style>
.st-key-mumo_panel {{
    position: fixed; top: 0; right: 0; width: {PANEL_WIDTH}px; height: 100vh;
    overflow-y: auto; z-index: 999; background: #ffffff;
    border-left: 1px solid rgba(16,21,27,0.08);
    box-shadow: -14px 0 34px -18px rgba(16,21,27,0.28);
    padding: 22px 24px 40px;
}}
@media (max-width: 900px) {{
    .st-key-mumo_panel {{ width: 100vw; }}
}}
</style>
""", unsafe_allow_html=True)
        h = st.columns([5, 1])
        h[0].markdown("<div class='mumo-panel-header'>Docking report</div>", unsafe_allow_html=True)
        if h[1].button("✕", key="close_panel", help="Close docking report"):
            ss.panel_open = False
            st.rerun()
        render_results()
elif ss.results and not ss.panel_open:
    if st.button("› Open docking report", key="open_panel"):
        ss.panel_open = True
        st.rerun()
