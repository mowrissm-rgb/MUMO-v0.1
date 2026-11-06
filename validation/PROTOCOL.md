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

**Addendum 0.8a (written after the first successful Orbit run, disclosed as such).** The post-fix run failed O2 on all 20 drugs. The cause was an error in the protocol and check, not in MUMO: O2 assumed the HOMO index equals the all-electron count divided by two (aspirin: 47). GFN2-xTB is a valence-electron method, so xTB's HOMO index is the valence-electron count divided by two (aspirin: 34), and MUMO reports 34. In all 20 runs MUMO's `homo_index` equalled the occupied-orbital count in both xTB's own Molden file and MUMO's captured copy. O2 is amended to compare `homo_index` with the **valence** electron count divided by two (computed with RDKit from group valence electrons, minus formal charge), with the Molden occupied count, and with the occupied count in MUMO's captured Molden export. O1, O3, Q1 and G1 are unchanged and passed. The first run is kept as recorded.

---

# Version 0.9 (draft), 2026-10-30. Adds Pose interactions. Earlier criteria are unchanged.

## Interactions: ProLIF contacts against PLIP on crystal complexes

**Question.** For a known ligand pose, does MUMO's ProLIF-based interaction analysis find the same contacting residues as PLIP, and is its record keeping internally correct?

**Scope, stated up front.** This tests **agreement with PLIP on crystal poses**. PLIP is a widely used reference tool but it is not ground truth, and ProLIF and PLIP use different geometric definitions (notably for hydrophobic contacts). It does **not** test docked poses, whether contacts are experimentally real, water bridges (MUMO does not report them), or the 2D and 3D rendering. This version also does not repeat the comparison with Discovery Studio noted in `SCIENTIFIC_VERIFICATION.md`.

**Comparator.** PLIP 3.0.0, run on the original PDB file (all chains, hydrogens added by PLIP's OpenBabel). PLIP 3.0 asks OpenBabel for an InChIKey that this OpenBabel build cannot produce, so the check replaces only that metadata call with an empty string. No interaction code is touched. PLIP is GPL-2.0 and is used here only to validate, not shipped with MUMO.

**Items.** The 11 holo complexes used for Pose docking (`manifests/interactions.json`).

**Method.** For each complex:
1. `clean_protein_pdb` as the app does.
2. The crystal ligand (first residue with the expected code) is given bond orders from the RCSB SMILES protonated at pH 7.4 (the state MUMO's own ligand preparation uses), hydrogens added with RDKit, and written to PDBQT with Meeko, keeping the crystal coordinates.
3. `analyze_interactions(cleaned, pdbqt, out_complex, ligand_smiles)` gives MUMO's contacts.
4. PLIP gives its contacts for the same ligand residue.
Contacts are compared at residue level, per interaction type: H-bond, hydrophobic, pi-stacking, salt bridge, halogen, pi-cation. A residue is identified by residue number and chain.

**Check I1, agreement with PLIP (pooled over complexes).**
- H-bond residues, with PLIP as reference: precision of at least 0.6 **and** recall of at least 0.6.
- Residues with any contact type, Jaccard similarity of at least 0.4. The floor is lower than for H-bonds because the two tools define hydrophobic contacts very differently.
- All thresholds are methodological choices fixed before the run. They are floors for "broadly agrees", not published standards. A complex whose preparation or analysis fails counts as an error and its PLIP contacts still enter the denominators.

**Check I2, distance bookkeeping.** For every MUMO hydrophobic record (one ligand atom and one protein atom), the recorded distance equals the Euclidean distance between its two recorded points to within 0.01 angstrom and does not exceed 4.5 angstrom plus that tolerance.
- Pass: 100% of such records, with at least one record present.

**Check I3, count consistency.** For every complex, `total_interactions` equals the number of records, each per-type count equals the number of records of that type, and the residue lists equal the unique residue tags of their records.
- Pass: 100% of complexes.

**Check I4, honest failure.** Two cases: a ligand file that does not exist, and a ligand SMILES that does not match the pose (ethanol against benzamidine). Each must return status `failed` with null counts (`total_interactions` is `None`, never 0) and must not raise.
- Pass: 2 of 2.

**Recorded, no pass/fail.** Per-type precision and recall, per-complex contact counts for both tools, contacts PLIP finds that MUMO misses and the reverse, PLIP water bridges (which MUMO does not report), rejected-record counts, and runtimes.

**Known limits.** Eleven complexes, mostly kinases, proteases and nucleotide-binding sites, show broad agreement only. Crystal ligands are easier than docked poses (exact geometry). Protonation and hydrogen placement differ between tools, so some H-bond disagreement is expected from preparation, not from detection rules.

**Addendum 0.9a (written after the first Interactions run, disclosed as such).** In the first run, three complexes (3ERT, 1HCK, 1ATP) returned an error: MUMO's pose-identity guard (`pose_matches_ligand`) rejected the crystal-derived ligand. The deposited SMILES of these ligands carry stereo labels (a double bond in 4-hydroxytamoxifen, phosphorus centres in ATP), and the stereo perceived from the crystal coordinates did not equal them. The guard exists to stop a docked pose being analysed under the wrong ligand name, which is not what this check tests, and for docked poses the stereo comes from the same SMILES. The check is therefore amended: when the analysis fails **only** with the identity message, it is repeated once with `ligand_smiles=None`, and the item records `identity_guard_bypassed`. Thresholds and criteria are unchanged. The first run is kept as recorded. The first run's I1 recall was depressed because the three failed complexes still contributed their PLIP contacts to the denominator, as the protocol specified.

---

# Version 1.0 (draft), 2026-10-30. Adds Anchor. Earlier criteria are unchanged.

## Anchor: gas-phase pose refinement and short relaxation

**Question.** Does Anchor (`agents.md_analyst`, run through MUMO's isolated runner) report its own energies and ligand movement consistently, behave reproducibly where it should, fail safely, and tell a crystal pose from a deliberately wrong one?

**What Anchor is.** MUMO describes it as a fast gas-phase pose refinement: energy minimisation of the complex, then about 2 ps of dynamics at 300 K with the protein backbone restrained, using Amber14 for the protein and OpenFF Sage for the ligand with Gasteiger charges. It is explicitly **not** production MD. This protocol tests it as what it claims to be.

**Scope, stated up front.** Not tested: long solvated MD, binding free energies, MM-GBSA, GPU execution, convergence, or whether a "stable" verdict predicts experimental binding. A pass shows internal consistency and a basic ability to flag a displaced pose, nothing about binding.

**Software.** OpenMM, OpenFF toolkit and openmmforcefields from conda-forge in an isolated environment under `bin/mdenv/`, created with micromamba 2.10.0 (binary hash in `manifests/anchor.json`). The package list and versions are recorded in every run. The check runs MUMO's own isolated path (`run_stability_md_isolated`) with `MUMO_MD_PYTHON` pointing at that environment.

**Items and selection rule, frozen.** From the 11 Pose complexes, those whose ligand has a net charge between -1 and +1 at pH 7.4 and at most 50 heavy atoms (a gas-phase refinement of a multiply charged ligand is not meaningful). That leaves 8: 1HSG, 1M17, 3ERT, 1STP, 2OJG, 1CX2, 3PTB, 2RH1. Excluded by the rule: 4DFR (charge -2), 1HCK and 1ATP (charge -3).

**Inputs.** As in the Interactions check: the cleaned receptor, and the crystal ligand with bond orders from the RCSB SMILES protonated at pH 7.4 and hydrogens added with RDKit, keeping crystal coordinates. Receptor waters are removed by Anchor itself.

**Decoy pose.** Each native ligand is also run after a fixed rigid move: rotation by 180 degrees about the axis (1, 2, 3) through its centroid, then translation of 3.0 angstrom along that axis. The move does not depend on any result.

**Check A1, movement bookkeeping (native runs).** From the refined complex PDB, the ligand atoms are the last N atoms (N = ligand atom count; element order must match). The RMSD between the input ligand coordinates and these final coordinates is computed independently. Anchor reports two movements: input to minimised (`lig_rmsd_min`) and minimised to relaxed (`lig_rmsd_relax`). By the triangle inequality the independent input-to-final RMSD must lie between |min - relax| and min + relax, each side within 0.02 angstrom (PDB coordinates are rounded).
- Pass: 100% of native runs, with the ligand-atom element order matching.

**Check A2, report consistency (all native and decoy runs).** `energy_drop` equals `energy_initial - energy_minimized` to 0.2 kcal/mol; `energy_drop` is not negative; `relax_ps` equals the requested value; the verdict matches the code's stated thresholds applied to `lig_rmsd_relax` (below 1.5 A "Stable", below 3.0 A "Mostly stable", otherwise "Unstable").
- Pass: 100% of runs.

**Check A3, repeatability.** For `3PTB`, `1STP` and `2OJG`, the native run is repeated. The deterministic quantities `energy_initial`, `energy_minimized` and `lig_rmsd_min` must be identical to 0.1 kcal/mol and 0.01 angstrom. The relaxation uses random velocities with no seed, so `lig_rmsd_relax` is expected to vary; its spread is recorded, not judged.
- Pass: 3 of 3.

**Check A4, honest failure.** Three cases must return an error record (a dict with `_error`) and not raise: a receptor path that does not exist; a ligand molecule with no 3D conformer; and `MUMO_MD_PYTHON` pointing at a missing interpreter.
- Pass: 3 of 3.

**Check B1, native versus displaced pose.** Over the 8 complexes:
- (i) the native run has a smaller `energy_drop` than its decoy in at least 75% of complexes (6 of 8);
- (ii) the native run's verdict is "Stable" in at least 50% of complexes (4 of 8).
- Both thresholds are methodological choices fixed before the run. They are floors for "does something sensible", not published standards. A decoy that lands in empty space might relax with little energy change, which is part of what this tests.

**Recorded, no pass/fail.** Per-complex energies, RMSDs, verdicts and runtimes for native and decoy; the spread of `lig_rmsd_relax` across repeats; package versions; any run that errored (errors count as failures in every denominator).

**Known limits.** Gas-phase minimisation with unoptimised hydrogens produces large energy drops for any pose, so the energy comparison rewards relative, not absolute, differences. Eight complexes and one fixed decoy per complex give a coarse picture. The 2 ps relaxation is far too short to say anything about binding stability, and MUMO's report says so.

---

# Version 1.1 (draft), 2026-10-30. Adds Helix. Earlier criteria are unchanged.

## Helix: BLAST sequence search

**Question.** Does `agents.blast_analyst.analyze_blast` fetch the right sequence, return the true best BLAST hits with the right numbers, handle a raw sequence the same way as a gene name, find known paralogues, and fail honestly?

**Software and data.** NCBI BLAST+ 2.17.0 (official Windows build, archive MD5 matching NCBI's published value) and a BLAST protein database built with `makeblastdb -parse_seqids` from UniProt Swiss-Prot downloaded on 2026-10-30 (575,748 sequences; file hash in `manifests/helix.json`). This follows MUMO's own container build. MUMO is pointed at the database with its `MUMO_BLAST_DB` setting and at BLAST+ through `PATH`.

**Scope, stated up front.** The independent comparison uses the **same BLAST+ and the same database**, so it tests MUMO's wrapper (sequence fetching, command options, parsing, ranking), **not** BLAST's accuracy. Not tested: other databases or programs, phylogeny and alignment views, NCBI web BLAST, runtime scaling.

**Items.** 10 human proteins by gene symbol (`manifests/helix.json`, accessions confirmed against UniProt before this freeze), plus 4 fault inputs.

**Independent reference.** For each protein, the check fetches the canonical sequence from UniProt by accession and runs `blastp` itself with a large hit limit (`-max_target_seqs 5000`, `-evalue 10`), then keeps the best-scoring alignment per subject and sorts by bit score. This avoids relying on `-max_target_seqs 25`, which in BLAST can return a truncated, not-best-first set.

**Check H1, query identity.** The accession Helix reports for the gene symbol equals the manifest UniProt accession, and its sequence length equals the length of the canonical UniProt sequence.
- Pass: 10 of 10.

**Check H2, hit fidelity.** For each protein, with Helix's default of 25 hits:
- (a) completeness: every subject whose bit score is strictly above the 25th independent bit score appears in Helix's list (ties at the cutoff may differ);
- (b) values: for subjects present in both, bit score within 0.1, percent identity within 0.1, and E-value within 1% (relative);
- (c) order: Helix's bit scores are non-increasing.
- Pass: 10 of 10 proteins satisfy (a)–(c).

**Check H3, paralogue retrieval.** Known human paralogues (listed per protein in the manifest, accessions verified against UniProt) must all appear in Helix's 25 hits. CFTR has no listed paralogue and is excluded from this check's denominator.
- Pass: at least 8 of the 9 proteins with paralogues. The floor is a methodological choice made before the run. This is a sanity check on BLAST's biology as delivered through Helix.

**Check H4, honest failure.** Four inputs must not return hits: an unknown gene symbol, an empty string and a 20-residue peptide must each raise `ValueError`; and with `blastp` unreachable (empty `PATH`) the call must raise an exception of any type.
- Pass: 4 of 4.

**Check H5, raw-sequence path.** For CDK2, ESR1 and ACHE, passing the canonical sequence as the query must give the same 25 accessions in the same order as passing the gene symbol.
- Pass: 3 of 3.

**Recorded, no pass/fail.** Hit counts, the self-hit identity and E-value, how many independent hits were missed or reordered, error messages for the fault inputs, runtimes, and the BLAST+ and database hashes.

**Known limits.** Ten proteins, and only human queries. The wrapper tests cannot reveal an error in the Swiss-Prot data itself.

---

# Version 1.2 (draft), 2026-10-30. Adds routing and specialist-outage tests. Earlier criteria are unchanged.

## Routing and outage: the dispatch layer and the specialist split

**Questions.** Does MUMO's deterministic request router pick the right workflow, stay quiet on questions, and flag out-of-scope requests? When a specialist service is down, does MUMO say so, keep serving the rest, and recover?

**Scope, stated up front.** This tests the deterministic code: `dispatch.py`, `services/registry.py`, `services/client.py`, `services/resilience.py` and `agent_catalog.py`. It does **not** test the LLM intent parser (`brain.parse_intent` with a model), the Streamlit chat interface, or message wording beyond the points below. Scout, Compass, Anchor and Quill are not routed by `dispatch.py` (they run inside the docking workflow or through report controls), so routing accuracy covers the seven routed actions: dock (Pose), analyze (Fate), qm (Orbit), metabolism (Flux), ramachandran (Atlas), string (Nexus) and blast (Helix).

**Labelled data.** `manifests/routing.json` holds 73 chat requests written by hand before any run, with the expected ordered list of actions. They are 35 plain requests (5 per action), 7 explicit invocations by workflow name, 6 multi-step requests, 14 questions, and 11 "trap" messages that use cue words without asking for anything (for example "the alpha helix near the active site is flexible", "do not dock anything yet"). The labels are my judgement of what a user means. The set is small and mine, not an independent benchmark.

### Part R: routing

**Check R1, request accuracy.** For the 48 request cases (plain, explicit, multi-step), `requested_actions(text)` must equal the expected ordered list exactly.
- Pass: at least 85% exact matches (41 of 48).

**Check R2, no false triggers.** For the 25 non-request cases (questions and traps), `requested_actions(text)` must return an empty list.
- Pass: false-trigger rate of at most 10% (at most 2 of 25).

**Check R3, multi-step order.** For the 6 multi-step requests the order of actions must match.
- Pass: at least 5 of 6.

**Check R4, readiness.** For 6 cases, `is_ready(action, convo)` must match the expected value (an action is ready only when its required slots are present).
- Pass: 6 of 6.

**Check R5, out-of-scope detection.** For 12 requests, `unsupported_request(text)` must be non-empty exactly for the 6 labelled out-of-scope ones (molecular dynamics, MM-GBSA, DFT, synthesis planning, clinical trials) and empty for the 6 in-scope ones. Two in-scope cases are deliberate traps: "dock aspirin into the chamber of the enzyme" (contains the substring "amber") and "blast the protein synthesis elongation factor EEF2" (contains "synthesi").
- Pass: at least 11 of 12.

All thresholds are methodological choices fixed before the run, floors for "mostly right", not published standards.

### Part O: specialist outage

All of these run in-process. Specialist services are made "remote" by setting their endpoint variables, to a dead local address (`http://127.0.0.1:9`) or to a small fake specialist server started by the check.

**Check O1, registry integrity.** Every routed action has an owning specialist, and `agent_for(action)` returns the documented workflow name for all 7 (Pose, Fate, Orbit, Flux, Atlas, Nexus, Helix).
- Pass: 7 of 7.

**Check O2, all up.** With no remote endpoints set and the xTB and MD paths provided, `client.call(capability, {})` returns `None` (meaning "run it here") for every capability in the registry (13).
- Pass: 13 of 13.

**Check O3, one specialist down.** With specialist A (Pose, which owns dock, ramachandran, md, structure) pointed at a dead address: each of its capabilities that has a resilience requirement raises `SpecialistUnavailable`; every capability owned by B, C and D still returns `None` (served locally); and `registry.unavailable('dock')` names the Pose service and the capability and states that no result is available.
- Pass: all three parts hold.

**Check O4, referral.** For every (capability, current specialist) pair, `referral(...)` is empty when the current specialist owns the capability and otherwise names the workflow from `agent_for` and offers to run it anyway ("I can still run this").
- Pass: 100% of pairs.

**Check O5, circuit breaker.** On the local capability `string`, with the breaker cooldown shortened to 0.3 s for the test: one failure does not open the breaker; two in a row do (`available` becomes false and `message` says the service is temporarily unavailable); a different capability (`blast`) stays available; after the cooldown the capability is available again; and a success clears recorded failures.
- Pass: all five parts hold.

**Check O6, remote specialist behaviour.** Against a fake specialist for `string`: a healthy server returns decoded JSON; an HTTP 500 raises `SpecialistUnavailable` mentioning `HTTP 500`; a 200 response with a non-JSON body raises `SpecialistUnavailable`; with the server stopped, the call raises `SpecialistUnavailable` and `health` reports down; and when a server is running again, `health` (forced) reports up and the call succeeds.
- Pass: 5 of 5.

**Recorded, no pass/fail.** Which routing cases failed and what they returned (a confusion table by category), the false triggers by message, runtimes, and the wording of the unavailable and referral messages.

**Known limits.** The labelled set is small and written by one person. The outage tests simulate failure with unreachable addresses and a fake server, not a real crashed Pose container (the original failure, a segmentation fault, is not reproduced). The message wording is checked only for the named points. The registry docstring says the unavailable message "always says what is still available"; the code does not say so, and this check does not require it. The README promise that MUMO "keeps serving everything else" is tested by O3.

---

# Version 1.3 (draft), 2026-10-30. Flux held-out re-test of rules added after seeing failures. Earlier criteria are unchanged.

## Flux held-out: do rules added from development misses generalise?

**Why.** After the first Flux run (protocol v0.5) five new rules were added to `agents.metabolism` because they recover development misses. Re-testing them on the same data would only show the data they were fitted to. This protocol tests them once on drugs that were never examined.

**Development data (seen, used to choose the rules).** The 66 drugs with one-step *human* records from the v0.5 run (`validation/runs/flux/20261029T101227Z/reference_snapshot.json`). The five rules were chosen by testing candidate rules against the misses on this set only. Rule inclusion criterion, fixed before looking at held-out data: a candidate rule is added only if it recovers **at least two** development misses. Candidates that recovered one or none (N-deethylation, desaturation, aromatic N-oxidation, N-glucuronidation of primary amines, sulfone formation, acyl glucuronidation, secondary-alcohol oxidation, deamination, amide N-hydroxylation) were **not** added, even where they are standard chemistry, because there is no development evidence for them.

**The five added rules.** Methyl hydroxylation (recovered 14 development misses), ketone or aldehyde reduction (7), secondary amine N-hydroxylation (3), tertiary C-H hydroxylation (2), O-deethylation (2). Their weights (0.10 to 0.22) are relative ranking choices set by analogy with existing rules, not occurrence ratios from Ridder and Wagener (2008). The rules and weights are in `src/agents/metabolism.py` at the commit this protocol is tagged on; they are not to change before the held-out run.

**Held-out data (never examined).** ChEMBL `metabolism` records whose organism is **not** `Homo sapiens` (rat, mouse, marmoset, dog, macaque, or unspecified species), where the substrate equals the drug (one-step edges), for drugs **not** in the development set, with both structures resolvable. The query found 132 drugs and 504 edges before structure filtering. This set was counted but its contents were not looked at.

**Limits of the held-out set, stated up front.** Most records (413 of 504) have no species recorded, so this is not a human test. Reference completeness differs from the human set. Metabolic chemistry is shared across mammals but not identical, so a gain here supports generality of the added transformations, not human accuracy.

**Method.** One run, same drugs, two rule sets: the *old* set is `ALL_RULES` without the five new rules, the *new* set is the current `ALL_RULES`. `predict_metabolites(smiles, depth=2, min_score=0.01, max_results=40)`. Matching, selection and metrics are as in protocol v0.5 (InChIKey connectivity block of the largest fragment; micro recall; score AUC with a drug-level bootstrap).

**Check FH1, recall gain.** Held-out micro recall with the new rules minus with the old rules is at least 0.05, **and** the lower bound of a paired 95% bootstrap interval of that difference (resampling drugs, 2000 resamples, seed 20261030) is above 0.
**Check FH2, ranking signal kept.** The new-rule score AUC lower bound (drug-level bootstrap, as in v0.5) is above 0.5.
**Check FH3, no burying.** Held-out top-10 micro recall with the new rules is no more than 0.02 below that with the old rules (more rules must not push hits out of the top of the list).
**Check FH4, integrity.** For every held-out drug under the new rules: every SMILES parses, no duplicates and the parent not listed, scores in (0, 1] and descending, `generation` equals pathway length, and two runs are identical. The three fault inputs (invalid SMILES, empty SMILES, `depth=0`) each return an error record without raising.
- Pass for each of FH1 to FH4 as stated. All thresholds are methodological choices fixed before the run.

**Recorded, no pass/fail.** Old and new recall, top-10 recall and AUC on the held-out set and on the development set (development numbers must not be quoted as evidence); mean predictions per drug and drugs that reach the 400-metabolite ceiling, old versus new; held-out recall split by unspecified-species versus named-species records; the hits recovered by each new rule; drugs whose structures could not be resolved.

**Known limits.** Ten more rules could be added without end. This test says whether these five generalise, not whether the rule set is good. A positive result here does not extend to the human-specific claims of protocol v0.5.

---

# Version 1.4 (draft), 2026-10-30. Atlas pocket detector: development comparison and held-out test. Earlier criteria are unchanged.

## Pocket detector: does anything beat the original, and how does the original do on unseen complexes?

**Why.** In protocol v0.6 the geometric pocket detector found the ligand site (centre within 4 angstrom) in 5 of 13 complexes, below the 0.5 floor. Any change tuned on those 13 would be scored on the data it was tuned on. So: develop on those 13 only, then test once on complexes chosen by a fixed rule.

**Development set (seen).** The 13 complexes of protocol v0.6. Candidate changes were compared there only. Adoption rule, fixed before the comparison: a change replaces the default only if it adds **at least 2** successes over the original (5 of 13, so 7 or more).

**Development outcome (recorded in `manifests/pocketheldout.json`).** Four cavity rankings (largest cluster, summed burial, size times squared burial, capped size times burial) all scored 5 of 13, and top-3 equalled top-1. Eight detection settings: original 5/13; burial threshold 0.60 5/13; 0.55 4/13; 0.50 2/13; link distance 2.6 5/13; threshold 0.55 with link 2.6 3/13; burial radius 14 6/13; threshold 0.55 with summed-burial ranking 4/13. **No change reached the adoption threshold, so no default was changed.** The only code change is a refactor: `detect_pockets` returns a ranked list and `detect_pocket` still returns the best one with unchanged defaults.

**Held-out set (never examined by the detector).** 40 entries chosen by this rule: RCSB search for X-ray structures with resolution at most 2.0 angstrom, exactly one polymer entity of 150 to 450 residues, exactly one non-polymer entity, released before 2020 (7,674 hits); shuffled with seed 20261030; take entries in that order, skipping the 13 development entries and any whose single hetero code is a listed additive (`src/crystal_additives.py`) or whose first ligand residue has fewer than 15 or more than 45 heavy atoms; stop at 40. The list is frozen in the manifest. One bound used while querying (a molecular-weight filter) returned no hits and was dropped before any selection; ligand size is checked from the structure file instead.

**Method.** As in protocol v0.6, part P: the protein ATOM records of the first model are passed to the detector with default parameters; the reference point is the heavy-atom centroid of the first residue with the ligand code; success is a centre-to-centre distance of at most 4.0 angstrom for the top-ranked pocket. The baseline is the protein-atom centroid scored the same way.

**Check PH1, success rate.** Success rate of the unchanged detector of at least 0.5.
**Check PH2, beats guessing.** Strictly more successes than the protein-centroid baseline.
**Check PH3, coverage.** The detector returns a pocket (not an empty result) for at least 90% of complexes.
- The 0.5 floor repeats the one fixed in v0.6, so a second miss would be a genuine second finding, not a re-tuned bar.

**Recorded, no pass/fail.** Wilson 95% interval of the success rate; top-3 success; the success rate of the best development variant (burial radius 14) on the same complexes (it missed the adoption threshold, so this is descriptive and not a recommendation); every distance, box size and whether the ligand centroid lies inside the predicted box; ligand size and protein size against success.

**Known limits.** Complexes are single-chain, single-ligand, high-resolution structures, an easier population than typical docking targets, so the rate probably overstates real use. Only the top-ranked pocket is scored, because MUMO docks into one box. P2Rank was not run (Java missing).

**Addendum 0.9b (written after the second Interactions run, disclosed as such).** The first run failed I1 on H-bond recall (0.463, precision 0.679). A diagnosis of the 11 PLIP H-bonds that MUMO missed in 8 complexes found 8 within 3.5 angstrom of a ligand atom but rejected because RDKit places hydroxyl and amino hydrogens at arbitrary torsions, 2 slightly beyond 3.5 angstrom, and 1 a histidine whose tautomer is fixed arbitrarily. The fix turns rotatable donor hydrogens (terminal OH, SH, sp3 NH2/NH3) toward an acceptor of the other molecule within 3.5 angstrom, as Reduce and PLIP do; the 130 degree angle and 3.5 angstrom limits are unchanged. Second run (`runs/interactions/20261031T063417Z`): H-bond precision 0.743, recall 0.634, any-contact Jaccard 0.509; I1 passes, I2 119/119, I3 10/11 and I4 2/2 unchanged. **These 11 complexes are the development set for this fix, since the failures were diagnosed on them, so the I1 pass is not an independent result.** A held-out re-test on fresh complexes is still required before the manuscript cites the new numbers. The histidine tautomer and the 3.5 angstrom limit were not changed.

## Version 1.5: Interactions held-out re-test of the donor-hydrogen orientation fix

Frozen before any held-out complex was analysed. Tag `validation-protocol-v1.5`.

**Why.** The fix in Addendum 0.9b was designed after diagnosing missed H-bonds on the 11 complexes of protocol v0.9. Its I1 pass on those 11 is therefore a development result. This version measures it on complexes the fix was never designed on.

**Held-out set.** 30 entries chosen by this rule (script `scripts/select_interactions_heldout.py`, which only selects and never runs MUMO): the RCSB query of protocol v1.4 (X-ray, resolution at most 2.0 angstrom, one polymer entity of 150 to 450 residues, one non-polymer entity, released before 2020; 7,674 hits), shuffled with seed 20261031; take entries in that order, skipping the 11 development entries of v0.9, any whose single hetero code is in `src/crystal_additives.py`, and any whose first ligand residue has fewer than 15 or more than 45 heavy atoms; stop at 30. The list, with the 78 entries skipped on the way, is frozen in `manifests/interactionsheldout.json`.

**Method.** As in protocol v0.9: crystal ligand pose rebuilt from the deposited SMILES at pH 7.4, cleaned protein, PLIP 3.0.0 on the raw file as comparator, contacts compared at residue level. The identity-guard handling of Addendum 0.9a applies from the start. Every complex is analysed **twice with identical preparation**: once with the hydrogen-orientation step switched off (the code before the fix) and once with it on (the shipped code). Only H-bond residues are scored for the fix; any-contact agreement is a sanity check.

**Counting rules.** Pooled true positives, false positives and false negatives over all complexes. A complex whose preparation or MUMO analysis fails counts as an error and its PLIP H-bond residues enter the denominators as false negatives for both arms. A complex where PLIP itself fails has no reference and cannot be counted; those are listed, not hidden.

**Check IH1, floors.** H-bond precision at least 0.6 **and** recall at least 0.6 for the shipped code. These are the floors of check I1, not re-tuned.
**Check IH2, the fix helps.** Strictly more true positives with orientation on than off.
**Check IH3, precision cost.** Precision with orientation on is at least the precision with it off minus 0.05.
**Check IH4, sanity.** Any-contact Jaccard at least 0.4, as in I1.

**Recorded, no pass/fail.** Recall and precision of both arms; a paired bootstrap 95% interval (2,000 resamples over complexes, seed 20261031) of the recall gain; per-complex counts.

**Commitments.** Whatever the outcome is recorded here and in `RESULTS.md`, including a failure. The code is not changed to rescue a failed floor on this set; if the held-out set fails, any later change needs another fresh set. Failed or errored complexes are not replaced.

**Known limits.** The set is single-ligand, high-resolution complexes, an easier population than typical docking targets. PLIP is a geometric detector, not experimental truth, so agreement with it is not a measure of correctness. Histidine tautomers and water bridges are not addressed by the fix and may cost recall here too.

**Result of v1.5 (run `runs/interactionsheldout/20261031T092556Z`, code at commit 4500fa4).** IH1 pass: precision 0.670, recall 0.645 (tp 69, fp 34, fn 38). IH2 pass: true positives 69 with orientation against 57 without (recall 0.645 against 0.533; paired bootstrap 95% interval of the recall gain +0.059 to +0.172). IH3 pass: precision 0.670 against 0.663. IH4 pass: any-contact Jaccard 0.489. 25 complexes ran, 5 errored. Two errors happened before a PLIP reference existed and so cannot be scored (2QXI: ligand template matching failed; 1LLO: PLIP produced no interaction set); three were MUMO failures and are counted as missed H-bonds in both arms (6R67 and 2B54: "Receptor preparation missing or does not match input"; 3QVH: "Python integer -8 out of bounds for uint32"). No complex was replaced and no code was changed after the run. The three MUMO failures are product defects that the fix does not touch and are carried forward as open items.

**Addendum 1.5a (written after the v1.5 result, disclosed as such).** The three MUMO failures were investigated and have three different causes. (1) 3QVH has a residue numbered -8 (expression tag); ProLIF stores residue numbers as unsigned integers and raised an overflow. MUMO now shifts residue numbers for ProLIF only and reports the numbers of the input file. (2) 2B54 carries deposited hydrogens at impossible distances (an arginine hydrogen 1.5 angstrom from CZ), so RDKit bonded them and the residue had five bonds on one atom; MUMO now retries once without the deposited hydrogens and adds its own. These two fixes only change inputs that failed before. (3) 6R67 fails because the cleaner keeps conformer A of every residue and the A conformers of Lys15 and Met13 are mutually exclusive in the crystal (NZ and CE 1.44 angstrom apart); this one is **not fixed**, because the cleaner is shared with docking and choosing a different conformer rule is a design decision. The three complexes were re-run once after fixes 1 and 2 (`manifests/interactionsheldout_rerun3.json`, `runs/interactionsheldout/20261031T094730Z`): 3QVH and 2B54 now analyse (H-bond true positives 8 with orientation, 3 without, over the three complexes; false positive 1), 6R67 still errors. **The registered v1.5 result above is unchanged and remains the result of record;** this re-run is post-hoc, was not pre-registered, and its numbers are not pooled into it. An earlier intermediate run of the same three complexes (after fix 1 was only half correct) was discarded.

**Addendum 1.5b (written after Addendum 1.5a).** The 6R67 failure was fixed by changing the receptor cleaner (`docking_engine.clean_protein_pdb`, shared with docking) to keep, for each residue with alternate conformers, the one with the highest summed occupancy (ties to 'A') and to blank the conformer label in its output, instead of keeping conformer 'A' of every residue. Re-run of the three complexes (`runs/interactionsheldout/20261031T094909Z`): all three analyse (H-bond true positives 8 with orientation, 3 without, over the three; false positive 1); PLIP reports no H-bonds on 6R67, so it does not move the scores. Because the cleaner is shared, Pose docking and Interactions were re-run on their original 11 complexes: Pose D1 is unchanged at 8/11 (the three misses, 1HSG 11.38, 1M17 7.83 and 4DFR 5.91 angstrom, are identical to the earlier run; `runs/pose/20261031T094927Z`), and Interactions I1 is unchanged (precision 0.743, recall 0.634, Jaccard 0.509; `runs/interactions/20261031T101332Z`). The registered v1.5 result is still the result of record; this is a post-hoc check.
