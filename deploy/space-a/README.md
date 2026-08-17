---
title: MUMO Docking Specialist
emoji: 🧬
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# MUMO — Specialist A (docking & structure)

Runs molecular docking and backbone-geometry validation as an isolated service
for [MUMO](https://mowriss-mumo.hf.space), so that a crash in the native
scientific stack cannot take the main application offline.

Not intended for direct use. Endpoints:

| | |
|---|---|
| `GET /health` | liveness, and whether Vina is actually present |
| `POST /run/dock` | run a docking job |
| `POST /run/ramachandran` | backbone geometry validation |
| `GET /jobs/<id>` | recover a job whose request was interrupted |
