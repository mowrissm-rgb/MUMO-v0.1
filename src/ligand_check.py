"""
MUMO — Ligand resolution helpers (NO chemistry filtering)
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

DESIGN INTENT — READ THIS FIRST
-------------------------------
MUMO must attempt ANY ligand the user gives, against ANY target. It does NOT
decide a compound is "not a real phytochemical" and refuse it, and it does NOT
pre-reject a molecule because AutoDock Vina lacks parameters for one of its
atoms. Those were both here once; they were removed on purpose. Vina's real
limits surface at the point of an actual dock (the ligand appears as FAILED in
the results table, with the reason), not as a gate that second-guesses the
user's input.

The ONLY things this module still stops are genuine dead ends, which are not
"filtering":
  * an empty entry — there is literally nothing to dock
  * a name no database can resolve to any structure — there is nothing to
    hand to Vina

Docking now runs in a crash-isolated subprocess, so a ligand Vina cannot
handle produces a clean per-ligand failure, never an app crash — which is what
makes "attempt everything" safe.

The element/derivatization DETECTION helpers are kept (they are accurate and
occasionally useful for an explanatory note), but nothing here calls them to
REJECT a ligand any more.
"""

import re

# Elements AutoDock Vina has no atom parameters for. Kept for optional
# annotation only — NOT used to skip a ligand. If one of these is present the
# dock may fail, and the user will see that failure with its reason, having
# asked for the attempt.
UNSUPPORTED_ELEMENTS = {
    "Si": "silicon",
    "B": "boron",
    "Se": "selenium",
    "Te": "tellurium",
    "As": "arsenic",
    "Sn": "tin",
}

_BRACKET_ATOM_RE = re.compile(r"\[([0-9]*)([A-Z][a-z]?)")


def elements_in_smiles(smiles):
    """Element symbols appearing in bracketed atoms of a SMILES string."""
    if not smiles:
        return set()
    return {m.group(2) for m in _BRACKET_ATOM_RE.finditer(str(smiles))}


def unsupported_elements(smiles):
    """Vina-unsupported elements present in a SMILES, as a sorted list.

    Detection only — informational. Used to EXPLAIN a failure if the user
    wants, never to prevent a dock being attempted.
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


def normalize_name(name):
    """Tidy a pasted compound name: collapse whitespace, drop stray trailing
    punctuation. Never repairs a truncated name — guessing the missing half
    would silently dock the wrong molecule."""
    if name is None:
        return ""
    return re.sub(r"\s+", " ", str(name)).strip().strip(",;").strip()


def looks_truncated(name):
    """True if a compound name looks cut off mid-phrase.

    Only used to make an UNRESOLVABLE name's message more helpful ("your list
    got split"), never to reject on its own — a full CAS name legitimately
    ends in a hyphen.
    """
    if not name:
        return False
    s = str(name).strip()
    if s.endswith((",", "(")):
        return True
    return bool(re.search(r"(?:^|[\s-])\w*oic$", s, re.I))


def _reject(name, smiles, code, reason):
    return {"ok": False, "name": name, "smiles": smiles, "code": code, "reason": reason}


def precheck_name(name):
    """Screen a ligand by NAME before structure lookup.

    Only stops a genuinely empty entry now — there is nothing to resolve or
    dock. Everything else is allowed through to be attempted, by design.
    """
    clean = normalize_name(name)
    if not clean:
        return _reject("", None, "empty", "Empty ligand entry.")
    return None


def postcheck_structure(name, smiles):
    """Screen a ligand once its structure is known.

    Intentionally never rejects. Kept as a stable hook so callers don't change
    shape, and so re-enabling a check later (if ever wanted) is a one-line
    edit here rather than a change spread across the pipeline.
    """
    return None


def unresolved(name):
    """A rejection dict for a name no database could resolve to a structure.

    This is a genuine dead end, not filtering: if PubChem has no structure and
    the text is not itself a valid SMILES, there is nothing to dock.
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
                   f"give me its SMILES directly and I'll dock it.")


def check_ligand(name, smiles=None):
    """Convenience wrapper. Returns {"ok", "name", "smiles", "code", "reason"}.

    Only an empty entry is not ok; any real ligand is accepted for docking.
    """
    verdict = precheck_name(name)
    if verdict:
        return verdict
    return {"ok": True, "name": normalize_name(name), "smiles": smiles,
            "code": "ok", "reason": ""}


def screen(items):
    """Pass ligands through for docking, dropping ONLY empty entries.

    Returns (accepted, rejected). `accepted` keeps the caller's original item
    objects untouched. `rejected` now only ever holds empty entries — no
    chemistry-based filtering happens here.
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
    """A single plain-language chat message for what couldn't be attempted."""
    if not rejected:
        return ""
    if len(rejected) == 1:
        return "I couldn't attempt one ligand:\n\n- " + rejected[0]["reason"]
    lines = "\n".join(f"- {r['reason']}" for r in rejected)
    return f"I couldn't attempt {len(rejected)} ligands:\n\n{lines}"
