"""
MUMO Agent — Ligand Scout
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

WHAT THIS AGENT DOES (plain English)
------------------------------------
You give it a TARGET (a gene/protein name like "CFTR", or a ChEMBL target ID).
It goes to ChEMBL — a giant free public database of known drug molecules and how
strongly they bind to proteins — and brings back the most potent known ligands
for that target, each with its SMILES string (ready to hand to the Docking Engine).

So this powers the user request: "I have a target. Find me ligands."

HOW IT WORKS (3 steps)
    1. Look up the target by name  -> get its ChEMBL target ID
    2. Ask ChEMBL for the strongest measured activities against that target
    3. Return a clean, de-duplicated list of candidate molecules + SMILES

NO API KEY. NO COST. Pure public REST calls over the internet.
"""

import requests

CHEMBL = "https://www.ebi.ac.uk/chembl/api/data"
HEADERS = {"Accept": "application/json"}


def find_target_id(query, organism="Homo sapiens"):
    """
    Step 1: Turn a human name ('CFTR') into a ChEMBL target ID ('CHEMBL...').
    We prefer a SINGLE PROTEIN in humans — that is what we can dock.
    """
    if query.upper().startswith("CHEMBL"):
        return query.upper(), query  # user already gave us an ID

    url = f"{CHEMBL}/target/search.json"
    r = requests.get(url, params={"q": query}, headers=HEADERS, timeout=30)
    r.raise_for_status()
    targets = r.json().get("targets", [])

    # Prefer a human single-protein hit; otherwise take the first result.
    best = None
    for t in targets:
        if t.get("target_type") == "SINGLE PROTEIN" and t.get("organism") == organism:
            best = t
            break
    if best is None and targets:
        best = targets[0]
    if best is None:
        return None, None
    return best["target_chembl_id"], best.get("pref_name", query)


def find_ligands(target_query, limit=10, min_pchembl=6.0):
    """
    Step 2 + 3: Given a target, return the top candidate ligands.

    min_pchembl = potency cut-off. pChEMBL 6.0 ~ 1 micromolar; higher = stronger.
                  We keep only reasonably potent, real, measured binders.

    Returns: (target_name, list_of_ligand_dicts)
        each ligand = {chembl_id, smiles, activity_type, value, units, pchembl}
    """
    target_id, target_name = find_target_id(target_query)
    if not target_id:
        raise ValueError(f"Could not find a ChEMBL target for '{target_query}'.")

    url = f"{CHEMBL}/activity.json"
    params = {
        "target_chembl_id": target_id,
        "pchembl_value__gte": min_pchembl,     # only potent compounds
        "order_by": "-pchembl_value",          # strongest first
        "limit": 1000,                          # pull a pool, then de-dup below
    }
    r = requests.get(url, params=params, headers=HEADERS, timeout=60)
    r.raise_for_status()
    activities = r.json().get("activities", [])

    ligands = []
    seen = set()                                # de-duplicate: one row per molecule
    for a in activities:
        cid = a.get("molecule_chembl_id")
        smiles = a.get("canonical_smiles")
        if not cid or not smiles or cid in seen:
            continue
        seen.add(cid)
        ligands.append({
            "chembl_id": cid,
            "smiles": smiles,
            "activity_type": a.get("standard_type"),
            "value": a.get("standard_value"),
            "units": a.get("standard_units"),
            "pchembl": a.get("pchembl_value"),
        })
        if len(ligands) >= limit:
            break

    return target_name, ligands


# ─────────────────────────────────────────────────────────────────────────────
# DEMO — run live against CFTR (Project 2: cystic fibrosis target)
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    query = "CFTR"
    print("=" * 72)
    print(f"MUMO LIGAND SCOUT — finding top ligands for target: {query}")
    print("=" * 72)
    name, hits = find_ligands(query, limit=10)
    print(f"Target matched: {name}\n")
    print(f"{'#':<3}{'ChEMBL ID':<16}{'Type':<8}{'Value':<10}{'pChEMBL':<9}SMILES")
    print("-" * 72)
    for i, lig in enumerate(hits, 1):
        val = f"{lig['value']} {lig['units'] or ''}".strip()
        print(f"{i:<3}{lig['chembl_id']:<16}{str(lig['activity_type']):<8}"
              f"{val:<10}{str(lig['pchembl']):<9}{lig['smiles'][:30]}")
