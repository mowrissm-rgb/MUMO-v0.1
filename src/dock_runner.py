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
import time
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

    def checkpoint(result):
        jobs._write_json(os.path.join(jd, 'checkpoint.json'), result)
        jobs.update_status(jd, completed_pairs=len(result.get('rows') or []),
                           expected_pairs=result.get('meta', {}).get('expected_pairs'))

    try:
        jobs.validate_job_spec(spec)
        # LLM for the narrative report (falls back to rule-based if no key in env)
        try:
            from llm_client import get_llm
            llm = get_llm()
        except Exception:
            llm = None

        from pipeline_core import run_job
        from docking_release import private_cache_enabled
        def choose_reuse(offer):
            return jobs.await_reuse_choice(jd, spec.get('generation'), spec.get('owner_id'),
                offer, timeout=spec.get('reuse_timeout_seconds', 900))
        result = run_job(spec["convo"], spec["vina"], spec["data_dir"], spec["venv"],
                         llm=llm, progress=progress, checkpoint=checkpoint,
                         cache_context=({'owner_id': spec.get('owner_id'),
                             'candidates': spec.get('cache_candidates') or [],
                             'notice': spec.get('cache_notice')} if private_cache_enabled() else None),
                         reuse_decision=choose_reuse)
        import uuid
        result.setdefault('run_id', str(uuid.uuid4()))
        if result.get('cache_entries'):
            try:
                from docking_reuse_ui import worker_cache_fields
                bounded = worker_cache_fields(spec.get('owner_id'), result['cache_entries'])
                result['cache_entries'] = bounded['cache_candidates']
            except Exception:
                result['cache_entries'] = []
                result.setdefault('meta', {}).setdefault('cache', {})['notice'] = (
                    'Private cache write unavailable; finished docking remains available.')
        if result.get('ok'):
            # An interrupted optional biological step must retain all completed pairs.
            checkpoint(result)
            from docking_biology import enrich_result
            result = enrich_result(result, progress=progress)

        # Deliver first. External storage must never withhold a computed result.
        progress('Publishing completed results…')
        jobs._write_json(os.path.join(jd, 'result.json'), result)
        jobs.update_status(jd, status='done', progress='Complete', error=None,
                           persisted=None, persist_error=None, run_id=result['run_id'])

        # Persist to Supabase so a reconnecting / brand-new session finds the
        # answer. This is the ONLY path that survives the browser session dying
        # mid-run, so its outcome is recorded in status.json rather than
        # swallowed — a run that computed fine but was never stored has to be
        # visible, not silent.
        conv_id = spec.get("conversation_id")
        saved, save_err = False, None
        if conv_id and result.get("ok"):
            try:
                from docking_ui_bridge import public_result
                history = public_result(result)
                from auth_store import standalone_client, save_results_with
                client = standalone_client()
                saved, save_err = save_results_with(
                    client, conv_id,
                    {"gene": history["meta"].get("gene"),
                     "run_id": result['run_id'],
                     "rows": history["rows"], "meta": history["meta"],
                     "viz": history["viz"],
                     "saved_at": time.time()})
            except Exception as e:
                save_err = f"{type(e).__name__}: {e}"
                traceback.print_exc()
            print(f"[persist] saved={saved} err={save_err}", flush=True)

        # Separate file avoids racing the UI's consumed flag in status.json.
        if (jobs._read_json(os.path.join(jd, 'status.json')) or {}).get('run_id') == result['run_id']:
            jobs._write_json(os.path.join(jd, 'worker_persist.json'),
                             {'persisted': saved, 'persist_error': save_err})
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
