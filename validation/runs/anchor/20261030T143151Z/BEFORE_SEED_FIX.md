# After the chain-break fix, before the seeding fix

7 of 8 receptors ran. A3 failed on all three repeats: minimised energies differed by 5 to 62 kcal/mol and `lig_rmsd_min` by up to 0.12 angstrom between identical runs. Diagnosis: OpenMM's `Modeller.addHydrogens` places some hydrogens at random, so the starting structure itself differed (starting energies -1792.4 and -1790.7 kcal/mol even with a single CPU thread). With Python and NumPy seeded, two hydrogen placements agreed to 0.0007 angstrom, against up to 1.9 angstrom unseeded. The seeding fix (and fixed Langevin and velocity seeds) is committed before the next run.

3ERT still errors: residue CYS 216 has missing side-chain atoms ("similar to CMET, but is missing 2 H atoms and 2 C atoms"). Amber templates cannot match a truncated residue, and fixing that needs a missing-atom rebuild (for example PDBFixer, not installed). It is recorded as an open limitation, not fixed.
