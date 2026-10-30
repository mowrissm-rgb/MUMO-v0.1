# Baseline before the fix

H1 and H5 pass; H2 (6/10), H3 (6/9) and H4 (3/4) fail. Causes, all in MUMO's wrapper:

- **Order (H2, four proteins):** hits come out in BLAST's order, which is by E-value. E-values underflow to 0 for strong matches, so the order among them is not by bit score. Helix now ranks by bit score explicitly.
- **Truncation (H2, ESR1):** Helix asked BLAST for `-max_target_seqs 25`, which does not guarantee the 25 best hits. A stronger hit (P57782) was missing from ESR1's list. Helix now asks for at least 1000 and keeps the top 25 itself.
- **Empty input (H4):** an empty string went to UniProt and raised an HTTP 400 error instead of `ValueError`. It now raises `ValueError`.
- **Paralogues (H3):** CDK2 missed CDK1 and CDK5, DRD2 missed DRD4, and ESR1 missed ESR2. Swiss-Prot holds many orthologues of the same protein from other species, and they fill a 25-hit list before the human paralogues. Part of this is the truncation above; the rest is a design limit (no species filter, a fixed 25 hits). The post-fix run shows how much was truncation.
