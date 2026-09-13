# Scientific verification changes

Verification means checks on recorded inputs, execution and outputs. It does not establish experimental validity.

- Interactions use reloaded prepared V3000 SDFs with explicit hydrogens, chemical state, atom mapping, hashes and a matching PDB. Distance-only N/O proximity is no longer counted as hydrogen bonding. ProLIF records retain geometry, atom/residue identifiers, version and settings. Unavailable analysis has null counts. Partially mapped contacts have a partial status and count only retained contacts.
- QM infers formal charge, validates spin/electron parity, requires successful MMFF preparation and xTB termination, and checks finite energies, units and gap consistency. The run keeps XYZ, stdout/stderr, settings and versions. Results are labeled semiempirical single-point predictions.
- Ramachandran records input/reference hashes, residue coordinates, chain boundaries, scoring coverage and unscored reasons.
- RDKit rules and ADMET-AI remain separate. Model outputs are validated per endpoint; missing models and invalid values are explicit. Unknown units, applicability and weight fingerprints remain limitations.
- Predicted metabolites carry transformation SMARTS and rule provenance. Failed rules are recorded; missing route edges are not invented.
- Docking records include input/output artifacts, replica settings and stage statuses. Reports use recorded replica counts. Scientific workflow summaries use deterministic result text. Run evidence is downloadable as JSON; prepared structures and records survive save/reload and ZIP export.
- Bare confirmations require a pending action identity. Persistence/service messages no longer claim success without evidence.

## Validation

Run `python -m unittest discover -s tests` from the repository root. The Docker build also runs this suite. Native xTB testing runs when its executable is installed; local Windows tests explicitly skip it when unavailable.

The fixtures cover real RDKit/ProLIF geometry and SDF round trips, positive/negative hydrogen-bond geometry, QM process/output failures, endpoint failures, residue traceability, report facts, partial results and export tampering. They do not establish universal agreement with Discovery Studio.

## Remaining scientific limits

Hydrogens use RDKit placement and residue charge templates; protein hydrogen geometry is not optimized and pH-dependent protonation is not established. Interaction results are qualified accordingly. Native redocking, ADMET applicability and all endpoints are not guaranteed for every input. A full live docking workflow and external Discovery Studio comparison still require a representative structure and matched preparation/settings. The user's original mismatching ZIP has not been supplied, so that exact case is unreproduced.

Free-form general conversation remains model-generated; deterministic scientific result summaries do not constitute a guarantee about every later conversational claim. Existing historical reports are not retroactively verified.
