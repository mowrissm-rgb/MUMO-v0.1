"""
MUMO — the specialist registry.

WHY THIS EXISTS
---------------
MUMO has been taken down three times by the same failure: one heavy native
component segfaults (exit 139) and the whole container dies, chat included.
Splitting the native stack into its own service means a Vina crash can kill
docking without touching STRING, BLAST or the chat itself.

This module is the single place that answers three questions:

    which specialist owns this capability?
    where does it live, and is it up?
    what do we tell the user when it is the wrong specialist, or down?

Nothing here performs work. It is a lookup table plus the referral wording, so
routing decisions are declarative and testable without deploying anything.

ROLLBACK BY CONFIG, NOT BY CODE
-------------------------------
Every specialist has an `endpoint` read from the environment. When it is unset
the capability is served LOCALLY, exactly as it is today. That is what makes
the migration reversible: unset the variable and MUMO is a monolith again, with
no code change and no redeploy of the front door.
"""

import os

# ── capabilities ───────────────────────────────────────────────────────────
# These names match the `action` values the router already produces, so the
# existing dispatch does not have to learn a new vocabulary.

SPECIALISTS = {
    "A": {
        "id": "A",
        "name": "Docking & structure",
        "blurb": "molecular docking, poses, interactions and backbone geometry",
        "capabilities": ("dock", "ramachandran", "md", "structure"),
        "env": "MUMO_SPACE_DOCKING",
        # The heavy native stack. This is the one that has historically
        # segfaulted, and the whole reason for the split.
        "heavy": True,
    },
    "B": {
        "id": "B",
        "name": "Sequence & network",
        "blurb": "STRING interaction networks, BLAST homology and sequence relationships",
        "capabilities": ("string", "blast", "phylogeny"),
        "env": "MUMO_SPACE_SEQUENCE",
        "heavy": False,
    },
    "C": {
        "id": "C",
        "name": "Cheminformatics",
        "blurb": "ADMET prediction, metabolism and drug-likeness",
        "capabilities": ("admet", "metabolism", "druglikeness"),
        "env": "MUMO_SPACE_CHEM",
        "heavy": False,
    },
    "D": {
        "id": "D",
        "name": "Reporting",
        "blurb": "full .docx reports, figures and structure exports",
        "capabilities": ("report", "export"),
        "env": "MUMO_SPACE_REPORT",
        "heavy": True,          # carries Chromium
    },
}

# capability -> specialist id, built once and asserted unique so a capability
# can never be silently claimed by two specialists.
OWNER = {}
for _sid, _spec in SPECIALISTS.items():
    for _cap in _spec["capabilities"]:
        assert _cap not in OWNER, f"capability {_cap!r} claimed twice"
        OWNER[_cap] = _sid


def owner_of(capability):
    """Which specialist should handle this action, or None if unclaimed."""
    return OWNER.get((capability or "").strip().lower())


def specialist(sid):
    return SPECIALISTS.get((sid or "").upper())


def endpoint(sid):
    """Base URL for a specialist, or None when it is served locally.

    Unset env var means "run it in this process", which is today's behaviour —
    so an un-migrated capability keeps working untouched.
    """
    spec = specialist(sid)
    if not spec:
        return None
    url = (os.environ.get(spec["env"]) or "").strip().rstrip("/")
    return url or None


def is_remote(capability):
    return endpoint(owner_of(capability)) is not None


def referral(capability, current_sid):
    """What a non-specialist says when handed work outside its speciality.

    Mowriss asked for this to read as professional and academic: state the
    better-suited specialist, but do not refuse — offering to run it anyway is
    the difference between helpful and obstructive.
    """
    owner = owner_of(capability)
    if not owner or owner == current_sid:
        return ""
    them, me = specialist(owner), specialist(current_sid)
    if not them:
        return ""
    mine = f" My own speciality is {me['blurb']}." if me else ""
    return (f"A note on scope: {capability} analysis is handled by the "
            f"{them['name']} specialist, which is optimised for {them['blurb']}."
            f"{mine} I can still run this for you here — results are identical, "
            f"the specialist is simply better resourced for it.")


def unavailable(capability):
    """Degrade loudly: name what is down, and confirm what still works.

    The point of the split is that one dead specialist is a missing feature,
    not a dead product — so this message always says what is still available.
    """
    owner = owner_of(capability)
    them = specialist(owner) if owner else None
    label = them["name"] if them else (capability or "that capability")
    others = [s["name"] for sid, s in SPECIALISTS.items()
              if sid != owner and endpoint(sid) is not None]
    if others:
        verb = "is" if len(others) == 1 else "are"
        listed = others[0] if len(others) == 1 else (
            ", ".join(others[:-1]) + " and " + others[-1])
        tail = f" Everything else is unaffected — {listed} {verb} running normally."
    else:
        tail = ""
    return (f"The {label} service is temporarily unavailable, so I can't run "
            f"{capability} right now.{tail} Your conversation and results are "
            f"saved; try this again shortly.")


def status_table():
    """Every specialist, where it lives and how it is being served — for the
    sidebar and for health checks."""
    rows = []
    for sid, spec in SPECIALISTS.items():
        url = endpoint(sid)
        rows.append({
            "id": sid,
            "name": spec["name"],
            "capabilities": ", ".join(spec["capabilities"]),
            "mode": "remote" if url else "local",
            "endpoint": url or "",
            "heavy": spec["heavy"],
        })
    return rows
