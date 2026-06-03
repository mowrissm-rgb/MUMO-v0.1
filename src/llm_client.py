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
import requests

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
            r = requests.post(url, timeout=90,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "temperature": temperature,
                      "max_tokens": max_tokens,
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": user}]})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

        if self.provider == "anthropic":
            r = requests.post("https://api.anthropic.com/v1/messages", timeout=90,
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
                json={"model": self.model, "max_tokens": max_tokens,
                      "system": system,
                      "messages": [{"role": "user", "content": user}]})
            r.raise_for_status()
            return r.json()["content"][0]["text"]

        if self.provider == "gemini":
            url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
                   f"{self.model}:generateContent?key={self.api_key}")
            r = requests.post(url, timeout=90,
                json={"system_instruction": {"parts": [{"text": system}]},
                      "contents": [{"parts": [{"text": user}]}]})
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]

        raise ValueError(f"Unknown provider: {self.provider}")


def get_llm():
    """Return a ready LLM, or None if no key is configured (→ rule-based fallback)."""
    cfg = _read_config()
    provider = cfg.get("provider")
    api_key = cfg.get("api_key")
    if provider in PROVIDERS and api_key:
        return LLM(provider, api_key, cfg.get("model"))
    return None
