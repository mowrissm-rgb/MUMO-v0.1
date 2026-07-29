"""
MUMO — LLM Client (provider-agnostic)
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

WHAT THIS DOES (plain English)
------------------------------
This is the single doorway MUMO uses to talk to ANY large language model —
GPT-4 (OpenAI), Claude (Anthropic), Gemini (Google), or a free model (Groq).
The rest of MUMO doesn't care which one is behind it; it just calls chat().

WHERE THE KEY COMES FROM
    1. Streamlit secrets (.streamlit/secrets.toml)  ← used on the cloud
    2. environment variables                        ← used locally
    3. a local mumo_config.json file                ← easy manual setup
If no key is found, get_llm() returns None and MUMO uses its rule-based brain
instead — so the app always works, with or without a paid key.

We use plain HTTP (requests) so there are NO heavy SDKs to install.
"""

import os
import json
import re
import time

import requests


def _retry_after_seconds(resp):
    """How long the provider says to wait, in seconds, or None if it didn't say.

    Groq answers a 429 with Retry-After, and also puts a human phrasing in the
    JSON body ("Please try again in 6.9s" / "in 21m30s"), so both are read.
    """
    ra = (resp.headers or {}).get("Retry-After")
    if ra:
        try:
            return float(ra)
        except (TypeError, ValueError):
            pass
    try:
        msg = resp.json().get("error", {}).get("message", "")
    except Exception:
        msg = resp.text or ""
    m = re.search(r"try again in\s+(?:(\d+)m)?\s*([\d.]+)?s", msg, re.I)
    if m:
        mins = float(m.group(1) or 0)
        secs = float(m.group(2) or 0)
        return mins * 60 + secs
    return None


def _rate_limit_message(resp, wait):
    """A 429 explained in terms the user can act on.

    The distinction that matters is per-minute versus per-day: one is worth
    waiting out, the other means the day's free quota is gone.
    """
    try:
        detail = resp.json().get("error", {}).get("message", "") or ""
    except Exception:
        detail = (resp.text or "")[:200]
    when = ""
    if wait is not None:
        when = (f" Try again in about {int(wait)} seconds."
                if wait < 120 else
                f" The limit resets in about {int(wait / 60)} minutes.")
    return ("The language model is rate-limited right now (HTTP 429) — the key "
            "works, it has simply been used too much in the last window." + when +
            (f" Provider said: {detail[:200]}" if detail else ""))

# Each provider: the endpoint, a default model, and how to read its key.
PROVIDERS = {
    "openai":    {"model": "gpt-4o-mini",                 "env": "OPENAI_API_KEY"},
    "anthropic": {"model": "claude-3-5-haiku-latest",     "env": "ANTHROPIC_API_KEY"},
    "gemini":    {"model": "gemini-1.5-flash",            "env": "GEMINI_API_KEY"},
    "groq":      {"model": "llama-3.3-70b-versatile",     "env": "GROQ_API_KEY"},
}


def _read_config():
    """Find provider + key from Streamlit secrets, env vars, or mumo_config.json."""
    # 1) Streamlit secrets (only if streamlit is running)
    try:
        import streamlit as st
        if "llm" in st.secrets:
            return dict(st.secrets["llm"])
    except Exception:
        pass
    # 2) local config file
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "mumo_config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path) as f:
                return json.load(f).get("llm", {})
        except Exception:
            pass
    # 3) environment variables — pick the first provider that has a key set
    for provider, meta in PROVIDERS.items():
        if os.environ.get(meta["env"]):
            return {"provider": provider, "api_key": os.environ[meta["env"]]}
    return {}


class LLM:
    """A tiny wrapper that knows how to call one provider."""
    def __init__(self, provider, api_key, model=None):
        self.provider = provider
        self.api_key = api_key
        self.model = model or PROVIDERS[provider]["model"]

    def chat(self, system, user, temperature=0.2, max_tokens=1024):
        """Send a system + user message, return the model's text reply."""
        if self.provider in ("openai", "groq"):
            url = ("https://api.openai.com/v1/chat/completions" if self.provider == "openai"
                   else "https://api.groq.com/openai/v1/chat/completions")
            payload = {"model": self.model, "temperature": temperature,
                       "max_tokens": max_tokens,
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}]}
            # Free tiers rate-limit per minute. A 429 is usually a short wait
            # rather than a failure, and the provider states how long — so
            # waiting beats losing the user's turn. Only a SHORT wait is worth
            # sitting through; a daily quota reports minutes or hours and is
            # surfaced instead of slept on.
            for attempt in range(3):
                r = requests.post(url, timeout=30,
                                  headers={"Authorization": f"Bearer {self.api_key}"},
                                  json=payload)
                if r.status_code != 429:
                    break
                wait = _retry_after_seconds(r)
                if wait is None or wait > 25 or attempt == 2:
                    raise RuntimeError(_rate_limit_message(r, wait))
                time.sleep(wait + 0.5)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

        if self.provider == "anthropic":
            r = requests.post("https://api.anthropic.com/v1/messages", timeout=30,
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
                json={"model": self.model, "max_tokens": max_tokens,
                      "system": system,
                      "messages": [{"role": "user", "content": user}]})
            r.raise_for_status()
            return r.json()["content"][0]["text"]

        if self.provider == "gemini":
            url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
                   f"{self.model}:generateContent?key={self.api_key}")
            r = requests.post(url, timeout=30,
                json={"system_instruction": {"parts": [{"text": system}]},
                      "contents": [{"parts": [{"text": user}]}]})
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]

        raise ValueError(f"Unknown provider: {self.provider}")

    def can_transcribe(self):
        """Voice input is available on Groq (Whisper, free) and OpenAI."""
        return self.provider in ("groq", "openai")

    def transcribe(self, audio_bytes, filename="speech.wav"):
        """Speech -> text. Uses Whisper on Groq (free) or OpenAI. Returns the transcript."""
        if not self.can_transcribe():
            raise ValueError("Voice input needs a Groq or OpenAI key.")
        url = ("https://api.groq.com/openai/v1/audio/transcriptions" if self.provider == "groq"
               else "https://api.openai.com/v1/audio/transcriptions")
        model = "whisper-large-v3" if self.provider == "groq" else "whisper-1"
        r = requests.post(url, timeout=60,
            headers={"Authorization": f"Bearer {self.api_key}"},
            files={"file": (filename, audio_bytes, "audio/wav")},
            data={"model": model, "response_format": "text"})
        r.raise_for_status()
        return r.text.strip()


def get_llm():
    """Return a ready LLM, or None if no key is configured (→ rule-based fallback)."""
    cfg = _read_config()
    provider = cfg.get("provider")
    api_key = cfg.get("api_key")
    if provider in PROVIDERS and api_key:
        return LLM(provider, api_key, cfg.get("model"))
    return None
