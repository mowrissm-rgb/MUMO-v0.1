# Named workflows

| Name | Responsibility |
|---|---|
| Pose | Docking, poses and ligand–residue interactions |
| Fate | ADME, toxicity and drug-likeness |
| Nexus | STRING and network pharmacology |
| Quill | Report writing and exports |
| Orbit | Calculated HOMO/LUMO energies and surfaces |
| Atlas | Protein preparation and Ramachandran validation |
| Compass | Disease-related target discovery |
| Flux | Metabolism and biotransformation prediction |
| Helix | BLAST, sequence relationships and phylogeny |
| Anchor | Molecular dynamics and pose-stability checks |
| Scout | Ligand discovery and screening |

Names identify workflows backed by existing tools, not separately trained models
or new independent deployments. Existing A/B/C/D service ownership is retained.
Chat supports explicit invocations such as `run Orbit on aspirin` and `run Fate
on this compound`. Compass and Scout operate inside the existing docking
discovery workflow; Quill and Anchor remain available through report controls.
Scientific words such as “pose” and “helix” do not alone invoke an agent.

## 2026-10-19 release

- Adopted the approved Gemini-inspired dark surfaces, rounded composer, neutral
  user bubbles and sans-serif chat typography while retaining real Streamlit
  inputs, uploads, themes, history and background jobs. No simulated HTML
  calculations or placeholder buttons were deployed.
- ADME and standalone orbital results use verified surface images. Numerical
  energies remain available when surface generation fails; no lobes are guessed.
- ADME report figures are generated from the same entries as the result panel.
  Standalone energy-only diagrams are optional and clearly labelled.
- Report caches depend on content and presentation version, not Python object IDs.
- A structure file accompanied by an ADME/QM/metabolism request follows that
  request and retains the uploaded compound's structure and name.
- Starting a new ADME/QM/metabolism request clears the old active panel, so a
  failed run cannot silently display the previous compound's results as current.

Rollback: revert this release's commits on top of the previous release; no
database schema or infrastructure changes are required. Previous release:
`647196f` (confirm remote head before deployment).
