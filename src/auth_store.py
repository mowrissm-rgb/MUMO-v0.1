"""
MUMO — Auth & Cloud Storage (Supabase)
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

Handles user accounts (email + password, via Supabase Auth) and persists
every conversation + every question a user asks to Supabase Postgres, so:
  - chat history survives a page refresh / a new browser session
  - MUMO can recall what THIS user has asked before and use it as light
    personalization context (see recent_user_topics)

Needs two secrets (see .streamlit/secrets.toml.example):
    SUPABASE_URL, SUPABASE_KEY   (the anon/public key — RLS protects rows)

If they're missing, every function here degrades to a no-op / None so the
rest of the app keeps working in local-only mode (same philosophy as
llm_client.get_llm() returning None with no API key).

Schema: run supabase_schema.sql once in the Supabase SQL editor.
"""

import os
import json
from datetime import datetime, timezone

import streamlit as st

try:
    from supabase import create_client
except Exception:
    create_client = None

QUERY_PARAM = "rt"  # carries the Supabase refresh token across a page reload

# mumo_config.json lives at the project root, found via THIS file's own path —
# unlike st.secrets, this doesn't depend on the process's working directory,
# which can differ from the project root depending on how streamlit was launched.
_CFG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "mumo_config.json")


def _config_file():
    if os.path.exists(_CFG_PATH):
        try:
            with open(_CFG_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _clean_ascii(v):
    """SUPABASE_URL and SUPABASE_KEY are guaranteed pure ASCII by construction
    (a URL and a JWT) — but secrets pasted into a web text box can pick up
    invisible/typographic characters (smart quotes, zero-width spaces, BOM)
    that later blow up strict-ASCII header encoding deep in httpx. Stripping
    anything outside ASCII is always safe here and neutralizes that class of
    bug regardless of exactly which character snuck in or how."""
    if not isinstance(v, str):
        return v
    return "".join(ch for ch in v if ord(ch) < 128).strip()


# MUMO's own Supabase project — the anon key is a PUBLIC key by design (every
# Supabase web app ships it client-side; Row Level Security is what actually
# protects the data, not secrecy of this key). It's hardcoded here, taking
# ABSOLUTE priority over st.secrets/env/config for these two names, because
# pasting it into a Streamlit Cloud secrets text box has repeatedly come back
# silently corrupted — one character swapped for a lookalike somewhere in the
# 208-char token, with no error at paste time, just a rejected "Invalid API
# key" later. Confirmed via a direct curl against Supabase that this exact
# value is correct. Streamlit Cloud also mirrors secrets.toml into
# os.environ, so an "env var can override" escape hatch would just let the
# same corrupted value back in through that door — hence no override at all
# for these two. To point this app at a different Supabase project, edit the
# values below directly.
_DEFAULTS = {
    "SUPABASE_URL": "https://kdvckgzvnkhuaplnskpg.supabase.co",
    "SUPABASE_KEY": (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6"
        "ImtkdmNrZ3p2bmtodWFwbG5za3BnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODI4NDU5"
        "NTIsImV4cCI6MjA5ODQyMTk1Mn0.TPc1TbiXtTPGWPjoeF_YUEz7aVpSxTtMGU2NWtCFP90"
    ),
}


def _secret(name):
    if name in _DEFAULTS:
        return _DEFAULTS[name]
    try:
        if name in st.secrets:
            return _clean_ascii(st.secrets[name])
    except Exception:
        pass
    if os.environ.get(name):
        return _clean_ascii(os.environ[name])
    return _clean_ascii(_config_file().get("supabase", {}).get(name))


def get_client():
    """A cached Supabase client, or None if not configured / not installed."""
    if create_client is None:
        return None
    url, key = _secret("SUPABASE_URL"), _secret("SUPABASE_KEY")
    if not url or not key:
        return None
    if "_sb_client" not in st.session_state:
        try:
            st.session_state["_sb_client"] = create_client(url, key)
        except Exception:
            st.session_state["_sb_client"] = None
    return st.session_state["_sb_client"]


def is_configured():
    return get_client() is not None


# ── resilient calls: Supabase (via httpx) keeps a persistent HTTP/2 connection,
#    and its server closes IDLE connections with a GOAWAY. The next query on the
#    stale cached client then raises a transport error (e.g. RemoteProtocolError:
#    ConnectionTerminated) — which, uncaught, used to crash the whole page when a
#    user clicked a past conversation after a quiet spell. `_run` retries once on
#    exactly those transport errors, dropping the cached client so it reconnects
#    fresh; reads pass swallow=True to return a safe default instead of crashing
#    if it still fails. ──
_RETRYABLE_NAMES = {
    "RemoteProtocolError", "RemoteDisconnected", "ConnectError", "ConnectTimeout",
    "ReadError", "ReadTimeout", "WriteError", "PoolTimeout", "ConnectionResetError",
    "ConnectionError", "ProtocolError",
}
_RETRYABLE_TEXT = ("ConnectionTerminated", "Server disconnected", "Connection reset",
                   "connection was closed", "RemoteProtocolError", "GOAWAY", "EOF occurred")


def _is_retryable(exc):
    if type(exc).__name__ in _RETRYABLE_NAMES:
        return True
    s = str(exc)
    return any(t in s for t in _RETRYABLE_TEXT)


def _run(fn, default=None, swallow=False, retries=1):
    """Run fn(sb) against the Supabase client with one transparent reconnect on a
    dropped-connection error. If it ultimately fails: return `default` when
    swallow=True (reads — never crash the app), else re-raise (auth/writes —
    surface the real error to the caller/UI)."""
    sb = get_client()
    if sb is None:
        return default
    last = None
    for attempt in range(retries + 1):
        try:
            return fn(sb)
        except Exception as e:
            last = e
            if attempt < retries and _is_retryable(e):
                st.session_state.pop("_sb_client", None)   # force a fresh connection
                sb = get_client()
                if sb is None:
                    break
                continue
            break
    if swallow:
        return default
    raise last


# ─────────────────────────── session lifecycle ────────────────────────────

def restore_session():
    """On a fresh page load, try to silently log the user back in using the
    refresh token carried in the URL (?rt=...). Call once, early, before
    rendering the app.

    Why a query param and not a cookie: Streamlit's own JS sandbox blocks the
    two usual browser-persistence routes — st.components.v1.html runs inside
    an iframe with no allow-top-navigation (so it can write a cookie but can
    never redirect the real tab to read one back), and st.markdown strips
    inline event-handler attributes from any HTML it renders (so no script
    execution in the top-level page either). st.query_params is the one
    piece of browser-persisted state Streamlit itself is willing to sync to
    the address bar, so the refresh token rides there instead. It survives a
    normal page refresh (same URL is reloaded) but is visible in the URL/
    browser history — acceptable for a small personal tool, worth revisiting
    (e.g. a proper custom component) before wider deployment."""
    sb = get_client()
    if sb is None or st.session_state.get("user"):
        return

    token = st.query_params.get(QUERY_PARAM)
    if not token:
        return

    try:
        # reconnect-retry on a dropped connection so a transient network blip
        # doesn't look like an invalid token and log the user out
        res = _run(lambda c: c.auth.refresh_session(token))
        st.session_state["user"] = {"id": res.user.id, "email": res.user.email}
        # Supabase rotates refresh tokens on use — the URL must be updated to
        # the new one or the *next* refresh will fail with a reused token.
        if res.session and res.session.refresh_token:
            st.query_params[QUERY_PARAM] = res.session.refresh_token
    except Exception:
        st.query_params.pop(QUERY_PARAM, None)  # stale/invalid — stop retrying it


def sign_up(email, password):
    return _run(lambda sb: sb.auth.sign_up({"email": email, "password": password}))


def sign_in(email, password):
    def _q(sb):
        res = sb.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state["user"] = {"id": res.user.id, "email": res.user.email}
        if res.session and res.session.refresh_token:
            st.query_params[QUERY_PARAM] = res.session.refresh_token
        return res
    return _run(_q)


def resend_confirmation(email):
    return _run(lambda sb: sb.auth.resend({"type": "signup", "email": email}))


def sign_out():
    sb = get_client()
    try:
        sb.auth.sign_out()
    except Exception:
        pass
    st.session_state.pop("user", None)
    st.query_params.pop(QUERY_PARAM, None)


def current_user():
    return st.session_state.get("user")


# ─────────────────────── conversation + message storage ───────────────────

def create_conversation(user_id, title):
    def _q(sb):
        r = sb.table("conversations").insert({"user_id": user_id, "title": title[:80]}).execute()
        return r.data[0]["id"]
    return _run(_q)


def touch_conversation(conversation_id, title=None):
    def _q(sb):
        payload = {"updated_at": datetime.now(timezone.utc).isoformat()}
        if title:
            payload["title"] = title[:80]
        sb.table("conversations").update(payload).eq("id", conversation_id).execute()
    # non-critical bookkeeping — never let it crash the app
    return _run(_q, swallow=True)


def list_conversations(user_id, limit=20):
    def _q(sb):
        r = (sb.table("conversations").select("id,title,updated_at")
             .eq("user_id", user_id).order("updated_at", desc=True).limit(limit).execute())
        return r.data or []
    return _run(_q, default=[], swallow=True)


def save_message(conversation_id, user_id, role, content):
    def _q(sb):
        sb.table("messages").insert({
            "conversation_id": conversation_id, "user_id": user_id,
            "role": role, "content": content,
        }).execute()
    return _run(_q)


def load_messages(conversation_id):
    def _q(sb):
        r = (sb.table("messages").select("role,content")
             .eq("conversation_id", conversation_id).order("created_at").execute())
        return [{"role": m["role"], "content": m["content"]} for m in (r.data or [])]
    return _run(_q, default=[], swallow=True)


def save_results(conversation_id, results_summary):
    """Store a small JSON summary of docking results (not the raw viz blobs)."""
    def _q(sb):
        sb.table("conversations").update({"results": results_summary}).eq("id", conversation_id).execute()
    return _run(_q)


def load_results(conversation_id):
    def _q(sb):
        r = sb.table("conversations").select("results").eq("id", conversation_id).single().execute()
        return (r.data or {}).get("results")
    return _run(_q, default=None, swallow=True)


def delete_conversation(conversation_id):
    def _q(sb):
        sb.table("conversations").delete().eq("id", conversation_id).execute()
    return _run(_q, swallow=True)


# ──────────── personalization: what has this user asked about before? ─────

def recent_user_topics(user_id, limit=40):
    """This user's own past USER questions (across all conversations), so
    MUMO's brain can recall what they've already explored — diseases,
    targets, ligands they keep returning to — instead of starting cold
    every session."""
    def _q(sb):
        r = (sb.table("messages").select("content")
             .eq("user_id", user_id).eq("role", "user")
             .order("created_at", desc=True).limit(limit).execute())
        return [m["content"] for m in (r.data or [])]
    return _run(_q, default=[], swallow=True)
