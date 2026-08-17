"""
MUMO Agent — Target Finder
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

WHAT THIS AGENT DOES (plain English)
------------------------------------
You give it a DISEASE ("cystic fibrosis", "asthma", "cystic bronchitis").
It returns the most evidence-backed PROTEIN TARGETS for that disease — each with
a score and a real database ID — so MUMO can then hand a target to the Ligand
Scout and Docking Engine.

This powers the hardest user request: "I only know the disease. Find the target."

WHY A DATABASE, NOT JUST AN LLM (important for selling MUMO)
-----------------------------------------------------------
We use Open Targets — a free, public platform (EMBL-EBI, Wellcome Sanger, GSK,
and others) that scores gene/disease links using REAL genetics, pathways, and
literature evidence. So every target MUMO suggests is TRACEABLE and CITABLE —
not invented by an AI. A GPT-4 conversation layer can sit on top later to explain
these results, but the science always comes from here.

NO API KEY. NO COST. Pure public GraphQL calls over the internet.
"""

import time
import requests

OT_API = "https://api.platform.opentargets.org/api/v4/graphql"


def _gql(query, variables, retries=3):
    """
    Tiny helper: send a GraphQL query to Open Targets and return the JSON data.
    If the server is briefly busy (e.g. 502/503/timeout), wait and try again a
    few times before giving up — public servers hiccup sometimes.
    """
    last_error = None
    for attempt in range(retries):
        try:
            r = requests.post(OT_API, json={"query": query, "variables": variables}, timeout=60)
            r.raise_for_status()
            payload = r.json()
            if "errors" in payload:
                raise RuntimeError(f"Open Targets error: {payload['errors']}")
            return payload["data"]
        except Exception as e:
            last_error = e
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))   # wait 2s, then 4s, then give up
    raise last_error


def find_disease_id(disease_name):
    """
    Step 1: Turn a disease name ('cystic fibrosis') into an Open Targets ID
    (an EFO/MONDO ID like 'EFO_0000341'). We take the best disease match.
    """
    query = """
    query Search($q: String!) {
      search(queryString: $q, entityNames: ["disease"], page: {index: 0, size: 1}) {
        hits { id name }
      }
    }
    """
    data = _gql(query, {"q": disease_name})
    hits = data["search"]["hits"]
    if not hits:
        return None, None
    return hits[0]["id"], hits[0]["name"]


def find_targets(disease_name, limit=10):
    """
    Step 2: Given a disease, return the top associated protein targets,
    ranked by Open Targets' overall association score (0..1, higher = stronger).

    Returns: (disease_name, list_of_target_dicts)
        each target = {symbol, ensembl_id, name, score}
    """
    disease_id, matched_name = find_disease_id(disease_name)
    if not disease_id:
        raise ValueError(f"Could not find a disease called '{disease_name}' in Open Targets.")

    query = """
    query Assoc($efoId: String!, $size: Int!) {
      disease(efoId: $efoId) {
        name
        associatedTargets(page: {index: 0, size: $size}) {
          rows {
            score
            target { id approvedSymbol approvedName }
          }
        }
      }
    }
    """
    data = _gql(query, {"efoId": disease_id, "size": limit})
    rows = data["disease"]["associatedTargets"]["rows"]

    targets = []
    for row in rows:
        t = row["target"]
        targets.append({
            "symbol": t["approvedSymbol"],
            "ensembl_id": t["id"],
            "name": t["approvedName"],
            "score": round(row["score"], 3),
        })
    return matched_name, targets


# ─────────────────────────────────────────────────────────────────────────────
# DEMO — run live for cystic fibrosis (Project 2) and cystic bronchitis (Project 1)
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    for disease in ["cystic fibrosis", "bronchitis"]:
        print("=" * 72)
        print(f"MUMO TARGET FINDER — disease: {disease}")
        print("=" * 72)
        try:
            name, targets = find_targets(disease, limit=10)
            print(f"Disease matched: {name}\n")
            print(f"{'#':<3}{'Gene':<12}{'Score':<8}{'Ensembl ID':<18}Full name")
            print("-" * 72)
            for i, t in enumerate(targets, 1):
                print(f"{i:<3}{t['symbol']:<12}{t['score']:<8}{t['ensembl_id']:<18}{t['name'][:30]}")
        except Exception as e:
            print(f"[Error] {e}")
        print()
