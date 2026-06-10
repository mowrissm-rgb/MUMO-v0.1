"""
MUMO Agent — ADMET / Drug-likeness panel
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

WHAT THIS DOES (plain English)
------------------------------
Given a molecule (SMILES), compute a full medicinal-chemistry ADMET profile —
the numbers a med-chemist uses to judge whether a molecule could become an oral drug:

  • Physicochemistry — MW, LogP, H-bond donors/acceptors, TPSA, rotatable bonds,
    aromatic rings, fraction sp3 carbons, heavy atoms, molar refractivity.
  • Drug-likeness rule sets — Lipinski (Ro5), Veber, Ghose, Egan + QED + lead-likeness.
  • Developability — synthetic accessibility (1 easy → 10 hard) and structural-alert
    counts (PAINS reactive/assay-interfering substructures, Brenk unwanted groups).
  • Absorption (rule-based predictions) — GI absorption and blood-brain-barrier (BBB).

It also resolves a drug NAME (e.g. "aspirin") into a SMILES via PubChem.

All free — RDKit (local) + PubChem (public). No API key. The absorption calls are
transparent literature rules (Egan/SwissADME-style), labelled as predictions — not a
black box, which keeps every number defensible.
"""

from urllib.parse import quote
import requests
from rdkit import Chem
from rdkit.Chem import Descriptors, Lipinski, Crippen, QED, rdMolDescriptors


def is_valid_smiles(s):
    """True if the string parses as a real molecule."""
    return bool(s) and Chem.MolFromSmiles(s) is not None


def name_to_smiles(name):
    """Resolve a drug/compound NAME to a SMILES via PubChem. Returns None if not found."""
    url = (f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
           f"{quote(name)}/property/SMILES,IsomericSMILES/JSON")
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 200:
            props = r.json()["PropertyTable"]["Properties"][0]
            return props.get("SMILES") or props.get("IsomericSMILES") or props.get("CanonicalSMILES")
    except Exception:
        pass
    return None


def _synthetic_accessibility(m):
    """SA score 1 (easy) → 10 (hard). Optional — returns None if the contrib module is absent."""
    try:
        import os, sys
        from rdkit.Chem import RDConfig
        sa_dir = os.path.join(RDConfig.RDContribDir, "SA_Score")
        if sa_dir not in sys.path:
            sys.path.append(sa_dir)
        import sascorer
        return round(sascorer.calculateScore(m), 2)
    except Exception:
        return None


def _alert_count(m, catalog_name):
    """Count structural-alert hits (PAINS / BRENK) via RDKit's FilterCatalog. 0 on failure."""
    try:
        from rdkit.Chem import FilterCatalog
        params = FilterCatalog.FilterCatalogParams()
        cat = getattr(FilterCatalog.FilterCatalogParams.FilterCatalogs, catalog_name)
        params.AddCatalog(cat)
        catalog = FilterCatalog.FilterCatalog(params)
        return len(catalog.GetMatches(m))
    except Exception:
        return 0


def druglikeness(smiles):
    """
    Full ADMET / drug-likeness panel for one SMILES.
    Returns an ordered dict of Property -> Value, ready to show as a table.
    (Name kept as `druglikeness` for backward compatibility with the chat app.)
    """
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        raise ValueError(f"Invalid SMILES: {smiles}")

    # ── physicochemistry ──
    mw   = Descriptors.MolWt(m)
    logp = Crippen.MolLogP(m)
    mr   = Crippen.MolMR(m)
    hbd  = Lipinski.NumHDonors(m)
    hba  = Lipinski.NumHAcceptors(m)
    tpsa = Descriptors.TPSA(m)
    rotb = Lipinski.NumRotatableBonds(m)
    arom = Lipinski.NumAromaticRings(m)
    csp3 = rdMolDescriptors.CalcFractionCSP3(m)
    heavy = m.GetNumHeavyAtoms()
    qed  = QED.qed(m)

    # ── drug-likeness rule sets (pass/fail) ──
    ro5_viol = sum([mw > 500, logp > 5, hbd > 5, hba > 10])
    lipinski = "Pass" if ro5_viol == 0 else f"{ro5_viol} violation(s)"
    veber = "Pass" if (rotb <= 10 and tpsa <= 140) else "Fail"
    ghose = "Pass" if (160 <= mw <= 480 and -0.4 <= logp <= 5.6
                       and 40 <= mr <= 130 and 20 <= heavy <= 70) else "Fail"
    egan = "Pass" if (tpsa <= 131.6 and logp <= 5.88) else "Fail"
    lead_like = "Yes" if (mw <= 350 and logp <= 3.5) else "No"

    # ── developability ──
    sa = _synthetic_accessibility(m)
    pains = _alert_count(m, "PAINS")
    brenk = _alert_count(m, "BRENK")

    # ── absorption (transparent rule-based predictions) ──
    gi_abs = "High" if (tpsa <= 131.6 and logp <= 5.88) else "Low"
    bbb = "Likely" if (tpsa <= 79 and 0.4 <= logp <= 6.0) else "Unlikely"

    verdict = ("Drug-like (passes Ro5)" if ro5_viol == 0 else
               "1 Ro5 violation" if ro5_viol == 1 else
               f"{ro5_viol} Ro5 violations")

    out = {
        "MW (g/mol)": round(mw, 1),
        "LogP": round(logp, 2),
        "H-bond donors": hbd,
        "H-bond acceptors": hba,
        "TPSA (Å²)": round(tpsa, 1),
        "Rotatable bonds": rotb,
        "Aromatic rings": arom,
        "Fraction Csp3": round(csp3, 2),
        "Heavy atoms": heavy,
        "Molar refractivity": round(mr, 1),
        "QED (0–1)": round(qed, 3),
        "Lipinski (Ro5)": lipinski,
        "Veber": veber,
        "Ghose": ghose,
        "Egan": egan,
        "Lead-like": lead_like,
        "Synthetic accessibility (1–10)": sa if sa is not None else "n/a",
        "PAINS alerts": pains,
        "Brenk alerts": brenk,
        "GI absorption (pred.)": gi_abs,
        "BBB permeant (pred.)": bbb,
        "Verdict": verdict,
    }
    return out


def resolve_ligand(text):
    """
    Turn whatever the user gave (a SMILES or a drug name) into a valid SMILES.
    Returns (smiles, label) or (None, None) if it can't be resolved.
    """
    if is_valid_smiles(text):
        return text, "your molecule"
    smi = name_to_smiles(text)
    if smi and is_valid_smiles(smi):
        return smi, text          # keep the friendly name as the label
    return None, None


if __name__ == "__main__":
    for q in ["aspirin", "ibuprofen", "imatinib"]:
        smi, label = resolve_ligand(q)
        print(f"\n{q}  ->  {smi}  ({label})")
        if smi:
            for k, v in druglikeness(smi).items():
                print(f"   {k}: {v}")
