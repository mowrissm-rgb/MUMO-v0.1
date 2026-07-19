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
from setup_env import ensure_vina
import auth_store as authdb
# NOTE: the heavy scientific stack (RDKit, AutoDock Vina, OpenBabel, PLIP,
# Meeko, gemmi) is imported LAZILY inside the functions that need it —
# brain, agents.*, pipeline, viz — NOT here at module top. Importing them
# eagerly cost ~15-30s on every cold start and rendered a blank page while
# they loaded. Deferring them lets the chat UI appear in ~1-2s; the heavy
# libs load only when the user actually runs an analysis/docking job.

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data"); os.makedirs(DATA, exist_ok=True)
VENV = os.path.join(BASE, ".venv", "Scripts" if os.name == "nt" else "bin")
VINA = ensure_vina()

st.set_page_config(page_title="MUMO", page_icon="⚛️", layout="wide")

ACCENT = "#6fb8ec"   # light blue — matches the React landing/login pages' accent
ACCENT2 = "#2f7fc4"  # gradient end stop (used on buttons/bubbles for the same look)

# Looping background videos for the cinematic intro landing page. Single
# constants so a MUMO-specific clip can be swapped in with one edit each.
INTRO_HERO_VIDEO = ("https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/"
                    "hf_20260418_080021_d598092b-c4c2-4e53-8e46-94cf9064cd50.mp4")
INTRO_FEAT_VIDEO = ("https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/"
                    "hf_20260418_094631_d30ab262-45ee-4b7d-99f3-5d5848c8ef13.mp4")
# The flower clip shown on the login page (page 2). It spins on Log in / Sign up.
FLOWER_VIDEO = ("https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/"
                "hf_20260616_212935_bbf608da-62d1-4f25-9be4-c346e4d09cc8.mp4")

# The React landing/login (deployed on Vercel) is now the ONE front door for the
# whole product. Streamlit is chat-only: an unauthenticated visitor is bounced to
# the React login, which authenticates with Supabase and hands off back here via a
# ?rt=<refresh_token> URL param (see auth_store.restore_session). Streamlit's own
# render_intro()/render_login_gate() are kept below but no longer reached.
LANDING_URL = "https://mumo-landing.vercel.app"
LANDING_LOGIN_URL = f"{LANDING_URL}/login"

# ── MUMO product theme — dark cinematic, matching the React landing/login ──
st.markdown(f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=IBM+Plex+Serif:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root {{ --accent: {ACCENT}; --accent2: {ACCENT2}; }}
html, body {{ background: #0a0d0f; }}
.stApp {{ background: #0a0d0f !important; }}
.block-container {{ padding-top: 1.6rem; max-width: 900px; }}
html, body, [class*="css"] {{ font-family:'Inter', system-ui, sans-serif; color: #eef5fa;
    -webkit-font-smoothing: antialiased; }}
::selection {{ background: rgba(111,184,236,0.28); }}
::-webkit-scrollbar {{ width:9px; }}
::-webkit-scrollbar-thumb {{ background: rgba(255,255,255,0.14); border-radius:6px; }}
::-webkit-scrollbar-track {{ background:transparent; }}
/* soft glass surface — same liquid-glass treatment as the React cards */
.liquid {{ background: rgba(255,255,255,0.03); backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px); border:1px solid rgba(255,255,255,0.10);
    box-shadow: 0 1px 2px rgba(0,0,0,0.3); }}
/* Sidebar — dark glass */
[data-testid="stSidebar"] {{
    background: #0d1114 !important; border-right: 1px solid rgba(255,255,255,0.08);
}}
[data-testid="stSidebar"] .stButton button {{
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.08);
    color: #cdd8df; border-radius: 12px;
    text-align: left; justify-content: flex-start; font-weight: 600; font-size: 13px;
}}
[data-testid="stSidebar"] .stButton button:hover {{
    border-color: var(--accent); color: #ffffff;
    background: rgba(111,184,236,0.10);
}}
.mumo-brand {{ display:flex; align-items:center; gap:.5rem; margin:.2rem 0 1rem .1rem; }}
.mumo-brand .wm {{
    font-family:'IBM Plex Serif',serif; font-style:italic; font-weight:600;
    font-size:1.35rem; color: #f2f7fa;
}}
.mumo-hero-logo {{ display:flex; align-items:center; justify-content:center; gap:14px; margin-bottom:.2rem; }}
.mumo-session {{
    padding:11px 12px; border-radius:11px; border-left:2px solid rgba(255,255,255,0.10);
    color: #93a0aa; font-size:11px; margin:2px 0 8px;
}}
/* Chat bubbles */
.mumo-msg-user {{ display:flex; justify-content:flex-end; margin:10px 0; }}
.mumo-msg-user .bubble {{
    max-width:78%; background-image: linear-gradient(90deg, {ACCENT} 0%, {ACCENT2} 100%); color: #051520;
    border-radius:18px 18px 4px 18px; padding:13px 18px;
    font:15px/1.55 'Inter',sans-serif; font-weight:500; box-shadow:0 8px 20px -10px rgba(47,127,196,.45);
}}
.mumo-msg-assistant {{ max-width:88%; margin:14px 0; }}
.mumo-msg-assistant .label {{
    font:600 11px 'Inter',sans-serif; letter-spacing:.8px; color: var(--accent);
    margin-bottom:6px; text-transform:uppercase;
}}
.mumo-msg-assistant .body {{
    font:17px/1.65 'IBM Plex Serif',serif; color: #eef5fa;
}}
.mumo-msg-assistant .body p {{ margin: 0 0 .6em; }}
[data-testid="stChatInput"] {{
    border: 1px solid rgba(255,255,255,0.12) !important;
    border-radius: 14px !important; background: rgba(255,255,255,0.04) !important;
}}
[data-testid="stChatInput"] [data-baseweb="textarea"],
[data-testid="stChatInput"] [data-baseweb="base-input"],
[data-testid="stChatInput"] div {{
    background: transparent !important; color: #eef5fa !important;
}}
[data-testid="stChatInput"] textarea {{ color: #eef5fa !important; }}
[data-testid="stChatInput"] textarea::placeholder {{ color: #93a0aa !important; }}
[data-testid="stBottom"], [data-testid="stBottomBlockContainer"] {{ background: transparent !important; }}
[data-testid="stBottom"] > div {{ background: transparent !important; }}
[data-testid="stHeader"] {{ background: transparent !important; }}
/* Welcome hero */
.mumo-hero {{
    text-align:center; margin: 8vh auto 0; padding: 2rem;
    max-width: 680px;
    display:flex; flex-direction:column; align-items:center; justify-content:center;
    gap: 14px;
}}
.mumo-hero-title {{
    font-family:'IBM Plex Serif',serif; font-style:italic; font-weight:600;
    font-size: 3.2rem; line-height:1; color: #f2f7fa;
}}
.mumo-hero-sub {{
    margin: 0 auto; max-width: 460px;
    font-size: 1.05rem; font-weight:400; color: #93a0aa; line-height:1.6;
}}
/* Results panel */
.mumo-panel-header {{
    font-family:'IBM Plex Serif',serif; font-style:italic; font-weight:600;
    font-size:19px; color: #f2f7fa;
}}
.mumo-panel-sub {{ font:12.5px 'Inter',sans-serif; color: #93a0aa; margin-bottom:14px; }}
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
ss.setdefault("panel_expanded", False)  # is the right drawer widened?
ss.setdefault("active_conversation_id", None)  # Supabase conversation row, once logged in
ss.setdefault("entered", False)  # has the visitor clicked past the intro landing page?
ss.setdefault("auth_mode", None)  # None | "login" | "signup" — which form the flower page reveals
ss.setdefault("job_id", None)     # id of an in-flight background docking job (subprocess)
ss.setdefault("anon_job_id", None)  # throwaway job id for a not-logged-in session
ss.setdefault("pending_actions", [])   # steps queued behind a running dock
ss.setdefault("asked_last_turn", False)  # did we just ask a clarifying question?

# how to name each follow-up step when telling the user what happens next
_ACTION_NAMES = {"analyze": "run the ADMET analysis",
                 "string": "build the interaction network",
                 "blast": "run the BLAST search",
                 "dock": "run the docking"}
_llm = get_llm()


def _trace(stage):
    """Print a flushed breadcrumb marking a stage of the main process.

    A native segfault (exit 139) kills the interpreter outright: no traceback,
    no exception, nothing Python can catch or log after the fact. What DOES
    survive is whatever already reached stdout, because Hugging Face keeps the
    tail of it in the Space's error message. So the only way to learn where the
    app died is to say where it is BEFORE it gets there — hence flush=True,
    which matters more than the message: a buffered line is lost in the crash.

    Placed at the boundaries where the main process enters native code (RDKit,
    Playwright, the 3D viewer), since that is where every one of this app's
    crashes has come from.
    """
    try:
        print(f"[mumo] {stage}", flush=True)
    except Exception:
        pass


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
    """Page 2 — the flower login page. A circular flower video sits centre
    stage with a quote beneath it and two buttons (Log in / Sign up). Clicking
    either one does two things at once: the flower spins (a one-shot CSS
    rotation that replays because Streamlit re-renders the element on rerun),
    and the matching email/password form is revealed inline right below — no
    page change. Submitting proceeds to chat."""
    mode = ss.auth_mode
    spin = "spin" if mode else ""
    st.markdown(f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Serif:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
.stApp {{ background: radial-gradient(1100px 700px at 50% 8%, #0d1417 0%, #050506 60%) !important; }}
[data-testid="stHeader"] {{ background: transparent !important; }}
.block-container {{ max-width: 560px !important; padding-top: 4vh !important; }}
html, body, [class*="css"] {{ color: #fff; }}
.flower-page {{ text-align: center; color: #fff; }}
.fbrand {{ display:inline-flex; align-items:center; gap:8px; margin-bottom:14px;
    font-family:'IBM Plex Serif',serif; font-style:italic; font-weight:600; font-size:22px; color:#fff; }}
.flower {{ width: 300px; height: 300px; margin: 4px auto 0; border-radius: 50%; overflow: hidden;
    box-shadow: 0 0 70px -12px rgba(63,198,216,0.45), inset 0 0 0 1px rgba(255,255,255,0.08); }}
.flower video {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
.flower.spin video {{ animation: flowerSpin 1.4s cubic-bezier(.2,.75,.2,1); }}
@keyframes flowerSpin {{ from {{ transform: rotate(0deg) scale(1.06); }} to {{ transform: rotate(360deg) scale(1); }} }}
.fquote {{ font-family:'IBM Plex Serif',serif; font-style:italic; font-size:22px; color:#eef3f6;
    margin-top: 26px; line-height:1.35; }}
.fquote-sub {{ font-size:14px; color: rgba(255,255,255,0.55); margin-top:8px; margin-bottom: 8px; }}
/* native buttons (mode chooser) */
.stButton button {{ background: rgba(255,255,255,0.06) !important; color:#fff !important;
    border: 1px solid rgba(255,255,255,0.18) !important; border-radius: 999px !important;
    font-family:'Inter',sans-serif !important; font-weight:600 !important; padding: 12px 0 !important;
    transition: transform .15s ease, filter .15s ease, border-color .15s ease !important; }}
.stButton button:hover {{ border-color: {ACCENT} !important; background: rgba(15,154,173,0.14) !important; }}
.stButton button:active {{ transform: scale(0.96); }}
.stButton button[kind="primary"] {{ background: {ACCENT} !important; color:#03242a !important;
    border: none !important; box-shadow: 0 12px 30px -12px {ACCENT} !important; }}
/* form inputs (dark) */
.stTextInput label {{ color: rgba(255,255,255,0.72) !important;
    font-family:'Inter',sans-serif !important; font-size:13px !important; }}
.stTextInput input {{ background: rgba(255,255,255,0.06) !important;
    border: 1px solid rgba(255,255,255,0.16) !important; color:#fff !important; border-radius:12px !important; }}
.stTextInput input:focus {{ border-color: {ACCENT} !important; box-shadow: 0 0 0 1px {ACCENT} !important; }}
[data-testid="stForm"] {{ border: 1px solid rgba(255,255,255,0.08) !important; border-radius: 18px !important;
    background: rgba(255,255,255,0.02) !important; padding: 18px 20px !important; }}
[data-testid="stFormSubmitButton"] button {{ background: {ACCENT} !important; color:#03242a !important;
    border: none !important; border-radius: 12px !important; font-weight: 700 !important;
    font-family:'Inter',sans-serif !important; box-shadow: 0 10px 24px -10px {ACCENT}; }}
[data-testid="stFormSubmitButton"] button:hover {{ filter: brightness(1.1); }}
@media (max-width: 600px) {{ .flower {{ width: 240px; height: 240px; }} .fquote {{ font-size:19px; }} }}
</style>
<div class="flower-page">
  <div class="fbrand">{mol_logo(20, 26, 'mgFlower')}<span>mumo</span></div>
  <div class="flower {spin}">
    <video autoplay loop muted playsinline preload="auto"><source src="{FLOWER_VIDEO}" type="video/mp4"></video>
  </div>
  <div class="fquote">"Every cure begins with a single question."</div>
  <div class="fquote-sub">Sign in to begin your discovery.</div>
</div>
""", unsafe_allow_html=True)

    if mode is None:
        cta = st.columns([1, 1])
        with cta[0]:
            if st.button("Log in", key="go_login", type="primary", use_container_width=True):
                ss.auth_mode = "login"
                st.rerun()
        with cta[1]:
            if st.button("Sign up", key="go_signup", use_container_width=True):
                ss.auth_mode = "signup"
                st.rerun()

    elif mode == "login":
        with st.form("login_form"):
            email = st.text_input("Email", key="li_email")
            pw = st.text_input("Password", type="password", key="li_pw")
            if st.form_submit_button("Log in", use_container_width=True):
                try:
                    authdb.sign_in(email.strip(), pw)
                    st.rerun()
                except Exception as e:
                    if "confirm" in str(e).lower():
                        st.error("Your email isn't confirmed yet — check your inbox (and spam folder) for the confirmation link.")
                        ss.unconfirmed_email = email.strip()
                    else:
                        st.error(f"Couldn't log in: {e}")
        if ss.get("unconfirmed_email"):
            if st.button("Resend confirmation email", key="resend_conf", use_container_width=True):
                try:
                    authdb.resend_confirmation(ss.unconfirmed_email)
                    st.success("Confirmation email resent — give it a minute to arrive.")
                except Exception as e:
                    st.error(f"Couldn't resend: {e}")
        if st.button("New here? Create an account", key="to_signup", use_container_width=True):
            ss.auth_mode = "signup"
            st.rerun()

    else:  # signup
        with st.form("signup_form"):
            email2 = st.text_input("Email", key="su_email")
            pw2 = st.text_input("Password", type="password", key="su_pw", help="At least 6 characters.")
            if st.form_submit_button("Create account", use_container_width=True):
                try:
                    authdb.sign_up(email2.strip(), pw2)
                    st.success("Account created — check your email to confirm, then log in.")
                    ss.auth_mode = "login"
                except Exception as e:
                    st.error(f"Couldn't sign up: {e}")
        if st.button("Already have an account? Log in", key="to_login", use_container_width=True):
            ss.auth_mode = "login"
            st.rerun()


def render_intro():
    """Page 1 of 3 — a cinematic, scroll-driven landing page that introduces
    MUMO and drug discovery, then hands off to the login page via the Start
    button. Full-bleed looping video backgrounds (raw <video>, which survives
    Streamlit's markdown sanitizer), a liquid-glass design system, and
    CSS-only scroll-reveal animations (animation-timeline: view()) since JS is
    stripped from injected markdown."""
    st.markdown(f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Serif:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500&family=Barlow:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
/* full-bleed dark canvas, no Streamlit chrome */
.stApp {{ background: #000 !important; }}
[data-testid="stHeader"] {{ background: transparent !important; }}
.stMain {{ align-items: stretch !important; }}
.block-container {{ max-width: 100% !important; width: 100% !important;
    padding: 0 !important; }}
.mumo-intro *, .mumo-intro {{ box-sizing: border-box; }}
.mumo-intro {{ font-family: 'Barlow', sans-serif; color: #fff; }}
/* liquid glass */
.lg {{ position: relative; overflow: hidden; background: rgba(255,255,255,0.02);
    backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
    box-shadow: inset 0 1px 1px rgba(255,255,255,0.12); border-radius: 22px; }}
.lg::before {{ content:""; position:absolute; inset:0; border-radius:inherit; padding:1.4px;
    background: linear-gradient(180deg, rgba(255,255,255,0.45), rgba(255,255,255,0.12) 25%,
        rgba(255,255,255,0) 45%, rgba(255,255,255,0) 60%, rgba(255,255,255,0.12) 80%, rgba(255,255,255,0.45));
    -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
    -webkit-mask-composite: xor; mask-composite: exclude; pointer-events:none; }}
/* sections */
.mumo-sec {{ position: relative; min-height: 100vh; overflow: hidden;
    display: flex; flex-direction: column; }}
.mumo-sec > video {{ position: absolute; inset: 0; width: 100%; height: 100%;
    object-fit: cover; object-position: top; z-index: 0; }}
.mumo-sec .veil {{ position:absolute; inset:0; z-index:1; pointer-events:none;
    background: linear-gradient(180deg, rgba(0,0,0,0.35), rgba(0,0,0,0.15) 40%, rgba(0,0,0,0.6)); }}
.mumo-sec .inner {{ position: relative; z-index: 2; flex: 1;
    display: flex; flex-direction: column; padding: 40px clamp(20px, 6vw, 90px); }}
/* nav */
.mumo-inav {{ display:flex; align-items:center; justify-content:space-between; }}
.mumo-inav .brand {{ display:flex; align-items:center; gap:9px;
    font-family:'IBM Plex Serif',serif; font-style:italic; font-size:26px; color:#fff; }}
.mumo-inav .navlinks {{ display:flex; gap:6px; padding:6px; }}
.mumo-inav .navlinks a {{ padding:8px 14px; font-size:14px; font-weight:500;
    color:rgba(255,255,255,0.9); text-decoration:none; border-radius:999px; }}
@media (max-width: 820px) {{ .mumo-inav .navlinks {{ display:none; }} }}
/* hero content */
.mumo-hero-c {{ flex:1; display:flex; flex-direction:column; align-items:center;
    justify-content:center; text-align:center; }}
.mumo-pill {{ display:inline-flex; align-items:center; gap:9px; padding:5px 14px 5px 5px;
    font-size:13.5px; color:rgba(255,255,255,0.92); margin-bottom:26px;
    animation: fadeUp .8s .3s both; }}
.mumo-pill .new {{ background:#fff; color:#000; font-weight:600; font-size:11.5px;
    padding:3px 10px; border-radius:999px; }}
.mumo-huge {{ font-family:'IBM Plex Serif',serif; font-style:italic;
    font-size: clamp(3rem, 8vw, 5.4rem); line-height:0.86; letter-spacing:-3px;
    color:#fff; max-width: 15ch; margin:0; }}
.mumo-huge .w {{ display:inline-block; margin-right:0.24em; opacity:0;
    animation: blurWord .7s both; filter: blur(10px); }}
.mumo-subh {{ margin-top:22px; max-width: 54ch; font-weight:300;
    font-size: clamp(0.95rem, 1.4vw, 1.05rem); line-height:1.5; color:rgba(255,255,255,0.92);
    animation: fadeUp .8s .9s both; }}
.mumo-cue {{ margin-top:34px; font-size:12px; letter-spacing:2px; text-transform:uppercase;
    color:rgba(255,255,255,0.6); animation: fadeUp .8s 1.2s both; }}
.mumo-cue .dot {{ display:block; width:22px; height:36px; border:1.5px solid rgba(255,255,255,0.4);
    border-radius:20px; margin:12px auto 0; position:relative; }}
.mumo-cue .dot::after {{ content:""; position:absolute; left:50%; top:7px; width:3px; height:7px;
    border-radius:3px; background:#fff; transform:translateX(-50%); animation: cue 1.6s infinite; }}
/* capabilities */
.mumo-kick {{ font-size:14px; color:rgba(255,255,255,0.75); margin-bottom:20px; }}
.mumo-h2 {{ font-family:'IBM Plex Serif',serif; font-style:italic;
    font-size: clamp(2.6rem, 7vw, 5.4rem); line-height:0.9; letter-spacing:-2px; margin:0; }}
.mumo-cards {{ display:grid; grid-template-columns: repeat(3, 1fr); gap:20px; margin-top:56px; }}
@media (max-width: 900px) {{ .mumo-cards {{ grid-template-columns: 1fr; }} }}
.mumo-card {{ padding:24px; min-height:340px; display:flex; flex-direction:column; }}
.mumo-card .ico {{ width:44px; height:44px; border-radius:12px; display:flex;
    align-items:center; justify-content:center; font-size:22px; }}
.mumo-card .tags {{ display:flex; flex-wrap:wrap; gap:6px; justify-content:flex-end; max-width:64%; }}
.mumo-card .tags span {{ font-size:11px; color:rgba(255,255,255,0.9); padding:4px 10px; border-radius:999px; }}
.mumo-card .top {{ display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }}
.mumo-card h3 {{ font-family:'IBM Plex Serif',serif; font-style:italic; font-size:2rem;
    letter-spacing:-1px; margin:0 0 10px; }}
.mumo-card p {{ font-size:14px; font-weight:300; line-height:1.5; color:rgba(255,255,255,0.9);
    max-width:34ch; margin:0; }}
/* cta section */
.mumo-cta-c {{ flex:1; display:flex; flex-direction:column; align-items:center;
    justify-content:center; text-align:center; }}
.mumo-cta-c .kick {{ font-size:14px; color:rgba(255,255,255,0.75); margin-bottom:20px; }}
.mumo-cta-c h2 {{ font-family:'IBM Plex Serif',serif; font-style:italic;
    font-size: clamp(2.4rem, 6vw, 4.4rem); line-height:0.92; letter-spacing:-2px; margin:0 0 14px; max-width:16ch; }}
.mumo-cta-c p {{ font-weight:300; max-width:46ch; color:rgba(255,255,255,0.9); line-height:1.5; margin:0 0 8px; }}
/* scroll reveal (CSS-only; ignored gracefully where unsupported -> just visible) */
.reveal {{ animation: revealUp linear both; animation-timeline: view();
    animation-range: entry 6% cover 34%; }}
@keyframes revealUp {{ from {{ opacity:0; filter:blur(10px); transform:translateY(46px); }}
    to {{ opacity:1; filter:blur(0); transform:none; }} }}
@keyframes fadeUp {{ from {{ opacity:0; transform:translateY(18px); }} to {{ opacity:1; transform:none; }} }}
@keyframes blurWord {{ 0% {{ opacity:0; filter:blur(10px); transform:translateY(30px); }}
    50% {{ opacity:.6; filter:blur(4px); transform:translateY(-4px); }}
    100% {{ opacity:1; filter:blur(0); transform:translateY(0); }} }}
@keyframes cue {{ 0% {{ opacity:0; transform:translate(-50%,0); }} 50% {{ opacity:1; }}
    100% {{ opacity:0; transform:translate(-50%,10px); }} }}
/* Start button (native st.button, restyled + press effect) */
.st-key-enter_mumo {{ padding: 0 0 90px; background:#000; }}
.st-key-enter_mumo button {{
    background: {ACCENT} !important; color:#03242a !important; border:none !important;
    font-family:'Barlow',sans-serif !important; font-weight:600 !important; font-size:17px !important;
    padding: 16px 46px !important; border-radius:999px !important;
    box-shadow: 0 14px 40px -12px {ACCENT} !important; transition: transform .18s ease, filter .18s ease !important; }}
.st-key-enter_mumo button:hover {{ filter:brightness(1.1); transform: translateY(-2px); }}
.st-key-enter_mumo button:active {{ transform: scale(0.94); filter:brightness(0.92); }}
</style>

<div class="mumo-intro">
  <!-- SECTION 1 — HERO -->
  <section class="mumo-sec">
    <video autoplay muted playsinline loop preload="auto"><source src="{INTRO_HERO_VIDEO}" type="video/mp4"></video>
    <div class="veil"></div>
    <div class="inner">
      <div class="mumo-inav">
        <div class="brand">{mol_logo(20, 26, 'mgIntro')}<span>mumo</span></div>
        <div class="navlinks lg"><a>Platform</a><a>Discovery</a><a>Docking</a><a>Reports</a><a>About</a></div>
        <div style="width:44px"></div>
      </div>
      <div class="mumo-hero-c">
        <div class="mumo-pill lg"><span class="new">New</span> AI that goes from disease to docked molecule</div>
        <h1 class="mumo-huge">
          <span class="w" style="animation-delay:.0s">Discover</span>
          <span class="w" style="animation-delay:.1s">medicine,</span>
          <span class="w" style="animation-delay:.2s">faster</span>
          <span class="w" style="animation-delay:.3s">than</span>
          <span class="w" style="animation-delay:.4s">ever.</span>
        </h1>
        <p class="mumo-subh">MUMO is a multi-agent AI drug-discovery partner. Name a disease, a target,
        or a molecule — it finds the target, scouts the strongest ligands, runs real molecular docking,
        and hands you a full report. From a single sentence to a validated hit.</p>
        <div class="mumo-cue">Scroll to explore<span class="dot"></span></div>
      </div>
    </div>
  </section>

  <!-- SECTION 2 — CAPABILITIES -->
  <section class="mumo-sec">
    <video autoplay muted playsinline loop preload="auto"><source src="{INTRO_FEAT_VIDEO}" type="video/mp4"></video>
    <div class="veil"></div>
    <div class="inner">
      <div class="reveal">
        <div class="mumo-kick">// What MUMO does</div>
        <h2 class="mumo-h2">Drug discovery,<br>evolved.</h2>
      </div>
      <div class="mumo-cards">
        <div class="mumo-card lg reveal">
          <div class="top"><div class="ico lg">🎯</div>
            <div class="tags"><span class="lg">Disease → gene</span><span class="lg">Open Targets</span><span class="lg">Ranked</span></div></div>
          <div style="flex:1"></div>
          <h3>Target Finder</h3>
          <p>Give MUMO a disease and it pinpoints the most relevant protein target, backed by
          curated genetics — no need to know the gene yourself.</p>
        </div>
        <div class="mumo-card lg reveal">
          <div class="top"><div class="ico lg">🧪</div>
            <div class="tags"><span class="lg">ChEMBL</span><span class="lg">SMILES</span><span class="lg">Drug-likeness</span></div></div>
          <div style="flex:1"></div>
          <h3>Ligand Scout</h3>
          <p>It scouts the strongest known binders from millions of bioactive molecules, or takes the
          exact compound you name, and screens them for drug-like properties.</p>
        </div>
        <div class="mumo-card lg reveal">
          <div class="top"><div class="ico lg">⚛️</div>
            <div class="tags"><span class="lg">AutoDock Vina</span><span class="lg">3D pose</span><span class="lg">Validated</span></div></div>
          <div style="flex:1"></div>
          <h3>Molecular Docking</h3>
          <p>Real physics-based docking with reproducible scoring, interaction maps and a 3D pose —
          the same result you'd get from a wet-lab computational pipeline.</p>
        </div>
      </div>
    </div>
  </section>

  <!-- SECTION 3 — CTA -->
  <section class="mumo-sec" style="min-height:82vh;">
    <video autoplay muted playsinline loop preload="auto"><source src="{INTRO_HERO_VIDEO}" type="video/mp4"></video>
    <div class="veil" style="background:linear-gradient(180deg, rgba(0,0,0,0.55), rgba(0,0,0,0.4) 40%, #000);"></div>
    <div class="inner">
      <div class="mumo-cta-c reveal">
        <div class="kick">// Begin</div>
        <h2>Start your journey into drug discovery.</h2>
        <p>Create an account or log in, then just start talking. MUMO takes it from there.</p>
      </div>
    </div>
  </section>
</div>
""", unsafe_allow_html=True)

    c = st.columns([1, 1, 1])
    with c[1]:
        if st.button("Get Started  →", key="enter_mumo", use_container_width=True):
            ss.entered = True
            st.rerun()




if authdb.is_configured() and not authdb.current_user():
    # Chat-only: no valid session (and no ?rt= handoff token restored one), so
    # send the visitor to the single front door — the React login on Vercel.
    # restore_session() has already run above, so a logged-in user never reaches
    # here; only genuinely-unauthenticated visitors get bounced (no redirect loop,
    # because the React login only returns here after a successful sign-in).
    components.html(
        f"""
        <div style="font-family:'Inter',system-ui,sans-serif;color:#93a0aa;
             text-align:center;padding-top:40vh;">Taking you to sign in…</div>
        <script>window.top.location.href = "{LANDING_LOGIN_URL}";</script>
        """,
        height=300,
    )
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
    "   - 'analyze' : the user only wants a molecule's drug-likeness / ADMET / toxicity, no docking.\n"
    "   - 'string'  : the user wants a protein–protein INTERACTION NETWORK / STRING analysis / "
    "functional partners / how targets connect into pathways. Put the protein(s) in 'target' — a "
    "single gene name, or a LIST of them for a family/set.\n"
    "   - 'blast'   : the user wants a BLAST SEQUENCE-SIMILARITY search — 'blast CFTR', 'find "
    "proteins similar to X', 'sequence search', or they pasted a protein sequence to search. Put "
    "the gene NAME or the raw SEQUENCE they gave in 'target'.\n"
    "   - 'chat'    : everything else — answering, teaching, explaining results, or asking "
    "ONE clarifying question. When unsure, use 'chat'.\n"
    "• CRITICAL: your 'reply' and your 'actions' MUST match. If your reply says you are "
    "running, docking, analyzing, blasting, or starting a simulation, the matching action "
    "MUST be in 'actions' — NEVER say you are running something while returning an empty "
    "list. If you still need something (e.g. a target), do NOT promise to run it; ASK for "
    "the missing piece and return [].\n"
    "• NEVER RE-ASK. Before asking anything, check 'Known so far' and the conversation. If "
    "the target (or disease) is already known and the user wants it docked, RUN IT — do not "
    "ask them to confirm, do not ask again in different words, do not ask for optional "
    "extras. Asking for something you have already been told is the single worst thing you "
    "can do. Only ask when a REQUIRED piece is genuinely absent: docking needs a target or "
    "a disease; ADMET needs a ligand; STRING and BLAST need a protein.\n"
    "• A bare 'yes', 'ok', 'go ahead' or 'run it' means RUN what you were about to run — "
    "never answer it with another question.\n"
    "• MULTI-STEP REQUESTS: one message can ask for SEVERAL things. Put every step in "
    "'actions', IN THE ORDER THE USER ASKED. Examples:\n"
    "   'dock 1NFK with luteolin and then run the ADME prediction for the ligand'\n"
    "       -> actions: [\"dock\", \"analyze\"], target 1NFK, ligand luteolin\n"
    "   'check the admet of quercetin then dock it against EGFR'\n"
    "       -> actions: [\"analyze\", \"dock\"]\n"
    "   'dock CFTR with aspirin and show me its interaction network'\n"
    "       -> actions: [\"dock\", \"string\"]\n"
    "  Do NOT drop the later steps. Do NOT ask which one to do first — the order is the "
    "order they wrote. For a pure question or explanation, return [].\n\n"
    "Reply with ONLY a JSON object, nothing else:\n"
    '{"actions": [<any of "dock","analyze","string","blast", in the order requested; '
    '[] for a pure chat/teaching reply>], '
    '"disease": <string|null>, "target": <gene or 4-char PDB ID|null>, '
    '"ligand": <drug name, SMILES, or a LIST of them|null>, '
    '"tier": <"Simple"|"Standard"|"Ambitious"|null>, '
    '"reply": "<your message — a full helpful/teaching answer, an explanation of the '
    'results, a short clarifying question, or a brief \'running it now\' note>"}'
)


STRING_REPORT_SYSTEM = (
    "You are MUMO, explaining a protein–protein interaction network to a pharmacy "
    "student who is NEW to network pharmacology and has never used STRING before. "
    "Make it genuinely easy to understand while staying scientifically correct.\n\n"
    "Write the report in markdown with these sections and headings:\n"
    "## What this network shows\n(2–3 sentences: what a protein–protein interaction "
    "network is, and what we're looking at here — in plain words.)\n"
    "## The main protein\n(what it is and what it does in the body, simply.)\n"
    "## Key partners and how they connect\n(for the most important partners: what each "
    "one does, and WHY it works with the main protein — the biological relationship. "
    "Explain the evidence in plain words: 'experiments' = scientists physically observed "
    "them interacting; 'databases' = expert-curated knowledge; 'co-expression' = they turn "
    "on together; 'text-mining' = repeatedly discussed together in the literature.)\n"
    "## The biology this network is doing\n(explain the enriched pathways/processes in "
    "plain language: what these proteins achieve together in the cell or body.)\n"
    "## Why this matters\n(the big-picture takeaway for drug discovery / for this target.)\n\n"
    "RULES: define EVERY technical term the first time it appears. Short paragraphs. Warm, "
    "encouraging tutor tone. No emojis. Use ONLY the data provided — never invent facts, "
    "gene names, or numbers."
)


def _string_narrative(data):
    """Ask MUMO's LLM to explain a STRING network in plain, beginner-friendly terms."""
    if _llm is None:
        return ""
    resolved = data.get("resolved", [])
    main = ", ".join(data.get("input", []))
    main_ann = resolved[0].get("annotation", "") if resolved else ""
    plines = []
    for p in data.get("partners", [])[:10]:
        ev = []
        if p.get("escore", 0) > 0.15: ev.append("experiments")
        if p.get("dscore", 0) > 0.15: ev.append("databases")
        if p.get("ascore", 0) > 0.15: ev.append("co-expression")
        if p.get("tscore", 0) > 0.15: ev.append("text-mining")
        plines.append(
            f"- {p['preferredName_B']} (confidence {round(p.get('score', 0), 2)}; "
            f"evidence: {', '.join(ev) or 'combined'}): {p.get('annotation_B', '')[:220]}")
    enr = sorted(data.get("enrichment", []), key=lambda e: e.get("fdr", 1.0))[:10]
    elines = [f"- [{e.get('category', '')}] {e.get('description', '')}" for e in enr]
    prompt = (f"MAIN PROTEIN(S): {main}\nWHAT IT DOES: {main_ann[:500]}\n\n"
              f"TOP PARTNERS (name, confidence 0-1, evidence, function):\n"
              + "\n".join(plines) + "\n\n"
              "ENRICHED PATHWAYS / FUNCTIONS:\n" + "\n".join(elines) +
              "\n\nWrite the beginner-friendly network report now.")
    try:
        return _llm.chat(STRING_REPORT_SYSTEM, prompt, temperature=0.4, max_tokens=1200)
    except Exception:
        return ""


BLAST_REPORT_SYSTEM = (
    "You are MUMO, explaining a BLAST sequence-similarity result to a pharmacy student who is "
    "NEW to bioinformatics and has never run BLAST. Make it genuinely easy while staying correct.\n\n"
    "Markdown sections and headings:\n"
    "## What BLAST just did\n(2–3 sentences: what BLAST is — searching databases of known "
    "proteins for sequences similar to the query — and what we searched here.)\n"
    "## Your protein\n(what the query protein is, briefly.)\n"
    "## The closest matches and what they mean\n(walk through the top hits: which proteins / "
    "organisms they are; explain '% identity' = how much of the sequence is literally the same, "
    "and 'E-value' = the chance the match is a coincidence, where smaller is better and a value "
    "near 0 means essentially certain. Say what a high-identity match implies biologically — same "
    "function, conserved across species.)\n"
    "## What this tells us\n(the takeaway: is the protein well conserved? part of a known family? "
    "what does that imply for its function or for drug discovery?)\n\n"
    "RULES: define EVERY technical term the first time it appears. Short paragraphs. Warm tutor "
    "tone. No emojis. Use ONLY the data provided — never invent hits, numbers, or organisms."
)


def _blast_narrative(data):
    """Ask MUMO's LLM to explain a BLAST result in plain, beginner-friendly terms."""
    if _llm is None:
        return ""
    hits = data.get("hits", [])[:10]
    hlines = [f"- {h['accession']} ({h.get('sciname', '')}): identity {h['identity']}%, "
              f"E-value {h['evalue']:.1e} — {h.get('title', '')[:80]}" for h in hits]
    prompt = (f"QUERY PROTEIN: {data.get('query_name', '')} "
              f"({data.get('accession', '')}, {data.get('seq_len', '?')} residues)\n"
              f"DATABASE: {data.get('database', '')} | PROGRAM: {data.get('program', '')}\n\n"
              "TOP HITS (accession, organism, % identity, E-value, description):\n"
              + "\n".join(hlines) + "\n\nWrite the beginner-friendly BLAST report now.")
    try:
        return _llm.chat(BLAST_REPORT_SYSTEM, prompt, temperature=0.4, max_tokens=1100)
    except Exception:
        return ""


ADMET_REPORT_SYSTEM = (
    "You are MUMO, explaining a drug-likeness / ADMET screen to a pharmacy student who is "
    "NEW to pharmacokinetics and toxicology prediction. Make it genuinely easy while staying "
    "scientifically correct.\n\n"
    "Markdown sections and headings:\n"
    "## What this screen checks\n(2–3 sentences: what drug-likeness and ADMET — Absorption, "
    "Distribution, Metabolism, Excretion, Toxicity — mean, and why they matter before a "
    "molecule can become a medicine.)\n"
    "## Drug-likeness\n(walk through the rule-based properties provided — e.g. molecular "
    "weight, LogP, H-bond donors/acceptors — and what a pass/fail on each implies for "
    "oral-drug potential.)\n"
    "## ADMET-AI predictions\n(if provided: pick out the notable endpoints — e.g. hERG "
    "cardiotoxicity, Ames mutagenicity, DILI liver injury, CYP interactions, "
    "blood-brain-barrier penetration — explain each term the first time it appears, and say "
    "in plain words whether the predicted values are reassuring or a red flag.)\n"
    "## Bottom line\n(an overall plain-language verdict on this molecule's drug-likeness and "
    "safety profile, and what a medicinal chemist would want to investigate next.)\n\n"
    "RULES: define EVERY technical term the first time it appears. Short paragraphs. Warm, "
    "encouraging tutor tone. No emojis. Use ONLY the data provided — never invent numbers."
)


def _admet_narrative(data):
    """Ask MUMO's LLM to explain a drug-likeness/ADMET screen in plain, beginner-friendly terms."""
    if _llm is None:
        return ""
    dl = data.get("druglikeness", {})
    adm = data.get("admet_ml") or {}
    prompt = (f"LIGAND: {data.get('lig_label', '')} ({data.get('lig_smiles', '')})\n\n"
              "DRUG-LIKENESS PROPERTIES:\n" + _json.dumps(dl, indent=2) + "\n\n")
    if adm and "_error" not in adm:
        prompt += "ADMET-AI PREDICTIONS (endpoint: value):\n" + _json.dumps(adm, indent=2) + "\n\n"
    prompt += "Write the beginner-friendly ADMET report now."
    try:
        return _llm.chat(ADMET_REPORT_SYSTEM, prompt, temperature=0.4, max_tokens=1100)
    except Exception:
        return ""


def _history_text(n=10):
    return "\n".join(f'{m["role"]}: {m["content"]}' for m in ss.messages[-n:])


def _resolve_ligands(lig, announce=True):
    """Resolve a ligand (name/SMILES) OR a list of them into [{label, smiles}].

    Each candidate is screened by ligand_check before AND after structure
    lookup, so a silylated GC-MS entry or any silicon-bearing molecule is
    turned away here — cheaply, with an explanation — instead of failing deep
    inside ligand prep minutes later. Anything dropped is reported in the chat
    rather than silently vanishing from the results table.
    """
    from agents.admet import resolve_ligand  # lazy: pulls in RDKit
    import ligand_check as lc
    _trace("resolve-ligands:enter (RDKit)")
    if not lig:
        return []
    items = lig if isinstance(lig, list) else [lig]
    out, rejected = [], []
    for x in items:
        verdict = lc.precheck_name(x)
        if verdict:
            rejected.append(verdict)
            continue
        name = lc.normalize_name(x)
        smi, label = resolve_ligand(name)
        if not smi:
            rejected.append(lc.unresolved(x))
            continue
        verdict = lc.postcheck_structure(name, smi)
        if verdict:
            rejected.append(verdict)
            continue
        out.append({"label": label, "smiles": smi})
    if rejected and announce:
        say(lc.rejection_message(rejected))
    return out


def _results_context():
    """Summarise the latest results so the brain can discuss them with real numbers."""
    r = ss.results
    if not r:
        return "Docking results so far: none yet."
    if "druglikeness" in r:
        return (f"Latest analysis — drug-likeness of {r['lig_label']} "
                f"({r['lig_smiles']}): {_json.dumps(r['druglikeness'])}")
    if r.get("kind") == "string" or "partners" in r:
        names = ", ".join(r.get("input", []))
        parts = ", ".join(p.get("preferredName_B", "") for p in r.get("partners", [])[:12])
        return (f"Latest STRING interaction network for {names}. "
                f"Top functional partners: {parts}. (Full network + report in the side panel.)")
    if r.get("kind") == "blast" or "hits" in r:
        hits = r.get("hits", [])[:8]
        hs = ", ".join(f"{h.get('accession', '')} ({h.get('identity', '?')}%)" for h in hits)
        return (f"Latest BLAST for {r.get('query_name', 'the query')} "
                f"({r.get('seq_len', '?')} aa) vs {r.get('database', '')}. Top hits: {hs}.")
    if r.get("kind") == "md":
        return (f"Latest stability simulation for {r.get('ligand', 'the ligand')}: "
                f"ligand moved {r.get('lig_rmsd_min')} Å on minimisation, "
                f"{r.get('lig_rmsd_relax')} Å on relaxation; energy relieved "
                f"{r.get('energy_drop')} kcal/mol. Verdict: {r.get('verdict')}. "
                f"(This is a fast OpenMM refinement, not full MD.)")
    if "rdf" not in r:
        return "The latest result is shown in the side panel."
    rdf = r["rdf"]
    rows = []
    for _, row in rdf.head(5).iterrows():
        ki = row.get("Est. Ki")
        le = row.get("Ligand efficiency")
        rel = row.get("Reliability")
        extra = ""
        if ki not in (None, "—"):
            extra += f", est. Ki {ki}"
        if le not in (None, "—"):
            extra += f", ligand efficiency {le}"
        if rel not in (None, "—"):
            extra += f", reliability {rel}"
        rows.append(f"- {row['Ligand']}: {row['Best affinity (kcal/mol)']} kcal/mol{extra}, "
                    f"{row['H-bonds']} H-bonds, {row['Total interactions']} total interactions; "
                    f"residues: {row['All interacting residues']}")
    return (f"Latest docking results — target {r['meta']['gene']} "
            f"(more negative kcal/mol = stronger binding; smaller Ki = tighter):\n" + "\n".join(rows))


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
    from brain import parse_intent  # lazy imports (heavy scientific stack)
    # NOTE: agents.admet (RDKit) is deliberately NOT imported here any more. It
    # moved into _run_sync_action, which only runs when an ADMET step actually
    # fires — so answering a question no longer drags the native chemistry
    # stack into the main Streamlit process for nothing.
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
            asked_for_ligands = bool(c.get("ligand"))
            c["ligand_objs"] = _resolve_ligands(c.get("ligand"))
            if asked_for_ligands and not c["ligand_objs"]:
                # same rule as the LLM path: never substitute scouted ligands for
                # the specific ones the user asked for (see the dock branch below)
                say("None of those ligands can be docked, so I've stopped here rather "
                    "than substituting different molecules.")
                return
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

    # ── decide what actually runs ──────────────────────────────────────────
    # The model proposes; `dispatch` disposes. It is a pure, unit-tested module
    # that overrides the model in the two cases that used to stall the app: the
    # model chatting when the user plainly asked to run something we already
    # have every input for, and the model asking a reworded version of a
    # question the conversation already answered. It also returns a PLAN — an
    # ordered list — so "dock X then run ADMET on it" is one request, not two.
    import dispatch
    actions = dispatch.plan(data, c, msg,
                            asked_last_turn=bool(ss.get("asked_last_turn")))

    if actions:
        ss.asked_last_turn = False
    else:
        # The model committed to an action we cannot run yet — its reply has
        # probably promised to run it. Say precisely what is missing, which is
        # the thing the old vague re-ask never did. (When the model chose to
        # chat it has already asked its own question; don't stack a second.)
        wanted = dispatch.model_actions(data)
        if wanted:
            gap = dispatch.gap_prompt(wanted[0], c)
            if gap:
                say(gap)
        ss.asked_last_turn = True

    _run_plan(actions, c)


def _run_sync_action(action, c):
    """Run one action that finishes within this script run (everything but dock).

    Split out of `converse` so a queued follow-up step can reuse it verbatim —
    "dock X then run ADMET" resumes here once the background dock lands, and
    gets exactly the same code path as if it had been asked on its own.
    """
    from agents.admet import resolve_ligand, druglikeness, admet_ml

    # analyze-only → drug-likeness + ADMET-AI predictions, no docking
    if action == "analyze" and c.get("ligand"):
        one = c["ligand"][0] if isinstance(c["ligand"], list) else c["ligand"]
        smi, label = resolve_ligand(str(one))
        if smi:
            res = {"kind": "admet", "druglikeness": druglikeness(smi),
                   "lig_label": label, "lig_smiles": smi}
            with st.spinner("Running ADMET-AI models (hERG, CYP, Ames, DILI…)"):
                res["admet_ml"] = admet_ml(smi)
            with st.spinner("Writing the ADMET report…"):
                res["narrative"] = _admet_narrative(res)
            ss.results = res
            ss.panel_open = True
        return

    # protein–protein interaction network → STRING
    if action == "string" and c.get("target"):
        from agents.string_analyst import analyze_string
        prot = c["target"]
        label = ", ".join(prot) if isinstance(prot, list) else str(prot)
        try:
            with st.spinner(f"Querying STRING for {label}…"):
                data_str = analyze_string(prot)
            with st.spinner("Writing the network report…"):
                data_str["narrative"] = _string_narrative(data_str)
            ss.results = {"kind": "string", **data_str}
            ss.panel_open = True
        except Exception as e:
            say(f"STRING analysis couldn't run: {e}")
        return

    # BLAST sequence similarity (self-hosted BLAST+ — runs in seconds)
    if action == "blast" and c.get("target"):
        from agents.blast_analyst import analyze_blast
        q = c["target"]
        q = q[0] if isinstance(q, list) else q
        try:
            with st.status("Searching similar proteins with BLAST…", expanded=True) as stt:
                data_bl = analyze_blast(
                    str(q), status_cb=lambda w: stt.write("…fetching the sequence and searching"))
                stt.update(label="BLAST complete", state="complete")
            with st.spinner("Writing the BLAST report…"):
                data_bl["narrative"] = _blast_narrative(data_bl)
            ss.results = {"kind": "blast", **data_bl}
            ss.panel_open = True
        except Exception as e:
            say(f"BLAST couldn't run: {e}")
        return


def _run_plan(actions, c):
    """Execute a planned sequence of actions.

    Docking is the only step that outlives this script run — it is a detached
    subprocess — so it cannot simply be called in a loop with the others. When
    the plan reaches a dock, the REMAINDER is parked in session state along with
    a snapshot of the conversation slots it will need, and `_apply_result`
    resumes it once the dock lands. Snapshotting matters because finishing a
    dock clears `ss.convo`, which would otherwise take the ligand for the
    queued ADMET step with it.
    """
    queue = list(actions or [])
    while queue:
        action = queue.pop(0)
        if action != "dock":
            _run_sync_action(action, c)
            continue

        # resolve the CURRENT ligand(s) fresh (a single name OR a comparison list)
        asked_for_ligands = bool(c.get("ligand"))
        c["ligand_objs"] = _resolve_ligands(c.get("ligand"))
        if asked_for_ligands and not c["ligand_objs"]:
            # The user named specific molecules and none of them survived screening.
            # Falling through would let the pipeline SCOUT substitutes from ChEMBL and
            # present them as the answer — silently docking something the user never
            # asked about. Stop instead; _resolve_ligands has already said why.
            say("None of those ligands can be docked, so I've stopped here rather than "
                "substituting different molecules. Give me one that works and I'll run it.")
            ss.pending_actions = []
            return
        c["tier"] = c.get("tier") or "Standard"
        # park the rest WITH the slots they need, then hand off to the dock
        ss.pending_actions = [{"action": a, "convo": dict(c)} for a in queue]
        if len(queue):
            nice = " then ".join(_ACTION_NAMES.get(a, a) for a in queue)
            say(f"Starting the docking run — I'll {nice} straight after it finishes.")
        ss.run_now = True
        return

    ss.pending_actions = []


def _resume_pending():
    """Run whatever was queued behind a docking run, now that it has finished.

    Kept deliberately defensive: a follow-up step failing must never discard the
    docking results the user was actually waiting for.
    """
    pend = ss.get("pending_actions") or []
    ss.pending_actions = []
    for step in pend:
        try:
            _run_sync_action(step.get("action"), dict(step.get("convo") or {}))
        except Exception as e:
            say(f"The follow-up {step.get('action')} step couldn't run: {e}")


def build_target(c):
    """Turn the chosen target string into a dockable target dict (gene or PDB ID)."""
    from agents.target_analyst import auto_grid_from_pdb  # lazy: pulls in gemmi
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


def _apply_result(result):
    """Turn a pipeline_core.run_job result dict into UI state: the chat message,
    the right-hand results panel, and Supabase persistence. Shared by BOTH the
    foreground fallback and the background-job poller, so there is exactly one
    place that knows how a finished run becomes UI."""
    if not result:
        say("The run didn't return anything — please try again.")
        return
    if not result.get("ok"):
        # a plain user-facing guard message (no target resolved / nothing to dock)
        say(result.get("say_text") or "I couldn't run that — please rephrase.")
        ss.stage = "start"
        ss.convo = {}
        return

    from viz import rehydrate_viz
    # result["viz"] is already in serialize_viz form (self-contained 2D SVG +
    # cropped complex text); rehydrate writes the complex back to disk for the
    # 3D viewer/report — identical to the history-reload path.
    viz = rehydrate_viz(result.get("viz") or {}, DATA)
    rdf = pd.DataFrame(result["rows"])         # already sorted best→worst by the core
    rdf.index = range(1, len(rdf) + 1)         # Rank starts at 1
    meta = result.get("meta") or {}
    ss.results = {"kind": "docking", "rdf": rdf, "viz": viz, "meta": meta,
                  "tier": result.get("tier") or "Standard"}
    ss.panel_open = True
    # persist the full summary so a reloaded conversation rebuilds the whole
    # report. Idempotent — the background worker may have already written this.
    if ss.active_conversation_id:
        try:
            authdb.save_results(ss.active_conversation_id,
                                {"gene": meta.get("gene"), "rows": result["rows"],
                                 "meta": meta, "viz": result.get("viz") or {}})
        except Exception:
            pass
    say(result["say_text"])
    ss.convo = {}   # reset for the next, independent request
    # A multi-step request ("dock X then run ADMET on it") parks its remaining
    # steps here while the dock runs in its subprocess. They carry their own
    # slot snapshot, which is why clearing ss.convo just above is safe.
    _resume_pending()


def run_pipeline(status_area):
    """FOREGROUND fallback: run the whole pipeline in-process, then apply the
    result. Used only when a detached background job can't be launched (e.g. an
    anonymous session with no persistent conversation to track the job against).
    The heavy scientific stack loads lazily inside pipeline_core."""
    from pipeline_core import run_job
    result = run_job(ss.convo, VINA, DATA, VENV, llm=_llm,
                     progress=lambda m: status_area.write(m))
    _apply_result(result)


def _job_data_dir(job_id):
    """A private working directory per background job, so concurrent/next runs
    never clash over the fixed c_lig_*/c_complex_* filenames dock_pipeline uses."""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(job_id))[:60] or "job"
    d = os.path.join(DATA, "jobs", safe, "work")
    os.makedirs(d, exist_ok=True)
    return d


def _start_background_job():
    """Launch the docking pipeline in a DETACHED subprocess so it keeps running
    even if the user closes the tab / refreshes / minimises / quits the browser,
    and — just as importantly — so a crash in native code cannot kill the app.
    Returns True if a background job is now in flight (→ switch to poll mode);
    False only if the subprocess could not be launched at all, in which case the
    caller falls back to a foreground run as a genuine last resort."""
    import docking_jobs as jobs
    # A logged-in session keys the job on its conversation id, so the run can be
    # reclaimed from any device by reopening that conversation. An ANONYMOUS
    # session has no such id — but it must still get its own process: the whole
    # point of the subprocess is that a native segfault (Vina/ProLIF/MDAnalysis)
    # kills only the child. Running it in-process instead would take the entire
    # app down for everyone, which is exactly the outage of 2026-07-19. So we
    # mint a throwaway id and isolate the run regardless; the only thing an
    # anonymous user gives up is reconnecting to it after closing the tab.
    job_id = ss.active_conversation_id or ss.get("anon_job_id")
    if not job_id:
        import uuid
        job_id = "anon-" + uuid.uuid4().hex[:16]
        ss.anon_job_id = job_id
    if jobs.is_running(job_id):
        ss.job_id = job_id
        say("A docking run is already going for this session — it keeps running on the "
            "server even if you leave. Results will appear here when it's done.")
        return True
    spec = {
        "job_id": job_id,
        "jobs_dir": jobs.default_jobs_dir(),
        "convo": dict(ss.convo),
        "vina": VINA,
        "data_dir": _job_data_dir(job_id),
        "venv": VENV,
        "conversation_id": ss.active_conversation_id,
    }
    try:
        started = jobs.start(job_id, spec)
    except Exception as e:
        say(f"Couldn't start the background run ({e}) — running it here instead.")
        return False
    if not started:
        return False
    ss.job_id = job_id
    ss.convo = {}   # captured in the spec already; clear so a new message starts fresh
    return True


def _render_job_progress():
    """If a background docking job is in flight (or just finished) for the current
    conversation, show its live progress and pick up its result. This is what
    makes a run survive a page reload: a reconnecting session finds the job by the
    conversation id and resumes watching it. Returns True if it handled a job."""
    import docking_jobs as jobs
    job_id = ss.get("job_id") or ss.active_conversation_id or ss.get("anon_job_id")
    if not job_id:
        return False
    st_ = jobs.read_status(job_id)
    if not st_:
        return False
    status = st_.get("status")

    if status == "running":
        ss.job_id = job_id
        with st.status("Docking is running on the server…", expanded=True) as area:
            area.write(st_.get("progress") or "Working…")
            area.write("✔ You can close this tab, refresh, or minimise — the run keeps "
                       "going and the result will be waiting here when you come back.")
        import time as _t
        _t.sleep(2.5)          # gentle poll cadence; the child does the real work
        st.rerun()
        return True

    if status == "done" and not st_.get("consumed"):
        result = jobs.read_result(job_id)
        jobs.mark_consumed(job_id)      # so a second tab / rerun won't re-announce it
        ss.job_id = None
        if result:
            _apply_result(result)
        else:
            say("The docking finished but its result couldn't be read — please re-run.")
        st.rerun()
        return True

    if status == "error" and not st_.get("consumed"):
        jobs.mark_consumed(job_id)
        ss.job_id = None
        say(f"The docking run stopped early: {st_.get('error')}")
        ss.stage = "start"
        st.rerun()
        return True

    return False


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
        ss.job_id = None
        ss.anon_job_id = None   # a new session gets a fresh job slot
        ss.pending_actions = []
        st.rerun()

    st.markdown(
        "<div style='font:600 11px \"Inter\",sans-serif;letter-spacing:1.2px;"
        "color:#93a0aa;margin:14px 0 4px;'>RECENT</div>",
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
                    from viz import rehydrate_viz
                    rdf = pd.DataFrame(stored["rows"])
                    rdf.index = range(1, len(rdf) + 1)   # match fresh docking (Rank starts at 1)
                    meta = stored.get("meta") or {}
                    meta.setdefault("gene", stored.get("gene"))
                    # rebuild the 2D/3D image data from what we persisted, so the
                    # reloaded report is as complete as a fresh one
                    viz = rehydrate_viz(stored.get("viz") or {}, DATA)
                    ss.results = {"kind": "docking", "rdf": rdf, "viz": viz,
                                  "meta": meta, "tier": "Standard"}
                else:
                    ss.results = None
                ss.stage, ss.active_conversation_id = "start", h["id"]
                # clear any job id from the previous conversation; the poller will
                # re-discover a job for THIS conversation from its id if one is live.
                ss.job_id = None
                ss.pending_actions = []
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
            ss.job_id = None
            ss.anon_job_id = None
            ss.pending_actions = []
            ss.auth_mode = None  # back to the flower's Log in / Sign up chooser
            st.rerun()

    # Data-source attributions (CC-BY / CC-BY-SA terms require credit) + tool credits.
    st.markdown("---")
    with st.expander("Data sources & credits"):
        st.markdown(
            "MUMO builds on open data and tools, with thanks:\n\n"
            "**Data**\n"
            "- UniProt — protein sequences (CC-BY 4.0)\n"
            "- STRING — interaction networks (CC-BY 4.0)\n"
            "- Open Targets — disease–target associations (CC-BY 4.0)\n"
            "- ChEMBL — bioactive compounds (CC-BY-SA 3.0)\n"
            "- AlphaFold DB — predicted structures (CC-BY 4.0)\n"
            "- RCSB PDB — experimental structures (public domain)\n"
            "- Therapeutics Data Commons — ADMET training data\n\n"
            "**Tools**\n"
            "- AutoDock Vina, RDKit, ProLIF, meeko, dimorphite-dl, "
            "ADMET-AI / Chemprop, self-hosted BLAST+\n"
            "- Built with Llama (Llama-3.3, via Groq)\n"
        )

# ── read chat input (pinned at bottom) ──
user_input = st.chat_input("Message MUMO…  e.g. “find a drug for cystic fibrosis”")
if user_input and user_input.strip():
    converse(user_input.strip())

# ── run the pipeline. Preferred path: a DETACHED SUBPROCESS that survives the
#    user leaving (tab close / refresh / minimise). Fallback: a foreground run
#    (anonymous sessions with no conversation id to track the job against). ──
if ss.run_now:
    ss.run_now = False
    if _start_background_job():
        st.rerun()                     # → poll mode, below
    else:
        with st.status("Running the pipeline…", expanded=True) as status_area:
            try:
                run_pipeline(status_area)
                status_area.update(label="Done", state="complete")
            except Exception as e:
                say(f"The run hit a snag: {e}")
                status_area.update(label="Failed", state="error")
        st.rerun()

# ── watch an in-flight (or freshly finished) background job for this conversation.
#    Runs every rerun, so a reconnecting session resumes the live progress. ──
_render_job_progress()


# ── report system: EVERY pipeline's output lands in the right-side panel,
# dispatched by its "kind". A new pipeline (STRING / BLAST / alignment / tree)
# plugs in by adding a title here + registering a renderer in _REPORT_RENDERERS
# — nothing else in the panel plumbing needs to change.
REPORT_TITLES = {
    "docking": "Docking report",
    "admet": "ADMET report",
    "string": "Interaction network",
    "blast": "BLAST results",
    "md": "Stability simulation",
    "alignment": "Sequence alignment",
    "phylogeny": "Phylogenetic tree",
}
_REPORT_RENDERERS = {}   # kind -> render fn(r); docking + admet handled inline below


def _report_kind(r):
    if not r:
        return None
    if r.get("kind"):
        return r["kind"]
    return "admet" if "druglikeness" in r else "docking"


def _report_title(r):
    return REPORT_TITLES.get(_report_kind(r), "Report")


def _run_stability_md(r, status_cb=lambda m: None):
    """Run the OpenMM pose-refinement + short relaxation on the best-scoring docked
    ligand of a docking result. Self-contained: derives the receptor + ligand from
    the (persisted) complex PDB, so it works for fresh AND reloaded results.
    Returns an md result dict, or {"_error": ...}."""
    from agents.md_analyst import run_stability_md
    from report_writer import _split_complex_pdb
    from rdkit import Chem
    from rdkit.Chem import AllChem

    rdf, viz, meta = r.get("rdf"), r.get("viz") or {}, r.get("meta") or {}
    label, smiles = None, None
    if rdf is not None:
        for _, row in rdf.iterrows():
            lab = row.get("Ligand")
            if str(row.get("Best affinity (kcal/mol)")) != "FAILED" and lab in viz:
                label, smiles = lab, row.get("SMILES")
                break
    if label is None:
        return {"_error": "No docked pose is available to simulate."}

    try:
        with open(viz[label]["complex"]) as f:
            complex_pdb = f.read()
    except Exception as e:
        return {"_error": f"Couldn't read the docked complex: {e}"}

    rec_pdb, lig_pdb = _split_complex_pdb(complex_pdb)
    if not rec_pdb or not lig_pdb:
        return {"_error": "Couldn't separate the protein and ligand."}

    lig = (Chem.MolFromPDBBlock(lig_pdb, sanitize=True, removeHs=False)
           or Chem.MolFromPDBBlock(lig_pdb, sanitize=False, removeHs=False))
    if lig is None:
        return {"_error": "Couldn't read the ligand structure."}
    if smiles:
        try:
            tmpl = Chem.MolFromSmiles(smiles)
            if tmpl is not None:
                lig = AllChem.AssignBondOrdersFromTemplate(tmpl, lig)
        except Exception:
            pass

    rec_path = os.path.join(DATA, "md_receptor.pdb")
    with open(rec_path, "w") as f:
        f.write(rec_pdb)

    res = run_stability_md(rec_path, lig, DATA, status=status_cb)
    if res and "_error" not in res:
        res["kind"], res["ligand"], res["meta"] = "md", label, meta
    return res


def render_results():
    from viz import render_complex_html  # lazy: 3D viewer helper
    _trace("render-results:enter")
    r = ss.results
    kind = _report_kind(r)
    _extra = _REPORT_RENDERERS.get(kind)
    if _extra:                       # new pipelines render through the registry
        _extra(r)
        return
    if kind == "admet":
        st.markdown(f"#### Drug-likeness — {r['lig_label']}")
        st.caption(f"`{r['lig_smiles']}`")
        narrative = r.get("narrative")
        if narrative:
            st.markdown(narrative)
            st.markdown("---")
        st.table(pd.DataFrame(list(r["druglikeness"].items()), columns=["Property", "Value"]))
        adm = r.get("admet_ml")
        if adm and "_error" not in adm:
            st.markdown("#### ADMET-AI predictions")
            st.caption("Pretrained ML models (Therapeutics Data Commons / Chemprop). "
                       "Classifier endpoints are probabilities 0–1 (higher = more likely); "
                       "regression endpoints are in native units.")
            st.table(pd.DataFrame(list(adm.items()), columns=["Endpoint", "Value"]))
        elif adm and "_error" in adm:
            st.caption(f"ADMET-AI predictions unavailable — {adm['_error']}")
        import report_writer
        _trace("report_writer:import+build (RDKit/Playwright)")
        st.download_button("Download report (.docx)", report_writer.build_admet_docx(r),
                           file_name=f"MUMO_ADMET_{r['lig_label']}.docx",
                           mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
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
                ("Best affinity (Vina)", f"{top['Best affinity (kcal/mol)']} kcal/mol"),
                ("Estimated Ki", str(top.get("Est. Ki", "—"))),
                ("Ligand efficiency", str(top.get("Ligand efficiency", "—"))),
                ("Vinardo rescore", f"{top.get('Vinardo (kcal/mol)', '—')} kcal/mol"),
                ("Consensus", str(top.get("Consensus", "—"))),
                ("Pose consistency", str(top.get("Pose consistency", "—"))),
                ("Confidence", str(top.get("Confidence", "—"))),
                ("Reliability", str(top.get("Reliability", "—"))),
                ("Total interactions", str(int(top["Total interactions"]))),
                ("H-bonds", str(int(top["H-bonds"]))),
            ]
            cells = "".join(
                f"<div style='min-width:110px;'>"
                f"<div style='font:10.5px \"Inter\",sans-serif;color:#93a0aa;"
                f"margin-bottom:4px;'>{label}</div>"
                f"<div style='font:600 20px \"IBM Plex Serif\",serif;color:#eef5fa;'>{value}</div>"
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

        # Full .docx report (every ligand: tables + write-up + 2D + 3D). Building it
        # renders a static screenshot per ligand via headless Chromium, which is too
        # slow to redo on every Streamlit rerun — so it's a two-step Generate → Download,
        # cached in session_state keyed by this results object (a fresh dock run gets a
        # fresh dict, so the cache naturally invalidates when new results land).
        import report_writer
        _trace("report_writer:import+build (RDKit/Playwright)")
        doc_key = f"_docx_bytes_{id(r)}"
        gcol, dcol = st.columns(2)
        with gcol:
            if st.button("Generate full report (.docx)", key=f"gen_{id(r)}"):
                with st.spinner("Building report — rendering 2D/3D snapshots for every "
                                "ligand (can take a minute for several ligands)…"):
                    ss[doc_key] = report_writer.build_docking_docx(r, _llm)
        with dcol:
            if ss.get(doc_key):
                st.download_button("Download report (.docx)", ss[doc_key],
                                   file_name=f"MUMO_{meta.get('gene', 'target')}_docking_report.docx",
                                   mime="application/vnd.openxmlformats-officedocument"
                                        ".wordprocessingml.document",
                                   key=f"dl_{id(r)}")

        # Raw structure export — the docked pose as PDB/SDF/MOL2 so the user can
        # open it in Discovery Studio / Maestro / BIOVIA / PyMOL. Derived from the
        # (persisted) complex PDB, so it works for fresh AND reloaded results. Cheap
        # file I/O → built once and cached, no separate "Generate" step needed.
        if r.get("viz"):
            zip_key = f"_struct_zip_{id(r)}"
            if zip_key not in ss:
                try:
                    ss[zip_key] = report_writer.build_structure_zip(r)
                except Exception:
                    ss[zip_key] = None
            if ss.get(zip_key):
                st.download_button("Download structures (.zip)", ss[zip_key],
                                   file_name=f"MUMO_{meta.get('gene', 'target')}_structures.zip",
                                   mime="application/zip", key=f"struct_{id(r)}")
                st.caption("Docked complex, ligand & receptor as PDB/SDF/MOL2 — open in "
                           "Discovery Studio, Maestro, BIOVIA, PyMOL, etc.")

        # Molecular stability simulation (OpenMM) — minimise + short relaxation of the
        # best docked complex. Only shown when the MD stack is actually installed
        # (it was rolled out of the shared conda env — see environment.yml note).
        try:
            from agents.md_analyst import MD_AVAILABLE as _MD_OK
        except Exception:
            _MD_OK = False
        if r.get("viz") and _MD_OK:
            if st.button("Run stability simulation (OpenMM)", key=f"md_{id(r)}",
                         help="Energy-minimise + briefly relax the docked complex with real "
                              "physics — a fast precursor to full molecular dynamics."):
                with st.status("Molecular simulation — this takes a few minutes…",
                               expanded=True) as _mds:
                    res = _run_stability_md(r, status_cb=lambda m: _mds.write(m))
                    if res and "_error" not in res:
                        with st.spinner("Writing the simulation report…"):
                            res["narrative"] = _md_narrative(res)
                        _mds.update(label="Simulation complete", state="complete")
                        ss.results = res
                        ss.panel_open = True
                        st.rerun()
                    else:
                        _mds.update(label="Simulation could not run", state="error")
                        st.error((res or {}).get("_error", "Unknown error."))
            st.caption("Refines the pose with real physics and checks the ligand stays in the "
                       "pocket (implicit solvent, protein restrained).")

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
                        f'<div style="background-color: white; padding: 16px; border-radius: 12px; border: 1px solid rgba(111,184,236,0.28); box-shadow: 0 8px 28px -10px rgba(0,0,0,0.5); display: flex; justify-content: center; align-items: center; max-width: 760px; margin: 1.5rem auto 0.5rem auto;">{svg_content}</div>',
                        unsafe_allow_html=True
                    )
                    def _sw(color, label):
                        return (f"<span style='display:inline-block;width:11px;height:11px;"
                                f"border-radius:50%;background:{color};margin:0 5px -1px 12px;'></span>{label}")
                    st.markdown(
                        "<div style='text-align:center; color:rgba(226,232,240,0.7); font-size:0.82rem; margin-top:0.3rem;'>"
                        + _sw("#2e8b3d", "H-bond") + _sw("#c665a6", "Hydrophobic")
                        + _sw("#cf4a2e", "Salt bridge") + _sw("#7a5cc0", "Pi-stack")
                        + _sw("#d5811f", "Pi-cation") + _sw("#1f93a6", "Halogen")
                        + "<br><span style='opacity:0.7;'>Each residue is a colour-coded circle linked "
                          "to the ligand atom it interacts with (solid = H-bond).</span></div>",
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
                    _trace("3d-viewer:build-html")
                    components.html(render_complex_html(entry["complex"], entry["ia"],
                                    options=opts, height=520), height=540)
                    _trace("3d-viewer:ok")
                except Exception as e:
                    st.caption(f"(3D view unavailable: {e})")


def _render_string_report(r):
    """STRING interaction report: network image + partners + enriched pathways."""
    import re
    names = ", ".join(r.get("input", [])) or "protein"
    st.markdown(f"#### Interaction network — {names}")
    st.caption("STRING protein–protein associations (known + predicted). "
               "Combined score 0–1 from several evidence channels.")

    svg = r.get("network_svg") or ""
    if svg:
        # make the root <svg> responsive: add a viewBox from its px width/height
        # (STRING uses single-quoted attrs, no viewBox), then let it scale to width
        m = re.search(r"<svg[^>]*?>", svg)
        if m:
            tag = m.group(0)
            wm = re.search(r'width=["\']([\d.]+)', tag)
            hm = re.search(r'height=["\']([\d.]+)', tag)
            newtag = tag
            if wm and hm and "viewbox" not in tag.lower():
                newtag = re.sub(r"<svg", f'<svg viewBox="0 0 {wm.group(1)} {hm.group(1)}"',
                                newtag, count=1)
            newtag = re.sub(r'\swidth=["\'][^"\']*["\']', ' width="100%"', newtag, count=1)
            newtag = re.sub(r'\sheight=["\'][^"\']*["\']', "", newtag, count=1)
            svg = svg.replace(tag, newtag, 1)
        st.markdown(
            f'<div style="background:#fff;padding:10px;border-radius:12px;'
            f'border:1px solid rgba(111,184,236,0.28);box-shadow:0 8px 28px -10px rgba(0,0,0,0.5);'
            f'overflow:auto;">{svg}</div>', unsafe_allow_html=True)

    narrative = r.get("narrative")
    if narrative:
        st.markdown(narrative)
        st.markdown("---")

    partners = r.get("partners") or []
    if partners:
        rows = [{"Partner": p.get("preferredName_B", "?"),
                 "Score": round(p.get("score", 0), 3),
                 "Experimental": round(p.get("escore", 0), 3),
                 "Database": round(p.get("dscore", 0), 3),
                 "Text-mining": round(p.get("tscore", 0), 3)} for p in partners]
        st.markdown("##### Functional partners")
        st.dataframe(pd.DataFrame(rows), use_container_width=True,
                     height=min(35 * (len(rows) + 1) + 3, 320))

    enr = r.get("enrichment") or []
    if enr:
        top = sorted(enr, key=lambda e: e.get("fdr", 1.0))[:12]
        rows = [{"Category": e.get("category", ""), "Term": e.get("description", ""),
                 "FDR": "{:.1e}".format(e.get("fdr", 1.0))} for e in top]
        st.markdown("##### Enriched pathways / functions")
        st.caption("Lower FDR = stronger over-representation in this neighbourhood.")
        st.dataframe(pd.DataFrame(rows), use_container_width=True,
                     height=min(35 * (len(rows) + 1) + 3, 320))

    # Full .docx report — rasterizing the network SVG via headless Chromium is too
    # slow to redo on every rerun, so it's a two-step Generate → Download (same
    # pattern as the docking report), cached in session_state per results object.
    import report_writer
    doc_key = f"_docx_bytes_{id(r)}"
    gcol, dcol = st.columns(2)
    with gcol:
        if st.button("Generate report (.docx)", key=f"gen_{id(r)}"):
            with st.spinner("Building report — rendering the network image…"):
                ss[doc_key] = report_writer.build_string_docx(r)
    with dcol:
        if ss.get(doc_key):
            st.download_button("Download report (.docx)", ss[doc_key],
                               file_name=f"MUMO_STRING_{names.replace(', ', '_')}.docx",
                               mime="application/vnd.openxmlformats-officedocument"
                                    ".wordprocessingml.document",
                               key=f"dl_{id(r)}")


_REPORT_RENDERERS["string"] = _render_string_report


def _render_blast_report(r):
    """BLAST report: query info + plain-language narrative + hits table."""
    st.markdown(f"#### BLAST results — {r.get('query_name', 'query')}")
    acc = r.get("accession")
    st.caption(f"{('UniProt ' + acc + ' · ') if acc else ''}{r.get('seq_len', '?')} residues · "
               f"{r.get('program', 'blastp')} vs {r.get('database', 'swissprot')}")

    narrative = r.get("narrative")
    if narrative:
        st.markdown(narrative)
        st.markdown("---")

    hits = r.get("hits") or []
    if hits:
        rows = [{"Accession": h.get("accession", ""), "Organism": h.get("sciname", ""),
                 "Identity %": h.get("identity"),
                 "E-value": "{:.1e}".format(h.get("evalue", 0)),
                 "Bit score": h.get("bit_score"),
                 "Description": h.get("title", "")[:60]} for h in hits]
        st.markdown("##### Top hits")
        st.dataframe(pd.DataFrame(rows), use_container_width=True,
                     height=min(35 * (len(rows) + 1) + 3, 380))
    else:
        st.info("No significant BLAST hits found.")


_REPORT_RENDERERS["blast"] = _render_blast_report


MD_REPORT_SYSTEM = (
    "You are MUMO, explaining a molecular-simulation result to a pharmacy student NEW to "
    "molecular dynamics. Make it genuinely easy while staying correct.\n\n"
    "Markdown sections and headings:\n"
    "## What this simulation did\n(2–3 sentences: docking gives one static best-guess pose; "
    "this step used real physics — energy minimisation plus a short relaxation with OpenMM — "
    "to let the docked complex settle and to check the drug doesn't immediately fall out of "
    "the pocket. Note it is a FAST, lightweight precursor to full molecular dynamics, not a "
    "long simulation.)\n"
    "## What happened to the pose\n(explain the ligand RMSD — root-mean-square deviation, i.e. "
    "how far on average the drug's atoms moved, in ångström — and the energy drop, which means "
    "steric clashes from docking were relieved. Say what a small vs large movement implies.)\n"
    "## What this tells us\n(the plain-language takeaway: is the docked pose physically "
    "sensible / likely to stay put, or does it look strained? What a medicinal chemist takes "
    "from this.)\n"
    "## The honest caveat\n(one line: a true 'does it stay bound over time' answer needs a "
    "much longer dynamics run on a GPU — this is the quick first look.)\n\n"
    "RULES: define EVERY technical term the first time it appears. Short paragraphs. Warm tutor "
    "tone. No emojis. Use ONLY the numbers provided — never invent values."
)


def _md_narrative(data):
    """Plain-language explanation of a stability-simulation result."""
    if _llm is None:
        return ""
    prompt = (
        f"LIGAND: {data.get('ligand', 'the ligand')}  TARGET: {data.get('meta', {}).get('gene', '')}\n"
        f"Energy before minimisation: {data.get('energy_initial')} kcal/mol\n"
        f"Energy after minimisation: {data.get('energy_minimized')} kcal/mol\n"
        f"Energy drop (strain relieved): {data.get('energy_drop')} kcal/mol\n"
        f"Ligand movement during minimisation (RMSD): {data.get('lig_rmsd_min')} Å\n"
        f"Ligand movement during {data.get('relax_ps')} ps relaxation (RMSD): {data.get('lig_rmsd_relax')} Å\n"
        f"Verdict: {data.get('verdict')}\n\n"
        "Write the beginner-friendly simulation report now.")
    try:
        return _llm.chat(MD_REPORT_SYSTEM, prompt, temperature=0.4, max_tokens=1000)
    except Exception:
        return ""


def _render_md_report(r):
    """Molecular stability-simulation report: metrics + narrative + refined structure."""
    st.markdown(f"#### Stability simulation — {r.get('ligand', 'ligand')}")
    st.caption("OpenMM energy minimisation + short relaxation (implicit solvent, protein "
               "restrained) — a fast precursor to full molecular dynamics.")

    metrics = [
        ("Verdict", str(r.get("verdict", "—"))),
        ("Ligand RMSD (minimise)", f"{r.get('lig_rmsd_min', '—')} Å"),
        ("Ligand RMSD (relax)", f"{r.get('lig_rmsd_relax', '—')} Å"
         if r.get("lig_rmsd_relax") is not None else "—"),
        ("Energy relieved", f"{r.get('energy_drop', '—')} kcal/mol"),
    ]
    cells = "".join(
        f"<div style='min-width:120px;'>"
        f"<div style='font:10.5px \"Inter\",sans-serif;color:#93a0aa;margin-bottom:4px;'>{label}</div>"
        f"<div style='font:600 19px \"IBM Plex Serif\",serif;color:#eef5fa;'>{value}</div></div>"
        for label, value in metrics)
    st.markdown(f"<div style='display:flex;flex-wrap:wrap;gap:18px;margin:12px 0 18px;'>{cells}</div>",
                unsafe_allow_html=True)

    narrative = r.get("narrative")
    if narrative:
        st.markdown(narrative)
        st.markdown("---")

    refined = r.get("refined_pdb")
    if refined:
        try:
            with open(refined) as f:
                st.download_button("Download refined structure (.pdb)", f.read(),
                                   file_name=f"MUMO_{r.get('ligand', 'complex')}_refined.pdb",
                                   mime="chemical/x-pdb", key=f"mdpdb_{id(r)}")
        except Exception:
            pass


_REPORT_RENDERERS["md"] = _render_md_report


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
# The drawer has two widths: a compact default and an expanded view (for wide
# tables, the 3D pose and reports). The chat column's width is derived from this,
# so it reflows automatically when the panel is expanded/collapsed.
PANEL_WIDTH = 760 if ss.panel_expanded else 420
panel_showing = bool(ss.results and ss.panel_open)

st.markdown(f"""
<style>
.block-container {{ transition: width .25s ease; }}
{f'''.stMain {{ align-items: flex-start !important; }}
.block-container {{
    max-width: none !important; width: calc(100% - {PANEL_WIDTH + 40}px) !important;
    padding-right: 24px;
}}''' if panel_showing else ''}
@media (max-width: 1200px) {{
    .stMain {{ align-items: center !important; }}
    .block-container {{ max-width: none !important; width: 100% !important; padding-right: 1rem !important; }}
}}
</style>
""", unsafe_allow_html=True)

render_chat()

if panel_showing:
    with st.container(key="mumo_panel"):
        st.markdown(f"""
<style>
.st-key-mumo_panel {{
    position: fixed; top: 0; right: 0; width: {PANEL_WIDTH}px; height: 100vh;
    overflow-y: auto; z-index: 999; background: #0d1114;
    border-left: 1px solid rgba(255,255,255,0.08);
    box-shadow: -14px 0 34px -18px rgba(0,0,0,0.6);
    padding: 22px 24px 40px;
    transition: width .25s ease;
}}
@media (max-width: 900px) {{
    .st-key-mumo_panel {{ width: 100vw; }}
}}
</style>
""", unsafe_allow_html=True)
        h = st.columns([5, 1, 1])
        _rep = _report_title(ss.results)
        h[0].markdown(f"<div class='mumo-panel-header'>{_rep}</div>", unsafe_allow_html=True)
        _exp_icon = "⤡" if ss.panel_expanded else "⤢"
        _exp_help = "Collapse panel" if ss.panel_expanded else "Expand panel"
        if h[1].button(_exp_icon, key="expand_panel", help=_exp_help):
            ss.panel_expanded = not ss.panel_expanded
            st.rerun()
        if h[2].button("✕", key="close_panel", help=f"Close {_rep.lower()}"):
            ss.panel_open = False
            st.rerun()
        render_results()
elif ss.results and not ss.panel_open:
    _rep = _report_title(ss.results).lower()
    if st.button(f"› Open {_rep}", key="open_panel"):
        ss.panel_open = True
        st.rerun()
