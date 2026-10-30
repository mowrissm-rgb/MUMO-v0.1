# Baseline before the fixes

R1 (47/48), R2 (1/25), R3 (5/6), R4, O2 to O6 pass; R5 (10/12) and O1 (6/7) fail. Defects in MUMO:

- **Second named workflow lost:** "run Flux and Orbit on paracetamol" returned only `metabolism`, because a workflow name was a cue only directly after "run". It also broke ordering. A chain of names after one verb is now recognised and positioned at its own name.
- **Negation ignored:** "do not dock anything yet" returned `dock`. A negation shortly before a cue now cancels it.
- **Out-of-scope cues matched inside words:** "chamber" (contains "amber") was flagged as molecular dynamics, and "protein synthesis" as synthesis planning. Cues now start at a word boundary, and the bare "synthesi" cue is replaced by chemistry-specific ones.
- **Router action with no owner:** `analyze` (the ADMET screen) had no owning specialist because the registry calls it `admet`. An alias fixes it.

**Finding, not fixed (descriptive wiring audit in the run summary):** nothing in `src/` outside `services/` references `client.call`, `MUMO_SPACE_*` or `registry.referral`. The front door (`mumo_chat.py`) uses only `services.resilience`, the local gate. The remote-specialist path (`services/client.py` and the registry's referral wording) is therefore code that behaves correctly in isolation (checks O3 to O6 pass) but is not connected to the app, so the README statement that a specialist can be switched to its own service "purely by an environment variable" does not hold for the front door in this repository. This needs a design decision.
