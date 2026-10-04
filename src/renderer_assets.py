"""Pinned local graphics assets for network-independent report capture."""
from functools import lru_cache
import hashlib
from pathlib import Path
import re


@lru_cache(maxsize=1)
def graphics_script():
    asset = Path(__file__).resolve().parent.parent / 'assets' / '3Dmol-2.1.0.min.js'
    data = asset.read_bytes()
    expected = '1da92a31f6a29e73e38894d3e8f2c6ae5f638fa3dc8f7d3ef909e8f49819be1d'
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('Bundled 3D graphics library failed its integrity check.')
    script = re.sub(r'</script', r'<\\/script', data.decode('utf-8'), flags=re.I)
    return '<script>' + script + '</script>'
