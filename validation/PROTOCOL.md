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

**Addendum 0.1a (written before the first run).** The field "a missing or non-finite value renders as unavailable text" cannot be tested on real drugs, because none of them yields a missing value. One fault-injection item is added: a drug-likeness record with one `None` value and one `NaN` value (see `injection` in `manifests/quill.json`), run through the ADMET report. It is reported as a 21st item, labelled `injection`, and counts toward the 100% criterion.

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

---

# Version 0.2 (draft), 2026-10-29. Adds Nexus. Quill and Scout criteria above are unchanged.

## Nexus: STRING retrieval fidelity

**Question.** Does `agents.string_analyst.analyze_string` return what STRING itself returns for the same proteins, and does it fail honestly on bad input?

**Items.** 10 single human proteins and 1 three-protein set in `manifests/nexus.json`, each with a gene symbol (the query a user would type) and a UniProt accession. Plus 2 fault-injection inputs (an unrecognised symbol and an empty string).

**Ground truth.** Independent STRING REST calls made by the check, by a different route from Nexus: POST requests, identifiers given as STRING IDs, and resolution through the UniProt accession instead of the gene symbol.

**Check N1, identifier resolution.** The STRING ID that Nexus resolves from the gene symbol must equal the STRING ID resolved independently from the UniProt accession, for every protein in the item.
- Pass: 100% of items.

**Check N2, partner fidelity.** Nexus is called with `limit=20`. Its partner list must equal an independent `interaction_partners` call with the same limit: same partner STRING IDs in the same order, and the combined score and every per-channel score equal to within 1e-9.
- Pass: 100% of items.

**Check N3, result integrity.** For every item:
- (a) every combined score is in [0, 1] and no partner equals a query protein;
- (b) the returned partner count equals the independent count;
- (c) Nexus's enrichment list equals an independent `enrichment` call on the same protein set (same terms, categories and false-discovery rates);
- (d) the network SVG parses as XML and is non-empty.
- Pass: 100% of items satisfy (a)–(d).

**Check N4, honest failure.** The unrecognised symbol and the empty string must each raise `ValueError`, not return a result and not raise any other exception type.
- Pass: 2 of 2.

**Recorded, no pass/fail.**
- STRING data version and request counts.
- Whether partners come back in descending score order.
- Consistency of each combined score with its channel scores under STRING's published prior-corrected combination rule (prior 0.041). The rule is applied from memory of the STRING documentation, so a mismatch is ambiguous between a wrong formula and a data issue. It is therefore reported as a diagnostic, not a criterion. A later protocol version may promote it once the rule is confirmed against the documentation.

**Known limits.** This shows fidelity to STRING, not that STRING's scores are biologically correct. UniProt dossiers and ChEMBL druggability blocks that `string_deep` adds are not covered by this check.

**Addendum 0.2a (written before the first Nexus run).** Check N3(a) says "no partner equals a query protein". For the three-protein set, STRING can legitimately return one query protein as a partner of another (for example ERBB2 as a partner of EGFR). The intended test is self-interaction, so N3(a) is read as: every combined score is in [0, 1] and no record pairs a protein with itself (STRING ID A not equal to STRING ID B).

---

# Version 0.3 (draft), 2026-10-29. Adds Fate. Earlier criteria are unchanged.

## Fate: drug-likeness panel fidelity

**Question.** Does the RDKit drug-likeness panel (`agents.admet.druglikeness`) report correct descriptors, apply the published rules correctly, and behave deterministically? Does the ADMET-AI wrapper (`agents.admet.admet_ml`) map, range-check and fail safely?

**Scope limit, stated up front.** ADMET-AI is not installed in the validation environment. This version therefore does **not** test ADMET-AI prediction accuracy. F3 tests only MUMO's wrapper logic, using a stub model that returns chosen values. Model accuracy needs a separate protocol item, a local install, and a held-out benchmark. Until then the paper should cite ADMET-AI's published performance and claim only that MUMO runs and presents it faithfully.

**Items.** The same 20 drugs as Quill (`manifests/fate.json`), plus 6 wrapper cases for F3.

**Check F1, descriptors against an independent source.** For each drug, MUMO's descriptors are compared with PubChem's computed properties, fetched by SMILES with POST requests (`MolecularWeight`, `HeavyAtomCount`, plus the descriptive properties below). PubChem uses a different toolkit, so agreement is not circular.
- Hard criteria: MUMO molecular weight within 0.1 Da of PubChem's (this covers MUMO's one-decimal rounding and atomic-weight table differences), and heavy-atom count exactly equal.
- Pass: 100% of drugs on both. A failed PubChem lookup counts as an error, not a pass.

**Check F2, rule consistency with published definitions.** Using only MUMO's own reported descriptor values, rule outcomes are recomputed from the original definitions:
- Lipinski rule of five (Lipinski 1997): violations counted for MW > 500, LogP > 5, H-bond donors > 5, H-bond acceptors > 10. MUMO's label must be `Pass` exactly when the count is 0, otherwise `<n> violation(s)` with the right n.
- Veber (Veber 2002): rotatable bonds ≤ 10 and TPSA ≤ 140.
- Egan (Egan 2000): TPSA ≤ 131.6 and LogP ≤ 5.88.
- Verdict string: consistent with the violation count (0, 1, or more).
- Pass: 100% of drugs on all four.

**Check F3, wrapper behaviour with a stub model.** Six cases for `admet_ml`:
1. All endpoints valid: status `verified`, every endpoint present, probabilities rounded to 3 decimals, regression values to 2.
2. A probability of 1.7: that endpoint is marked failed and absent from the output, overall status `partial`.
3. A NaN value: that endpoint failed, never printed as a number.
4. A missing model column: that endpoint marked `missing`, status `partial`.
5. Invalid SMILES: returns an error record, raises nothing.
6. Model raises an exception: returns an `unavailable` error record, raises nothing.
- Pass: 6 of 6.

**Check F4, determinism.** `druglikeness` is run 3 times per drug; every output must be identical.
- Pass: 20 of 20 drugs.

**Recorded, no pass/fail.**
- PubChem agreement for TPSA, H-bond donors, H-bond acceptors, rotatable bonds and LogP (MUMO's Crippen LogP against PubChem's XLogP), as mean and maximum absolute difference and exact-agreement rate. The toolkits define these differently, so differences are expected and are not defects by themselves.
- Ghose filter. MUMO tests the atom count 20–70 on **heavy atoms**. As I understand Ghose et al. 1999, the criterion counts **all atoms including hydrogens**. This is an unverified recollection, so the discrepancy is reported (drugs where the two readings give different outcomes) and not made a criterion. Check the paper before the manuscript states anything about the Ghose rule.
- Lead-like rule (MUMO: MW ≤ 350 and LogP ≤ 3.5, no lower bound). Lead-like definitions vary between papers; recorded only.
- GI-absorption and BBB labels follow BOILED-Egg-style thresholds but use Crippen LogP rather than WLOGP, so they are heuristics. Recorded only.

**Known limits.** Agreement with PubChem shows the descriptors are computed correctly. It does not show the rule-based absorption labels predict real absorption.
