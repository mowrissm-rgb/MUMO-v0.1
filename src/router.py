"""
MUMO Router — "The Brain"
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

WHAT THIS FILE DOES (plain English)
-----------------------------------
This is the part of MUMO that decides WHICH agents to run, and in WHAT ORDER,
based on what the user already has and what they want.

A real user can walk in from any starting point:
    - "Here is my target AND my ligand, just dock them."
    - "Here is my target, find me a ligand."
    - "I only know the disease — find the target AND a ligand for me."
    - "Here is a drug, just tell me its ADMET."

The Router reads the situation and builds a step-by-step PLAN (an ordered list
of agents). The rest of MUMO simply runs that plan. Nothing else in MUMO needs
to know about these rules — that is what makes it easy to add new agents later.

IMPORTANT: This version uses simple, FREE, rule-based logic (no paid LLM, no API
key). Later we can swap the `route()` function's insides for an LLM call without
changing anything else. The output format (a Plan) stays the same.
"""

from dataclasses import dataclass, field
from typing import List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# 1) THE "AGENTS" MUMO CAN CALL TODAY
#    (just names for now — each maps to a real module we build later)
# ─────────────────────────────────────────────────────────────────────────────
TARGET_FINDER  = "Target Finder"   # disease  -> druggable protein target(s)   [Open Targets]
TARGET_ANALYST = "Target Analyst"  # protein  -> cleaned + active site ready    [BioPython/P2Rank]
LIGAND_SCOUT   = "Ligand Scout"    # target   -> candidate ligands              [ChEMBL/PubChem]
DOCKING_ENGINE = "Docking Engine"  # target+ligand -> binding score            [AutoDock Vina]  ✅ already works
ADMET_ANALYST  = "ADMET Analyst"   # ligand   -> absorption/tox properties      [SwissADME/pkCSM]
REPORT_WRITER  = "Report Writer"   # everything-> one clean report              [LLM/template]


# ─────────────────────────────────────────────────────────────────────────────
# 2) WHAT THE USER GIVES US, AND THE PLAN WE GIVE BACK
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class UserRequest:
    """Everything we know about what the user has and wants."""
    disease: Optional[str] = None   # e.g. "cystic fibrosis"
    target:  Optional[str] = None   # e.g. a PDB ID "6LU7" or a gene "CFTR"
    ligand:  Optional[str] = None   # e.g. a SMILES string
    want_admet: bool = True         # almost always yes; user can turn off


@dataclass
class Plan:
    """The ordered list of agents MUMO will run, plus a human-readable reason."""
    steps: List[str] = field(default_factory=list)
    reason: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# 3) THE ROUTER ITSELF — the decision logic
# ─────────────────────────────────────────────────────────────────────────────
def route(req: UserRequest) -> Plan:
    """
    Look at what the user has, and build the pipeline.
    Read it top-to-bottom like a recipe: each 'if' fills a missing ingredient.
    """
    steps: List[str] = []

    # If we have NO target but we DO have a disease -> find the target first.
    if not req.target and req.disease:
        steps.append(TARGET_FINDER)

    # If we will have a target at all -> prepare it for docking.
    if req.target or req.disease:
        steps.append(TARGET_ANALYST)

    # If we have a target but NO ligand -> go find candidate ligands.
    if (req.target or req.disease) and not req.ligand:
        steps.append(LIGAND_SCOUT)

    # If we will have BOTH a target and a ligand -> dock them.
    if (req.target or req.disease) and (req.ligand or LIGAND_SCOUT in steps):
        steps.append(DOCKING_ENGINE)

    # ADMET runs whenever there is (or will be) a ligand and the user wants it.
    if req.want_admet and (req.ligand or LIGAND_SCOUT in steps):
        steps.append(ADMET_ANALYST)

    # A report is always the last thing — even an ADMET-only request gets one.
    if steps:
        steps.append(REPORT_WRITER)

    # Special case: user gave ONLY a ligand and wants ADMET (no target at all).
    if not steps and req.ligand and req.want_admet:
        steps = [ADMET_ANALYST, REPORT_WRITER]

    reason = _explain(req, steps)
    return Plan(steps=steps, reason=reason)


def _explain(req: UserRequest, steps: List[str]) -> str:
    """Build a one-line plain-English summary of the decision."""
    have = []
    if req.disease: have.append(f"disease='{req.disease}'")
    if req.target:  have.append(f"target='{req.target}'")
    if req.ligand:  have.append("ligand=given")
    have_str = ", ".join(have) if have else "nothing"
    return f"User has [{have_str}] -> run: {' -> '.join(steps) if steps else 'nothing (need more input)'}"


# ─────────────────────────────────────────────────────────────────────────────
# 4) DEMO — prove all four real-world scenarios route correctly
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    scenarios = {
        "A) Target + Ligand (just dock)":   UserRequest(target="6LU7", ligand="CC(=O)Oc1ccccc1C(=O)O"),
        "B) Target only (find a ligand)":   UserRequest(target="6LU7"),
        "C) Disease only (find both)":      UserRequest(disease="cystic fibrosis"),
        "D) Ligand only (ADME for a drug)": UserRequest(ligand="CC(=O)Nc1ccc(O)cc1"),
    }
    print("=" * 70)
    print("MUMO ROUTER — scenario test")
    print("=" * 70)
    for name, req in scenarios.items():
        plan = route(req)
        print(f"\n{name}")
        print(f"  {plan.reason}")
