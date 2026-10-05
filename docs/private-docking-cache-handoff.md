# Private exact docking cache: local backend handoff

Implemented on `docking-view-presentation`; local edits only. No hosted migration,
commit, push, deployment, billing change or large matrix benchmark was performed.

## Stable UI/server contract

- Obtain the authenticated client through the existing `auth_store` path and a
  server-verified owner id. Call `load_worker_cache_fields(client, owner_id)` and
  merge its `owner_id`, `cache_candidates`, `cache_notice` into the **top-level**
  detached job spec. Never derive these fields from LLM conversation output.
- `docking_jobs.start` allocates a new UUID generation. Both initial status and
  `awaiting_reuse` status include `owner_id` and `generation`. Check the owner
  against the logged-in user before displaying `reuse_offer`.
- `reuse_offer` includes `hit_count`, `total_pairs`, `docking_mode`, and matching
  keys, original run/date, reliability, interaction notes and native validation.
  Render explicit reuse/redock buttons, and call
  `submit_reuse_choice(job_id, generation, 'reuse'|'redock', owner_id, jobs_dir)`.
  The first valid choice wins; stale generation, wrong owner, invalid action,
  dead worker and duplicate choice are rejected.
- `awaiting_reuse` is active for launch prevention and reconnect discovery. The
  worker heartbeats while waiting. Default timeout is 900 seconds (spec override
  `reuse_timeout_seconds`, capped at 24 hours). Expiry fails without executing
  missing pairs, retaining existing checkpoints; it never silently computes fresh.
- Worker `result.json` retains bounded **root** `cache_entries`. Report metadata
  has `meta['cache']` with choice/hit counts, reused/new pair counts and notices.
  Cache entries do not belong in `meta` or `per_target` report metadata. The parent
  UI bridge should inspect root entries before asynchronous saving and remove
  root entries in `public_result` copies used for history/report state.
- `persist_completed_pairs(client, owner_id, result)` returns
  `{'saved_pairs': int, 'notice': str|None}`. Run it on the parent's authenticated
  async save path after displaying the result. The worker does not initialize a
  cache database client. Its legacy history save uses `public_result` and only
  rows/meta/viz; no root cache-entry payload is included in that history summary.
- Foreground fallback can remain explicitly fresh. A caller choosing foreground
  reuse must supply `cache_context` and an explicit `reuse_decision(offer)` callback
  to `run_job`. No callback or invalid choice with hits raises before execution.

## Scientific and execution contracts

`prepare_docking` retains actual prepared files and per-ligand failures.
`run_job` with a cache context prepares all targets in distinct directories before
matching or requesting consent. The detached worker always supplies that context,
including anonymous jobs (no cross-session reuse). Legacy foreground calls without
it retain their fresh behavior. Prepared bytes are checked again before either
reuse or execution. A changed retained file becomes a failed pair, not a stale hit.

Manifests cover actual receptor/ligand SHA256, source coordinate-file accession,
species and retained chains, Meeko-output isomeric SMILES/formal charge, preparation
pH/seed/conformers/torsion settings, grid, Vina scoring/exhaustiveness/three seeds,
pose count/energy range, interaction protocol and installed software/source hashes.
Unknown identities or versions are misses. Coordinate-file identity comes from the
parent-owned `protein_identity.extract_identity`; provided conflicting identifiers
stop target preparation. Cache fingerprint failure after valid preparation degrades
to fresh docking.

Reusable evidence requires finite scores, all three seeded poses, selected winning
pose, raw logs/configurations with integrity hashes and matching settings, original
run/date, and completed interactions. Successfully completed `qualified` ProLIF
analysis is accepted only with export/reload checks and no rejected contacts.
Hydrogen-geometry, receptor and native-redocking qualifications remain visible;
these are predictions, not experimental validation. Failed/partial interaction
evidence never qualifies. Reuse does not change stored scores or coordinates.

Row provenance fields: `Calculation origin` (`new`/`reused`), `Original run ID`,
`Original calculation date`, `Pair key`; existing replica/reliability evidence is
retained. Fresh row original-run ids agree with the core result's `run_id`.
The parent can read actual input metadata from single `meta` or `meta['per_target']`,
including `accession`, `species`, `chains` and `pdb_id`.

The runner checkpoints the complete successful docking result, then invokes the
parent-owned `enrich_result(result, progress=progress)` once, then publishes the
integrated result. A biological-step interruption retains all docking rows.
No biology module or report source was changed by this worker.

## Bounds and database limitation

Evidence uses lossless gzip/base64 with 16 MiB decoded / 4 MiB encoded limits per
entry. Decoder bounds inflation and rejects invalid, truncated or trailing gzip.
At most 64 candidates and 64 MiB decoded evidence per candidate/export batch are
retained; reads also cap aggregate encoded evidence at 16 MiB and fetch one payload
at a time. Entries retain only their pair's reliability data. Job launch rejects
credential fields; credentials are not sent in specs or cache entries.

The authenticated adapter validates its current `auth.get_user()` owner before
reads/writes and applies explicit owner predicates. Exceptions, missing schema,
quota failures and corrupt evidence produce misses/notices without hiding results.

`docs/sql/private_docking_cache.sql` is an **unapplied local SQL draft**. It defines
owner SELECT/INSERT/DELETE RLS, no UPDATE permission, immutable first-key evidence,
and a serialized invoker-security owner quota of 64 entries / 64 MiB encoded.
Syntax and live RLS/trigger/grant behavior have not been executed against Postgres.
Before rollout, test owner A/B and anon SELECT/INSERT/DELETE denial, owner reassignment
and UPDATE denial, duplicate preservation, concurrent quota enforcement, cascade
deletion and missing-table fallback against an actual local/test Supabase database.
Do not claim hosted tenant isolation until those tests pass.

## Changed files owned by this worker

`src/pipeline.py`, `src/pipeline_core.py`, `src/docking_jobs.py`,
`src/dock_runner.py`, `src/docking_memory.py`, `src/docking_cache_store.py`,
`src/docking_reuse_ui.py`, `tests/test_docking_memory.py`,
`tests/test_private_cache_flow.py`, `tests/test_private_cache_scientific.py`,
`docs/sql/private_docking_cache.sql`, and this document.

Parent-owned mode, biology, UI, identity and report files remain separate. The
mixed-line-ending helper touches parent-owned files, so it was not run during
concurrent editing; parent should apply it only when editing has stopped.

## Verification

Tests include 5 of 20 hits executing 15 engine pairs, redock executing all 20,
immutable cached scores/coordinates/dates, owner/charge/stereo/grid/version/seed
mismatches, corrupt logs/config/poses/gzip, stale/duplicate consent, reconnect,
dead workers, timeout and checkpoints before optional biology.

Opt-in real test: set `MUMO_CACHE_SCIENTIFIC=1` and run
`python -m unittest discover -s tests -p test_private_cache_scientific.py -v` with
the supplied scientific runtime. Uses local CDK4 source and Standard 3-seed Vina;
no STRING/ADME/database calls. Saves cold, partial and full-hit evidence under a
new `D:/my vault/tmp/private-cache-smoke-*` directory. A successful 1x1 run at
`private-cache-smoke-38ejso0b` measured 9.80 s cold and 3.88 s full-hit, score
−2.984 kcal/mol, unchanged coordinates/date and zero executed full-hit replicas.
The final cold/partial/full-hit run passed at
`D:/my vault/tmp/private-cache-smoke-6ml3p_ko/result.json` (gzip): 10.36 s cold,
11.31 s partial (ethanol reused + benzamidine newly docked), 4.81 s full hit.
Executed requested pairs/replicas were respectively 1/3, 1/3, and 0/0. The ethanol
score, original date and retained cache evidence were unchanged. No biological
network/model calls were included in these timings. These tiny local timings are
not a large-batch speed claim. Final regression suite: 156 tests, OK, 5 skipped;
the opt-in real test passed separately. Assigned modules compiled and scoped diff
whitespace check passed with CRLF recognized. No mixed-ending rewrite was run.

Local ADMET-AI model availability and hosted RLS remain unverified by this backend
worker; the parent observed local ADMET-AI unavailable. Existing scientific-engine
ResourceWarnings and dependency deprecations were observed during verification.
