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

---

# Version 0.4 (draft), 2026-10-29. Adds Compass. Earlier criteria are unchanged.

## Compass: disease-to-target fidelity and sanity recall

**Question.** Does `agents.target_finder.find_targets` resolve a typed disease name to the right ontology term, return Open Targets' ranking faithfully, and surface known drug targets near the top?

**Items.** 10 disease names in `manifests/compass.json`, typed as a user would, plus 3 fault-injection inputs.

**What this does and does not show.** The answer key for C3 comes from ChEMBL approved-drug mechanisms. Open Targets itself uses ChEMBL clinical evidence in its scores, so C3 is **partly circular**. It is a sanity floor (does the tool surface known drug targets at all), not a measure of discovery power. To make that visible, the run also records which recovered targets have supporting evidence from datatypes other than `clinical` and `literature`. No claim that Compass finds *new* targets is supported by this check.

**Independent sources.**
- C1: the EBI Ontology Lookup Service (OLS), exact label match on the typed name in EFO and MONDO.
- C2: a second Open Targets query with a different page size, plus `targets(ensemblIds)` entity lookups for symbol and name.
- C3: ChEMBL approved-drug indications and mechanisms.

**Check C1, disease resolution.** The ID Compass resolves must be one of the ontology IDs OLS returns for an exact label match of the typed name.
- Pass: at least 9 of 10 diseases. Failures are listed by name.

**Check C2, ranking fidelity.** For every disease Compass resolved, `find_targets(limit=10)` is compared with the first 10 rows of an independent query (page size 50, same disease ID):
- (a) association scores (rounded to 3 decimals) are equal in order;
- (b) target Ensembl IDs match, tie-aware: within a group of equal scores the ID sets must be equal, except the last group, where Compass's IDs must be a subset of the independent group (page boundaries can cut a tie group);
- (c) for every returned target, approved symbol and approved name equal those from the independent `targets(ensemblIds)` lookup.
- Pass: 100% of resolved diseases satisfy (a)–(c).

**Check C3, sanity recall against known drug targets.** The answer key for a disease is the set of UniProt accessions of targets in ChEMBL mechanisms of drugs with `max_phase_for_ind = 4` for that disease. Disease matching uses the ChEMBL indication whose `mesh_id` is a MeSH cross-reference of the resolved Open Targets disease, or whose `efo_id` equals the resolved ID written with a colon. Compass's top-10 targets are mapped to UniProt (Swiss-Prot) accessions through the independent `targets` lookup. A disease **hits** if at least one key target is in Compass's top 10.
- Applies only to diseases whose key is non-empty. Diseases with an empty key are listed and excluded from the C3 denominator.
- Pass: hit rate of at least 0.7 over diseases with a non-empty key.
- The 0.7 threshold is a methodological choice made before the run. It is a floor, not a published standard.

**Check C4, honest failure.** The unrecognised name, the empty string and the whitespace-only string must each raise `ValueError`.
- Pass: 3 of 3.

**Recorded, no pass/fail.**
- Open Targets API and data versions.
- Key size, recall at 10 and at 25, and which key targets were found, per disease.
- Per recovered target: whether it has evidence from datatypes other than `clinical` and `literature` (a rough view of non-circular support).
- The docstring in `target_finder.py` cites `EFO_0000341` for cystic fibrosis. That ID returns nothing in the current Open Targets platform (the live ID is `MONDO_0009061`). The code resolves IDs by search, so it is not affected, but the comment is out of date.

**Known limits.** Open Targets is a living resource. Results are valid for the recorded data version only. The key counts only exact-term indications and may miss drugs approved for child terms, so recall is conservative.

---

# Version 0.5 (draft), 2026-10-29. Adds Flux. Earlier criteria are unchanged.

## Flux: metabolite prediction against literature-curated metabolism

**Question.** Does `agents.metabolism.predict_metabolites` reproduce known human metabolites, does its score ranking carry signal, and is its output internally sound?

**Independent answer key.** The ChEMBL `metabolism` table: literature-curated drug-to-metabolite records with structures, independent of Flux's rule set (adapted from Ridder and Wagener 2008). No metabolite list is hand-typed.

**Selection rule, frozen.** Keep records with `organism = Homo sapiens`. An *edge* is a record whose `substrate_chembl_id` equals its `drug_chembl_id` (a one-step metabolite of the drug). The items are **every** such drug with at least one edge where both drug and metabolite structures resolve in ChEMBL. Nothing is added or removed by hand. Drugs dropped for a missing structure are listed in the run. The resolved list and raw records are saved in the run folder with a SHA-256.

**Matching.** A predicted metabolite matches a reference metabolite when the first block of their InChIKeys is equal (connectivity only, so stereochemistry and many charge or tautomer differences are ignored). Reference structures are reduced to their largest fragment first. This is a methodological choice and is a limit: a reference metabolite that differs from the prediction in connectivity is a miss.

**Predictions.** `predict_metabolites(smiles, depth=2, min_score=0.01, max_results=40)`, the settings the app uses.

**Check X1, coverage.** Micro-averaged recall: reference edges matched by any of the (up to 40) predictions, divided by all reference edges.
- Pass: micro recall at least 0.25.
- The 0.25 floor is a methodological choice made before the run: "clearly better than nothing". It is not a published standard, and the actual recall is the result worth reporting.

**Check X2, ranking signal.** Over all predicted metabolites pooled across drugs that have at least one hit, the ROC-AUC of Flux's `score` for separating predictions that match a reference from those that do not. Confidence interval: 95% percentile bootstrap resampling drugs (2000 resamples, seed 20261029).
- Pass: lower bound of the interval above 0.5.
- Caveat: a prediction that matches no reference is not proven wrong, because the curated table is incomplete. AUC under these weak negatives is a ranking sanity check, not a precision estimate.

**Check X3, output integrity.** For every item, all of:
- (a) every predicted SMILES parses in RDKit;
- (b) no duplicate SMILES, and the parent is not listed as its own metabolite;
- (c) scores are in (0, 1] and in descending order;
- (d) each metabolite's `generation` equals the length of its `pathway`;
- (e) two repeat runs give identical output.
- Pass: 100% of drugs satisfy (a)–(e).

**Check X4, honest failure.** Three fault inputs (invalid SMILES, empty SMILES, `depth=0`) must each return an error record (a dict with `_error`) and must not raise.
- Pass: 3 of 3.

**Recorded, no pass/fail.**
- Recall at the top 10 (`top_k`) and at all predictions, by drug and pooled; macro (per-drug mean) recall alongside micro.
- Number of predictions per drug, and the share of hits at generation 1 versus 2.
- Which rule produced each hit, and the reference edges missed (so the paper can say which transformations are absent from the rule set).
- Time per drug and any drug where the 400-metabolite ceiling was reached.
- ChEMBL release version.

**Known limits.** Flux has 20 rules, far fewer than published tools, so low recall for cytochrome-driven or less common transformations is expected and is a finding, not a defect. SyGMa (the published comparator) is GPL-3.0 and failed to build in this environment, so no comparator is run in this version. A comparison with SyGMa or BioTransformer is a candidate for a later protocol version.

---

# Version 0.6 (draft), 2026-10-29. Adds Atlas. Earlier criteria are unchanged.

## Atlas: Ramachandran validation, pocket detection and target identity

**Question.** Does Atlas compute backbone torsions and Ramachandran classes that agree with the wwPDB's own validation, does its geometric pocket detector find real ligand sites, and does it fetch the right protein?

Three parts. Entry lists are fixed in `manifests/atlas.json`. Every PDB ID and ligand code was confirmed to exist, and every entry to have a validation report, before this protocol was frozen. That confirmation looked at file availability only, not at Atlas output.

### Part R: Ramachandran against wwPDB validation reports

**Independent source.** The wwPDB validation report XML (`*_validation.xml.gz`) for each entry. It lists, per residue, phi, psi and a Ramachandran class (`Favored`, `Allowed`, `OUTLIER`) computed by the wwPDB's MolProbity-based pipeline. It is independent of MUMO's code and of MUMO's angle routine.

**Items.** 23 X-ray entries, including some with many reported outliers (1TIM, 3HFM) so the outlier path is tested.

**Method.** `ramachandran.compute(pdb_text)` on the PDB file. Residues are matched to report records by chain, residue number, insertion code and residue name. Only report records of model 1 with phi, psi and class present, and alternate-location blank or `A`, are used.

**Check R1, angles.** Fraction of matched residues where phi and psi each differ from the report by at most 0.2 degrees (angles wrapped at 360; the report rounds to 0.1).
- Pass: at least 99.5% of matched residues, pooled.

**Check R2, classes.** Pooled three-class agreement between MUMO's region (`favoured`, `allowed`, `outlier`) and the report class.
- Pass: agreement of at least 0.95.
- The 0.95 floor is a methodological choice made before the run. The wwPDB and MUMO may use different Top8000 reference releases, so exact agreement is not expected. Class cutoffs are the thing under test.

**Recorded, no pass/fail.** Per-entry agreement, the full confusion matrix, outlier precision and recall (wwPDB as truth), residues present in the report but not scored by MUMO and the reverse, and the largest angle differences with their residues.

### Part P: pocket detection against bound-ligand position

**Independent source.** The position of the co-crystallised ligand in the same PDB file.

**Items.** 13 holo complexes with a named ligand code (`manifests/atlas.json`).

**Method.** `target_analyst.detect_pocket` on the **protein ATOM records only** (all chains, first model, no hetero atoms, no waters), with default parameters. The reference point is the mean position of the heavy atoms of the first residue with the ligand code. A distance-to-centre (DCC) is measured from the predicted pocket centre to that point. A `None` result counts as a failure.

**Baseline.** The centroid of the protein atoms, scored the same way. This represents blind docking over the whole protein.

**Check P1.** Success means DCC of at most 4.0 angstrom.
- Pass: success rate of at least 0.5, **and** strictly more successes than the centroid baseline.
- The 0.5 floor is a methodological choice made before the run, a bar for "clearly better than guessing".

**Recorded, no pass/fail.** Every DCC, the baseline distances, predicted box size, whether the ligand centroid lies inside the predicted box, and timing.

**Limits.** Only the top-ranked pocket is returned, so no top-3 figure exists. P2Rank is the natural published comparator (it ships in `bin/`), but it needs Java and none is installed, so it is not run. A later version can add it.

### Part I: target identity and structure fetching

**Independent source.** UniProt accessions and canonical sequences from UniProt itself.

**Items.** 10 gene symbols (same targets as Scout).

**Check I1.** `target_analyst.gene_to_uniprot(gene)` with no cache must equal the manifest UniProt accession.
- Pass: 10 of 10.

**Check I2.** `download_alphafold(accession)` must return a model whose residue sequence equals the UniProt canonical sequence (the sliced range when the model covers a fragment), with every atom coordinate finite and every B-factor (pLDDT) between 0 and 100. A download failure counts as an error.
- Pass: 10 of 10.

**Check I3, honest failure.** Four cases must each fail safely: `gene_to_uniprot` on an unknown symbol raises `ValueError`; `ramachandran.compute` on the empty string, on non-PDB text, and on a structure with fewer than three residues each return an error record and do not raise.
- Pass: 4 of 4.

**Known limits.** wwPDB agreement shows MUMO's torsions and classes match the community standard on these entries. It does not show that a structure is suitable for docking. Pocket detection on 13 chosen complexes shows a rough success rate, not performance on a blind benchmark.

---

# Version 0.7 (draft), 2026-10-29. Adds Pose (docking only). Earlier criteria are unchanged.

## Pose: native redocking, reproducibility and bookkeeping

**Question.** Does MUMO's docking workflow, run end to end as the app runs it, put a known ligand back where the crystal structure has it, give reproducible results, and report its own replica statistics correctly?

**Scope, stated up front.** This version tests **pose reproduction only**. It does **not** test scoring power (whether scores track experimental affinity), screening power, cross-docking, AlphaFold or apo targets, or the ProLIF interaction analysis. Interaction analysis (ProLIF against PLIP on crystal complexes) is left for a separate protocol version. Docking scores must not be described in the manuscript as validated predictors of affinity on the strength of this check.

**Software.** AutoDock Vina 1.2.5, the official Windows build downloaded from the AutoDock-Vina GitHub release (1,203,712 bytes, SHA-256 in `manifests/pose.json`, recorded again in every run). The check refuses to run if the binary's hash or version differs.

**Items and selection rule, frozen.** The 13 holo complexes already used for pocket detection in Atlas, minus two excluded by a mechanical rule: ligands with more than 50 heavy atoms (1AKE) and ligands covalently bound to the protein (6LU7). That leaves 11 complexes. Membership does not depend on any docking result.

**Method.** For each complex, the steps the app runs:
1. `clean_protein_pdb`, then `prepare_receptor` (Meeko).
2. `auto_grid_from_pdb` for the box.
3. `validate_native_redock` with exhaustiveness 16, seed 42, 3 replicas (best replica by score).
`validate_native_redock` picks its own ligand (the largest eligible hetero group), docks it from a SMILES taken from the RCSB chemical component dictionary, and returns heavy-atom RMSD to the crystal ligand with no alignment.

**Check D1, redocking success.** A complex is a success when the returned RMSD is below 2.0 angstrom **and** the ligand MUMO selected equals the expected ligand code. A `None` result (skipped), an exception, or a different ligand counts as a failure. All 11 stay in the denominator.
- Pass: success rate of at least 0.5.
- The 0.5 floor is a methodological choice made before the run. Published Vina redocking rates on curated sets are higher, but this is a small mixed set and the floor is a bar for "clearly better than failing". The Wilson 95% interval is reported with the rate.

**Check D2, reproducibility.** For the subset `3PTB, 1STP, 4DFR`, the full native redock is run a second time with identical inputs and settings.
- Pass: the RMSD is identical to two decimals in all 3.

**Check D3, replica bookkeeping.** For the same three complexes, `dock_with_replicas` is run on the prepared native ligand (3 replicas). Its report must satisfy all of:
- `best_score` equals the minimum of `all_best`;
- `sd` equals the population standard deviation of `all_best` to three decimals, and `mean` equals the arithmetic mean;
- `confidence` follows the rule stated in the code (High if sd at most 0.5, Medium if at most 1.0, otherwise Lower);
- `modes` are in non-decreasing score order and the first equals `best_score`;
- `vinardo` and `consensus` are finite numbers.
- Pass: all five hold for 3 of 3.

**Check D4, honest failure.** Three cases:
- (a) `validate_native_redock` on a structure with no ligand (1UBQ) returns `None`;
- (b) `prepare_ligand` on `not a smiles` raises `ValueError`;
- (c) `run_docking` with a ligand file that does not exist raises an exception and does not return a log path.
- Pass: 3 of 3.

**Recorded, no pass/fail.** Per-complex RMSD, ligand chosen versus expected, best score, replica spread, wall time, Vina version and binary hash. The difference between Vina's own `--score_only` of the returned pose and the reported best score. Which complexes failed and by which route (wrong ligand, skipped, RMSD above 2 angstrom).

**Known limits.** Eleven complexes give a wide interval and no claim about performance across target classes. Native redocking is the easiest docking task (the pocket and ligand are known). The ligand-selection rule inside `validate_native_redock` and the receptor box come from MUMO and are part of what is tested. Rotatable-bond capping (`max_rot=10`) changes flexible ligands such as indinavir, so a failure may reflect that preparation choice.

**Addendum 0.7a (written after the first Pose run, disclosed as such).** The first Pose run failed D3 on all 3 complexes. The cause was an error in the protocol and check, not in MUMO: the D3 text and code assumed `consensus` is a finite number, but in MUMO it is a text verdict (`Both functions agree` or `Functions disagree — interpret with care`). The other four D3 sub-checks passed on all 3 complexes. D3's last bullet is therefore amended to: `vinardo` is a finite number and `consensus` is one of those two labels (not an `unavailable (...)` message). The original run is kept as recorded. The descriptive `--score_only` comparison also failed to parse Vina's output because the check passed a box; it now uses `--autobox` as MUMO does.

---

# Version 0.8 (draft), 2026-10-29. Adds Orbit. Earlier criteria are unchanged.

## Orbit: GFN2-xTB orbital energies

**Question.** Does `agents.qm_analyst.orbitals` report what xTB computed, handle charge and spin correctly, fail safely, and give orbital energies that track DFT?

**Software.** xTB 6.7.1pre, the official Windows build from the `grimme-lab/xtb` GitHub release (zip SHA-256 `043e578d…d28d9c`, matching the published checksum; executable hash in `manifests/orbit.json`). The check refuses to run if the executable hash differs. MUMO is pointed at it through its own `MUMO_XTB` setting.

**Scope, stated up front.** This tests orbital **energies**, charge and spin handling, and the exported Molden file. It does **not** test orbital surface rendering (`orbital_figures`, `orbital_worker`), excitation energies, or any property other than HOMO, LUMO, gap and the recorded total energy. GFN2-xTB is a semiempirical method. The DFT comparison measures how far its orbital energies sit from B3LYP, which is a known and expected deviation, not a software defect.

**Part O, fidelity to xTB (20 drugs, same SMILES as Quill).** For each drug MUMO's `orbitals(smiles)` is run. The check then runs xTB itself on the XYZ geometry MUMO recorded in its evidence (same settings: `--gfn 2 --sp --chrg --uhf`, plus `--molden`), in a separate folder, and reads orbital energies and occupations from the **Molden file**, which is a different output channel from the stdout text MUMO parses.

- **O1.** MUMO's `homo_eh`, `lumo_eh` equal the Molden values (highest occupied and lowest empty orbital) to within 1e-4 Eh, and `gap_ev` equals (LUMO − HOMO) in eV to within 1e-3 eV. Pass: 20 of 20.
- **O2.** `homo_index` equals the number of occupied orbitals (electron count divided by two for closed shells), `lumo_index` equals `homo_index + 1`, and MUMO's captured Molden export reports the same occupied-orbital count. Pass: 20 of 20.
- **O3.** Two MUMO runs on the same SMILES give identical HOMO, LUMO and gap. Pass: 20 of 20.

**Part Q, electronic state and failure handling (8 cases in `manifests/orbit.json`).**
1. An open-shell radical without a stated spin returns an error record.
2. The same radical with `unpaired_electrons=1` returns a verified result with finite values.
3. An anion (acetate) returns a verified result, and xTB's own output reports net charge −1.
4. A disconnected salt returns an error record.
5. An invalid SMILES returns an error record.
6. An empty string returns an error record.
7. A requested charge that disagrees with the structure returns an error record.
8. With `MUMO_XTB` pointing at a nonexistent file, `orbitals` returns an error record and does not raise.
- **Q1 (criterion).** Pass: 8 of 8 behave as listed. An error record means a dict with `_error`; nothing may raise.

**Part G, agreement with DFT (QM9).** A fixed random sample of 200 molecules from the QM9 table (seeded, seed in the manifest; file hash in the manifest) is run through `orbitals(smiles)` with a 90-second timeout. QM9 gives B3LYP/6-31G(2df,p) HOMO, LUMO and gap in Hartree (converted at 27.211386 eV per Hartree). MUMO uses its own RDKit MMFF geometry, not QM9's DFT geometry, so part of the difference is geometry.
- A molecule MUMO cannot compute (error record, timeout, unsupported structure) counts against coverage and is listed. Error statistics use only molecules that were computed.
- **G1 (criterion).** Pass: coverage of at least 0.9 **and** Pearson correlation of the gap of at least 0.6 between MUMO and QM9 over the computed molecules.
- Both thresholds are methodological choices fixed before the run: a floor for "tracks DFT at all" and "computes almost everything". They are not published standards.

**Recorded, no pass/fail.** For HOMO, LUMO and gap: mean absolute error, root-mean-square error, mean signed error (bias) and Spearman correlation against QM9, plus the error of a mean-only predictor for the gap as a reference. Total-energy and dipole values, xTB wall time, the molecules that failed and why, and xTB and file hashes.

**Known limits.** Agreement with xTB's own output shows MUMO transcribes it correctly; it says nothing about whether GFN2 is accurate. Agreement with B3LYP on small QM9 molecules does not carry over to large drug-like or charged systems, and Kohn-Sham orbital energies are themselves only approximate. A systematic offset between GFN2 and DFT gaps is expected, so the paper should quote bias along with error.
