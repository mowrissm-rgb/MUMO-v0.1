"""
MUMO — Action dispatch (pure logic, no Streamlit, no LLM)
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

WHAT THIS FIXES
---------------
Two failures the chat brain had, both structural rather than promptable:

1. STALLING. The action was whatever the LLM put in one JSON field. When it was
   unsure it defaulted to "chat" and asked a clarifying question — so a user who
   had ALREADY given the target and the ligand got asked for them again, reworded
   each time, and the run never started. A prompt can reduce that; it cannot
   remove it, because nothing downstream ever checked "do we actually have
   everything needed?" This module makes that a deterministic check the model
   cannot talk itself out of.

2. ONE TASK PER MESSAGE. "dock 1NFK with luteolin and then run ADME on it" is a
   single request with two steps, but `action` was one string, so the second
   step was silently dropped. Actions are a PLAN (an ordered list) here.

WHY IT LIVES IN ITS OWN MODULE
------------------------------
Everything here is pure: strings in, decisions out. No Streamlit, no network, no
native libraries. That means the intelligence is unit-testable on a laptop,
which matters in an app whose failures have all been unreproducible crashes in
native code. The Streamlit layer stays a thin caller.

THE CENTRAL RULE
----------------
Never ask for something you already have. If the slots an action needs are
present and the user asked for that action, run it — regardless of what the
model decided. Asking is only allowed when something is genuinely missing.
"""

import re

# What each action needs before it can run. A tuple of alternatives means "any
# one of these is enough" — docking works from an explicit target OR a disease
# it can derive the target from.
ACTION_SLOTS = {
    "dock":    (("target", "disease"),),
    "analyze": (("ligand",),),
    "string":  (("target",),),
    "blast":   (("target",),),
}

REAL_ACTIONS = tuple(ACTION_SLOTS)

# Keywords that name an action in the USER's own words. Ordered matching on
# position is what lets "dock X and then run ADME" produce [dock, analyze]
# rather than a single guess.
ACTION_CUES = {
    "analyze": (r"\badmet?\b", r"\bdrug-?likeness\b", r"\btoxicity\b", r"\btoxic\b",
                r"\bpharmacokinetic", r"\babsorption\b", r"\bbioavailab",
                r"\blipinski\b", r"\bherg\b", r"\bames\b"),
    "blast":   (r"\bblast\b", r"\bsequence similar", r"\bhomolog", r"\bsimilar protein"),
    "string":  (r"\bstring\b", r"\binteraction network\b", r"\bppi\b",
                r"\bfunctional partner", r"\bprotein[-–\s]protein\b", r"\bpathway network\b"),
    "dock":    (r"\bdock\b", r"\bdocking\b", r"\bbinding affinity\b", r"\bbind to\b",
                r"\bsimulat"),
}

# An imperative somewhere in the message is what separates "dock CFTR with
# aspirin" from "what is docking?". Without one, an action keyword is a topic,
# not a request.
RUN_VERBS = (r"\bdock\b", r"\brun\b", r"\banaly[sz]e\b", r"\bpredict\b", r"\bcheck\b",
             r"\bperform\b", r"\bdo\b", r"\bstart\b", r"\bcalculate\b", r"\bcompute\b",
             r"\bcompare\b", r"\bscreen\b", r"\btest\b", r"\bgo ahead\b", r"\bproceed\b",
             # requests are just as often phrased as "build/show me/get" as
             # "run"; without these, "build the interaction network for CFTR"
             # reads as having no imperative at all and silently stalls
             r"\bbuild\b", r"\bshow\b", r"\bgenerate\b", r"\bmake\b", r"\bget\b",
             r"\bgive\b", r"\bfind\b", r"\bfetch\b", r"\bmap\b", r"\bsearch\b",
             r"\bplot\b", r"\bdraw\b", r"\bneed\b", r"\bwant\b")

# Bare confirmations: the user is not naming an action, they are saying "yes, the
# thing we were just discussing". These are the replies that used to stall.
CONFIRMATIONS = (r"^\s*(yes|yep|yeah|yup|ok|okay|sure|please|go|go ahead|do it|run it|"
                 r"run|proceed|continue|start|carry on|of course|correct|right)\b[\s.!]*$")

QUESTION_STARTS = ("what", "what's", "whats", "how", "why", "when", "which", "who",
                   "is", "are", "was", "were", "can", "could", "should", "would",
                   "does", "do i", "did", "explain", "tell me", "teach", "define",
                   "describe", "meaning of")


def _norm(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def looks_like_question(text):
    """True if the message reads as a question or a request to be taught.

    This is the guard that keeps MUMO's teaching mode intact: "what is docking?"
    contains the word 'dock', and without this check the deterministic promoter
    would helpfully start a docking run instead of answering.
    """
    s = _norm(text).lower()
    if not s:
        return False
    if s.endswith("?"):
        return True
    return any(s.startswith(w + " ") or s == w for w in QUESTION_STARTS)


def is_confirmation(text):
    """True for a bare 'yes' / 'go ahead' / 'run it' with nothing else in it."""
    return bool(re.match(CONFIRMATIONS, _norm(text).lower()))


def missing_slots(action, convo):
    """Which required slots are absent for `action`. Empty list means ready."""
    convo = convo or {}
    gaps = []
    for group in ACTION_SLOTS.get(action, ()):
        if not any(convo.get(s) for s in group):
            gaps.append(" or ".join(group))
    return gaps


def is_ready(action, convo):
    """Can this action run right now with what we already know?"""
    return action in ACTION_SLOTS and not missing_slots(action, convo)


def requested_actions(text):
    """The actions the USER named, in the order they named them.

    Ordering by first mention is what makes multi-step requests work: in "dock
    1NFK with luteolin and then run the ADME prediction", 'dock' appears before
    'ADME', so the plan comes out [dock, analyze] without needing to parse
    "then" or trust the model to preserve sequence.

    Returns [] for questions and for messages with no imperative, so discussing
    a technique is never mistaken for asking to run it.
    """
    s = _norm(text)
    if not s or looks_like_question(s):
        return []
    low = s.lower()
    if not any(re.search(v, low) for v in RUN_VERBS):
        return []
    hits = []
    for action, patterns in ACTION_CUES.items():
        pos = min((m.start() for p in patterns
                   for m in [re.search(p, low)] if m), default=None)
        if pos is not None:
            hits.append((pos, action))
    return [a for _, a in sorted(hits)]


def plan(data, convo, user_msg, asked_last_turn=False):
    """Decide what to actually run this turn.

    `data` is the model's parsed JSON. Returns an ordered, de-duplicated list of
    ready-to-run actions — empty means "just reply".

    The model is trusted first, because it sees conversational nuance this
    module cannot. It is OVERRIDDEN in exactly two situations, both of which are
    the stall the user reported:

      * it chose to chat while the user plainly asked to run something we have
        everything for, and
      * it asked a clarifying question when nothing is actually missing —
        especially right after already asking one, which is the reworded-
        re-ask loop.

    Actions whose slots are missing are dropped, so a plan never contains a step
    that would immediately fail; the caller asks for the gap instead.
    """
    convo = convo or {}
    model = _model_actions(data)
    user = requested_actions(user_msg)

    # A bare "yes / go ahead" carries no action of its own: it authorises
    # whatever the conversation has been building toward.
    if not user and is_confirmation(user_msg):
        user = [a for a in ("dock", "analyze", "string", "blast") if is_ready(a, convo)][:1]

    if model:
        chosen = model
        # The user asked for more steps than the model planned — it dropped the
        # tail of a multi-part request. Keep the user's order, append the rest.
        if len(user) > len(chosen):
            chosen = _merge(user, chosen)
    elif user and (not looks_like_question(user_msg) or asked_last_turn):
        chosen = user                      # the model stalled; the user did not
    else:
        chosen = []

    return [a for a in _dedupe(chosen) if is_ready(a, convo)]


def model_actions(data):
    """The real actions the model committed to this turn (public wrapper)."""
    return _model_actions(data)


def _model_actions(data):
    """Normalise the model's output to a list of real actions.

    Accepts the new "actions" array and the older single "action" string, so a
    model reply in either shape keeps working.
    """
    data = data or {}
    raw = data.get("actions")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        raw = []
    if not raw and data.get("action"):
        raw = [data["action"]]
    return [a for a in (str(x).strip().lower() for x in raw) if a in REAL_ACTIONS]


def _merge(primary, secondary):
    """Everything from both, in `primary`'s order, extras appended."""
    out = list(primary)
    out.extend(a for a in secondary if a not in out)
    return out


def _dedupe(seq):
    seen, out = set(), []
    for a in seq:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def gap_prompt(action, convo):
    """A specific question for what's missing — never a generic re-ask.

    Naming the action and the gap ("To dock I still need a target…") is what
    stops the reworded loop: the user can see exactly which piece is absent
    instead of being asked the same vague thing again.
    """
    gaps = missing_slots(action, convo)
    if not gaps:
        return ""
    human = {"target or disease": "a target — a gene like CFTR, a 4-character PDB ID "
                                  "like 6LU7, or a disease I can derive one from",
             "target": "a target — a gene name or a 4-character PDB ID",
             "ligand": "a ligand — a drug name, a compound name, or a SMILES string"}
    need = human.get(gaps[0], gaps[0])
    verb = {"dock": "dock", "analyze": "run the ADMET analysis",
            "string": "build the interaction network", "blast": "run BLAST"}.get(action, action)
    return f"To {verb} I still need {need}."
