"""
MUMO — Ligand pre-flight screening
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

WHY THIS EXISTS
---------------
Docking is expensive and its native stack is fragile. Feeding it a molecule it
can never handle wastes minutes of free-tier CPU and, at worst, dies inside
native code where Python can't catch it. Every check in here is CHEAP and PURE
(regex + optional RDKit) so it runs in milliseconds, long before Vina is
touched, and can be unit-tested without Vina or a GPU.

The two failures this was written for, both seen in the wild:

1. SILICON. AutoDock Vina has no atom type for Si — a silicon ligand is not
   "hard to dock", it is undockable, and the failure surfaces deep in ligand
   prep as an opaque parse error.

2. DERIVATIZED GC-MS ENTRIES. A GC-MS run reports compounds AFTER silylation,
   so the peak list is full of trimethylsilyl (TMS) esters/ethers. Those are
   artifacts of sample preparation, not the natural products actually present
   in the plant — docking them answers a question nobody asked. They also
   happen to contain silicon, so they fail anyway, but the user deserves to be
   told WHY rather than just "failed".

Everything here degrades gracefully: no check ever raises, and if RDKit is
missing the regex path still catches the important cases.
"""

import re

# Vina's atom typing has no parameters for these. Silicon is the one we have
# actually been bitten by; the rest are listed because they fail the same way
# and it is cheaper to say so up front than to let ligand prep discover it.
UNSUPPORTED_ELEMENTS = {
    "Si": "silicon",
    "B": "boron",
    "Se": "selenium",
    "Te": "tellurium",
    "As": "arsenic",
    "Sn": "tin",
}

# Name fragments that mark a GC-MS silylation artifact rather than a real
# natural product. Matched case-insensitively against the compound NAME.
_DERIVATIZATION_MARKERS = (
    "trimethylsilyl",
    "tert-butyldimethylsilyl",
    "tbdms",
    "silyl",
    "siloxane",
    "silane",
    "tms derivative",
)

# A bracketed atom is the only way silicon can appear in valid SMILES — Si is
# not in the organic subset, so it must be written [Si], [SiH3], [Si@], etc.
_BRACKET_ATOM_RE = re.compile(r"\[([0-9]*)([A-Z][a-z]?)")


def elements_in_smiles(smiles):
    """Element symbols appearing in a SMILES string.

    Only bracketed atoms are inspected. That is deliberate: every element we
    care about here (Si, Se, Sn, …) is outside the organic subset and therefore
    *must* be bracketed, while scanning bare text would misread the 'S' of a
    sulfur or the 'C'+'l' of an aliphatic chain.
    """
    if not smiles:
        return set()
    return {m.group(2) for m in _BRACKET_ATOM_RE.finditer(str(smiles))}


def unsupported_elements(smiles):
    """The unsupported elements present in this SMILES, as a sorted list.

    Uses RDKit when it is importable (authoritative — it understands the real
    molecular graph) and falls back to the bracket-atom regex otherwise, so
    this stays useful in a lightweight environment.
    """
    try:
        from rdkit import Chem
        m = Chem.MolFromSmiles(str(smiles))
        if m is not None:
            found = {a.GetSymbol() for a in m.GetAtoms()}
            return sorted(found & set(UNSUPPORTED_ELEMENTS))
    except Exception:
        pass
    return sorted(elements_in_smiles(smiles) & set(UNSUPPORTED_ELEMENTS))


def looks_derivatized(name):
    """True if the compound NAME looks like a GC-MS silylation artifact."""
    if not name:
        return False
    low = str(name).lower()
    return any(marker in low for marker in _DERIVATIZATION_MARKERS)


def looks_truncated(name):
    """True if a compound name looks cut off mid-phrase.

    Chemical names routinely contain spaces and commas ('Benzenepropanoic acid,
    methyl ester'), so a list split on whitespace leaves stubs. This flags them
    so an unresolvable name can be EXPLAINED rather than silently dropped.

    Deliberately does NOT treat a trailing hyphen as truncation: CAS index
    nomenclature legitimately ends that way ('2(3H)-Furanone, 5-heptyldihydro-'
    is a complete, dockable compound). Treating it as damage would reject a
    large fraction of a real GC-MS peak list.
    """
    if not name:
        return False
    s = str(name).strip()
    if s.endswith((",", "(")):
        return True
    # a bare acid stem with no following 'acid' is the classic whitespace-split
    # stub: 'Benzenepropanoic acid' → 'Benzenepropanoic'
    return bool(re.search(r"(?:^|[\s-])\w*oic$", s, re.I))


def normalize_name(name):
    """Tidy a pasted compound name: collapse whitespace, drop stray trailing
    punctuation. Does NOT try to repair a truncated name — guessing at the
    missing half would silently dock the wrong molecule."""
    if name is None:
        return ""
    return re.sub(r"\s+", " ", str(name)).strip().strip(",;").strip()


def _reject(name, smiles, code, reason):
    return {"ok": False, "name": name, "smiles": smiles, "code": code, "reason": reason}


def precheck_name(name):
    """Screen a ligand by NAME ALONE, before any structure lookup.

    Returns a rejection dict, or None if the name is worth resolving. Kept
    separate from the structure check so an obviously-useless entry never costs
    a PubChem round-trip.
    """
    clean = normalize_name(name)
    if not clean:
        return _reject("", None, "empty", "Empty ligand entry.")
    if looks_derivatized(clean):
        return _reject(clean, None, "derivatized",
                       f"**{clean}** is a trimethylsilyl (TMS) derivative — an artifact of GC-MS "
                       f"sample preparation, not a compound that exists in the plant. It also "
                       f"contains silicon, which AutoDock Vina cannot dock. Dock the parent "
                       f"compound instead (the name without the silyl group).")
    return None


def postcheck_structure(name, smiles):
    """Screen a ligand once its structure is known.

    Returns a rejection dict, or None if it is safe to dock. This is the check
    that catches silicon hiding behind an innocuous-looking name.
    """
    clean = normalize_name(name)
    bad = unsupported_elements(smiles)
    if bad:
        elems = ", ".join(UNSUPPORTED_ELEMENTS[b] for b in bad)
        return _reject(clean, smiles, "unsupported_element",
                       f"**{clean}** contains {elems} ({', '.join(bad)}), which AutoDock Vina has "
                       f"no atom parameters for — it cannot be docked.")
    return None


def unresolved(name):
    """A rejection dict for a name no database could resolve to a structure.

    Truncation is diagnosed HERE rather than used as a veto of its own: a
    cut-off name is only a problem because nothing can look it up, and saying
    'your list got split' is far more actionable than 'compound not found'.
    """
    raw = str(name or "").strip()
    clean = normalize_name(name)
    if looks_truncated(raw) or looks_truncated(clean):
        return _reject(clean, None, "truncated",
                       f"**{clean}** looks like a cut-off compound name, so I couldn't look it up. "
                       f"If you pasted a list, put one compound per line — names containing spaces "
                       f"and commas get split apart otherwise.")
    return _reject(clean, None, "unresolved",
                   f"I couldn't find a structure for **{clean}** in PubChem. Check the spelling, or "
                   f"give me its SMILES directly.")


def check_ligand(name, smiles=None):
    """Convenience wrapper: run whichever checks the available data supports.

    Returns {"ok", "name", "smiles", "code", "reason"}. Never raises.
    """
    verdict = precheck_name(name)
    if verdict:
        return verdict
    if smiles:
        verdict = postcheck_structure(name, smiles)
        if verdict:
            return verdict
    return {"ok": True, "name": normalize_name(name), "smiles": smiles,
            "code": "ok", "reason": ""}


def screen(items):
    """Screen a list of ligands (names, or {label, smiles} dicts).

    Returns (accepted, rejected) where `accepted` keeps the caller's original
    item objects untouched and `rejected` is a list of check_ligand dicts.
    Screening never removes everything silently — the caller is expected to
    tell the user what was dropped and why.
    """
    accepted, rejected = [], []
    for it in (items or []):
        if isinstance(it, dict):
            name, smi = it.get("label"), it.get("smiles")
        else:
            name, smi = it, None
        verdict = check_ligand(name, smi)
        if verdict["ok"]:
            accepted.append(it)
        else:
            rejected.append(verdict)
    return accepted, rejected


def rejection_message(rejected):
    """A single plain-language chat message explaining what was skipped.

    Written for beginners, in line with MUMO's house style: say what was
    dropped, why, and what to do about it — never a bare error code.
    """
    if not rejected:
        return ""
    if len(rejected) == 1:
        return "I skipped one ligand:\n\n- " + rejected[0]["reason"]
    lines = "\n".join(f"- {r['reason']}" for r in rejected)
    return f"I skipped {len(rejected)} ligands:\n\n{lines}"
