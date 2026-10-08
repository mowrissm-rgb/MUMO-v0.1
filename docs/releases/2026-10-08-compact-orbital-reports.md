# Compact calculated orbital figures

## Changed

- Shared app and report figures show LUMO above HOMO, recorded energy ladders,
  horizontal energy levels, a double-headed gap arrow and the compound name.
- Red and blue identify opposite orbital phases, not charge. Signed amplitude
  thresholds remain +0.03 and -0.03 a.u.; no decorative surfaces are introduced.
- Four compounds fit each portrait sheet. Complete runs of up to eight compounds
  use a compact report with per-page energy tables and a short method note.
- A slightly wider camera fit preserves space around atoms and lobes.
- Partial runs retain unavailable/failed entries through the detailed report path.

## Verification

- Orbital tests: 17 run, 15 passed, 2 local native-engine checks skipped.
- Full local suite: 159 run, 154 passed, 5 engine-availability checks skipped.
- Eight retained ligand identities were independently recalculated locally with
  GFN2-xTB. All eight coefficient/grid checks passed, and all 16 orbital views
  rendered offline. New images use their matching new calculation energies.
- The eight-ligand report contains two figure sheets and two tables. It is designed
  for two A4 portrait pages; final Word pagination could not be rendered locally
  because the bundled LibreOffice executable is unavailable.
- Build-time tests and the real aspirin release smoke check remain enabled.

## Scope and rollback

No docking scores, protein-validation figures, secrets, hardware settings or
service endpoints change. Scientific outputs remain computational predictions.
Previous deployable revision: d19f4938546945c863b3c6ed16848b2a38e34d20.
Rollback can revert this presentation-only commit without changing stored jobs.
