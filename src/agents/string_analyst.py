"""
MUMO Agent — STRING Interaction Analyst
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

WHAT THIS AGENT DOES (plain English)
------------------------------------
You give it a protein (a gene name like 'CFTR', or a whole set/family).
It goes to STRING — a free public database of known + predicted protein–protein
interactions — and brings back:

  • the interaction NETWORK picture (who this protein works with),
  • the top functional PARTNERS, each with a confidence score (0–1) built from
    several evidence channels (experiments, curated databases, co-expression,
    text-mining, gene neighbourhood, fusion, co-occurrence),
  • functional ENRICHMENT — the pathways / GO terms / KEGG maps the neighbourhood
    is over-represented in (what biology this cluster is doing).

For Project 1 (multiple cystic-bronchitis targets) this shows how those targets
wire together into pathways; for Project 2 it maps a mucolytic enzyme's partners.

All free — STRING REST API, no key. Pure `requests`, no new dependencies.
"""

from urllib.parse import quote
import requests

STRING_API = "https://string-db.org/api"
HUMAN = 9606


def _ids_param(identifiers):
    """STRING joins multiple identifiers with a carriage-return (%0d)."""
    if isinstance(identifiers, (list, tuple)):
        return "%0d".join(quote(str(i)) for i in identifiers if str(i).strip())
    return quote(str(identifiers))


def _get(method_path, params, timeout=30):
    url = f"{STRING_API}/{method_path}?{params}"
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r


def resolve_ids(identifiers, species=HUMAN):
    """Map names → STRING's preferred names + annotation. [] if none recognised."""
    r = _get("json/get_string_ids",
             f"identifiers={_ids_param(identifiers)}&species={species}&limit=1&echo_query=1")
    try:
        return r.json()
    except Exception:
        return []


def interaction_partners(identifiers, species=HUMAN, limit=20):
    """Top functional partners with combined + per-channel scores."""
    r = _get("json/interaction_partners",
             f"identifiers={_ids_param(identifiers)}&species={species}&limit={limit}")
    return r.json()


def network_svg(identifiers, species=HUMAN, add_nodes=12):
    """The STRING network as an SVG string (crisp inline render). '' on failure."""
    try:
        r = _get("svg/network",
                 f"identifiers={_ids_param(identifiers)}&species={species}"
                 f"&add_white_nodes={add_nodes}&network_flavor=confidence")
        return r.text
    except Exception:
        return ""


def enrichment(identifiers, species=HUMAN):
    """Functional enrichment (GO / KEGG / Reactome …) for a set of proteins."""
    try:
        r = _get("json/enrichment",
                 f"identifiers={_ids_param(identifiers)}&species={species}")
        return r.json()
    except Exception:
        return []


def analyze_string(identifiers, species=HUMAN, limit=20):
    """
    Full STRING report for one protein or a set. Returns a dict:
      input, resolved, partners, network_svg, enrichment, species.
    Raises ValueError only if STRING can't recognise ANY of the proteins.
    """
    resolved = resolve_ids(identifiers, species)
    if not resolved:
        raise ValueError(
            f"STRING didn't recognise “{identifiers}”. Try an official gene symbol "
            f"(e.g. CFTR, EGFR) or a UniProt/Ensembl id.")
    names = [x["preferredName"] for x in resolved]

    partners = interaction_partners(names, species, limit)

    # enrichment is meaningful for a SET — feed the protein(s) + their top partners
    enr_set = list(dict.fromkeys(names + [p["preferredName_B"] for p in partners[:12]]))
    enr = enrichment(enr_set, species) if len(enr_set) > 2 else []

    return {
        "input": names,
        "resolved": resolved,
        "partners": partners,
        "network_svg": network_svg(names, species),
        "enrichment": enr,
        "species": species,
    }


if __name__ == "__main__":
    res = analyze_string("CFTR")
    print("input:", res["input"])
    print("partners:", len(res["partners"]))
    for p in res["partners"][:8]:
        print(f"  {p['preferredName_B']:12s} score={round(p['score'],3)}")
    print("network svg chars:", len(res["network_svg"]))
    print("enrichment terms:", len(res["enrichment"]))
