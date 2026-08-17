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


# A leading list enumerator that leaked into a pasted name — "35) ", "35. ",
# "35 - ", "• ", "- ". Stripped before lookup so a numbered list ("35) Autotaxin-
# IN-5") resolves as the compound, not the literal "35) …" PubChem never has.
# Deliberately narrow: the number must be followed by a real delimiter + space,
# so chemical locants like "2-acetyl", "1,2-dimethyl" or "5 beta" are left alone.
_LIST_MARKER_RE = re.compile(
    r"^\s*(?:\d{1,3}\s*[.)\]:]\s+"     # 35)  35.  35]  35:
    r"|\d{1,3}\s+[-–—]\s+"   # 35 -  (number, space, dash, space)
    r"|[•·*▪‣◦]\s+"   # bullet glyphs
    r"|[-–—]\s+)"            # dash bullet
)


def normalize_name(name):
    """Tidy a pasted compound name: collapse whitespace, strip a leading list
    number/bullet, drop stray trailing punctuation. Never repairs a truncated
    name — guessing the missing half would silently dock the wrong molecule."""
    if name is None:
        return ""
    s = re.sub(r"\s+", " ", str(name)).strip()
    s = _LIST_MARKER_RE.sub("", s).strip()
    return s.strip(",;").strip()


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


# ── splitting a pasted list into individual ligands ────────────────────────

# NOTE: a numeric marker is "1)" / "1." / "1:" and never "1-", because "1-Butanol"
# and "2-Furanmethanol" start with a locant. A bullet must be followed by
# whitespace for the same reason.
_LIST_MARKER = re.compile(r"^\s*(?:\d+\s*[\).:]\s*|[\-\*•]\s+)")


def _is_cas_continuation(frag, chain_open=False):
    """True if this comma-fragment continues the PREVIOUS name rather than
    starting a new one.

    CAS index nomenclature inverts the parent and its substituents, so one
    compound is written with commas inside it:

        Phenol, o-(benzylthio)-
        Propanamide, N-(4-ethoxyphenyl)-
        1-Butanol, 3-methyl-, acetate

    Splitting those on commas would shatter real GC-MS entries into nonsense,
    which is why this is a merge rule and not a plain str.split. A continuation
    fragment carries its own CAS marker (a locant, a substituent prefix, or the
    trailing hyphen CAS uses) — EXCEPT the plain-word case ("acetate" above),
    which has no marker of its own and is only a continuation because the
    fragment before it was ITSELF still open (ended in "-"). Without that
    `chain_open` gate, a plain lowercase compound name — "aspirin", "lupeol" —
    looks identical to "acetate" and a whole comma-separated list of ordinary
    names collapses into one unresolvable string. That is not hypothetical: it
    is exactly what happened with "lupeol, pytol, aspirin".
    """
    f = (frag or "").strip()
    if not f:
        return True
    if f.endswith("-"):
        return True
    if re.match(r"^[0-9]", f) and not re.match(r"^[0-9].*\b(acid|ol|one|ate|ine|al)\b", f, re.I):
        return True                                  # "3-methyl-", but not "2-Methoxy-4-vinylphenol"
    if re.match(r"^[NOSPC]-", f):                    # "N-(4-ethoxyphenyl)-"
        return True
    # "(E)-piperolein" continues a name; "(E)-Piperolein A" is its own compound
    if re.match(r"^\([RSEZ0-9,\-]+\)-?[a-z]", f):
        return True
    if chain_open and re.match(r"^[a-z][a-z ]*$", f):  # "acetate" — only inside an open chain
        return True
    return False


def split_ligand_names(text):
    """A pasted blob of ligand names -> a list of individual names.

    The model sometimes returns fifteen compounds as ONE comma-separated
    string. Passing that straight to PubChem looks up a 200-character
    non-existent compound and reports "one ligand" that could not be found —
    which is what happened, and why it looked like a spelling problem when
    every name was spelled correctly.

    Newlines, semicolons and list markers always separate. Commas separate only
    where they are not part of a CAS name (see _is_cas_continuation) and not
    between digits, so "3,4-Methylenedioxycinnamic acid" stays intact.
    """
    if isinstance(text, (list, tuple)):
        # already split by the caller; flatten one level in case an entry is
        # itself a pasted blob
        out = []
        for item in text:
            out.extend(split_ligand_names(item))
        return out
    if not isinstance(text, str):
        return [text] if text else []

    # hard separators first: newlines and semicolons are never inside a name
    chunks = [c for c in re.split(r"[\n;]+", text) if c.strip()]

    out = []
    for chunk in chunks:
        chunk = _LIST_MARKER.sub("", chunk.strip())
        # protect commas between digits ("3,4-") before splitting
        guarded = re.sub(r"(?<=\d),(?=\d)", "\x00", chunk)
        parts = [p.strip() for p in guarded.split(",")]
        merged = []
        for p in parts:
            p = p.replace("\x00", ",")
            # "X, Y, and Z" — "and"/"or" is an English list connector, not part
            # of the last compound's name; strip it before anything else sees it.
            p = re.sub(r"^(?:and|or)\s+", "", p, flags=re.I).strip()
            if not p:
                continue
            chain_open = bool(merged) and merged[-1].endswith("-")
            if merged and _is_cas_continuation(p, chain_open):
                merged[-1] = merged[-1] + ", " + p      # put the CAS name back together
            else:
                merged.append(p)
        out.extend(m for m in (x.strip(" ,") for x in merged) if m)
    return out
