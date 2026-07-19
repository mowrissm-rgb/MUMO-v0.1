"""
MUMO — Background docking jobs (SUBPROCESS-based, crash-isolated)
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

WHY A SUBPROCESS (and not a thread)
-----------------------------------
Docking pulls in native code (AutoDock Vina, RDKit, ProLIF, MDAnalysis, BLAS).
Running that native stack OFF the main interpreter thread SEGFAULTS the whole
Streamlit container (exit 139) — uncatchable from Python, so the app just dies.
We learned this the hard way twice. A *separate process* is fully isolated: if
the native code segfaults, only the child dies. The parent (the Streamlit app)
sees the child exit and reports a clean error instead of crashing.

HOW IT SURVIVES A CLOSED TAB
----------------------------
A Streamlit script run is tied to the browser WebSocket, so closing the tab /
refreshing / minimising kills the script run. The docking subprocess is spawned
DETACHED (new session / new process group) from the Streamlit server process, so
it keeps running independently of any browser connection. Progress and the final
result are written to plain files under a per-job directory on disk, and the
worker ALSO persists the result to Supabase — so a reconnecting session (even a
brand-new one) finds the running/finished job by its id and picks up where it
left off.

FILE LAYOUT  (jobs_dir/<job_id>/)
    spec.json     the job input (target, ligands, params) — written by start()
    status.json   {status, progress, pid, started, updated, error}
    result.json   the finished pipeline result — written by the worker on success
    worker.log    the child's stdout/stderr (for debugging a crash)

The worker (dock_runner.py) is a plain `python dock_runner.py <spec.json>` — no
Streamlit imports at all.
"""

import os
import sys
import json
import time
import tempfile
import subprocess

_RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dock_runner.py")


# ───────────────────────────── path helpers ──────────────────────────────

def default_jobs_dir():
    """Where jobs live by default: <project>/data/jobs."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(base, "data", "jobs")
    os.makedirs(d, exist_ok=True)
    return d


def job_dir(jobs_dir, job_id):
    return os.path.join(jobs_dir, _safe(job_id))


def _safe(job_id):
    return "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in str(job_id))[:80] or "job"


# ─────────────────────────── atomic json files ───────────────────────────

def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_json(path, obj):
    """Write atomically (temp file + os.replace) so a reader never sees a
    half-written file — important because the worker and the UI poll the same
    status.json concurrently."""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass
        raise


def update_status(jd, **fields):
    """Merge `fields` into the job's status.json (used by the worker to report
    progress). `jd` is the job directory."""
    path = os.path.join(jd, "status.json")
    cur = _read_json(path) or {}
    cur.update(fields, updated=time.time())
    _write_json(path, cur)


# ───────────────────────────── pid liveness ──────────────────────────────

def _pid_alive(pid):
    """True if a process with this pid is currently running. Cross-platform:
    signal-0 probe on POSIX, OpenProcess+exit-code probe on Windows."""
    if not pid:
        return False
    pid = int(pid)
    if os.name == "nt":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            k = ctypes.windll.kernel32
            h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return False
            code = ctypes.c_ulong()
            k.GetExitCodeProcess(h, ctypes.byref(code))
            k.CloseHandle(h)
            return code.value == STILL_ACTIVE
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True   # exists but not ours — still alive
    except Exception:
        return False
    return True


# ─────────────────────────────── public API ──────────────────────────────

def start(job_id, spec, jobs_dir=None, python_exe=None, runner=None, extra_env=None):
    """Launch the docking worker for `spec` in a DETACHED subprocess.

    Idempotent: if a job with this id is already running, returns False and does
    not start a second one. Returns True when a new worker was launched.

    `spec` is a JSON-serialisable dict the worker understands (see dock_runner).
    """
    jobs_dir = jobs_dir or default_jobs_dir()
    jd = job_dir(jobs_dir, job_id)

    # already running? don't double-launch.
    st = read_status(job_id, jobs_dir)
    if st and st.get("status") == "running":
        return False

    os.makedirs(jd, exist_ok=True)
    _write_json(os.path.join(jd, "spec.json"), spec)
    # clear any stale result from a previous run of this id
    for stale in ("result.json",):
        try:
            os.remove(os.path.join(jd, stale))
        except OSError:
            pass
    _write_json(os.path.join(jd, "status.json"),
                {"status": "running", "progress": "Starting…", "pid": None,
                 "started": time.time(), "updated": time.time(), "error": None})

    python_exe = python_exe or sys.executable
    runner = runner or _RUNNER
    log = open(os.path.join(jd, "worker.log"), "w", encoding="utf-8")

    env = dict(os.environ)
    if extra_env:
        env.update({k: str(v) for k, v in extra_env.items()})
    # the worker needs to find sibling modules (pipeline, agents, …)
    env["PYTHONPATH"] = (os.path.dirname(os.path.abspath(__file__)) +
                         os.pathsep + env.get("PYTHONPATH", ""))

    kwargs = {"stdout": log, "stderr": subprocess.STDOUT, "cwd": jd, "env": env,
              "close_fds": True}
    if os.name == "nt":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True   # setsid: survives parent/WebSocket death

    proc = subprocess.Popen([python_exe, runner, os.path.join(jd, "spec.json")], **kwargs)
    update_status(jd, pid=proc.pid)
    return True


def read_status(job_id, jobs_dir=None):
    """A snapshot of the job's status, or None if there is no job for this id.

    Crash detection: if the status still says 'running' but the worker process
    is dead and never wrote a result, we surface a synthetic 'error' status so
    the UI shows a clean message instead of polling a dead job forever. This is
    exactly the case a native segfault produces."""
    jobs_dir = jobs_dir or default_jobs_dir()
    jd = job_dir(jobs_dir, job_id)
    st = _read_json(os.path.join(jd, "status.json"))
    if st is None:
        return None
    if st.get("status") == "running":
        pid = st.get("pid")
        result_exists = os.path.exists(os.path.join(jd, "result.json"))
        # give a just-launched job a moment before deciding its pid is 'dead'
        launched_recently = (time.time() - st.get("started", 0)) < 8
        if pid and not _pid_alive(pid) and not result_exists and not launched_recently:
            st = dict(st, status="error",
                      error="The docking process stopped unexpectedly. This can happen "
                            "on very large/flexible ligands that exhaust the free CPU tier. "
                            "Try fewer or smaller ligands, or re-run.")
    return st


def read_result(job_id, jobs_dir=None):
    """The finished result dict, or None if the job hasn't produced one yet."""
    jobs_dir = jobs_dir or default_jobs_dir()
    return _read_json(os.path.join(job_dir(jobs_dir, job_id), "result.json"))


def is_running(job_id, jobs_dir=None):
    st = read_status(job_id, jobs_dir)
    return bool(st and st.get("status") == "running")


def mark_consumed(job_id, jobs_dir=None):
    """Flag that a UI session has already applied+announced this finished job, so
    another rerun (or a second tab) doesn't render/say it twice."""
    jobs_dir = jobs_dir or default_jobs_dir()
    jd = job_dir(jobs_dir, job_id)
    if os.path.exists(os.path.join(jd, "status.json")):
        update_status(jd, consumed=True)


def find_for_conversations(conversation_ids, jobs_dir=None):
    """Job ids belonging to these conversations that still need attention.

    When the browser's websocket drops mid-run — which a flaky host does often —
    the reconnecting session is BRAND NEW: no job id, no active conversation, so
    the poller has nothing to key on and the finished run is orphaned. That is
    what "it just opens a new chat and the result never comes" looks like from
    the outside, even though the subprocess completed fine.

    Scanning the job directory for this user's conversations recovers it. Only
    jobs that are running, or done/errored and NOT yet consumed, are returned —
    a run the user has already seen is not resurfaced.
    """
    wanted = {str(c) for c in (conversation_ids or []) if c}
    if not wanted:
        return []
    jobs_dir = jobs_dir or default_jobs_dir()
    out = []
    try:
        entries = sorted(os.listdir(jobs_dir))
    except OSError:
        return []
    for name in entries:
        jd = os.path.join(jobs_dir, name)
        spec = _read_json(os.path.join(jd, "spec.json")) or {}
        conv = str(spec.get("conversation_id") or spec.get("job_id") or "")
        if conv not in wanted:
            continue
        st = read_status(spec.get("job_id") or name, jobs_dir)
        if not st or st.get("consumed"):
            continue
        if st.get("status") in ("running", "done", "error"):
            out.append({"job_id": spec.get("job_id") or name,
                        "conversation_id": conv,
                        "status": st.get("status"),
                        "started": st.get("started") or 0})
    out.sort(key=lambda j: -(j.get("started") or 0))
    return out


def clear(job_id, jobs_dir=None):
    """Remove all files for a job (best-effort)."""
    import shutil
    jobs_dir = jobs_dir or default_jobs_dir()
    try:
        shutil.rmtree(job_dir(jobs_dir, job_id))
    except Exception:
        pass
