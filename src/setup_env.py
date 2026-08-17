"""
MUMO — environment helper
Makes MUMO run identically on Windows (local) and Linux (Streamlit Cloud).

ensure_vina() returns a usable AutoDock Vina executable — and specifically one
new enough to do the job.

WHY THE VERSION CHECK EXISTS
----------------------------
bioconda's `autodock-vina` package has only ever published **1.1.2**, and
environment.yml requests it unpinned, so that is what the container installs.
This function used to take the first `vina` it found on PATH, which meant it
always picked 1.1.2 and never reached the official 1.2.5 static binary it goes
on to download.

That silently broke a whole feature. Vinardo scoring and `--autobox` were both
introduced in Vina 1.2.0, so `docking_engine.score_pose` was invoking flags
that did not exist; Vina errored, the caller swallowed it, and every report
showed an empty "Vinardo" and "Consensus" column with no explanation. Worse,
it means affinities were produced by 1.1.2's scoring function rather than the
1.2.x one the rest of the code assumes.

So: probe each candidate, and only accept one that is >= 1.2.
"""

import os
import re
import sys
import stat
import shutil
import platform
import subprocess
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(BASE, "bin")

# Official AutoDock Vina 1.2.5 static Linux binary
VINA_LINUX_URL = ("https://github.com/ccsb-scripps/AutoDock-Vina/releases/"
                  "download/v1.2.5/vina_1.2.5_linux_x86_64")

# Vinardo rescoring and --autobox both arrived in 1.2.0. Below this, the
# consensus-scoring feature cannot work at all.
MIN_VERSION = (1, 2)


def vina_version(path):
    """(major, minor, patch) reported by a vina binary, or None if unusable.

    Never raises: a missing file, a binary for the wrong architecture, or a
    hang all just mean "cannot use this one", and the caller moves on.
    """
    if not path:
        return None
    # Resolve to an absolute path first: os.path.exists() happily accepts a
    # relative one, but subprocess does not resolve it the same way (it fails
    # outright on Windows), so a perfectly good binary can look unusable.
    try:
        path = os.path.abspath(path)
        out = subprocess.run([path, "--version"], capture_output=True,
                             text=True, timeout=20)
    except Exception:
        return None
    text = (out.stdout or "") + " " + (out.stderr or "")
    m = re.search(r"v?(\d+)\.(\d+)(?:\.(\d+))?", text)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def _usable(path):
    """A path that exists, runs, and is new enough — else None."""
    if not path or not os.path.exists(path):
        return None
    v = vina_version(path)
    if v and v[:2] >= MIN_VERSION:
        return path
    if v:
        print(f"[setup_env] Ignoring Vina {v[0]}.{v[1]}.{v[2]} at {path} — "
              f"Vinardo rescoring and --autobox need "
              f">= {MIN_VERSION[0]}.{MIN_VERSION[1]}.")
    return None


def _download_official(dest):
    """Fetch the official static Linux build, and verify it before trusting it."""
    urllib.request.urlretrieve(VINA_LINUX_URL, dest)
    st = os.stat(dest)
    os.chmod(dest, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return _usable(dest)


def ensure_vina():
    """Return a path to a Vina executable that is new enough to use.

    Falls back to the newest thing available if nothing meets MIN_VERSION, so
    docking still runs rather than the app failing outright — but it says so
    loudly, because in that state consensus scoring is silently unavailable.
    """
    os.makedirs(BIN, exist_ok=True)

    if platform.system() == "Windows":
        bundled = os.path.join(BIN, "vina.exe")
        return _usable(bundled) or bundled

    candidates = [
        shutil.which("vina"),
        os.path.join(os.path.dirname(sys.executable), "vina"),
        os.path.join(BIN, "vina"),                 # a previous download
    ]
    for c in candidates:
        good = _usable(c)
        if good:
            return good

    # Nothing new enough is installed — fetch the official 1.2.5 build.
    local = os.path.join(BIN, "vina")
    try:
        good = _download_official(local)
        if good:
            return good
    except Exception as e:
        print(f"[setup_env] Could not download Vina {MIN_VERSION[0]}."
              f"{MIN_VERSION[1]}+: {type(e).__name__}: {e}")

    # Last resort: use whatever exists, and be explicit about the consequence.
    for c in candidates:
        if c and os.path.exists(c):
            print(f"[setup_env] WARNING: falling back to {c}, which is older "
                  f"than {MIN_VERSION[0]}.{MIN_VERSION[1]} — Vinardo/consensus "
                  f"scoring will be unavailable.")
            return c
    return local
