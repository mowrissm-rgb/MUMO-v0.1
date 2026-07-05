"""
MUMO Streamlit Cloud Entry Point
Wrapper that imports and runs the main app from src/
"""

import sys
import os

# Add src to path so imports work on Streamlit Cloud
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Import and run the main app
from app import *
