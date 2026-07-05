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
ss.setdefault("active_conversation_id", None)  # Supabase conversation row, once logged in
ss.setdefault("entered", False)  # has the visitor clicked past the intro landing page?
ss.setdefault("auth_mode", None)  # None | "login" | "signup" — which form the flower page reveals
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
    "   - 'chat'    : everything else — answering, teaching, explaining results, or asking "
    "ONE clarifying question. When unsure, use 'chat'.\n\n"
    "Reply with ONLY a JSON object, nothing else:\n"
    '{"action": "chat"|"dock"|"analyze"|"string", '
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


def _history_text(n=10):
    return "\n".join(f'{m["role"]}: {m["content"]}' for m in ss.messages[-n:])


def _resolve_ligands(lig):
    """Resolve a ligand (name/SMILES) OR a list of them into [{label, smiles}]."""
    from agents.admet import resolve_ligand  # lazy: pulls in RDKit
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
    if r.get("kind") == "string" or "partners" in r:
        names = ", ".join(r.get("input", []))
        parts = ", ".join(p.get("preferredName_B", "") for p in r.get("partners", [])[:12])
        return (f"Latest STRING interaction network for {names}. "
                f"Top functional partners: {parts}. (Full network + report in the side panel.)")
    if "rdf" not in r:
        return "The latest result is shown in the side panel."
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
    from brain import parse_intent  # lazy imports (heavy scientific stack)
    from agents.admet import resolve_ligand, druglikeness, admet_ml
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

    # analyze-only → drug-likeness + ADMET-AI predictions, no docking
    if action == "analyze" and c.get("ligand"):
        one = c["ligand"][0] if isinstance(c["ligand"], list) else c["ligand"]
        smi, label = resolve_ligand(str(one))
        if smi:
            res = {"kind": "admet", "druglikeness": druglikeness(smi),
                   "lig_label": label, "lig_smiles": smi}
            with st.spinner("Running ADMET-AI models (hERG, CYP, Ames, DILI…)"):
                res["admet_ml"] = admet_ml(smi)
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

    if action == "dock":
        # resolve the CURRENT ligand(s) fresh (supports a single name OR a comparison list)
        c["ligand_objs"] = _resolve_ligands(c.get("ligand"))
        c["tier"] = c.get("tier") or "Standard"
        ss.run_now = True
    # action == "chat" → the reply IS the whole answer; nothing more to run


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


def run_pipeline(status_area):
    # lazy imports — the heavy docking/scientific stack only loads on a real run
    from agents.target_finder import find_targets
    from agents.ligand_scout import find_ligands
    from pipeline import dock_pipeline
    from brain import write_report
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
    ss.results = {"kind": "docking", "rdf": rdf, "viz": viz, "meta": meta,
                  "tier": c["tier"] or "Standard"}
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
            ss.auth_mode = None  # back to the flower's Log in / Sign up chooser
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


# ── report system: EVERY pipeline's output lands in the right-side panel,
# dispatched by its "kind". A new pipeline (STRING / BLAST / alignment / tree)
# plugs in by adding a title here + registering a renderer in _REPORT_RENDERERS
# — nothing else in the panel plumbing needs to change.
REPORT_TITLES = {
    "docking": "Docking report",
    "admet": "ADMET report",
    "string": "Interaction network",
    "blast": "BLAST results",
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


def render_results():
    from viz import render_complex_html  # lazy: 3D viewer helper
    r = ss.results
    kind = _report_kind(r)
    _extra = _REPORT_RENDERERS.get(kind)
    if _extra:                       # new pipelines render through the registry
        _extra(r)
        return
    if kind == "admet":
        st.markdown(f"#### Drug-likeness — {r['lig_label']}")
        st.caption(f"`{r['lig_smiles']}`")
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
                    components.html(render_complex_html(entry["complex"], entry["ia"],
                                    options=opts, height=520), height=540)
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


_REPORT_RENDERERS["string"] = _render_string_report


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
}}
@media (max-width: 900px) {{
    .st-key-mumo_panel {{ width: 100vw; }}
}}
</style>
""", unsafe_allow_html=True)
        h = st.columns([5, 1])
        _rep = _report_title(ss.results)
        h[0].markdown(f"<div class='mumo-panel-header'>{_rep}</div>", unsafe_allow_html=True)
        if h[1].button("✕", key="close_panel", help=f"Close {_rep.lower()}"):
            ss.panel_open = False
            st.rerun()
        render_results()
elif ss.results and not ss.panel_open:
    _rep = _report_title(ss.results).lower()
    if st.button(f"› Open {_rep}", key="open_panel"):
        ss.panel_open = True
        st.rerun()
