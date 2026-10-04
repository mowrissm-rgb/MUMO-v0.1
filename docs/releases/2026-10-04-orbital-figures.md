# Orbital figure release

- Calculated GFN2-xTB orbital surfaces are shown with orange/blue phase colors.
- Atom key: C green, H yellow, S gold, O red, N blue.
- Paired HOMO/LUMO figures include energies, a dotted I-shaped gap connector and compound name.
- Up to six compound panels are included per report sheet; missing surfaces stay explicitly unavailable.
- Ramachandran reference regions use red/yellow without changing the reference thresholds.
- Orbital conversion runs in an isolated Python 3.12 environment; a worker failure does not replace numerical results with invented surfaces.
- Internal output checks are not experimental validation. Initial surface support is closed-shell H/C/N/O-style s/p wavefunctions; unsupported basis conventions are rejected.
- The licensed ERRAT/ProSA five-panel demonstration is not an automated production feature in this release.

## Deployment gate

The container runs regression tests and a real aspirin calculation-to-cubes-to-images-to-DOCX smoke test before startup.

## Rollback

Previous working Space revision: afb75071501167c1dbc6ae56bf6a33c106c8c837.
If the new app cannot start or core regression checks fail, revert this release commit and redeploy. Do not change hardware, billing or user data.
