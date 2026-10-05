# MUMO docking modes, private calculation memory, and integrated biology

Date: 2026-10-05. Baseline source: `c568c25`.
Status: conversational design approved; written-spec review precedes implementation.

## Outcome

Let users select Medium (8), Standard (16), or High (32) exhaustiveness;
avoid repeating compatible calculations with their consent; add target STRING
context and per-target leading-candidate ADME to the same docking report.
Keep existing free hardware and do not enable paid services or automatic upgrades.
No promised runtime or experimental-validity percentage accompanies a mode.

## Delivery order and alternatives

1. Modes and reproducible settings: one request-wide choice, default Standard.
2. Private pair memory and bounded preparation reuse: the preferred initial speed improvement.
3. STRING and lead ADME orchestration, report rendering, and end-to-end benchmarking.

An optional two-stage screen followed by deeper finalist docking is deferred:
it changes the scientific protocol and cannot silently replace the selected mode.
Extra paid hardware is excluded. Grid reuse and parallel workers are benchmarked
optimizations, not prerequisites or presumed speedups.

## Modes and reliability

- Medium: exhaustiveness 8; three independently seeded replicas.
- Standard: exhaustiveness 16; three independently seeded replicas.
- High: exhaustiveness 32; three independently seeded replicas.
- The selected mode is explicitly passed through chat, job specification,
  pipeline, engine configuration, result metadata, and report methodology.
- Preserve per-replica scores/seeds, spread, pose-convergence qualifications,
  target validation, raw evidence, and failure/timeout states.
- Mode selection cannot retrospectively relabel a cached Medium result as High.
  Exhaustiveness controls search effort; it does not establish experimental validity.

## Private calculation memory

Memory is an execution-artifact cache, not LLM recollection or name matching.
The first release is private to the authenticated owner. Anonymous users have
no durable cross-session cache. Cross-user/public reuse is deferred until there
is a separate explicit publication/withdrawal and privacy design.

Each pair key covers hashes of the actual prepared receptor and ligand, receptor
chain selection, resolved identifiers/species, ligand stereochemistry and
protonation/charge, search-box center/dimensions, scoring function, exhaustiveness,
replica seeds/count, Vina version, preparation versions/settings, interaction
analysis version/settings, and workflow schema version. Preserve original source
coordinates, identifiers, dates, and logs alongside these preparation fingerprints.
Unknown versions, ambiguous identity, changed coordinates/settings, or incomplete
evidence mean a cache miss. NF-kB is not a unique protein structure identifier.

Only executed, finite, schema-checked docking results with their required poses,
replica evidence, and completed interaction analysis qualify for full-pair reuse.
Failed/unfinished pairs never become hits; qualifications and native-redocking
failures remain visible, not upgraded to a claim of validated efficacy.
Preparation and validation caches have their own input/version fingerprints.
Missing derived data may be regenerated from a retained verified pose, explicitly
recorded as a separate step rather than claimed as a new docking calculation.

Persist owner-scoped metadata and losslessly compressed evidence with bounded
storage. Owner checks and database/storage RLS must both apply, including reads
and writes; never substitute a service-role bypass for a user's permission.
Cache access failures or quota limits fall back to fresh calculation and an
honest storage notice. A failed cache write cannot hide a finished result.
Do not store passwords or refresh tokens in cache entries, keys, or job files.
The execution worker remains isolated; authenticated persistence is coordinated
through the existing user-session path without blocking result display.

## Reuse interaction and mixed batches

Resolve identities and preparation fingerprints before looking up eligible pairs.
When matching results exist, show their count, mode, date, and qualifications and
offer two actions: reuse matching pairs and calculate missing pairs, or redock all.
Do not begin the missing-pair work until that choice is made. No hits starts a fresh
run normally. Persist this choice in the job specification so reconnects do not
launch duplicates or reinterpret an old conversation's answer.

For 20 requested pairs with five compatible hits, approved reuse schedules 15
new pairs. Merge by exact target/ligand identity, not label or list position.
Each output row includes reused/new origin, original run ID/date, selected settings,
and evidence status. Every requested pair is accounted for, including failures;
unfinished calculations retain no fabricated score. Rank compatible candidates
within each target; do not infer an overall biological lead from raw scores across
different proteins. Existing checkpoints and crash-isolated execution remain in place.

## Automatic biological additions

After target validation, query one combined STRING network for the resolved targets
of the appropriate species. Resolve PDB inputs through verified protein identifiers;
unmapped targets are listed rather than substituted. Mixed species are analyzed
separately. Include network image, identifier mapping, association confidence,
functional/pathway enrichment where available, query date, parameters, and sources.
Association evidence supplies biological context, not proof of ligand binding.
Network/API failure is isolated and reported; successful docking still proceeds.
STRING snapshots are versioned/date-stamped separately from the docking cache.

After docking, choose the lowest finite docking score among completed eligible
pairs within each target, with ties retained and reliability qualifications shown.
Call this a top docking candidate, not an experimentally proven lead. If no eligible
pair exists, record that there is no candidate for ADME. Analyze each unique selected
chemical structure once using existing RDKit and ADMET-AI functions; reuse across
targets only when structure/chemical state and model/settings versions match.
Distinguish calculated descriptors from ML predictions, retain unavailable endpoints,
and never replace missing model output with narrative guesses.

## Report and website

Keep the existing methodology-before-results format. Results order:
target validation/Ramachandran, STRING, ligand HOMO/LUMO, docking,
per-target top-candidate ADME, discussion, conclusion, references.
Extend methodology and references with actual mode, preparation protocol, cache
provenance, STRING parameters, and ADME methods/model versions. Reused data retain
original calculation dates. Preserve existing 2D/3D figures and source structures.
Store executed enrichment outputs with the job, so downloading/regenerating a report
does not rerun docking, STRING, or ADME. Cached poses do not count as newly executed
independent replicas. A fully cached run still completes any missing requested
biological steps before declaring the integrated report complete.

## Measurement and acceptance

Instrument preparation, validation, each replica, interactions, persistence,
STRING, ADME, and report rendering separately. The reported two-hour user run is
not a controlled baseline. Adding biological analyses can increase uncached runtime.
Record cold-cache, partial-hit, and full-hit wall time, peak memory, executed pair
and replica counts, and software/input fingerprints on fixed hardware.

Tests must cover all three mode configurations; owner isolation; mismatched
coordinates, stereochemistry, charge, grids, versions and seeds; corrupt/failed
cache entries; explicit reuse/redock choices; 5-of-20 reuse executing only 15 pairs;
unchanged cached scores/coordinates; matrix accounting; per-target ranking/ties;
STRING/ADME failures; repeated report downloads without repeated computation;
and retained checkpoints during interruptions.

Start with a real small controlled matrix and seeded cached/uncached comparisons.
Only after correctness passes, evaluate a representative 8-ligand/9-target batch
within an agreed runtime/usage budget. Benchmark one two-core worker versus bounded
single-core workers; prevent CPU oversubscription. Adopt reusable Vina maps only
after output and convergence comparisons establish acceptable equivalence under
a documented protocol. Publish measured speedups, not assumed percentages.

## Review and release boundary

Review this written spec before the implementation plan. Implement and verify the
three increments locally, with privacy tests before enabling durable memory.
Database/storage migrations need their own inspected, reversible rollout; no schema
or hosting changes have been performed by writing this document. Do not push or
deploy without the user's explicit release approval. Existing user files and
unrelated untracked scientific-figure plans remain untouched.
