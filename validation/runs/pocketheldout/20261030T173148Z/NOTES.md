# Pocket detector, held-out result (unchanged detector; protocol v1.4)

40 complexes chosen by a fixed RCSB query and a seeded sample (seed 20261030), none seen by the detector.

- **PH1 fails:** 13 of 40 (33%, Wilson 95% CI 20% to 48%) within 4 angstrom, against the 0.5 floor. This matches the development rate (5 of 13, 38%), so the first result was not a small-sample accident.
- **PH2 passes:** the protein-centroid baseline found the site in only 2 of 40.
- **PH3 passes:** a pocket was returned for 39 of 40.
- **Descriptive:** top-3 success 17 of 40 (43%); the predicted docking box contains the ligand centroid in 27 of 40 (68%); the best development variant (burial radius 14) scored 15 of 40 (38%), about two more than the default, which fits its +1 on development data and does not reach a meaningful gain (it was below the adoption threshold and no default was changed).
- **Reading it:** the detector is clearly better than guessing but finds the exact ligand site (within 4 angstrom) about one time in three on these easy complexes. As a docking box it contains the ligand centroid about two times in three. For ligand-free targets such as AlphaFold models, MUMO's blind pocket detection should be treated as a rough starting point and checked.
