"""
MUMO — Background docking jobs
Multi-Agent Drug Discovery & Development AI Platform

Runs a docking job in a DAEMON THREAD so it keeps going even if the user closes
the tab, refreshes, or minimises the browser (a Streamlit script run is tied to
the WebSocket; a plain thread in the server process is not). Progress + the final
result live in a process-global registry keyed by a job id (the conversation id),
so a reconnecting session finds the running/finished job. The worker also persists
the result to the database on its own, so results survive even across page loads.

The worker MUST be pure Python — no Streamlit calls (`st.*` has no ScriptRunContext
in a spawned thread). It talks to the DB via a standalone client, not the session's.
"""

import threading
import time

_JOBS = {}          # job_id -> dict(status, progress, result, error, started, updated)
_LOCK = threading.Lock()


def _set(job_id, **kw):
    with _LOCK:
        j = _JOBS.get(job_id)
        if j is not None:
            j.update(updated=time.time(), **kw)


def status(job_id):
    """A snapshot of the job, or None if there's no job for this id."""
    with _LOCK:
        j = _JOBS.get(job_id)
        return dict(j) if j else None


def is_running(job_id):
    j = _JOBS.get(job_id)
    return bool(j and j.get("status") == "running")


def clear(job_id):
    with _LOCK:
        _JOBS.pop(job_id, None)


def start(job_id, work):
    """Start `work(progress_cb)` in a background daemon thread. `work` returns the
    result dict; `progress_cb(msg)` reports progress. Idempotent: if a job is
    already running for this id, does nothing."""
    with _LOCK:
        existing = _JOBS.get(job_id)
        if existing and existing.get("status") == "running":
            return False
        _JOBS[job_id] = {"status": "running", "progress": "Starting…", "result": None,
                         "error": None, "started": time.time(), "updated": time.time()}

    def _progress(msg):
        _set(job_id, progress=str(msg))

    def _worker():
        try:
            result = work(_progress)
            _set(job_id, status="done", result=result, progress="Complete")
        except Exception as e:
            import traceback
            traceback.print_exc()
            _set(job_id, status="error", error=f"{type(e).__name__}: {e}")

    threading.Thread(target=_worker, daemon=True, name=f"dock-{job_id}").start()
    return True
