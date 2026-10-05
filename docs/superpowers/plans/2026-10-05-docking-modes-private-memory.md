# Docking modes and private memory implementation plan

> **For agentic workers:** Use executing-plans to implement the following test-first increments in this checkout. No release or hosted migration is authorized.

**Goal:** User-selected reproducible docking, consent-based private reuse, and stored STRING/ADME biology in the integrated report.

**Architecture:** Keep the detached worker and pair checkpoints. Resolve a validated protocol before target preparation. Separate exact prepared-input cache eligibility from authenticated persistence and job consent. Biological additions operate on stored target identities and completed rows, never invented scores.

**Tech Stack:** Python unittest, Streamlit, Vina, RDKit, ProLIF, existing Supabase authentication, python-docx.

## Global constraints

- Medium 8, Standard 16, High 32; three replicas with seeds 42, 43, 44 in every mode.
- Unknown settings fail before any docking, rather than silently becoming Standard.
- No cross-user reuse, paid hardware, automatic upgrades, or deployment.
- Incomplete evidence, unknown versions, failed interactions, and nonfinite scores cannot be cache hits.
- Target validation → STRING → HOMO/LUMO → docking → per-target candidate ADME → discussion → conclusion → references.
- Retain existing figures, checkpoints, and failure accounting.

## Increment 1: Protocol selection

Files: create `src/docking_protocol.py`, `tests/test_docking_modes.py`; modify `pipeline_core.py`, `mumo_chat.py`, `report_methods.py`.

Interface: `resolve_protocol(mode=None) -> dict` returns mode, exhaustiveness, replicas, base seed and replica seeds. `request_for_mode(convo, mode) -> dict` copies the request and captures its mode before detached launch or foreground fallback.

- [ ] Write failing tests exercising `run_job` with 61 ligands and all three modes, using a fake docking boundary to avoid native computation. Assert each engine invocation receives the literal expected exhaustiveness, replicas=3 and seed=42, and result metadata agrees. Exercise invalid modes and default Standard.
- [ ] Run `python -m unittest discover -s tests -p test_docking_modes.py -v` and observe the missing settings contract.
- [ ] Implement resolver with `{'Medium': 8, 'Standard': 16, 'High': 32}`; reject unknown values with ValueError. Capture sidebar choice in both request paths. Forward settings explicitly, retaining per-target and checkpoint metadata. Include mode in methodology parameters.
- [ ] Repeat targeted tests and the complete unittest suite. Compile changed modules. Review only the selected diff.

## Increment 2: Exact private memory

Files: create `src/docking_memory.py`, `tests/test_docking_memory.py`, a locally reviewed RLS migration; extend pipeline preparation, job specification, runner and UI.

Interfaces: `pair_key(manifest) -> str | None`; `eligible_entry(entry, owner_id, key) -> bool`; manifest contains actual prepared hashes, identity/chemical state, grid, full protocol and versioned preparation/interaction settings. A cache entry contains owner, key, source run/date, row, pose, replica records and completed interaction evidence. Invalid or incomplete entries return misses, not exceptions that stop docking.

- [ ] Test each fingerprint mutation independently, unknown versions, stereochemistry/charge, nonfinite scores, failed/incomplete evidence, wrong owner and corrupt payloads. Observe failure before implementation.
- [ ] Implement deterministic canonical-JSON SHA256 with required fields and no name-only matching. Validate every returned entry against its owner and requested exact key.
- [ ] Refactor preparation into a retained prepared-input plan before execution. Shared ligand preparation uses the recorded chemical state and seed; per-target paths remain distinct.
- [ ] Add generation-scoped `awaiting_reuse` job state and explicit reuse/redock action. Test reconnect, stale consent rejection, duplicate launch prevention, worker death and bounded consent wait. Never execute missing pairs before consent.
- [ ] Add authenticated owner-scoped persistence using inspected RLS migration; no service role or credentials in job files. Missing table, read failure or quota failure degrades to fresh calculations and a storage notice. Do not apply the migration remotely.
- [ ] Test the 5-of-20 case executes exactly 15 pairs after consent; redock-all executes 20; retained cached bytes/scores/source dates remain unchanged. Benchmark a real small cold/partial/full-hit matrix before any speed claim.

## Increment 3: Integrated biological additions

Files: create `src/docking_biology.py`, `src/report_biology.py` and focused tests; modify `pipeline_core.py`, `report_writer.py`, `report_methods.py`, `mumo_chat.py`.

Interfaces: `select_candidates(rows) -> dict[target, list[row]]` retains per-target ties among finite completed interaction-qualified pairs; `analyze_biology(rows, targets) -> dict` stores STRING species groups/mapping and unique-structure ADME entries plus failure states and date/version provenance.

- [ ] Test per-target selection, ties, nonfinite/FAILED rows, no candidate, deduplicated chemistry and independent STRING/ADME API failure. Inject external clients only at the network/model boundary.
- [ ] Resolve PDB to verified UniProt/species before STRING; group species and list unresolved inputs. Call existing STRING functions once per species and RDKit/ADMET-AI once per unique candidate structure. Store outputs in result metadata and preserve them through compression/history.
- [ ] Add report renderers reading stored data only. Test section order and regenerated report downloads with external computations disabled; include missing endpoints without fabricated values.
- [ ] Show stored network and ADME in the docking results panel. Preserve existing 2D/3D and orbital rendering. Render a complete sample DOCX and inspect each page.
- [ ] Run full tests and real small matrix, inspect performance counts and unchanged scientific settings. Request separate release approval with honest limitations; no push in this plan execution.
