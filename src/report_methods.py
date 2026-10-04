"""Run-aware docking report methods and bibliographic references."""

def add_docking_methodology(doc, meta, targets, add_table):
    doc.add_heading('Methodology', level=1)
    doc.add_heading('Target preparation and backbone validation', level=2)
    doc.add_paragraph(
        'MUMO obtains the target coordinates from the recorded uploaded, PDB or AlphaFold '
        'structure. The docking pipeline cleans the receptor and prepares PDBQT atom types '
        'with Meeko. Residues without supported templates may be excluded; this is a '
        'preparation limitation, not a repaired experimental structure. The saved cleaned '
        'receptor coordinates before template-based exclusions are used for the '
        'validation figure and solvent exposure. Preparation exclusions are recorded '
        'separately for the receptor actually used in docking.')
    doc.add_paragraph(
        'Backbone phi and psi angles are calculated from adjacent C, N, CA and C coordinates '
        'in the first model. Blank or A alternate locations are selected. Peptide links '
        'must belong to the same chain segment and have a C–N separation within 2.0 Å. '
        'Termini, chain breaks and incomplete backbone geometry are counted as unscored '
        'rather than included in the percentage denominator. Each scored residue uses its '
        'MolProbity Top8000 class: general, glycine, cis-proline, trans-proline, pre-proline '
        'or Ile/Val. Bilinear interpolation of the reference grid supplies the density. '
        'Favoured density is at least 0.02; allowed minima are 0.0005 for general, 0.002 '
        'for cis-proline and 0.001 for the remaining classes. Reported percentages use '
        'only residues with a defined phi/psi pair [1]. This is backbone validation, '
        'not the complete MolProbity clashscore or rotamer assessment.')
    doc.add_paragraph(
        'FreeSASA calculates solvent-accessible surface area using the Lee–Richards '
        'algorithm, a 1.4 Å probe and 20 slices with its default atom classifier [2]. '
        'All retained protein chains are evaluated together. The first model and '
        'blank/A alternate atom locations are selected; hydrogens and HETATM records '
        'are excluded. Unknown atom types are skipped rather than assigned invented '
        'radii. Total, polar and apolar areas are reported in Å². The green graph shows '
        'raw per-residue area; the stacked graph separates polar and apolar contributions. '
        'Chain and residue identifiers are retained, including insertion codes. SASA '
        'describes exposure in this coordinate model and is not a structural energy score.')
    doc.add_heading('Ligand electronic calculations', level=2)
    doc.add_paragraph(
        'Ligands are identified by their recorded names and SMILES. RDKit adds explicit '
        'hydrogens, embeds a 3D conformer with seed 42 and performs MMFF geometry '
        'optimization for at most 200 iterations. A non-converged geometry is not accepted '
        'as a successful calculation. GFN2-xTB then performs a gas-phase single-point '
        'calculation; formal charge comes from the input chemical structure and the '
        'unpaired-electron count is checked [3]. This is a semiempirical calculation, '
        'not a DFT optimization. HOMO and LUMO energies are parsed from explicit engine '
        'labels; their ordering and Hartree/eV conversion are checked, and the gap is '
        'LUMO minus HOMO. Failed calculations are reported without substitute values.')
    doc.add_paragraph(
        'Orbital surfaces are generated from the same xTB Molden wavefunction coefficients '
        'and orbital indices, evaluated on a volumetric grid in an isolated conversion '
        'process. The renderer draws positive and negative isosurfaces at ±0.03 a.u. '
        'in orange and blue; these colors denote wavefunction phase, not positive and '
        'negative charge. The LUMO is above the HOMO, separated by a labeled energy gap. '
        'Surface generation and image capture must both complete before a surface is '
        'included. An orbital gap by itself does not quantify chemical stability or activity.')
    doc.add_heading('Docking and interaction analysis', level=2)
    doc.add_paragraph(
        'MUMO prepares ligand protonation near pH 7.4, embeds multiple conformers with '
        'RDKit and selects a low-energy MMFF conformer before Meeko PDBQT preparation. '
        'AutoDock Vina searches a fixed receptor within the recorded box [4]. Replicas '
        'use successive seeds from the recorded base seed; the selected result is the '
        'best-scoring replica. Score spread and available pose-consistency evidence '
        'should be inspected alongside the selected score. When a native co-crystal '
        'ligand is available, the separate redocking check reports its RMSD; that test '
        'does not establish accuracy for every screened ligand.')
    doc.add_paragraph(
        'ProLIF detects geometrically and chemically defined contacts on the prepared '
        'ligand–receptor pose [5]. Canonical interaction records drive the table, 2D '
        'diagram and colored 3D contact lines. Unavailable interaction analysis is not '
        'equivalent to zero interactions. Report figures show the full protein ribbon '
        'and a binding-site close-up from the same complex. Vina scores are predictions '
        'in kcal/mol. Any Ki inferred from a score is a heuristic, not a measured inhibition constant.')
    per_target = meta.get('per_target') or {}
    for target in targets:
        tm = per_target.get(target) or (meta if len(targets) == 1 else {})
        doc.add_heading(f'{target} run parameters', level=3)
        add_table(doc, [
            ('Search box center (Å)', tm.get('center', 'Not recorded')),
            ('Search box size (Å)', tm.get('size', 'Not recorded')),
            ('Pocket source', tm.get('pocket', 'Not recorded')),
            ('Vina exhaustiveness', tm.get('exhaustiveness', 'Not recorded')),
            ('Docking replicas', tm.get('replicas', 'Not recorded')),
            ('Base random seed', tm.get('seed', 'Not recorded')),
            ('Excluded receptor residues', tm.get('dropped_residues', 'Not recorded')),
        ])


def add_docking_references(doc):
    doc.add_heading('References', level=1)
    for text in [
        '[1] Williams CJ et al. MolProbity: More and better reference data for improved '
        'all-atom structure validation. Protein Science (2018). doi:10.1002/pro.3330.',
        '[2] Mitternacht S. FreeSASA: An open source C library for solvent accessible '
        'surface area calculations. F1000Research (2016), 5:189. doi:10.12688/f1000research.7931.1.',
        '[3] Bannwarth C, Ehlert S, Grimme S. GFN2-xTB. Journal of Chemical Theory and '
        'Computation (2019), 15:1652–1671. doi:10.1021/acs.jctc.8b01176.',
        '[4] Trott O, Olson AJ. AutoDock Vina: improving the speed and accuracy of docking '
        'with a new scoring function, efficient optimization, and multithreading. '
        'Journal of Computational Chemistry (2010), 31:455–461. doi:10.1002/jcc.21334.',
        '[5] Bouysset C, Fiorucci S. ProLIF: a library to encode molecular interactions '
        'as fingerprints. Journal of Cheminformatics (2021), 13:72. doi:10.1186/s13321-021-00548-6.',
    ]:
        doc.add_paragraph(text)
