"""
MUMO — deep biology behind a STRING network.

WHAT THIS ADDS THAT STRING DOES NOT
-----------------------------------
STRING answers "what is connected to what, and how confident are we". It does
not tell you what any of those proteins actually DO. This module builds a
dossier for every protein in the network from UniProt:

  * molecular function   — GO F terms + the catalytic activity / EC number
  * biological process   — GO P terms
  * cellular component   — GO C terms (where in the cell it acts)
  * function prose       — UniProt's curated description
  * disease links        — curated disease involvement
  * domains              — structural/functional units in the sequence
  * sequence             — cached here so the phylogeny view costs no extra call

Everything is REST + stdlib + requests, which the image already has. No new
dependency: adding heavy packages has taken this Space down twice, and a
network report is not worth a third outage.

Failures are contained per-protein. A dossier that cannot be built comes back
empty rather than raising, so one unrecognised partner never costs the user
the whole report.
"""

from concurrent.futures import ThreadPoolExecutor

import requests

UNIPROT = "https://rest.uniprot.org/uniprotkb/search"
HUMAN = 9606

# UniProt prefixes GO terms with the aspect they belong to.
_ASPECT = {"F": "molecular_function", "P": "biological_process", "C": "cellular_component"}

_FIELDS = ",".join([
    "accession", "id", "protein_name", "gene_names", "length", "sequence",
    "cc_function", "cc_catalytic_activity", "cc_subcellular_location",
    "cc_disease", "ft_domain", "go_f", "go_p", "go_c",
])


def _first_text(comments, kind, limit=2):
    out = []
    for c in comments:
        if c.get("commentType") != kind:
            continue
        for t in c.get("texts", []) or []:
            v = (t.get("value") or "").strip()
            if v:
                out.append(v)
        if len(out) >= limit:
            break
    return out[:limit]


def _reactions(comments, limit=4):
    """CATALYTIC ACTIVITY does not use `texts` — the reaction lives in
    `reaction.name`, with the EC number alongside it. Reading it as prose
    silently returns nothing, which is how this was missed the first time.
    """
    out = []
    for c in comments:
        if c.get("commentType") != "CATALYTIC ACTIVITY":
            continue
        rx = c.get("reaction") or {}
        name = (rx.get("name") or "").strip()
        if name:
            out.append({"reaction": name, "ec": rx.get("ecNumber") or ""})
        if len(out) >= limit:
            break
    return out


def _locations(comments, limit=6):
    """SUBCELLULAR LOCATION is a third distinct shape: a list of
    `subcellularLocations[].location.value`, optionally with a topology.
    Three of UniProt's comment types store their payload somewhere other than
    `texts`, so each needs its own reader."""
    out = []
    for c in comments:
        if c.get("commentType") != "SUBCELLULAR LOCATION":
            continue
        for sl in c.get("subcellularLocations", []) or []:
            val = ((sl.get("location") or {}).get("value") or "").strip()
            if not val:
                continue
            topo = ((sl.get("topology") or {}).get("value") or "").strip()
            out.append(f"{val} ({topo})" if topo else val)
            if len(out) >= limit:
                return out
    return out


def _diseases(comments, limit=4):
    """DISEASE likewise carries a structured `disease` object, not `texts`."""
    out = []
    for c in comments:
        if c.get("commentType") != "DISEASE":
            continue
        d = c.get("disease") or {}
        name = (d.get("diseaseId") or "").strip()
        if not name:
            continue
        out.append({
            "name": name,
            "acronym": (d.get("acronym") or "").strip(),
            "description": _clean(d.get("description") or ""),
        })
        if len(out) >= limit:
            break
    return out


def _clean(text):
    """UniProt prose carries inline evidence tags — readable for a curator,
    noise for a beginner report. Strip '(PubMed:123, ECO:...)' style trailers."""
    import re
    text = re.sub(r"\s*\((?:PubMed|ECO|By similarity|Probable|Similarity)[^)]*\)", "", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def dossier(gene, species=HUMAN, timeout=30):
    """Everything UniProt knows about one protein, shaped for a report.

    Returns {} when the protein cannot be resolved — never raises, so a single
    bad name in a 20-protein network degrades that row and nothing else.
    """
    try:
        r = requests.get(UNIPROT, params={
            "query": f"gene:{gene} AND organism_id:{species} AND reviewed:true",
            "fields": _FIELDS, "format": "json", "size": "1",
        }, timeout=timeout)
        r.raise_for_status()
        hits = r.json().get("results") or []
        if not hits:
            return {}
        d = hits[0]
    except Exception:
        return {}

    comments = d.get("comments", []) or []

    go = {v: [] for v in _ASPECT.values()}
    for x in d.get("uniProtKBCrossReferences", []) or []:
        if x.get("database") != "GO":
            continue
        term = evidence = ""
        for p in x.get("properties", []) or []:
            if p.get("key") == "GoTerm":
                term = p.get("value") or ""
            elif p.get("key") == "GoEvidenceType":
                evidence = (p.get("value") or "").split(":")[0]
        if len(term) > 2 and term[1] == ":":
            aspect = _ASPECT.get(term[0])
            if aspect:
                go[aspect].append({"id": x.get("id"), "term": term[2:],
                                   "evidence": evidence})

    domains = []
    for f in d.get("features", []) or []:
        if f.get("type") != "Domain":
            continue
        loc = f.get("location", {})
        domains.append({
            "name": f.get("description") or "domain",
            "start": (loc.get("start") or {}).get("value"),
            "end": (loc.get("end") or {}).get("value"),
        })

    desc = d.get("proteinDescription", {}) or {}
    full = ((desc.get("recommendedName") or {}).get("fullName") or {}).get("value")

    return {
        "gene": gene,
        "accession": d.get("primaryAccession"),
        "entry": d.get("uniProtkbId") or d.get("id"),
        "protein_name": full or gene,
        "length": (d.get("sequence") or {}).get("length"),
        "sequence": (d.get("sequence") or {}).get("value") or "",
        "function": [_clean(t) for t in _first_text(comments, "FUNCTION")],
        "catalytic_activity": _reactions(comments),
        "ec_numbers": sorted({r["ec"] for r in _reactions(comments) if r["ec"]}),
        "subcellular_location": _locations(comments),
        "disease": _diseases(comments),
        "domains": domains[:8],
        "go": {k: v[:10] for k, v in go.items()},
        "go_counts": {k: len(v) for k, v in go.items()},
    }


def dossiers(genes, species=HUMAN, max_workers=8):
    """Dossiers for a whole network, fetched concurrently.

    Each lookup is an independent network round-trip with no shared state, so
    they parallelise cleanly — the same reasoning as the per-ligand narrative
    calls in report_writer. Order of the input list is preserved.
    """
    genes = [g for g in dict.fromkeys(genes) if g]
    if not genes:
        return {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(genes))) as ex:
        found = list(ex.map(lambda g: dossier(g, species), genes))
    return {g: d for g, d in zip(genes, found) if d}


# ── evidence channels ──────────────────────────────────────────────────────
# STRING scores each interaction through independent channels. The combined
# score hides WHY a link exists — two partners at 0.9 are not equivalent if one
# is backed by experiments and the other only by co-mention in abstracts.

CHANNELS = [
    ("escore", "Experiments"),
    ("dscore", "Databases"),
    ("ascore", "Co-expression"),
    ("nscore", "Neighbourhood"),
    ("fscore", "Fusion"),
    ("pscore", "Co-occurrence"),
    ("tscore", "Text mining"),
]


def evidence_matrix(partners, limit=15):
    """Partners x STRING channels, ready to draw as a heatmap.

    Returns {"rows": [name...], "cols": [label...], "values": [[float]...]}.
    """
    rows, values = [], []
    for p in partners[:limit]:
        name = p.get("preferredName_B") or p.get("stringId_B") or "?"
        row = []
        for key, _ in CHANNELS:
            try:
                row.append(max(0.0, min(1.0, float(p.get(key) or 0.0))))
            except (TypeError, ValueError):
                row.append(0.0)
        rows.append(name)
        values.append(row)
    return {"rows": rows, "cols": [lab for _, lab in CHANNELS], "values": values}


def dominant_channel(partner):
    """The single strongest line of evidence for one interaction — what a
    reader actually wants to know about a link."""
    best, best_v = "", -1.0
    for key, label in CHANNELS:
        try:
            v = float(partner.get(key) or 0.0)
        except (TypeError, ValueError):
            v = 0.0
        if v > best_v:
            best, best_v = label, v
    return (best, round(best_v, 3)) if best_v > 0 else ("", 0.0)


# ── sequence-similarity tree ───────────────────────────────────────────────
# The dossiers already carry sequences, so clustering the network by sequence
# costs no extra network call.
#
# HONEST LABELLING: this is k-mer distance + UPGMA, not a multiple-sequence
# alignment with a substitution model. It answers "which of these proteins are
# built from similar sequence" — family structure, paralogues, shared domains —
# and it is fast and deterministic. It is NOT a publication phylogeny, and the
# rendered figure says so. A real one needs an MSA plus FastTree/IQ-TREE, which
# are native binaries this image deliberately does not carry.

def _kmers(seq, k=3):
    seq = (seq or "").upper()
    if len(seq) < k:
        return {}
    counts = {}
    for i in range(len(seq) - k + 1):
        km = seq[i:i + k]
        counts[km] = counts.get(km, 0) + 1
    return counts


def _cosine_distance(a, b):
    """1 - cosine similarity over shared k-mer counts. Bounded [0, 1], and
    unlike raw identity it does not need the sequences to be the same length."""
    if not a or not b:
        return 1.0
    common = a.keys() & b.keys()
    dot = sum(a[k] * b[k] for k in common)
    na = sum(v * v for v in a.values()) ** 0.5
    nb = sum(v * v for v in b.values()) ** 0.5
    if not na or not nb:
        return 1.0
    return max(0.0, min(1.0, 1.0 - dot / (na * nb)))


def distance_matrix(named_sequences, k=3):
    """[(name, seq)] -> (labels, DxD list-of-lists of distances)."""
    labels = [n for n, s in named_sequences if s]
    profs = [_kmers(s, k) for _, s in named_sequences if s]
    n = len(labels)
    D = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = _cosine_distance(profs[i], profs[j])
            D[i][j] = D[j][i] = d
    return labels, D


def upgma(labels, D):
    """Average-linkage tree. Returns a nested dict:
       {"name":..., "height":0}  |  {"children":[l, r], "height": h}

    UPGMA rather than neighbour-joining because the result is ultrametric —
    every leaf ends at the same depth — which draws as an honest rectangular
    dendrogram without needing a root to be guessed.
    """
    nodes = [{"name": lab, "height": 0.0, "_n": 1} for lab in labels]
    D = [row[:] for row in D]
    idx = list(range(len(nodes)))

    while len(idx) > 1:
        bi, bj, best = None, None, float("inf")
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                d = D[idx[a]][idx[b]]
                if d < best:
                    best, bi, bj = d, a, b
        i, j = idx[bi], idx[bj]
        ni, nj = nodes[i]["_n"], nodes[j]["_n"]
        merged = {"children": [nodes[i], nodes[j]], "height": best / 2.0,
                  "_n": ni + nj}
        nodes.append(merged)
        new = len(nodes) - 1
        # extend the matrix for the new node, average-linkage
        for row in D:
            row.append(0.0)
        D.append([0.0] * (len(D) + 1))
        for other in idx:
            if other in (i, j):
                continue
            d = (D[i][other] * ni + D[j][other] * nj) / (ni + nj)
            D[new][other] = D[other][new] = d
        idx = [x for x in idx if x not in (i, j)] + [new]

    root = nodes[idx[0]]

    def strip(node):
        node.pop("_n", None)
        for c in node.get("children", []):
            strip(c)
        return node

    return strip(root)


def similarity_tree(dossier_map):
    """{gene: dossier} -> UPGMA tree over their sequences, or None."""
    pairs = [(g, d.get("sequence", "")) for g, d in (dossier_map or {}).items()]
    pairs = [(g, s) for g, s in pairs if s]
    if len(pairs) < 3:
        return None
    labels, D = distance_matrix(pairs)
    return upgma(labels, D)


# ── report text ────────────────────────────────────────────────────────────

def biology_blocks(dossier_map, order=None, limit=12):
    """Dossiers -> ordered, display-ready blocks.

    One shared shape for the app panel and the .docx, so the two renderings
    cannot drift apart the way a screen-only feature usually does.

    Each block: {gene, protein_name, accession, length, summary,
                 rows: [(label, text), ...]}
    """
    doss = dossier_map or {}
    keys = [g for g in (order or list(doss)) if g in doss][:limit]
    blocks = []
    for g in keys:
        d = doss[g]
        rows = []

        mf = [t["term"] for t in d.get("go", {}).get("molecular_function", [])][:5]
        bp = [t["term"] for t in d.get("go", {}).get("biological_process", [])][:5]
        cc = [t["term"] for t in d.get("go", {}).get("cellular_component", [])][:4]
        if mf:
            rows.append(("Molecular function", "; ".join(mf)))
        if d.get("catalytic_activity"):
            rx = d["catalytic_activity"][0]
            txt = rx["reaction"] + (f"  (EC {rx['ec']})" if rx.get("ec") else "")
            rows.append(("Catalytic activity", txt))
        elif d.get("ec_numbers"):
            rows.append(("Enzyme class", ", ".join(f"EC {e}" for e in d["ec_numbers"])))
        if bp:
            rows.append(("Biological process", "; ".join(bp)))
        if cc:
            rows.append(("Found in", "; ".join(cc)))
        elif d.get("subcellular_location"):
            rows.append(("Found in", "; ".join(d["subcellular_location"][:3])))
        if d.get("domains"):
            rows.append(("Domains", "; ".join(x["name"] for x in d["domains"][:4])))
        if d.get("disease"):
            dis = "; ".join(
                f"{x['name']}" + (f" ({x['acronym']})" if x.get("acronym") else "")
                for x in d["disease"][:3])
            rows.append(("Disease links", dis))

        summary = (d.get("function") or [""])[0]
        if len(summary) > 420:
            summary = summary[:418].rsplit(" ", 1)[0] + "…"

        blocks.append({
            "gene": g,
            "protein_name": d.get("protein_name") or g,
            "accession": d.get("accession") or "",
            "length": d.get("length"),
            "summary": summary,
            "rows": rows,
        })
    return blocks


# ── druggability ───────────────────────────────────────────────────────────
# A network tells you what a protein is connected to. It does not tell you
# whether anyone can actually drug it — which is the question that decides
# whether a partner is a lead worth chasing or a dead end.

CHEMBL = "https://www.ebi.ac.uk/chembl/api/data"


def _chembl_target(accession, timeout=45):
    """UniProt accession -> ChEMBL SINGLE PROTEIN target id.

    Queried by ACCESSION, not by name: the dossiers already carry accessions,
    and a gene symbol can match several ChEMBL entries. The same lookup for
    EGFR returns 16 targets, most of them PROTEIN FAMILY groupings — taking
    the first hit would attribute a family's drugs to one protein.
    """
    try:
        r = requests.get(f"{CHEMBL}/target",
                         params={"target_components__accession": accession,
                                 "format": "json"}, timeout=timeout)
        r.raise_for_status()
        for t in r.json().get("targets") or []:
            if t.get("target_type") == "SINGLE PROTEIN":
                return t.get("target_chembl_id"), t.get("pref_name") or ""
    except Exception:
        pass
    return None, ""


def _phase_label(phase):
    try:
        p = float(phase)
    except (TypeError, ValueError):
        return "preclinical"
    if p >= 4:
        return "approved"
    if p >= 1:
        return f"phase {int(p)}"
    return "preclinical"


def druggability(accession, timeout=45, max_drugs=6):
    """What is known to modulate this protein, from ChEMBL.

    Returns {} when the protein is not in ChEMBL — which is itself a finding,
    not an error, and is reported as such rather than as a failure.
    """
    if not accession:
        return {}
    tid, tname = _chembl_target(accession, timeout)
    if not tid:
        return {"target_chembl_id": None, "verdict": "not in ChEMBL",
                "drugs": [], "n_mechanisms": 0, "approved": 0}

    try:
        m = requests.get(f"{CHEMBL}/mechanism",
                         params={"target_chembl_id": tid, "format": "json",
                                 "limit": 60}, timeout=timeout)
        m.raise_for_status()
        mech = m.json()
        rows = mech.get("mechanisms") or []
        total = (mech.get("page_meta") or {}).get("total_count", len(rows))
    except Exception:
        return {"target_chembl_id": tid, "target_name": tname,
                "verdict": "lookup failed", "drugs": [], "n_mechanisms": 0,
                "approved": 0}

    by_mol = {}
    for x in rows:
        mid = x.get("molecule_chembl_id")
        if mid and mid not in by_mol:
            by_mol[mid] = {"action": x.get("action_type") or "",
                           "moa": x.get("mechanism_of_action") or ""}
    drugs = []
    if by_mol:
        ids = ",".join(list(by_mol)[:40])
        try:
            d = requests.get(f"{CHEMBL}/molecule",
                             params={"molecule_chembl_id__in": ids, "format": "json",
                                     "limit": 40,
                                     "only": "molecule_chembl_id,pref_name,max_phase"},
                             timeout=timeout)
            d.raise_for_status()
            for mol in d.json().get("molecules") or []:
                mid = mol.get("molecule_chembl_id")
                meta = by_mol.get(mid) or {}
                try:
                    phase = float(mol.get("max_phase") or 0)
                except (TypeError, ValueError):
                    phase = 0.0
                drugs.append({
                    "chembl_id": mid,
                    "name": (mol.get("pref_name") or mid or "").title(),
                    "phase": phase,
                    "stage": _phase_label(phase),
                    "action": (meta.get("action") or "").title(),
                    "moa": meta.get("moa") or "",
                })
        except Exception:
            pass

    drugs.sort(key=lambda x: (-x["phase"], x["name"]))
    approved = sum(1 for x in drugs if x["phase"] >= 4)
    if approved:
        verdict = f"{approved} approved drug{'s' if approved > 1 else ''}"
    elif any(1 <= x["phase"] < 4 for x in drugs):
        verdict = "in clinical trials"
    elif drugs or total:
        verdict = "chemical tools only"
    else:
        verdict = "no known modulators"

    return {"target_chembl_id": tid, "target_name": tname, "verdict": verdict,
            "n_mechanisms": total, "approved": approved,
            "drugs": drugs[:max_drugs]}


def druggability_map(dossier_map, max_workers=6, limit=12):
    """{gene: druggability} for a whole network, fetched concurrently.

    Skips proteins with no accession — without one the lookup would fall back
    to name matching, which is exactly the ambiguity this avoids.
    """
    items = [(g, d.get("accession")) for g, d in (dossier_map or {}).items()
             if d.get("accession")][:limit]
    if not items:
        return {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as ex:
        got = list(ex.map(lambda it: druggability(it[1]), items))
    return {g: r for (g, _), r in zip(items, got) if r}
