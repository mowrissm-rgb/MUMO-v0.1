# Agent names and report consistency implementation plan

> **For agentic workers:** Use executing-plans task-by-task. Changes are approved for deployment.

**Goal:** Name all existing workflows, preserve real execution beneath the approved Gemini-inspired interface, and make orbital figures consistent in ADME, standalone QM and docking.

**Architecture:** A pure agent catalogue maps existing action keys to short names without changing service ownership. Shared orbital presentation helpers prepare and display the same verified surface images and generate content-derived report keys. Existing Streamlit controls retain uploads, authentication and background jobs; no simulated HTML results enter production.

**Tech stack:** Python, Streamlit, python-docx, existing xTB/PySCF surface rendering and Playwright.

## Global constraints

- Short names only: Pose, Fate, Nexus, Quill, Orbit, Atlas, Compass, Flux, Helix, Anchor, Scout.
- Existing IDs, endpoint configuration, scientific settings and auth remain unchanged.
- No guessed surfaces, fabricated scores or demo controls in the running app.
- Preserve dark/light themes and accessible real input controls.

### Task 1: Name and expose existing workflows

Files: `src/agent_catalog.py`, `src/mumo_chat.py`, `tests/test_agent_catalog.py`.

- [x] Write failing tests that all service capabilities resolve to an agent and required user-facing names have no product prefix.
- [x] Implement `agent_for(action)` and expose the catalogue in the sidebar and report headings.
- [x] Add Gemini-inspired surface/composer styling to existing controls; retain real actions rather than copying simulated scripts.
- [x] Run catalogue tests and compile the Streamlit module.

### Task 2: Unify orbital figure and report identity

Files: `src/orbital_presentation.py`, `src/report_writer.py`, `src/mumo_chat.py`, `tests/test_orbital_consistency.py`.

- [x] Write failing tests that ADME reports embed verified surface images and that changed molecule/energy/image evidence changes the cache key.
- [x] Implement `admet_entries(result)`, `prepare_admet_surfaces(result, browser)`, and `report_cache_key(kind, result)`.
- [x] Route ADME screen and DOCX through verified surface entries; keep numerical energies when genuine surfaces fail, never replace them with decorative lobes.
- [x] Remove default duplicate legacy energy images from standalone QM; retain optional clearly labelled energy-only diagram.
- [x] Use content-derived keys for standalone QM report downloads.
- [x] Run tests and inspect generated DOCX image relationships and ligand labels.

### Task 3: Verify and release

- [x] Run the complete test suite and check the diff for unrelated changes/secrets.
- [x] Obtain independent code review and resolve important findings.
- [ ] Commit, fetch the latest Hugging Face main and use a normal non-force push.
- [ ] Confirm the exact release reaches RUNNING and the health endpoint returns ok. Preserve the previous commit for rollback.
