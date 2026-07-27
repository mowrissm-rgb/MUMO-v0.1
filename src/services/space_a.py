"""
MUMO Specialist A — docking & structure.

Runs the heavy native stack (Vina, RDKit, ProLIF, meeko) as its own service so
that a crash in it cannot take down chat, STRING or BLAST. This is the whole
point of the split: three outages so far were one native component segfaulting
and killing the entire container.

TWO LAYERS OF ISOLATION, NOT ONE
--------------------------------
Running this in its own Space protects the OTHER specialists. It does not
protect this one — an in-process Vina segfault would still kill it. So docking
is executed in a SUBPROCESS via the existing docking_jobs manager, which is
already hardened for exactly this (detached process, crash detection, a dead
pid with no result becomes a clean error rather than a hang). A segfault then
kills a child and this service answers the next request normally.

Ramachandran is pure numpy with no native stack, so it runs in-process.

WHY STDLIB HTTP AND NOT FASTAPI
-------------------------------
FastAPI pulls in pydantic, whose core ships as a compiled extension. Adding a
native package to this image is precisely what caused two of the outages. The
service accepts a JSON job and returns JSON; ThreadingHTTPServer does that with
nothing new installed.

Endpoints
    GET  /health              liveness + what this specialist can actually do
    POST /run/dock            run a docking job, wait for it, return the result
    POST /run/ramachandran    backbone geometry validation (fast, in-process)
    GET  /jobs/<id>           recover a job whose HTTP request was lost
"""

import json
import os
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.dirname(_HERE)
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

CAPABILITIES = ("dock", "ramachandran")
POLL_SECONDS = 2.0


def _vina_path():
    try:
        import setup_env
        return setup_env.ensure_vina()
    except Exception:
        return ""


def health():
    """Liveness AND capability truth.

    Reports whether Vina is actually present rather than just that the process
    is up: a docking specialist that cannot dock should not claim it is
    healthy, or the router will keep sending it work it will fail.
    """
    vina = _vina_path()
    ok_vina = bool(vina) and os.path.exists(vina)
    version = ""
    if ok_vina:
        try:
            import setup_env
            version = ".".join(str(x) for x in (setup_env.vina_version(vina) or ()))
        except Exception:
            version = ""
    return {
        "ok": ok_vina,
        "specialist": "A",
        "name": "Docking & structure",
        "capabilities": list(CAPABILITIES),
        "vina": {"present": ok_vina, "version": version},
    }


def run_ramachandran(payload):
    """Backbone geometry. Pure numpy, so it is safe in-process."""
    import ramachandran as ram
    pdb = payload.get("pdb_text") or ""
    if not pdb.strip():
        raise ValueError("ramachandran needs 'pdb_text'")
    res = ram.compute(pdb)
    if res.get("_error"):
        raise ValueError(res["_error"])
    if payload.get("svg", True):
        res["svg"] = ram.plot_svg(res, title=payload.get("title"))
    return res


def run_dock(payload, wait=True):
    """Dock in a detached subprocess, then wait for it.

    The subprocess is not an optimisation — it is the reason a Vina segfault
    (exit 139, uncatchable in-process) leaves this service standing.
    """
    import docking_jobs

    job_id = payload.get("job_id") or f"svc-{int(time.time()*1000):x}"
    spec = dict(payload.get("spec") or {})
    if not spec:
        raise ValueError("dock needs a 'spec' object")
    spec.setdefault("vina", _vina_path())

    docking_jobs.prune()
    docking_jobs.start(job_id, spec)
    if not wait:
        return {"job_id": job_id, "status": "started"}

    deadline = time.time() + float(payload.get("max_seconds") or 1800)
    while time.time() < deadline:
        st = docking_jobs.read_status(job_id) or {}
        state = st.get("state")
        if state == "done":
            return {"job_id": job_id, "status": "done",
                    "result": docking_jobs.read_result(job_id)}
        if state == "error":
            return {"job_id": job_id, "status": "error",
                    "error": st.get("message") or "docking failed"}
        time.sleep(POLL_SECONDS)

    # Not a failure: the job is still running and recoverable by id. Saying so
    # is better than reporting an error for something that may yet succeed.
    return {"job_id": job_id, "status": "running",
            "note": "still running; poll /jobs/<id>"}


def job_state(job_id):
    import docking_jobs
    st = docking_jobs.read_status(job_id) or {}
    out = {"job_id": job_id, "status": st.get("state") or "unknown"}
    if out["status"] == "done":
        out["result"] = docking_jobs.read_result(job_id)
    elif out["status"] == "error":
        out["error"] = st.get("message") or "docking failed"
    return out


RUNNERS = {"dock": run_dock, "ramachandran": run_ramachandran}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):        # one tidy line, not apache noise
        sys.stderr.write(f"[space-a] {self.address_string()} {fmt % args}\n")

    def _send(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass                                # caller gave up; job still ran

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")
        if path in ("/health", ""):
            h = health()
            return self._send(200 if h["ok"] else 503, h)
        if path.startswith("/jobs/"):
            return self._send(200, job_state(path.split("/jobs/", 1)[1]))
        self._send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")
        if not path.startswith("/run/"):
            return self._send(404, {"error": "not found"})
        cap = path.split("/run/", 1)[1]
        runner = RUNNERS.get(cap)
        if not runner:
            return self._send(404, {
                "error": f"specialist A does not handle {cap!r}",
                "capabilities": list(CAPABILITIES)})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            return self._send(400, {"error": f"bad JSON body: {e}"})

        try:
            return self._send(200, runner(payload))
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:
            # Return the reason, not a bare 500. The front door surfaces this,
            # and a specialist that fails silently is impossible to diagnose
            # from the other side of an HTTP call.
            sys.stderr.write("[space-a] " + traceback.format_exc())
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})


def serve(port=None):
    port = int(port or os.environ.get("PORT") or 7860)
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    srv.daemon_threads = True
    h = health()
    sys.stderr.write(f"[space-a] listening on :{port} — vina "
                     f"{'ok ' + h['vina']['version'] if h['ok'] else 'MISSING'}\n")
    srv.serve_forever()


if __name__ == "__main__":
    serve()
