"""
MUMO — in-process resilience.

WHAT THIS IS FOR
----------------
"Unstoppable" was never really about running four servers. It was about MUMO
surviving a broken component instead of dying with it. That property is
achievable inside one Space, for nothing, and this is it.

Two mechanisms:

  * **Pre-flight probing.** Before running a capability, check that what it
    needs is actually here — the module imports, the binary exists. A missing
    RDKit should produce "docking is unavailable, everything else works", not
    an ImportError traceback in the middle of a chat reply.

  * **A circuit breaker.** After repeated failures a capability is marked down
    for a cooldown instead of being retried on every message. Without this, a
    component that crashes on import gets re-imported on every rerun, which is
    both slow and a good way to OOM a 2-vCPU container.

WHAT IT CANNOT DO, HONESTLY
---------------------------
A native segfault (exit 139) cannot be caught in-process — the signal kills the
interpreter before any `except` runs. That is precisely why docking already
executes in a SUBPROCESS: the child dies, the job manager reports an error, and
this layer turns that into a clean message. For anything that must run in-
process, the honest protection is the pre-flight probe, not a try/except.

Recovery is automatic. A capability marked down is re-probed once the cooldown
expires, so a transient failure heals itself without a restart.
"""

import importlib
import os
import time

from . import registry

# What each capability actually needs to run here. Kept declarative so the
# probe is a data question, not a pile of special cases.
REQUIREMENTS = {
    "dock": {"modules": ("rdkit", "meeko"), "needs_vina": True},
    "ramachandran": {"modules": ("numpy",), "needs_vina": False},
    # MD deliberately does NOT run in this process — openmm lives in an
    # isolated env at /opt/mdenv and is reached by subprocess. So the probe
    # asks whether that environment exists, not whether openmm imports here;
    # importing it here is the thing we are avoiding.
    "md": {"modules": ("rdkit",), "needs_vina": False, "needs_mdenv": True},
    "string": {"modules": ("requests",), "needs_vina": False},
    "blast": {"modules": ("requests",), "needs_vina": False},
    "phylogeny": {"modules": ("requests",), "needs_vina": False},
    "admet": {"modules": ("rdkit",), "needs_vina": False},
    # xtb is an executable, so "is the module importable" is the wrong test;
    # needs_xtb checks the binary is actually on PATH.
    "qm": {"modules": ("rdkit",), "needs_vina": False, "needs_xtb": True},
    "metabolism": {"modules": ("rdkit",), "needs_vina": False},
    "druglikeness": {"modules": ("rdkit",), "needs_vina": False},
    "report": {"modules": ("docx",), "needs_vina": False},
    "export": {"modules": ("rdkit",), "needs_vina": False},
}

PROBE_TTL = 300.0          # a good probe is trusted for five minutes
FAIL_THRESHOLD = 2         # consecutive failures before the breaker opens
COOLDOWN = 180.0           # seconds a capability stays down before re-probing

_probe_cache = {}          # capability -> (checked_at, ok, reason)
_failures = {}             # capability -> [count, opened_at, last_reason]


def _vina_ok():
    try:
        import setup_env
        path = setup_env.ensure_vina()
        return bool(path) and os.path.exists(path)
    except Exception:
        return False


def probe(capability, force=False):
    """Can this capability actually run in this process right now?

    Returns (ok, reason). Cached, because importing rdkit to answer the
    question is itself expensive enough to matter on a 2-vCPU box.
    """
    cap = (capability or "").strip().lower()
    req = REQUIREMENTS.get(cap)
    if req is None:
        return True, ""                     # unknown capability: don't block it

    now = time.time()
    hit = _probe_cache.get(cap)
    if hit and not force and (now - hit[0]) < PROBE_TTL:
        return hit[1], hit[2]

    ok, reason = True, ""
    for mod in req["modules"]:
        try:
            importlib.import_module(mod)
        except Exception as e:
            ok = False
            reason = f"{mod} is not available ({type(e).__name__})"
            break
    if ok and req["needs_vina"] and not _vina_ok():
        ok, reason = False, "the AutoDock Vina binary is missing"
    if ok and req.get("needs_mdenv"):
        try:
            from agents.md_analyst import md_isolated_available
            if not md_isolated_available():
                ok, reason = False, ("the isolated molecular-simulation "
                                     "environment is not installed")
        except Exception as e:
            ok, reason = False, f"MD env check failed ({type(e).__name__})"
    if ok and req.get("needs_xtb"):
        try:
            from agents.qm_analyst import xtb_available
            if not xtb_available():
                ok, reason = False, "the xtb quantum-chemistry binary is missing"
        except Exception as e:
            ok, reason = False, f"xtb check failed ({type(e).__name__})"

    _probe_cache[cap] = (now, ok, reason)
    return ok, reason


def _breaker_open(cap):
    """Is the breaker currently open for this capability?"""
    rec = _failures.get(cap)
    if not rec or rec[0] < FAIL_THRESHOLD:
        return False
    if time.time() - rec[1] >= COOLDOWN:
        _failures.pop(cap, None)            # cooldown served: try again
        _probe_cache.pop(cap, None)
        return False
    return True


def record_failure(capability, reason=""):
    """Note that a capability failed. Two in a row opens the breaker."""
    cap = (capability or "").lower()
    rec = _failures.get(cap) or [0, 0.0, ""]
    rec[0] += 1
    rec[1] = time.time()
    rec[2] = str(reason)[:200]
    _failures[cap] = rec
    _probe_cache.pop(cap, None)


def record_success(capability):
    """A success clears the slate — a transient wobble must not accumulate
    across an entire session into a permanent outage."""
    _failures.pop((capability or "").lower(), None)


def available(capability):
    """(ok, reason) combining the breaker and the pre-flight probe."""
    cap = (capability or "").lower()
    if _breaker_open(cap):
        rec = _failures.get(cap) or [0, 0, ""]
        left = int(COOLDOWN - (time.time() - rec[1]))
        return False, (f"it failed {rec[0]} times in a row and is resting for "
                       f"{max(left, 1)}s ({rec[2]})" if rec[2] else "recent repeated failures")
    return probe(cap)


def message(capability):
    """What the user is told. Reuses the registry's degrade-loudly wording so
    a locally-broken capability reads exactly like a remotely-dead one."""
    ok, reason = available(capability)
    if ok:
        return ""
    base = registry.unavailable(capability)
    return f"{base} (Reason: {reason}.)" if reason else base


def run(capability, fn, *args, **kwargs):
    """Execute a local capability under the guard.

    Raises RuntimeError carrying the user-facing message when the capability
    is unavailable, and converts a failure inside `fn` into the same shape —
    so one broken capability degrades to a message instead of a traceback, and
    everything else keeps serving.
    """
    ok, reason = available(capability)
    if not ok:
        raise RuntimeError(message(capability))
    try:
        out = fn(*args, **kwargs)
    except Exception as e:
        record_failure(capability, f"{type(e).__name__}: {e}")
        raise RuntimeError(message(capability)) from e
    record_success(capability)
    return out


def status():
    """Every capability and whether it can run — for a status panel."""
    rows = []
    for cap in sorted(REQUIREMENTS):
        ok, reason = available(cap)
        sid = registry.owner_of(cap)
        spec = registry.specialist(sid) if sid else None
        rows.append({
            "capability": cap,
            "specialist": spec["name"] if spec else "-",
            "mode": "remote" if registry.is_remote(cap) else "local",
            "ok": ok,
            "reason": reason,
        })
    return rows


def reset():
    """Clear all cached state. For tests and for a manual 'try again'."""
    _probe_cache.clear()
    _failures.clear()
