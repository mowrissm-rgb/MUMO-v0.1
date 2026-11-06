# Flux held-out result (five rules added from development misses; protocol v1.3)

Held-out set: 130 drugs, 371 reference metabolites (ChEMBL one-step records from non-human or unspecified-species sources, for drugs outside the development set; 72 candidate edges dropped for missing structures). 413 of the original 504 edges had no species recorded, so this is not a human test.

| | old rules | new rules |
|---|---|---|
| held-out micro recall | 0.342 | **0.442** (gain +0.100, paired 95% CI +0.069 to +0.134) |
| held-out top-10 recall | 0.275 | 0.315 |
| held-out score AUC | 0.839 | 0.794 (new lower bound 0.756) |
| mean predictions per drug | 38.3 | 38.7 |
| drugs hitting the 400-metabolite ceiling | 9 | 15 |

All four criteria pass. Points to carry into the paper:

- **The gain is real but smaller than on the data the rules were fitted to.** On the development set recall rose from 0.410 to 0.559 (+0.149); on the held-out set it rose +0.100. The development figure must not be quoted as evidence.
- **The score ranking got worse even though recall improved.** AUC fell from 0.839 to 0.794. The new rules add matches but their relative weights (set by analogy, not measured) rank them less well. It stays well above 0.5 (criterion FH2 is only a floor).
- **More drugs now reach the 400-metabolite ceiling** (9 to 15), so the search is truncated for more large molecules.
- **Which new rules helped on held-out drugs:** methyl hydroxylation (22 hits), tertiary C-H hydroxylation (7), ketone/aldehyde reduction (6), O-deethylation (1). Secondary amine N-hydroxylation produced none.
- **Gain holds in both subsets:** unspecified-species edges 0.350 to 0.447, named-species edges 0.306 to 0.419.
