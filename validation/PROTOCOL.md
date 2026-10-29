# MUMO validation protocol

**Version 0.1 (draft), 2026-10-29. Covers Quill and Scout only.**
Other workflows are added in later versions, each committed before its first run.

Rule: pass criteria below are fixed before any result is produced. If a criterion turns out to be badly chosen, record that in a new protocol version and report both. Do not edit a criterion to make a run pass. Errors and timeouts count as failures in the denominator.

Scope: these checks measure **integration fidelity** (does MUMO return and report what the source says, correctly). They do not show that MUMO improves any underlying database or tool, or that predictions are experimentally true.

## Quill: report fidelity

**Question.** Does every value in a generated `.docx` report equal the value in the run evidence it was built from?

**Items.** 20 drugs listed in `manifests/quill.json` (fixed SMILES, no name lookup).

**Method.** For each drug:
1. Compute the real Fate drug-likeness record (`agents.admet.druglikeness`) and the real Flux prediction (`agents.metabolism.predict_metabolites`). Both run offline.
2. Build the ADMET report (`report_writer.build_admet_docx`) and the metabolism report (`report_writer.build_metabolism_docx`).
3. Extract every table row from each `.docx`.
4. Compare against the evidence record from `verification.evidence_json`.

Fixture note: ADMET-AI is not installed in the validation environment, so the ADMET-AI section is fed a fixed fixture dictionary and tests rendering only. It says nothing about ADMET-AI accuracy.

**Fields checked.**
- Every public (non-underscore) drug-likeness key and value appears as a table row with an equal value.
- Every metabolite row (SMILES, transformation, phase, score, route) appears with an equal value, in the same rank order.
- The evidence JSON parses and its numeric values equal the values passed to the report.
- A missing or non-finite value renders as unavailable text, never as `None`, `nan` or `0`.

**Pass criterion.** 100% of fields match on 100% of drugs. Rendering is deterministic, so any mismatch is a defect.

## Scout: ChEMBL retrieval fidelity

**Question.** Given a gene symbol, does Scout resolve the correct ChEMBL target and return the true most-potent measured ligands?

**Items.** 10 human targets in `manifests/scout.json`, each with a gene symbol (the query a user would type) and a UniProt accession (ground truth).

**Ground truth.** Independent ChEMBL REST queries made by the check itself, by a different route from Scout: target lookup by UniProt accession, and activity lookup by a pChEMBL threshold instead of Scout's ordered query.

**Check S1, target resolution.** Scout's resolved target must be the human SINGLE PROTEIN target whose component accession equals the manifest UniProt.
- Pass: at least 9 of 10 targets resolve correctly. Failures are reported by name.

**Check S2, ligand list, run on targets that pass S1.** Scout is called with `limit=10, min_pchembl=6.0`. For each target all of the following must hold:
- (a) every returned ligand has a measured pChEMBL value of at least 6.0 on that target in the independent query;
- (b) the list is in descending pChEMBL order;
- (c) the molecules are unique;
- (d) every SMILES parses in RDKit;
- (e) completeness: no molecule with a pChEMBL strictly above the 10th returned value is missing from the list.
- Pass: every S1-passing target satisfies (a)–(e).
- Inconclusive: if the independent pool for (e) exceeds the fetch cap (5000 activities), the target is INCONCLUSIVE. It counts as not passed.

**Recorded, no pass/fail.** ChEMBL release version, request counts, per-target resolved ID, top pChEMBL, any ligand whose independent record carries a data-validity comment. Scout does not filter on assay confidence or validity flags. That is a limitation to state in the paper, not hidden here.

**Known limit.** ChEMBL is a living database. Results are valid for the recorded release only.
