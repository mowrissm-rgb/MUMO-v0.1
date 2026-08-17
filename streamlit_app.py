"""
MUMO Streamlit Cloud Entry Point
Wrapper that imports and runs the main app from src/mumo_chat.py.

NOTE: this must point at mumo_chat (the current chat-first, themed app),
NOT the old src/app.py "Phase 1 POC" interface — pointing here at `app`
is what made the deployed site render a blank/old page.
"""

import sys
import os

# Add src to path so mumo_chat's own imports (llm_client, agents, ...) resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Import and run the real app (executing mumo_chat's body renders the app)
from mumo_chat import *  # noqa: F401,F403
