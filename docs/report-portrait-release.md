# Portrait report export

The docking report now uses A4 portrait pages and the following section order:
Methodology; Results (Ramachandran and target validation, ligand HOMO/LUMO,
docking); Discussion; Conclusion; References.

Each target figure contains five panels: the actual protein ribbon, calculated
FreeSASA per-residue exposure, Ramachandran residue counts, enlarged Top8000
Ramachandran plot, and polar/apolar solvent-accessible area. No density panel
or ERRAT/ProSA score is substituted. SASA is an area, not an energy.

New runs retain the full cleaned receptor coordinates and recorded box sizes,
base seed and structure identifiers. Old runs without those coordinates need
a new analysis to produce the complete target figure.

FreeSASA 2.2.1 runs in an isolated environment. Failed native calculations and
image captures remain unavailable, never zero-valued substitute results. The
Docker build gate executes the worker and checks residue identity and areas.

Local verification includes regression tests, an executed FreeSASA calculation
on 3ERT, and Microsoft Word rendering of the portrait panel and a docking report
assembled from captured real COX-2/aspirin docking and orbital outputs. These
export checks are not a new docking accuracy benchmark or an experimental
validation of biological activity.
