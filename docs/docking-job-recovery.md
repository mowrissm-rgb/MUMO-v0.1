# Docking job recovery repair — 2026-10-04

## User-visible changes

- A dead Linux worker, including an unreaped zombie, no longer remains “running.”
- Finished results are published locally before history saving; authenticated
  history retries run independently of the results screen.
- Each attempted target–ligand pair is checkpointed, including failed pairs.
  A worker failure exposes the partial table and its available structures,
  not invented scores for unfinished pairs.
- Main Vina searches have a configurable 1,800-second limit **per replica**
  (`MUMO_VINA_TIMEOUT_SECONDS`). Timeout means no completed score for that pair;
  search depth and replica count are unchanged.
- Result/checkpoint files and cloud result payloads use lossless gzip encoding.
  Old plain-JSON files and histories remain readable. No atoms or evidence are removed.
- Repeat saves of the same run ID do not create duplicate history entries.

## Verification

Regression tests cover dead/zombie workers, corrupt result files, failed launches,
publication before external persistence, pair checkpoints, timeouts, slow history
saving, denied database writes, repeat runs, and lossless compression.
A real CDK4 smoke test used ethanol and phenol at exhaustiveness 4 / one replica
to exercise execution and checkpoints, **not** to validate study results or potency.
It produced two distinct scores and checkpoint counts 1 then 2.
The 7,024,177-byte checkpoint compressed to 1,228,058 bytes and round-tripped exactly.

## Limitations and rollout

Local checkpoints survive browser reconnects, not deletion/replacement of the
Space container. Cloud history is durable only after an authorized save succeeds.
This repair does not recover calculations lost before checkpoints existed,
automatically resume unfinished pairs, guarantee a batch completion time,
or independently establish docking accuracy.
The user approved replacing the old stuck run and starting a fresh run.
Hosting stays on the existing free hardware; no billing changes are required.

Rollback: revert this repair commit and redeploy. Preserve/download new compressed
results first; old code cannot read the new gzip files or cloud envelopes without
the backward-compatible storage reader from this repair.
