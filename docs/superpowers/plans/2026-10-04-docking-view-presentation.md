# Docking view presentation implementation plan

**Goal:** Full protein ribbon on the website, binding-site zoom, all detected interactions and a matching two-view report figure.
**Architecture:** Keep the existing 3Dmol viewer and the prepared complex/interaction records unchanged. Presentation colors and camera controls live in `viz.py`; `report_writer.py` captures full and binding-site cameras and composes one labeled image.
**Tech stack:** 3Dmol, Playwright, Pillow, existing python-docx.

## Constraints
- Hydrogen bonds are green dotted connectors; other interaction colors match the existing 2D map.
- Do not recalculate, invent or change interaction counts or geometry.
- Show all detected interaction types by default.
- Report: full protein ribbon plus binding-site close-up, with a legend.
- No paid tools; show a real prepared-complex preview before publishing this revision.

## Tasks
- [x] Add failing tests in `tests/test_docking_presentation.py`: full camera, binding camera, legend, source-record immutability and two labeled report panels.
- [x] In `src/viz.py`, add full/binding camera mode, two accessible buttons, type-based connector colors and a detected-contact legend.
- [x] In `src/report_writer.py`, capture both cameras through the same `render_complex_html` helper and compose a full-ribbon/close-up figure.
- [x] Keep the existing 2D interaction diagram, but make the website legend readable in both themes.
- [x] Run regressions and render the existing real COX-2/aspirin prepared complex. Check both report panels and zoom buttons in a fresh headless browser.
- [ ] Show the preview to the user; do not publish the docking revision before approval.

Test contract: `render_complex_html(path, ia)` returns HTML with full camera and two zoom buttons; `options={'view_mode':'binding'}` uses the ligand camera. Changing colors must leave `ia` byte-for-byte equivalent after JSON serialization.
