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


import re as _re


def _name_candidates(name):
    """A short, ordered list of name spellings to try against PubChem.

    A hand-typed CAS name almost resolves but for punctuation PubChem is strict
    about: "cholan-24-oic acid,3,12-dioxo-,5 beta-" fails, while the exact
    "Cholan-24-oic acid, 3,12-dioxo-, (5.beta.)-" resolves. Two fixes cover the
    common cases:
      * stereo descriptors: "5 beta" / "5beta" / "(5beta)" -> "(5.beta.)"
      * a space after a comma that ENDS A WORD, while leaving locant lists like
        "3,12" (comma between two digits) untouched

    Every candidate is still an EXACT name lookup — so a match is always the
    compound with that name. PubChem autocomplete is deliberately NOT used: it
    returned "3-oxo" for a "3,12-dioxo" query in testing, i.e. a plausible but
    WRONG molecule, and silently docking the wrong compound is worse than
    saying "not found".
    """
    seen, out = set(), []

    def add(s):
        s = (s or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)

    add(name)
    stereo = _re.sub(r"\(?\b(\d+)\s*(alpha|beta|gamma|delta)\b\.?\)?",
                     r"(\1.\2.)", name, flags=_re.I)
    add(stereo)
    add(_re.sub(r"(?<=[^\d\s]),(?=\S)", ", ", stereo))
    add(_re.sub(r"(?<=[^\d\s]),(?=\S)", ", ", name))
    return out


def name_to_smiles(name):
    """Resolve a drug/compound NAME to a SMILES via PubChem. Returns None if not found.

    Tries the name as given first, then a few careful re-spellings (see
    _name_candidates) so a hand-typed CAS name with slightly-off punctuation
    still resolves instead of being reported as "not found". The extra lookups
    only happen when the first attempt fails, so a clean name still costs one
    request.
    """
    for candidate in _name_candidates(name):
        url = (f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
               f"{quote(candidate)}/property/SMILES,IsomericSMILES/JSON")
        try:
            r = requests.get(url, timeout=20)
            if r.status_code == 200:
                props = r.json()["PropertyTable"]["Properties"][0]
                smi = (props.get("SMILES") or props.get("IsomericSMILES")
                       or props.get("CanonicalSMILES"))
                if smi:
                    return smi
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


# ─────────────────────────────────────────────────────────────────────────────
# ADMET-AI — pretrained ML predictions (Therapeutics Data Commons / Chemprop)
# The RDKit panel above is transparent/rule-based; this adds real predictive
# tox/CYP/PK from validated ML models. Loaded lazily + cached (the models are
# heavy). Never raises — degrades to an empty panel so the rest of MUMO works.
# ─────────────────────────────────────────────────────────────────────────────

_ADMET_MODEL = None


def _get_admet_model():
    """Load the admet-ai model bundle once and cache it (≈40 Chemprop models)."""
    global _ADMET_MODEL
    if _ADMET_MODEL is None:
        from admet_ai import ADMETModel
        _ADMET_MODEL = ADMETModel()
    return _ADMET_MODEL


# Curated endpoints we surface: (friendly label, substring to find in the raw key,
# kind). "prob" = 0–1 risk/likelihood from a classifier; "reg" = numeric value.
# Matched by substring so minor naming differences in admet-ai don't break us.
_ADMET_PANEL = [
    # Absorption
    ("Caco-2 permeability (logPapp)", "Caco2_Wang", "reg"),
    ("HIA — intestinal absorption",   "HIA_Hou", "prob"),
    ("Oral bioavailability",          "Bioavailability_Ma", "prob"),
    ("P-gp inhibitor",                "Pgp_Broccatelli", "prob"),
    ("Aqueous solubility (logS)",     "Solubility_AqSolDB", "reg"),
    # Distribution
    ("BBB penetration",               "BBB_Martins", "prob"),
    ("Plasma protein binding (%)",    "PPBR_AZ", "reg"),
    ("Vol. of distribution (VDss)",   "VDss_Lombardo", "reg"),
    # Metabolism — CYP450 inhibition
    ("CYP1A2 inhibitor",              "CYP1A2_Veith", "prob"),
    ("CYP2C19 inhibitor",             "CYP2C19_Veith", "prob"),
    ("CYP2C9 inhibitor",              "CYP2C9_Veith", "prob"),
    ("CYP2D6 inhibitor",              "CYP2D6_Veith", "prob"),
    ("CYP3A4 inhibitor",              "CYP3A4_Veith", "prob"),
    # Excretion
    ("Hepatocyte clearance",          "Clearance_Hepatocyte", "reg"),
    ("Half-life",                     "Half_Life_Obach", "reg"),
    # Toxicity
    ("hERG blocker (cardiotox)",      "hERG", "prob"),
    ("Ames mutagenicity",             "AMES", "prob"),
    ("DILI (liver injury)",           "DILI", "prob"),
    ("Clinical toxicity",             "ClinTox", "prob"),
    ("Carcinogenicity",               "Carcinogen", "prob"),
    ("Acute toxicity (LD50)",         "LD50_Zhu", "reg"),
    ("Skin reaction",                 "Skin_Reaction", "prob"),
]


def admet_ml(smiles):
    """
    Run admet-ai (TDC pretrained models) on one SMILES → an ordered dict of the
    curated endpoints with friendly labels. Classification endpoints come back as
    probabilities (0–1); regression endpoints in their native units. Returns
    {"_error": msg} if admet-ai isn't available or the prediction fails, so the
    caller can show the transparent RDKit panel alone.
    """
    try:
        import pandas as pd
        model = _get_admet_model()
        preds = model.predict(smiles=smiles)
        if isinstance(preds, pd.DataFrame):
            raw = preds.iloc[0].to_dict()
        elif isinstance(preds, pd.Series):
            raw = preds.to_dict()
        else:
            raw = dict(preds)

        lut = {str(k).lower(): v for k, v in raw.items()}

        def _find(sub):
            sub = sub.lower()
            for lk, v in lut.items():
                if sub in lk and "percentile" not in lk and "drugbank" not in lk:
                    return v
            return None

        out = {}
        for label, sub, kind in _ADMET_PANEL:
            v = _find(sub)
            if v is None:
                continue
            try:
                out[label] = round(float(v), 3 if kind == "prob" else 2)
            except (TypeError, ValueError):
                out[label] = v
        return out or {"_error": "admet-ai returned no recognised endpoints"}
    except Exception as e:
        return {"_error": f"ADMET-AI unavailable: {e}"}


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
