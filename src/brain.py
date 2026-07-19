"""
MUMO — The Brain (conversational intent + report writing)
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

WHAT THIS DOES (plain English)
------------------------------
Two jobs, both powered by an LLM when a key is available, with a smart fallback
when it isn't:

  1. parse_intent(text)  — read a plain-English request and figure out what the
     user HAS (disease / target / ligand) and WANTS. Feeds the Router.
        "I have CFTR, find me a drug and dock it"
            -> {target: "CFTR", ligand: None, disease: None, want_dock: True}

  2. write_report(...)   — turn raw docking results into a clean, readable summary
     in the user's chosen tier (Simple / Standard / Ambitious).

If no LLM key is set, parse_intent uses keyword rules and write_report uses a
clean template — so MUMO always works.
"""

import re
import json
from router import UserRequest, route


# ─────────────────────────────────────────────────────────────────────────────
# INTENT PARSING
# ─────────────────────────────────────────────────────────────────────────────
_INTENT_SYSTEM = (
    "You are MUMO's intent parser for a drug-discovery platform. "
    "Read the user's message and output ONLY a JSON object with these keys: "
    "disease (string or null), target (a gene symbol or 4-char PDB ID, or null), "
    "ligand (if the user TYPED a SMILES string, return it exactly; if the user NAMED "
    "a drug/compound like 'aspirin', return that NAME as-is and do NOT convert it to "
    "SMILES — we look the structure up authoritatively; else null), "
    "want_admet (true/false). "
    "For 'target', if the user names a gene, return its CORRECT official human "
    "gene symbol — silently fix obvious typos and letter transpositions "
    "(e.g. CTRF->CFTR, EGRF->EGFR, TP35->TP53). If the user describes a protein in "
    "plain words (e.g. 'lung mucus protein'), map it to the right gene symbol "
    "(e.g. MUC5B). Default want_admet to true unless the user clearly only wants "
    "something else. Do not add any text outside the JSON."
)


def _llm_parse(text, llm):
    """Use the LLM to extract structured intent as JSON."""
    raw = llm.chat(_INTENT_SYSTEM, text, temperature=0.0, max_tokens=300)
    # pull the JSON object out (models sometimes wrap it in ```json fences)
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    data = json.loads(m.group(0) if m else raw)
    return {
        "disease": data.get("disease") or None,
        "target": data.get("target") or None,
        "ligand": data.get("ligand") or None,
        "want_admet": bool(data.get("want_admet", True)),
    }


# crude but useful patterns for the no-key fallback
_SMILES_RE = re.compile(r"^[A-Za-z0-9@+\-\[\]\(\)=#%/\\.]{4,}$")
_PDBID_RE = re.compile(r"\b([1-9][A-Za-z0-9]{3})\b")
_GENE_RE = re.compile(r"\b([A-Z][A-Z0-9]{2,5})\b")


def _looks_like_smiles(token):
    """A token is SMILES-ish if it has chemistry punctuation or ring atoms + digits.

    The cheap pattern alone is not enough: this function runs over whitespace-
    split words, and chemical NAME fragments like 'Cholan-24-oic' satisfy it
    (letters, a hyphen, digits) despite being nothing like a structure. Treating
    one as a ligand means docking a molecule the user never named, so when RDKit
    is available we let it settle the question — a string is SMILES only if it
    actually parses into a molecule.
    """
    if not _SMILES_RE.match(token):
        return False
    if not (re.search(r"[()=#\[\]]", token) or re.search(r"[cnoCNO].*\d", token)):
        return False
    try:
        from rdkit import Chem, RDLogger
        RDLogger.DisableLog("rdApp.*")   # a failed parse is an ANSWER here, not an error
        return Chem.MolFromSmiles(token) is not None
    except Exception:
        return True     # no RDKit — fall back to the heuristic verdict


# Words that follow "with"/"using" but are not molecules.
_NOT_A_LIGAND = {"the", "a", "an", "it", "this", "that", "them", "these", "those",
                 "high", "low", "more", "less", "default", "standard", "simple",
                 "ambitious", "vina", "mumo", "docking", "adme", "admet"}


def _rule_parse(text):
    """Keyword/pattern fallback when there is no LLM key.

    Also returns `actions`, so the no-key path routes through the same planner
    the LLM path uses instead of assuming every message means "dock".
    """
    disease = target = ligand = None
    low = text.lower()

    # 1) a SMILES anywhere in the message → ligand
    for tok in text.split():
        if _looks_like_smiles(tok):
            ligand = tok
            break

    # 1b) a NAMED ligand: "dock 1NFK with luteolin", "screen using quercetin".
    # Without this the fallback saw only SMILES, so an ordinary request like
    # "dock CFTR with aspirin" silently lost its ligand and scouted instead.
    if not ligand:
        m = re.search(r"\b(?:with|using|for)\s+([A-Za-z][A-Za-z0-9\-]{2,40})", text, re.I)
        if m and m.group(1).lower() not in _NOT_A_LIGAND:
            ligand = m.group(1)

    # 2) a PDB ID (1abc style) → target
    pid = _PDBID_RE.search(text)
    if pid and pid.group(1).upper() not in ("ADME",):
        target = pid.group(1).upper()

    # 3) gene near the word "target": "CFTR target" or "target CFTR/is CFTR"
    if not target:
        m = (re.search(r"\b([A-Z][A-Z0-9]{1,5})\b\s+(?:target|protein|receptor)", text)
             or re.search(r"target\s+(?:is\s+|protein\s+)?([A-Za-z0-9]{2,6})", text, re.I))
        if m:
            target = m.group(1).upper()

    # 4) disease cue words
    m = re.search(r"(?:disease|treat(?:ing)?|cure|against)\s+([a-z ]{3,40})", low)
    if m and not target:
        disease = m.group(1).strip().rstrip(".")

    # 5) last resort: a standalone gene-like ALL-CAPS token (e.g. CFTR, EGFR)
    if not target and not disease:
        STOP = {"I", "A", "MUMO", "ADME", "ADMET", "DNA", "RNA", "PDB", "AND",
                "THE", "FOR", "DOCK", "ME", "MY", "IT", "OK"}
        for tok in re.findall(r"\b[A-Z][A-Z0-9]{1,5}\b", text):
            if tok not in STOP and not _looks_like_smiles(tok):
                target = tok
                break

    want_admet = ("admet" in low or "adme" in low or "toxic" in low
                  or "absorption" in low or True)  # default on

    # Route through the same planner the LLM path uses, so without a key MUMO
    # still answers questions instead of docking them, and still honours a
    # multi-step request.
    try:
        import dispatch
        actions = dispatch.requested_actions(text)
    except Exception:
        actions = []
    return {"disease": disease, "target": target, "ligand": ligand,
            "want_admet": want_admet, "actions": actions}


def parse_intent(text, llm=None):
    """
    Turn a plain-English request into a structured intent dict + a Router plan.
    Returns: {intent: {...}, plan: [agent names], reason: str, used_llm: bool}
    """
    used_llm = False
    if llm is not None:
        try:
            intent = _llm_parse(text, llm)
            used_llm = True
        except Exception:
            intent = _rule_parse(text)
    else:
        intent = _rule_parse(text)

    req = UserRequest(disease=intent["disease"], target=intent["target"],
                      ligand=intent["ligand"], want_admet=intent["want_admet"])
    plan = route(req)
    return {"intent": intent, "plan": plan.steps, "reason": plan.reason, "used_llm": used_llm}


# ─────────────────────────────────────────────────────────────────────────────
# REPORT WRITING
# ─────────────────────────────────────────────────────────────────────────────
_REPORT_SYSTEM = {
    "Simple": "Write a short, friendly explanation for a non-scientist. No jargon. "
              "Explain what the result means in everyday language. If an estimated Ki, "
              "ligand efficiency, or reliability is given, explain each in plain words "
              "(e.g. a smaller Ki means tighter binding).",
    "Standard": "Write a concise technical summary for a researcher. Mention the binding "
                "affinity, the estimated Ki and ligand efficiency (define ligand efficiency "
                "as binding energy per heavy atom), the key interacting residues, the overall "
                "reliability of the result and why, and a brief interpretation.",
    "Ambitious": "Write a detailed, publication-style results paragraph (Vancouver tone): "
                 "binding affinity, estimated inhibition constant (Ki), ligand efficiency, "
                 "interaction profile, key residues, the reliability/validation of the run, "
                 "and significance.",
}


def write_report(results, llm=None, tier="Standard"):
    """
    results: a dict like
        {target, ligand, affinity, n_hbonds, hbond_residues, n_hydrophobic,
         interacting_residues, total_interactions}
    Returns a readable report string.
    """
    if llm is not None:
        try:
            system = (_REPORT_SYSTEM.get(tier, _REPORT_SYSTEM["Standard"])
                      + " Do not use any emojis; keep it clean and professional.")
            user = "Docking result:\n" + json.dumps(results, indent=2)
            return llm.chat(system, user, temperature=0.3, max_tokens=600)
        except Exception:
            pass  # fall through to template

    # template fallback (no LLM)
    res = results
    verdict = ("very strong" if res.get("affinity", 0) <= -8 else
               "good" if res.get("affinity", 0) <= -6 else
               "moderate" if res.get("affinity", 0) <= -4 else "weak")
    hb = ", ".join(res.get("hbond_residues", [])) or "none"
    stat_line = ""
    if res.get("estimated_ki") or res.get("ligand_efficiency") is not None:
        stat_line = (f"Estimated Ki: {res.get('estimated_ki','?')} "
                     f"(binding constant; smaller = tighter). "
                     f"Ligand efficiency: {res.get('ligand_efficiency','?')} kcal/mol per heavy atom.\n")
    rel_line = ""
    if res.get("reliability"):
        rel_line = f"Overall reliability: {res['reliability']}"
        if res.get("reliability_reason"):
            rel_line += f" ({res['reliability_reason']})"
        rel_line += ".\n"
    return (
        f"**{res.get('ligand','Ligand')} vs {res.get('target','target')}**\n\n"
        f"Best binding affinity: **{res.get('affinity','?')} kcal/mol** ({verdict} binding).\n"
        f"{stat_line}"
        f"Total interactions: {res.get('total_interactions','?')} "
        f"({res.get('n_hbonds',0)} hydrogen bonds, {res.get('n_hydrophobic',0)} hydrophobic).\n"
        f"Hydrogen-bond residues: {hb}.\n"
        f"Interacting residues: {', '.join(res.get('interacting_residues', [])) or 'n/a'}.\n"
        f"{rel_line}"
    )
