# Reference Anchor run (after terminal-oxygen, chain-break and seeding fixes)

A1, A2 and A3 fail; A4 and B1 pass. Reading the failures:

- **A1, A2 (7/8):** every complex that ran is consistent; only 3ERT errors (residue CYS 216 has missing side-chain atoms, which Amber templates cannot match; fixing it needs a missing-atom rebuild such as PDBFixer, not installed).
- **A3 (0/3):** repeats still differ, but less than before the seeding fix (minimised-energy differences of 0.9 to 25 kcal/mol, against 5 to 62; `lig_rmsd_min` within 0.04 angstrom). A follow-up diagnostic (3PTB, single CPU thread, seeded): the starting energies are now identical (-1799.3 kcal/mol twice), so hydrogen placement is deterministic, yet the minimised energies still differ (-3771.0 and -3730.1). The remaining source is therefore not hydrogen placement and not obviously thread count; it was not isolated. Verdicts did not change between repeats.
- **B1 passes:** the native pose has the smaller energy drop in 7 of 8 and a "Stable" verdict in 6 of 8.
