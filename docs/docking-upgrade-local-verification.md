# Docking upgrade: local verification and remaining release gates

Date: 5 October 2026. Local implementation only; no push, hosted migration or deployment.

## Implemented and exercised

- Medium 8 / Standard 16 default / High 32, each with seeds 42, 43, 44. Explicit settings remain unchanged for larger matrices.
- Exact prepared-input matching, private authenticated cache adapter, bounded evidence, explicit generation-scoped reuse/redock choice and owner-guarded UI.
- Cached and new rows retain calculation origin, original run/date and pair key. Report history excludes duplicated cache payloads.
- Per-species target STRING snapshots and per-target tied-candidate ADME. Identical canonical input structures are analyzed once within a run; optional failures retain completed docking.
- Website and Word render stored biology; repeated report generation does not query STRING or run ADME again. Report provenance identifies reused calculations.
- Invalid/empty ligand structures, failed records and missing contact counts are not converted into successful values.
- Full regression suite: 156 tests, OK, 5 skipped. Scoped whitespace check and modified-module compilation pass. The real Vina cache test is opt-in and tested separately.
- Real local CDK4 checks demonstrated unchanged cached ethanol scores, coordinates and original date, zero replicas on a full hit, and only the missing benzamidine pair executed for partial reuse. Settings: Standard, 16 exhaustiveness, three seeds. These small tests are not an 8-ligand/9-target speed benchmark.

## Not yet established

- `docs/sql/private_docking_cache.sql` is an unapplied draft. Test its SQL, grants, owner isolation, immutable writes and concurrent quotas against a disposable real PostgreSQL/Supabase database before enabling durable memory. No hosted tenant-isolation claim is made.
- Local ADMET-AI is not installed. Actual RDKit descriptors run; unavailable ML predictions are retained as unavailable. The hosted Docker image declares ADMET-AI, but this new integration has not been verified live.
- STRING lookup can fail because of unmapped input identity, species uncertainty or connectivity. It does not justify assuming every input is human or inventing a network.
- The managed Word page renderer is unavailable. Structural DOCX checks and individual figure inspection do not substitute for inspection of every rendered page.
- No large-matrix runtime reduction, docking accuracy percentage, experimental activity or independently validated quantum surfaces is inferred from the cache tests.
- Independent real-cache rerun (`D:/my vault/tmp/private-cache-smoke-pgp737yy/result.json`) passed the correctness assertions but took 5,085 seconds in total: cold 21.15 s, full hit 334.96 s, partial 4,726.37 s. Vinardo rescoring hit its 120-second timeout. The cause of this unexpectedly slow local execution is unresolved; this result supersedes any implication that the earlier tiny timings prove a dependable speed improvement. Performance remains a release investigation, not a verified improvement.

## Release boundary

Request explicit push/deployment approval only after local review and database safety verification. Preserve unrelated scientific-figure plans. Neither the report repair nor local code completion changes the live website.
