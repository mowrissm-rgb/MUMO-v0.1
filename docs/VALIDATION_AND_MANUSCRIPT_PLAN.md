# MUMO validation and manuscript plan

Drafted 2026-10-29. Updated 2026-10-30. Status: **Phases 0 to 3 are largely done.** All 12 workflow checks and the routing and specialist-outage tests have run, with protocols frozen and tagged first. Full results, defects fixed and open failures are in [`validation/RESULTS.md`](../validation/RESULTS.md). The Flux rules added after seeing failures have had their held-out re-test (protocol v1.3), and the Atlas pocket detector has been measured on 40 held-out complexes (protocol v1.4; no improvement found, defaults unchanged). The new components (pharmacophore, mass-spec) are not built, and the held-out re-test for the two Pose entries is still to do.

## 1. Goal and sequencing

1. **Validate the 11 existing workflows now** and save all evidence in a reproducible form.
2. **Build the new components** later, with no deadline: the pharmacophore agent first, then the mass-spec pipeline, then the extra analysis graphs.
3. **Validate the new components** with the same protocol.
4. **Write the manuscript** from the saved evidence and submit.

Decisions so far (2026-10-29): pharmacophore and mass-spec come after the current workflows are validated, pharmacophore first; no journal chosen; authors to be supplied by Mowriss; MUMO is for education and research only, not commercial software or a commercial website.

Rule carried over from the ERK2 pilot: **write the protocol and pass criteria down before running anything.** Never pick the metric after seeing the result. A failed workflow is reported as a failed workflow; it is not tuned until it passes.

## 2. What "validated" means here

`SCIENTIFIC_VERIFICATION.md` already says current tests check recorded inputs, execution and outputs, not experimental validity. The 34 unit-test modules therefore support **"the software behaves as designed"**. The manuscript needs a second layer: **"the output agrees with independent ground truth."**

Each workflow gets two tiers:

| Tier | Question | Evidence |
|---|---|---|
| A. Technical | Does it run, fail honestly, and reproduce? | Existing tests, plus repeat-run determinism and failure-injection |
| B. Scientific | Does it agree with a known answer, and beat or match a baseline? | Public benchmark, a prespecified metric, a comparator, an uncertainty estimate |

Several workflows wrap existing published tools (Vina, ADMET-AI, xTB, BLAST+, STRING, Open Targets). For those, the defensible claim is **integration fidelity**: MUMO returns what the underlying tool returns, with correct preparation and units. It is **not** that MUMO improved the tool. The paper should say so plainly.

## 3. Per-workflow validation design

Benchmarks below are proposals. Confirm each is current and licensable before freezing the protocol.

| Workflow | Tier B test | Primary metric | Comparator |
|---|---|---|---|
| **Pose** (Vina + Vinardo) | Redocking on CASF-2016 core set (285 complexes) and PoseBusters set; screening power on LIT-PCBA targets | Top-1 RMSD < 2 Å success rate; Pearson/Spearman vs experimental affinity; EF1% | Plain Vina; published CASF baselines |
| **Pose, interactions** (ProLIF) | Native-contact recovery on crystal complexes | Per-contact precision/recall | PLIP and the PDB's own annotations; document the Discovery Studio comparison gap noted in `SCIENTIFIC_VERIFICATION.md` |
| **Atlas** | Ramachandran outlier calls and pocket detection | Agreement with MolProbity on a fixed PDB list; pocket success (distance to true ligand centre ≤ 4 Å) | MolProbity; P2Rank (already in `bin/`) |
| **Scout** (ChEMBL) | Retrieval of known ligands for targets with curated actives | Exact agreement with direct ChEMBL query; potency ranking correct | ChEMBL web API itself |
| **Compass** (Open Targets) | Disease → known approved/clinical target recovery | Precision@k, recall@k | Open Targets own ranking; random. Guard against circularity: score against a source Compass does not read |
| **Fate** (ADMET-AI) | Held-out scaffold-split endpoints from TDC; unit and standardization checks | Per-endpoint AUROC or MAE | Published ADMET-AI numbers. Claim fidelity, not new accuracy |
| **Flux** (SMARTS rules) | Known drug metabolites from literature/DrugBank | Recall of reported metabolites at top-k; precision; false-route rate | SyGMa, BioTransformer if obtainable |
| **Orbit** (GFN2-xTB) | HOMO/LUMO energies for a small molecule set | MAE and correlation vs DFT reference values | DFT literature values. xTB gaps are known to deviate; report the bias, don't hide it |
| **Anchor** (OpenMM) | Native pose vs decoy pose stability | Ligand RMSD drift, replicate spread; native should be more stable than decoy | Native vs deliberately wrong poses |
| **Nexus** (STRING) | Reproduction fidelity; pathway recovery for curated gene sets | Match to STRING API scores; KEGG recovery | STRING direct |
| **Helix** (BLAST+) | Homolog retrieval and tree sanity | Hit agreement with NCBI BLAST; known family clustered correctly | NCBI BLAST on same SwissProt version |
| **Quill** | Report fidelity | Every number in the report equals the run-evidence JSON (automated diff) | Run-evidence JSON |

Cross-cutting checks:
- **Routing accuracy.** Labelled set of chat requests; does `dispatch.py` pick the right workflow? Include ambiguous words ("pose", "helix") and misspelled compound names.
- **Honest failure.** Inject outages in each specialist (A–D) and confirm MUMO reports what is down and keeps serving the rest.
- **Determinism.** Rerun each workflow 3 times; record what varies (docking seeds, MD, ADMET weights).

## 4. New components

Both need a short specification and a frozen protocol **before** they are built.

**Pharmacophore agent.** The separate repo `mumo-pharmacophore-corrected` already holds a strong negative result: on ERK2 the pharmacophore lost to a similarity baseline (AP 0.45 vs 0.92 against decoys). That repo's own rule is that MUMO integration waits for validation, and the ERK2 test set is already spent. Decision needed (section 7): either integrate with the limitation stated openly, or validate on a new prespecified multi-target panel first. I recommend the panel. A single-target negative result is a weak foundation for a paper.

**Mass-spec agent.** Not started and not in either repo. Needs: input formats, which task (formula assignment, MS/MS identification, metabolite matching, or something else), and a reference library. Proposed validation: identification accuracy on held-out spectra from public libraries (MassBank, GNPS), top-k hit rate, and score calibration against a decoy library.

**Analysis graphs.** Treat as part of Quill. Validate by automated check that plotted values equal the evidence JSON, plus a figure review pass.

## 5. Data and evidence layout

New top-level folder `validation/` in this repo (large raw inputs stay out of git, referenced by hash):

```
validation/
  PROTOCOL.md              frozen before any run; dated; git-tagged
  manifests/<workflow>.json  dataset source, version, URL, SHA-256, licence
  runs/<workflow>/<date>/    raw outputs, logs, run-evidence JSON
  results/<workflow>.csv     one row per item (complex, compound, spectrum)
  results/summary.json       metrics, confidence intervals, pass/fail vs frozen criteria
  figures/                   generated by script from results/ only
  env/                       conda lock, tool versions, commit hash, seeds
```

Every run records: git commit, tool versions, settings, random seeds, input hashes, wall time, and any item that errored. **Errors stay in the denominator**; they are reported, not dropped. A single `scripts/run_validation.py <workflow>` should regenerate each result from the manifest.

## 6. Phases

| Phase | Work | Output |
|---|---|---|
| 0. Freeze | Choose benchmarks, metrics, pass criteria per workflow; resolve section 7; tag `PROTOCOL.md` | **Done per workflow**: each protocol version was committed and tagged (`validation-protocol-v0.1` to `v0.9a`) before its first run |
| 1. Tier A | Repeat-run, failure-injection, routing tests; fix defects found | **Done**: repeat-run and failure-injection are in every workflow check, and the routing-accuracy and specialist-outage tests have run. Open finding: the remote-specialist path is not wired into the app. |
| 2. Tier B, light workflows | Quill, Scout, Compass, Nexus, Helix, Fate, Flux | **Done.** Helix paralogue retrieval is an open failure (6/9). |
| 3. Tier B, heavy workflows | Pose, Atlas, Anchor, Orbit | **Done.** Open failures: Atlas pocket detector, Pose interactions (H-bond recall), Anchor (3ERT and run-to-run differences). |
| 4. Build new components | Pharmacophore agent, mass-spec agent, graphs | Not started |
| 5. Validate new components | Same protocol, frozen first | Not started |
| 6. Manuscript | Section 8 | Not started; evidence summary is in `validation/RESULTS.md` |

Deviation from section 5: results are kept per run under `validation/runs/` (items, summary, environment) and summarised in `validation/RESULTS.md`; the separate `results/`, `figures/` and `env/` folders were not created. Figures can be generated from the run folders when the manuscript needs them.

Phases 0–3 do not depend on the mass-spec or pharmacophore decisions, so they can start now. Phase 3 needs the compute answer.

## 7. Decisions and open questions

**Decided**
- **Order.** New components wait. Pharmacophore agent first, then mass-spec, no hurry. Both are Phase 4 or later and do not block Phases 0–3.
- **Licensing.** MUMO is education and research only, not commercial. The commercial-use constraint behind replacing GPL tools (PLIP, OpenBabel) is no longer a blocker. Attribution duties (for example ChEMBL CC-BY-SA) still apply and `NOTICE.md` stays current. State the non-commercial scope in the paper's Availability section.

**Still open**
1. **Journal and article type.** None chosen. Decide before Phase 0 ends, since it sets how deep each benchmark must go. Until then the plan assumes a full research article, the more demanding case.
2. **Authors and affiliations.** Mowriss will supply these later. Not needed until drafting.
3. **Compute.** Everything so far ran on this Windows machine (16 cores); the largest run took about 35 minutes. The plan's CASF-scale docking was replaced by an 11-complex redocking set. Whether to scale up on the Cloud Run Specialist A is still open and is needed only for a larger docking benchmark or Anchor.
4. **Public Space during review.** Does the Hugging Face Space stay public? Some journals expect a working link.
5. **Mass-spec scope** (task, data format, reference library). Not needed until Phase 4.
6. **Pharmacophore integration route.** Disclose the ERK2 negative result, or validate on a new multi-target panel first (recommended). Not needed until Phase 4.

## 8. Manuscript outline (written from saved evidence)

1. Abstract
2. Introduction: fragmented discovery tooling; what a multi-workflow chat platform adds; what this paper does and does not claim
3. System design: workflows, specialist split, routing, failure isolation
4. Validation methods: tiers, frozen protocol, benchmarks, metrics
5. Results, one subsection per workflow, plus routing and failure behaviour
6. Limitations, stated openly: tools wrapped rather than retrained; known-weak workflows; hydrogen/protonation caveats; decoy-set limits
7. Availability: code, DOI-archived validation data, live service
8. Supplement: full per-item tables, environment locks, protocol

Order of drafting: Methods first (after freeze), Results as each phase lands, Introduction and Discussion last. Before submission, a simulated peer review pass and a reproducibility pass from a clean environment.

## 9. Immediate next steps

1. Mowriss picks a journal (or confirms "full article for now"). Authors and the public-Space decision can wait until drafting.
2. Decide whether the remote-specialist path is wired into the front door or removed from the README (section 3 finding).
3. Resolve the open failures, using held-out data for anything tuned after seeing results: Atlas pocket detector, Pose interaction H-bond recall (start with 1CX2), and the three Pose redocking misses.
4. Check the Ghose and TPSA source papers, then decide whether to add the TPSA sulfur and phosphorus variant.
5. Rerun every check from a fresh environment at a tagged commit.
6. Begin Phase 4 (pharmacophore agent first) only after Mowriss decides the integration route in section 7.
