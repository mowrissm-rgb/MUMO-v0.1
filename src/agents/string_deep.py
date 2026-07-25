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
