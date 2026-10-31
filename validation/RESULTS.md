# MUMO validation results

Status as of 2026-10-30. Every number below comes from a saved run under `validation/runs/<workflow>/<timestamp>/` (items, summary, environment, git commit and hashes). Protocols are in `validation/PROTOCOL.md`, frozen and tagged (`validation-protocol-v0.1` to `v0.9a`) before the run they govern.

## How to read this

- **Integration fidelity, not novelty.** Most workflows wrap an existing tool (Vina, xTB, ADMET-AI, STRING, ChEMBL, Open Targets, ProLIF). The tests ask whether MUMO prepares inputs correctly, returns what the tool returns, and fails honestly. They do not show that MUMO improves any tool or that predictions are experimentally true.
- **Pass criteria are floors chosen before running.** Where a threshold is a methodological choice, the protocol says so. A "pass" means the floor was met, not that performance is high.
- **Errors count as failures.** No item was dropped to improve a number.
- **Two tiers.** Tier A is technical (runs, fails safely, reproduces). Tier B is agreement with independent ground truth or a comparator.

## Summary

| Workflow | Tested against | Result | Status |
|---|---|---|---|
| Quill (reports) | Run-evidence JSON, 20 drugs + 1 fault injection | 1179/1179 fields match after fix | Pass |
| Scout (ChEMBL ligands) | Independent ChEMBL queries, 10 targets | Target resolution 10/10; ligand lists 10/10 | Pass |
| Nexus (STRING) | Independent STRING calls, 10 proteins + 1 set | N1 to N4 all pass | Pass |
| Fate (RDKit panel, ADMET-AI wrapper) | PubChem properties, published rule definitions | F1 to F4 pass; ADMET-AI accuracy not tested | Pass (scope-limited) |
| Compass (Open Targets) | OLS ontology, second Open Targets query, ChEMBL phase-4 drug targets | C1 9/10; C2 10/10; C3 9/10; C4 3/3 | Pass (C3 partly circular) |
| Flux (metabolism) | ChEMBL curated human metabolism, 66 drugs | Recall 0.41; score AUC 0.815 (CI 0.777 to 0.852) | Pass |
| Flux held-out (5 rules added from development misses) | 130 unseen drugs from non-human or unspecified-species ChEMBL records | Recall 0.342 to 0.442 (gain +0.100, CI +0.069 to +0.134); top-10 0.275 to 0.315; AUC 0.839 to 0.794 | Pass (not a human test) |
| Atlas: Ramachandran | wwPDB validation reports, 23 entries, 8,838 residues | Classes 100% agree; angles 99.69% within 0.2 degrees | Pass |
| Atlas: target identity | UniProt | 10/10 accessions; 10/10 AlphaFold sequences | Pass |
| Atlas: pocket detection | Bound-ligand position, 13 complexes | 5/13 within 4 A (centroid baseline 0/13) | **Fail** (floor 0.5) |
| Atlas: pocket detection, held-out | 40 complexes chosen by a fixed PDB query and seed, unchanged detector | 13/40 = 33% (CI 20 to 48%); centroid baseline 2/40; pocket returned 39/40; docking box contains the ligand centroid 27/40 | **Fail** (floor 0.5); confirms the first result |
| Pose: docking | Native redocking, 11 complexes | 8/11 under 2 A (73%, 95% CI 43 to 90%); repeatable; bookkeeping consistent | Pass |
| Pose: interactions | PLIP 3.0 on crystal poses, 11 complexes | Before fix: H-bond precision 0.68, recall 0.46, Jaccard 0.455. After hydrogen-orientation fix: precision 0.74, recall 0.63, Jaccard 0.51; 10/11 run | I1 **Pass after fix, on the development set** (not independent; held-out re-test pending); I3 fails on 1ATP |
| Orbit (xTB orbitals) | xTB's own output; QM9 DFT, 200 molecules | Transcription 20/20; state handling 8/8; gap r = 0.85 | Pass (large offsets vs DFT) |
| Anchor (gas-phase pose refinement) | Independent RMSD from output PDB; repeat runs; native vs displaced decoy, 8 complexes | 7/8 run; bookkeeping consistent on all that ran; native beats decoy 7/8 and is "Stable" 6/8; repeats not exactly reproducible | **Fail** (A1 to A3 on 3ERT and run-to-run differences); B1 and A4 pass |
| Routing (request router, `dispatch.py`) | 73 hand-labelled chat requests, 12 out-of-scope cases, 6 readiness cases | 48/48 request cases, 0/25 false triggers, 12/12 out-of-scope after fixes | Pass |
| Specialist split and outage (registry, client, resilience) | Dead and fake specialist servers, circuit breaker timing | O1 to O6 all pass after the owner alias; **the remote path is not wired into the app** | Pass (module level); wiring gap open |
| Helix (BLAST) | Independent `blastp` on the same BLAST+ and Swiss-Prot, 10 proteins | Query identity 10/10; hit lists, values and order 10/10; raw-sequence path 3/3; paralogues 6/9 | **Fail** (H3 floor 8/9); H1, H2, H4, H5 pass |

## Defects the validation found, fixed and rechecked

Each fix has a regression test, and the failing baseline run is kept beside the passing one.

| Workflow | Defect | Before | After |
|---|---|---|---|
| Quill | Missing values printed as `None` and `nan` in key-value report tables | 20/21 items | 21/21 |
| Flux | Empty SMILES returned a normal empty result, not an error | X4 2/3 | 3/3 |
| Fate | Ghose filter counted heavy atoms; the original rule counts all atoms including hydrogens | 6 of 20 drugs mislabelled | 0 of 20 |
| Pose docking | Grid centring and native-redock validation used different ligand-exclusion lists, so 1CX2 was silently skipped (heme) and 2RH1 chose cholesterol | 6/11 | 8/11 |
| Orbit | xTB output could not be decoded on Windows (cp1252), so every orbital calculation failed locally | 0/20 | 20/20 |
| Pose interactions | Ligands with unlabelled stereocentres or double bonds failed the export check, so the whole analysis was rejected | 8/11 complexes ran | 10/11 |
| Anchor | Receptors without a terminal oxygen (OXT) at a chain end or beside a chain break could not be parameterised | 1/8 receptors ran | 4/8 |
| Anchor | OpenMM bonds residues across a gap, so a capped residue still failed template matching; a TER record now ends the chain | 4/8 | 7/8 |
| Helix | Hits were left in BLAST's E-value order, and E-values underflow to 0 for strong matches, so the order among them was not by bit score | H2 6/10 | 10/10 |
| Helix | `-max_target_seqs 25` does not guarantee the 25 best hits; a stronger hit was missing for ESR1. Helix now requests 1000 and keeps the top 25 | included in the row above | fixed |
| Helix | An empty query raised an HTTP 400 error from UniProt instead of `ValueError` | H4 3/4 | 4/4 |
| Routing | "run Flux and Orbit on X" lost the second workflow (a name was a cue only directly after "run"); a chain of names after one verb is now recognised in the user's order | 47/48 | 48/48 |
| Routing | "do not dock anything yet" started a docking run; a negation shortly before a cue now cancels it | 1 false trigger in 25 | 0 |
| Routing | Out-of-scope cues matched inside words ("chamber" flagged as molecular dynamics) and "protein synthesis" was flagged as synthesis planning | 10/12 | 12/12 |
| Specialist registry | The router's `analyze` action had no owning specialist (the registry calls it `admet`); an alias fixes it | O1 6/7 | 7/7 |
| Anchor | Hydrogen placement by OpenMM is random (up to 1.9 A between runs); Python and NumPy are now seeded, and the integrator and velocities use a fixed seed | repeat energies differed by 5 to 62 kcal/mol | 0.9 to 25 kcal/mol (not yet exact) |
| Compass | Stale disease-ID in a comment | n/a | corrected |

## Protocol and check errors made and disclosed

These were errors in my protocol or check code, not in MUMO. Each is recorded as a dated addendum in `validation/PROTOCOL.md`, and the original run is kept.

- Quill: added a fault-injection item before the first run (addendum 0.1a).
- Nexus: clarified N3(a) before the first run (addendum 0.2a).
- Pose D3: assumed `consensus` was a number; MUMO returns a text verdict (addendum 0.7a).
- Orbit O2: assumed the all-electron count; xTB uses valence electrons (addendum 0.8a).
- Interactions: crystal-derived stereo tripped MUMO's pose-identity guard; the check now retries once without it and records that (addendum 0.9a).

## Findings to state in the manuscript

**Open failures**
- **Atlas pocket detector** was re-tested on 40 held-out complexes chosen by a fixed rule (protocol v1.4) and finds the ligand site within 4 A in 13 of 40 (33%, CI 20 to 48%), confirming the first result (5 of 13). A development comparison of four cavity rankings and eight detection settings found nothing that adds the required two successes (best +1), so no default was changed; top-3 is 17 of 40. It is clearly better than the protein centroid (2 of 40) and its box contains the ligand centroid in 27 of 40. Treat blind pocket detection as a rough starting point. Original first-run detail: it finds the ligand site within 4 A in 5 of 13 complexes. Four near misses (4 to 9 A) and four complete misses. The docking box still contains the ligand centroid in 9 of 13. It matters only when no co-crystal ligand exists, for example AlphaFold models. P2Rank was not run (Java missing).
- **Pose interactions** reported fewer H-bonds than PLIP (recall 0.46) and no water bridges. The cause was hydroxyl/amino hydrogens placed at arbitrary torsions; orienting them toward nearby acceptors raised recall to 0.63 and precision to 0.74 on the same 11 complexes (a development result, not held-out). Histidine tautomers and the 3.5 A limit are unchanged, and water bridges are still not reported. 1ATP fails cleanly because RDKit adds an extra bond to the Arg165 backbone oxygen.
- **Pose docking** misses 1HSG (11.4 A, flexible indinavir with torsions capped), 1M17 (7.8 A, seed-sensitive erlotinib) and 4DFR (5.9 A).

- **The remote-specialist path is not connected to the app.** A search of `src/` finds no use of `client.call`, `MUMO_SPACE_*` or `registry.referral` outside `services/`; the front door (`mumo_chat.py`) uses only `services.resilience`, the local gate. The client, registry and referral wording behave correctly in isolation (tested against a dead address and a fake server), but the README statement that each specialist can be switched to its own deployed service "purely by an environment variable" does not hold for the front door in this repository. A design decision is needed: wire it in, or change the README. Also not tested: a real crashed container (the original segmentation fault) and the LLM intent parser; the routing labels are one person's judgement on a small set.
- **Helix** returns only 25 hits and has no species filter, so orthologues of the query from other species crowd out its human paralogues: DRD2 misses DRD4, ESR1 misses ESR2, and CDK2 misses CDK1 and CDK5 (paralogues found in 6 of 9 proteins, floor 8). This persists after the truncation fix. A longer list or a species option would address it. The independent check uses the same BLAST+ and database, so it shows the wrapper is faithful, not that BLAST is accurate.
- **Anchor** is a gas-phase refinement with a 2 ps relaxation, not production MD, and the check treats it as such. 3ERT fails because a residue has missing side-chain atoms (needs a missing-atom rebuild; PDBFixer is not installed). 1CX2 (a large multi-chain structure) takes about 21 minutes per run, close to the 25-minute timeout. Repeat runs still differ (minimised energies by 0.9 to 25 kcal/mol, ligand movement by up to 0.04 A) after the seeding fix; the cause was not isolated, since a single-thread test also differed. Verdicts did not change between repeats, so report verdicts, not exact energies.

**Limitations of passing results**
- **Orbit:** GFN2-xTB orbital energies sit on a different scale from DFT. Gaps are 2.07 eV lower on average, HOMO 4.0 eV lower, LUMO 6.1 eV lower than QM9 B3LYP values. The gap tracks DFT (r = 0.85) but its absolute error (2.2 eV) is worse than predicting the mean (1.08 eV), so raw gaps are useful only after calibration.
- **Flux:** all recovered metabolites come from the first step, and multi-step pathways were not evaluated. Rules were missing (sulfone formation, methyl hydroxylation). Five rules were added from the development misses and tested once on 130 unseen drugs from non-human or unspecified-species records (protocol v1.3): held-out recall rose from 0.342 to 0.442 and top-10 recall from 0.275 to 0.315, but score AUC fell from 0.839 to 0.794 (new rule weights are unmeasured, set by analogy) and more drugs reach the 400-metabolite ceiling (9 to 15). The gain on the development set (0.410 to 0.559) was larger than on held-out data and must not be quoted. The held-out set is not human, and nine candidate rules with no development evidence (sulfone formation, acyl glucuronidation and others) were not added. Four large drugs hit the 400-metabolite ceiling in the original run. No comparator was run (SyGMa is GPL and did not build).
- **Compass:** Parkinson disease's top 10 contains no approved-drug target, because the ranking is driven by genetic evidence. The recall test is partly circular because Open Targets uses ChEMBL clinical evidence.
- **Fate:** the TPSA variant (with or without sulfur and phosphorus) was left unchanged; RDKit's default excludes them, PubChem includes them, and the difference reaches 25 square angstroms for chlorpromazine. ADMET-AI accuracy was not tested.
- **Scout:** ties at the potency cutoff mean the completeness check cannot tell which tied molecules should be kept. Scout does not filter on ChEMBL validity flags.
- **Nexus:** the enrichment check only detects passthrough bugs. UniProt dossiers and druggability blocks were not covered.
- **Atlas Ramachandran:** 27 residues differ from the wwPDB angle by more than 0.2 degrees, all at or beside residues with alternate conformers. For Ser64 in 4DFR the wwPDB report gives conformer A the angles of conformer B, and an independent calculation matches MUMO.

## Not validated

Anchor's long solvated MD, binding free energies and GPU use, docking scoring power and screening power, cross-docking, AlphaFold docking, orbital surface rendering, the comparison with Discovery Studio, ADMET-AI accuracy on a held-out benchmark, and the pharmacophore and mass-spec agents (not yet built).

## Recommended follow-ups before submission

1. **Held-out sets** for any improvement made after seeing results. Done for the Flux rules (protocol v1.3). Done for the Atlas pocket detector (protocol v1.4): no improvement was found on the development set, so the unchanged detector was measured on 40 held-out complexes (33%). Still to do: the two Pose entries (1CX2, 2RH1) whose fix followed their failure, and a stronger pocket method if blind pocket finding matters (for example P2Rank, which needs Java).
2. Re-test the H-bond fix on fresh complexes (protocol to be frozen first).
3. Decide whether the remote-specialist path should be wired into the front door or removed from the README. Decide whether to add PDBFixer for Anchor (3ERT), find the source of Anchor's remaining run-to-run differences, and decide whether Helix should return more than 25 hits or offer a species filter.
4. Check the Ghose and TPSA source papers before the paper cites either rule.
5. A fresh-environment rerun of all checks from the tagged commit.

## Reproducing

```
python scripts/run_validation.py <quill|scout|nexus|fate|compass|flux|atlas|pose|orbit|interactions|anchor|helix|routing|fluxheldout|pocketheldout>
```

External files used (hashes are in the manifests and every run record): AutoDock Vina 1.2.5 (Windows build, `bin/vina.exe`), xTB 6.7.1pre (`bin/xtb-6.7.1pre/`), the QM9 table (`validation/data/qm9.csv`), BLAST+ 2.17.0 and a Swiss-Prot BLAST database for Helix (`bin/blast`, database under `E:\mumo-validation-env\blastdb`, built from the UniProt file downloaded 2026-10-30), and a micromamba 2.10.0 conda-forge environment for Anchor (`bin/mdenv`, 5.1 GB, with `openmmforcefields` 0.15.1 added by pip without AmberTools because AmberTools does not exist for Windows). The MD environment and micromamba cache live on `E:\mumo-validation-env\` and are reached through junctions at `bin/mdenv` and `bin/mamba/root`. None of these is committed. The runner uses the operating-system certificate store (`truststore`) because the local antivirus intercepts TLS. PLIP 3.0 needs a stub for one OpenBabel metadata call (InChIKey); interaction results are unaffected.
