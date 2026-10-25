---
title: MUMO
emoji: 🧬
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
short_description: Multi-Agent Drug Discovery & Development AI Platform
---

<!-- The YAML block above configures the Hugging Face Space (Docker SDK).
     Harmless on GitHub; required by HF — keep it as the first thing in the file. -->

# 🧬 MUMO — Multi-Agent Drug Discovery & Development AI Platform

**Multiple agents · Unified Mission · One interface.**

MUMO is a chat-first drug-discovery platform. You talk — a disease, your own
protein target, a ligand, a pasted SMILES, an uploaded structure or spreadsheet
— MUMO asks what it needs to know, then runs the matching workflow and opens
the result in the right-hand panel: target discovery → structure → docking →
interaction profiling → ADMET → reports, or any one of those on its own.

**Live:** [mowriss-mumo.hf.space](https://mowriss-mumo.hf.space)

---

## The 11 workflows

Each name identifies a workflow backed by real tools below — not a separately
trained model. Chat supports explicit invocations (`run Orbit on aspirin`,
`run Fate on this compound`) as well as plain requests MUMO routes itself.

| Name | Job | Backed by |
|---|---|---|
| 🧭 Compass | Disease → evidence-scored protein targets | Open Targets |
| 🔭 Scout | Target → strongest known / candidate ligands | ChEMBL |
| ⚓ Atlas | Structure prep, active-site detection, Ramachandran validation | AlphaFold, UniProt, Top8000/MolProbity contours |
| ⚙️ Pose | Docking, poses, ligand–residue interactions | AutoDock Vina + Vinardo, ProLIF |
| 🧬 Anchor | Molecular dynamics, pose-stability checks | OpenMM (isolated environment) |
| ☢️ Orbit | Calculated HOMO/LUMO energies and orbital surfaces | GFN2-xTB (isolated environment) |
| 💊 Fate | ADME, toxicity, drug-likeness | ADMET-AI (TDC / Chemprop) |
| 🔄 Flux | Biotransformation and metabolism prediction, drawn routes | Rule-based SMARTS transforms |
| 🕸️ Nexus | STRING protein–protein interaction networks, pathway biology | STRING |
| 🧵 Helix | Sequence similarity, homology, phylogeny | Self-hosted BLAST+ (SwissProt) |
| 📝 Quill | Full `.docx` / A4 PDF reports, structure exports, run evidence (JSON) | python-docx, Playwright, matplotlib |

Every entry point works on its own — disease-only, target-only, ligand-only,
structure-only — and in combination. Sign in (Supabase, via the
[landing page](https://mumo-landing.vercel.app)) for cross-device chat history;
without it MUMO still runs, local-only.

---

## Why it doesn't go down in one piece

MUMO has been taken down three times by the same failure: one heavy native
component (the docking/MD/QM stack) segfaults and the whole container dies,
chat included. The fix was a specialist split, not a rewrite:

| Specialist | Owns | Why separate |
|---|---|---|
| **A — Pose** | docking, Ramachandran, MD | the heavy native stack; historically the one that segfaults |
| **B — Nexus** | STRING, BLAST, phylogeny | light, no native deps |
| **C — Fate** | ADMET, metabolism, QM | light, no native deps |
| **D — Quill** | reports, exports | carries a full headless Chromium |

Each specialist can run locally in-process (today's default) or as its own
deployed service, switched purely by an environment variable — no code change,
no redeploy of the front door. When a specialist is down, MUMO says exactly
what's unavailable and keeps serving everything else; when a request lands on
the wrong specialist, it says so and runs it anyway rather than refusing.
Specialist A also ships as its own [Cloud Run service](deploy/space-a/).

---

## What each workflow actually does

- **Docking (Pose).** AutoDock Vina ≥1.2 (version-checked — bioconda only ships
  1.1.2, which silently drops Vinardo scoring and `--autobox`), geometric
  pocket detection instead of blind docking, Vina + Vinardo consensus scoring,
  pose clustering, docking replicates so every affinity carries an error bar,
  and a private per-user docking cache with explicit reuse controls.
- **Interactions.** ProLIF fingerprints (Apache-2.0) — not PLIP+OpenBabel
  (GPL) — on reloaded, explicit-hydrogen V3000 SDFs with atom-mapped,
  hash-verified geometry. 2D and 3D interaction views, residue-level H-bond,
  hydrophobic and other contacts.
- **Structure validation (Atlas).** Backbone geometry scored against the same
  Top8000 percentile contours MolProbity, Phenix and the wwPDB use, so results
  agree with wwPDB validation reports.
- **Orbitals (Orbit).** GFN2-xTB single-point calculations with validated
  charge/spin, finite-energy and gap checks; calculated HOMO/LUMO surfaces
  rendered directly (no browser dependency), with numeric energies available
  even when surface rendering fails.
- **ADMET (Fate) & metabolism (Flux).** ADMET-AI (TDC/Chemprop) toxicity, CYP
  and PK predictions; metabolite prediction with transformation SMARTS and
  rule provenance — no invented route edges.
- **Networks (Nexus).** STRING interaction networks with a biology layer
  underneath: evidence matrices, partner dossiers, similarity trees, not just
  a graph.
- **Sequence (Helix).** Self-hosted BLAST+ against SwissProt baked into the
  image at build time — no dependency on NCBI's web BLAST, which isn't
  licensed for this kind of use.
- **Reports (Quill).** Full `.docx` and continuous-flow A4 PDF reports —
  docking, STRING, ADMET, orbitals — built from the same data as the on-screen
  result, plus raw run evidence downloadable as JSON.
- **Input.** Pasted SMILES, uploaded structures, spreadsheets, PDF reports,
  hand-typed or slightly misspelled compound/CAS names, PDB IDs.

See [`docs/agent-workflows.md`](docs/agent-workflows.md) for the current
routing rules and release notes, and
[`SCIENTIFIC_VERIFICATION.md`](SCIENTIFIC_VERIFICATION.md) for what "verified"
means here — recorded inputs/outputs and consistency checks, not a claim of
experimental validity. 34 test files exercise this; `python -m unittest
discover -s tests` runs them, and the Docker build runs them again.

---

## Data & licensing

Target, structure and bioactivity data come from Open Targets, UniProt,
AlphaFold DB, ChEMBL, STRING, RCSB PDB and the Top8000 reference set — mostly
CC-BY, ChEMBL CC-BY-SA. The scientific stack is Apache-2.0/BSD/MIT throughout
(Vina, RDKit, ProLIF, meeko, dimorphite-dl, ADMET-AI); GPL components (PLIP,
OpenBabel) were deliberately replaced to keep MUMO usable commercially. Full
attributions, including the one GPL *dependency* that remains transitive
(MDAnalysis, via ProLIF), are in [`NOTICE.md`](NOTICE.md).

---

## Run locally

The scientific stack (RDKit, Vina, xTB, BLAST+) comes from conda-forge/bioconda:

```bash
conda env create -f environment.yml -n mumo
conda activate mumo
streamlit run src/mumo_chat.py
```

`setup_env.ensure_vina()` resolves a Vina ≥1.2 binary itself on both Windows
and Linux — conda's own package is too old, so don't rely on it being on PATH.
MD (OpenMM), QM (pyscf) and SASA run in their own isolated conda environments,
as in the Dockerfile, to keep native-library crashes from taking down the
whole process; running those two workflows locally without that isolation is
unsupported.

## Deploy

- **Main app** — this repo, Hugging Face Spaces (Docker SDK), `app_port: 7860`.
  `.github/workflows/keep-warm.yml` pings it every 6 hours so the free tier
  doesn't sleep, and fails loudly (with the Space's actual runtime stage) if
  it's down rather than just asleep.
- **Specialist A (docking)** — optionally its own Cloud Run service; see
  [`deploy/space-a/`](deploy/space-a/).

---

## Project layout

- `src/mumo_chat.py` — the app: chat-first Streamlit UI, routing, theming
- `src/agents/` — one module per scientific capability (docking, ADMET,
  STRING, BLAST, QM, MD, metabolism, target discovery, ligand scouting)
- `src/services/` — the specialist registry: who owns what, where it lives,
  what to say when it's down (see "Why it doesn't go down in one piece")
- `src/agent_catalog.py` — the 11 user-facing workflow names and routing
- `docs/` — release notes and workflow documentation
- `tests/` — 34 test modules; run with `python -m unittest discover -s tests`
- `deploy/space-a/` — Specialist A's standalone Cloud Run deployment
- `NOTICE.md`, `SCIENTIFIC_VERIFICATION.md` — attributions and what
  "verified" means in this codebase

---

*Built by Mowriss. "I am trying to achieve the impossible. And I will never back off from this idea."*
