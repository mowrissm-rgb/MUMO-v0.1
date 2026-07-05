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

MUMO is an open-source, conversational drug-discovery platform. Start from anything —
a disease, your own protein target, or your own ligand — and MUMO runs the full
pipeline: target discovery → 3D structure → pocket detection → ligand sourcing →
molecular docking → interaction profiling → publication-ready 3D figures.

> **Version 0.1** — engines complete. LLM conversational layer coming next.

---

## What MUMO does (the 6 agents)

| Agent | Job | Powered by |
|---|---|---|
| 🎯 Target Finder | disease → evidence-scored protein targets | Open Targets |
| 🎯 Target Analyst | gene → AlphaFold structure + active-site grid box | AlphaFold, UniProt |
| 🔬 Ligand Scout | target → strongest known ligands | ChEMBL |
| ⚙️ Docking Engine | dock ligand into target | AutoDock Vina |
| 🧲 Interaction Analyst | H-bonds, hydrophobic, residues, etc. | PLIP |
| 🧪 3D Visualiser | interactive, customizable pose figures | py3Dmol |

Every entry point works: disease-only · target-only · ligand-only · target+ligand.
All free, no API key required.

---

## Run locally (Windows)

```bash
.venv\Scripts\streamlit.exe run src/mumo_chat.py
```

## Deploy on Streamlit Community Cloud

1. Push this repo to GitHub.
2. On [share.streamlit.io](https://share.streamlit.io) → **New app**.
3. Pick this repo, set **Main file path** to `src/mumo_chat.py`.
4. Deploy. Dependencies install automatically from `environment.yml`.

---

## Project layout

- `src/` — agents, docking engine, viewer, and the unified Streamlit app
  - `preview_pipeline.py` — the main app (unified interface)
  - `agents/` — Target Finder, Target Analyst, Ligand Scout, Interaction Analyst
  - `docking_engine.py`, `viz.py`, `setup_env.py`
- `environment.yml` — cloud dependencies (conda + pip)
- `bin/`, `data/` — local binaries & generated files (git-ignored)

---

*Built by Mowriss. "I am trying to achieve the impossible. And I will never back off from this idea."*
