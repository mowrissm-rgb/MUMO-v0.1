# Target resolution repair

Bare NF-κB requests pause in chat before ligand lookup or docking. The user sees
all five family members and their broad roles, and may choose a member or exact
PDB ID. A choice resumes the saved batch without guessing again. Explicit
parenthesized PDB identifiers take priority over model-extracted family names.
NFKB1 and NFKB2 AlphaFold models represent their precursors, not automatically the
processed p50/p52 domains; the chat prompt explains this distinction.

IL-6 and interleukin-6 resolve to IL6. Exact reviewed human UniProt accessions are
also accepted. Gene resolution retains species and refuses multiple identities.

Structures use validated AlphaFold coordinates, then experimental PDB entries
linked by UniProt if AlphaFold retrieval fails. Experimental fallback selects one
model, retains distinct annotated processed chains, and preserves nearby bound
ligands regardless of ligand chain ID. Source, accession, model, chain selection
and coordinate hash are retained. Identity and validated structures are cached
to survive repeat database outages; old unvalidated caches are not trusted.

Limits: public databases can be unavailable; fallback does not guarantee every
target is dockable or that a geometric pocket is biologically relevant. This
repair does not replace user-selected PDB structures, prove binding activity,
or invent missing ligand identities. Preparation failures remain real failures.

Local live verification prepared IL6/P05231, RELA/Q04206 and NFKB1/P19838 from
AlphaFold, and IL6/1ALU chain A via experimental fallback. These checks validate
retrieval and receptor preparation, not docking accuracy or activity.
