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


def _secret(name):
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
        res = sb.auth.refresh_session(token)
        st.session_state["user"] = {"id": res.user.id, "email": res.user.email}
        # Supabase rotates refresh tokens on use — the URL must be updated to
        # the new one or the *next* refresh will fail with a reused token.
        if res.session and res.session.refresh_token:
            st.query_params[QUERY_PARAM] = res.session.refresh_token
    except Exception:
        st.query_params.pop(QUERY_PARAM, None)  # stale/invalid — stop retrying it


def sign_up(email, password):
    sb = get_client()
    return sb.auth.sign_up({"email": email, "password": password})


def sign_in(email, password):
    sb = get_client()
    res = sb.auth.sign_in_with_password({"email": email, "password": password})
    st.session_state["user"] = {"id": res.user.id, "email": res.user.email}
    if res.session and res.session.refresh_token:
        st.query_params[QUERY_PARAM] = res.session.refresh_token
    return res


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
    sb = get_client()
    r = sb.table("conversations").insert({"user_id": user_id, "title": title[:80]}).execute()
    return r.data[0]["id"]


def touch_conversation(conversation_id, title=None):
    sb = get_client()
    payload = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if title:
        payload["title"] = title[:80]
    sb.table("conversations").update(payload).eq("id", conversation_id).execute()


def list_conversations(user_id, limit=20):
    sb = get_client()
    r = (sb.table("conversations").select("id,title,updated_at")
         .eq("user_id", user_id).order("updated_at", desc=True).limit(limit).execute())
    return r.data or []


def save_message(conversation_id, user_id, role, content):
    sb = get_client()
    sb.table("messages").insert({
        "conversation_id": conversation_id, "user_id": user_id,
        "role": role, "content": content,
    }).execute()


def load_messages(conversation_id):
    sb = get_client()
    r = (sb.table("messages").select("role,content")
         .eq("conversation_id", conversation_id).order("created_at").execute())
    return [{"role": m["role"], "content": m["content"]} for m in (r.data or [])]


def save_results(conversation_id, results_summary):
    """Store a small JSON summary of docking results (not the raw viz blobs)."""
    sb = get_client()
    sb.table("conversations").update({"results": results_summary}).eq("id", conversation_id).execute()


def load_results(conversation_id):
    sb = get_client()
    r = sb.table("conversations").select("results").eq("id", conversation_id).single().execute()
    return (r.data or {}).get("results")


def delete_conversation(conversation_id):
    sb = get_client()
    sb.table("conversations").delete().eq("id", conversation_id).execute()


# ──────────── personalization: what has this user asked about before? ─────

def recent_user_topics(user_id, limit=40):
    """This user's own past USER questions (across all conversations), so
    MUMO's brain can recall what they've already explored — diseases,
    targets, ligands they keep returning to — instead of starting cold
    every session."""
    sb = get_client()
    r = (sb.table("messages").select("content")
         .eq("user_id", user_id).eq("role", "user")
         .order("created_at", desc=True).limit(limit).execute())
    return [m["content"] for m in (r.data or [])]
