# MUMO — Attributions & Third-Party Notices

MUMO (Multi-Agent Drug Discovery & Development AI Platform) is built on open
scientific data and open-source software. This file records the required
attributions and licences. It is provided for compliance and transparency;
it is not legal advice.

## Data sources

Several data sources are licensed under Creative Commons terms that require
attribution (CC-BY) or attribution + share-alike (CC-BY-SA). MUMO credits them
here and in the app's "Data sources & credits" panel.

| Source | Used for | Licence |
|--------|----------|---------|
| [UniProt](https://www.uniprot.org/) | Protein sequences (gene → sequence) | CC-BY 4.0 |
| [STRING](https://string-db.org/) | Protein–protein interaction networks | CC-BY 4.0 |
| [Open Targets](https://www.opentargets.org/) | Disease–target associations | CC-BY 4.0 |
| [ChEMBL](https://www.ebi.ac.uk/chembl/) | Bioactive compounds / ligands | CC-BY-SA 3.0 |
| [AlphaFold DB](https://alphafold.ebi.ac.uk/) | Predicted protein structures | CC-BY 4.0 |
| [RCSB PDB](https://www.rcsb.org/) | Experimental structures; chemical component dictionary | Public domain |
| [Therapeutics Data Commons](https://tdcommons.ai/) | ADMET model training data | Dataset-specific (see TDC) |

CC-BY-SA (ChEMBL): derived data distributed by MUMO that incorporates ChEMBL
data is shared under compatible terms.

## Third-party software

| Tool | Purpose | Licence |
|------|---------|---------|
| [AutoDock Vina](https://vina.scripps.edu/) | Molecular docking | Apache-2.0 |
| [RDKit](https://www.rdkit.org/) | Cheminformatics, 2D depiction, MOL2/SDF export | BSD-3-Clause |
| [ProLIF](https://prolif.readthedocs.io/) | Protein–ligand interaction fingerprints | Apache-2.0 |
| [MDAnalysis](https://www.mdanalysis.org/) | Structure handling (ProLIF dependency) | GPL-2.0+ (used as a library dependency of ProLIF) |
| [meeko](https://github.com/forlilab/Meeko) | Ligand/receptor preparation, pose parsing | Apache-2.0 |
| [dimorphite-dl](https://durrantlab.pitt.edu/dimorphite-dl/) | Protonation at physiological pH | Apache-2.0 |
| [ADMET-AI](https://github.com/swansonk14/admet_ai) / [Chemprop](https://github.com/chemprop/chemprop) | ADMET property prediction | MIT |
| [BLAST+](https://blast.ncbi.nlm.nih.gov/) | Sequence similarity search (self-hosted) | U.S. Government public domain |
| [gemmi](https://gemmi.readthedocs.io/) | Structure I/O | MPL-2.0 |
| [Streamlit](https://streamlit.io/), [Supabase](https://supabase.com/), [py3Dmol](https://3dmol.csb.pitt.edu/) / 3Dmol.js | UI, auth/storage, 3D viewer | Apache-2.0 / MIT / BSD |
| [python-docx](https://python-docx.readthedocs.io/) | .docx report export | MIT |
| [Playwright](https://playwright.dev/) | Headless rendering of report images | Apache-2.0 |

MDAnalysis note: MDAnalysis is GPL and is pulled in transitively by ProLIF.
It is used only as an unmodified library dependency at runtime; MUMO's own code
is not a derivative work of MDAnalysis. If distribution terms require otherwise
for a given release, revisit this before shipping a commercial binary.

## Large language model

MUMO's conversational reasoning and beginner-friendly report narratives use
**Llama 3.3** (Meta) served via Groq.

**Built with Llama.** Use of Llama is subject to the
[Llama Community License](https://www.llama.com/llama3_3/license/).

---

_This project is being prepared for commercial use; see the private IP/licence
audit. Engage a qualified attorney before any filing or launch — this NOTICE is
a working record, not legal advice._
