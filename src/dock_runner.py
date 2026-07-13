"""
MUMO — Detached docking worker
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

Run as:  python dock_runner.py <spec.json>

This is the process that docking_jobs.start() spawns DETACHED. It runs the whole
pipeline via pipeline_core.run_job (pure Python — NO Streamlit), streaming
progress into the job's status.json and writing the final result to result.json.
It also persists the result to Supabase directly, so the answer survives even if
the user closed the tab and comes back in a fresh session (or the container is
hit by a different replica).

Because this is a SEPARATE PROCESS, a native segfault in the docking stack kills
only this worker — the Streamlit app stays up and reports a clean error (the
job manager notices the pid died with no result). That isolation is the whole
point of doing background docking this way instead of in a thread.

The spec is a JSON dict:
    {job_id, jobs_dir, convo, vina, data_dir, venv, conversation_id}
"""

import os
import sys
import json
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import docking_jobs as jobs


def main(spec_path):
    spec = jobs._read_json(spec_path)
    if not spec:
        print(f"dock_runner: could not read spec {spec_path}", flush=True)
        return 2

    job_id = spec["job_id"]
    jobs_dir = spec["jobs_dir"]
    jd = jobs.job_dir(jobs_dir, job_id)

    def progress(msg):
        # keep the child alive-and-reporting even if a status write momentarily fails
        try:
            jobs.update_status(jd, progress=str(msg))
        except Exception:
            pass
        print(f"[progress] {msg}", flush=True)

    try:
        # LLM for the narrative report (falls back to rule-based if no key in env)
        try:
            from llm_client import get_llm
            llm = get_llm()
        except Exception:
            llm = None

        from pipeline_core import run_job
        result = run_job(spec["convo"], spec["vina"], spec["data_dir"], spec["venv"],
                         llm=llm, progress=progress)

        # persist to Supabase so a reconnecting / brand-new session finds the answer
        conv_id = spec.get("conversation_id")
        if conv_id and result.get("ok"):
            try:
                from auth_store import standalone_client, save_results_with
                client = standalone_client()
                save_results_with(client, conv_id,
                                  {"gene": result["meta"].get("gene"),
                                   "rows": result["rows"], "meta": result["meta"],
                                   "viz": result["viz"]})
            except Exception:
                traceback.print_exc()

        jobs._write_json(os.path.join(jd, "result.json"), result)
        jobs.update_status(jd, status="done", progress="Complete", error=None)
        print("[done]", flush=True)
        return 0

    except Exception as e:
        traceback.print_exc()
        jobs.update_status(jd, status="error",
                           error=f"{type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python dock_runner.py <spec.json>", flush=True)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
