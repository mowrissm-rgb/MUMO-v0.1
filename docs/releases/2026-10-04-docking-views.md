# Docking presentation release

- Full protein ribbon is the website default, with Full protein and Binding site camera buttons.
- Every detected interaction is shown by default; green dashed connectors identify hydrogen bonds. A type/color legend reports atom-pair contact counts, which can differ from unique-residue counts.
- Binding-site residue labels are visible in the close-up. Full-fold labels are hidden to reduce overlap.
- The report includes full-ribbon and binding-site images as one stacked figure, followed by the existing 2D interaction map.
- Brighter contact colors are shared by the website and report; the report ribbon is blue.
- No scoring, geometry, chemical identity or interaction calculation was changed. These remain computational predictions.

## Verification and rollback

Local regressions and the genuine prepared aspirin/COX-2 (1CX2) preview test preserve input records and exercise both zoom buttons. The container also runs regression and real orbital smoke checks before startup.

Previous live revision: a6c0b4840db807ccc442e066eebaa420a80d8d7c. Revert this release commit if startup fails; do not change billing or user data.
