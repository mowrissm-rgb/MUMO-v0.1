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
#
# `fallbacks` are smaller models on the SAME provider, tried in order when the
# primary model's quota is exhausted. Groq's free-tier limits are per-model AND
# per-organisation-per-day: llama-3.3-70b-versatile allows only 100k tokens a
# day, which at MUMO's ~4k per turn is roughly 25 messages. The 8b model has a
# far larger daily budget, so falling back to it keeps MUMO usable for the rest
# of the day instead of failing every request until midnight. Making a NEW API
# KEY does not help — the limit is charged to the organisation, not the key.
PROVIDERS = {
    "openai":    {"model": "gpt-4o-mini",                 "env": "OPENAI_API_KEY",
                  "fallbacks": []},
    "anthropic": {"model": "claude-3-5-haiku-latest",     "env": "ANTHROPIC_API_KEY",
                  "fallbacks": []},
    "gemini":    {"model": "gemini-1.5-flash",            "env": "GEMINI_API_KEY",
                  "fallbacks": []},
    "groq":      {"model": "llama-3.3-70b-versatile",     "env": "GROQ_API_KEY",
                  "fallbacks": ["llama-3.1-8b-instant", "gemma2-9b-it"]},
}


def _is_daily_limit(resp):
    """True when a 429 is the per-DAY quota rather than a per-minute burst.

    The distinction decides what to do: a burst is worth waiting a few seconds
    for, a daily cap is not — nothing will change until it resets, so the only
    useful move is a different model.
    """
    try:
        msg = resp.json().get("error", {}).get("message", "") or ""
    except Exception:
        msg = resp.text or ""
    return bool(re.search(r"per day|\bTPD\b|\bRPD\b", msg, re.I))


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
            msgs = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
            # Models to try in order: the configured one, then smaller ones on
            # the same provider. A per-minute burst is waited out; a per-DAY cap
            # is not, because nothing changes until it resets — the only useful
            # move there is a different model.
            models = [self.model] + [m for m in
                                     PROVIDERS.get(self.provider, {}).get("fallbacks", [])
                                     if m != self.model]
            last_429 = None
            for model in models:
                payload = {"model": model, "temperature": temperature,
                           "max_tokens": max_tokens, "messages": msgs}
                for attempt in range(3):
                    r = requests.post(url, timeout=30,
                                      headers={"Authorization": f"Bearer {self.api_key}"},
                                      json=payload)
                    if r.status_code != 429:
                        break
                    last_429 = r
                    if _is_daily_limit(r):
                        break                      # waiting cannot help; next model
                    wait = _retry_after_seconds(r)
                    if wait is None or wait > 25 or attempt == 2:
                        break
                    time.sleep(wait + 0.5)

                if r.status_code == 429:
                    continue                       # try the next, smaller model
                r.raise_for_status()
                if model != self.model:
                    self.active_model = model      # so the UI can say which answered
                return r.json()["choices"][0]["message"]["content"]

            # every model was rate-limited
            raise RuntimeError(_rate_limit_message(
                last_429, _retry_after_seconds(last_429) if last_429 else None))

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
