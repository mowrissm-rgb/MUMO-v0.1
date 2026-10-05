# Docking modes and integrated biology release

User approved deployment on 5 October 2026.

## Added

- Medium (8), Standard (16, default) and High (32) docking search depths, each using three seeded replicas.
- Stored species-aware STRING context after target validation and candidate ADME after docking in the website and Word report.
- Per-target tied-candidate selection, explicit missing-data states and calculation provenance.

## Staged, not enabled

Private calculation reuse code is default-off under `MUMO_PRIVATE_CACHE_ENABLED`. No database migration is applied. The switch must remain off until actual database permissions, isolation and quotas are tested. Owner: MUMO maintainer; review by 19 October 2026. No automatic activation.

## Verification and limitations

Full local regressions and a separate real small cache correctness check were exercised. The independent real run was unexpectedly slow and hit a Vinardo rescoring timeout; this release does not claim a performance improvement. ADMET model/API failures remain explicit rather than being filled with invented values. Actual hosted end-to-end docking and report generation require a fresh run after deployment.

## Rollback

Last verified remote version before this release: `c568c25256284d4e6d5e48a2dc088650d4a06a93`. Record the new pushed revision after deploy. If the app fails to boot or introduces result-integrity faults, revert only this release's commits in reverse order on a clean scoped checkout, push the revert normally (no force push), and verify the Space health endpoint. No hosted database change needs reversal.

Deployment remains on existing free CPU hardware. Deploying restarts the container and may interrupt an active run; retain downloaded results and begin a fresh small test after startup.
