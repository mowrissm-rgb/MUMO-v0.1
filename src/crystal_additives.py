"""Hetero groups in a PDB file that are not the bound drug.

One list shared by every code path that picks "the" ligand of a structure
(grid-box centring and native-redock validation). They used to keep separate
lists, so the box could be centred on the inhibitor while validation chose the
heme, or the reverse.
"""

NOT_LIGAND = frozenset({
    # water and common ions / buffer species
    "HOH", "WAT", "SOL", "DOD", "TIP", "CL", "NA", "K", "MG", "CA", "ZN", "MN",
    "FE", "FE2", "NI", "CU", "CD", "HG", "SO4", "PO4", "ACT", "FMT", "NO3",
    "SCN", "CO3", "NH4", "IOD", "BR",
    # crystallisation additives and buffers
    "GOL", "EDO", "PEG", "PGE", "P6G", "1PE", "PG4", "12P", "DMS", "BU1", "ACM",
    "TRS", "MES", "EPE", "CIT", "TAR", "MLI",
    # prosthetic groups are not co-crystal inhibitors
    "HEM", "HEA", "HEC",
    # glycans
    "NAG", "BMA", "MAN", "FUC", "GAL",
    # membrane lipids, fatty acids and detergents
    "CLR", "OLC", "OLA", "OLB", "PLM", "MYR", "STE", "BOG", "LMT", "DDM", "LDA",
})
