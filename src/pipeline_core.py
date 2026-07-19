"""
MUMO — Pipeline core (UI-agnostic, no Streamlit)
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

The ENTIRE docking run — resolve target, scout ligands, dock, score, write the
narrative report — with NO Streamlit calls, so it can run either:
  • in the foreground of the chat app (the stable fallback path), or
  • inside a detached SUBPROCESS worker (dock_runner.py), where `st.*` would
    have no ScriptRunContext.

Progress is reported through a `progress(message)` callback the caller supplies.
The return value is a plain, JSON-friendly dict the caller turns into UI:

    {"ok": True,
     "rows":  [ {col: val, …}, … ],   # sorted best→worst, ready for a DataFrame
     "meta":  {gene, pocket, exhaustiveness, replicas, validation, reliability_by},
     "viz":   { label: {"pdb": <cropped complex PDB text>, "ia": {...}} },  # serialize_viz form
     "say_text": "<the assistant's chat message with the report>",
     "tier":  "Standard"}

  or  {"ok": False, "say_text": "<a plain user-facing message>", "tier": …}
      when there's nothing to dock (no target / no ligands found).

Raising is fine too — the caller (foreground try/except, or the subprocess
worker) turns an exception into a clean error message.
"""

import os
import re


def build_target(c, data_dir):
    """Turn the chosen target string into a dockable target dict (gene or PDB ID).
    Pure version of the chat app's build_target — takes an explicit data_dir
    instead of a module global."""
    import requests
    from agents.target_analyst import auto_grid_from_pdb  # lazy: pulls in gemmi
    t = c["target"]
    if re.match(r"^[1-9][A-Za-z0-9]{3}$", t):       # PDB ID — fetch from RCSB
        content = None
        for _ in range(3):
            try:
                r = requests.get(f"https://files.rcsb.org/download/{t}.pdb", timeout=45)
                if r.status_code == 200 and r.content:
                    content = r.content
                    break
            except Exception:
                pass
        if content is None:
            raise RuntimeError(f"Couldn't download {t} from RCSB (network was slow). Please try again.")
        raw = os.path.join(data_dir, f"{t}_chat.pdb")
        with open(raw, "wb") as f:
            f.write(content)
        center, size, pocket = auto_grid_from_pdb(raw)
        return {"gene": t, "pdb_path": raw, "center": center, "size": size,
                "source": f"PDB {t} · {pocket}"}
    return {"gene": t, "pdb_path": None, "center": None, "size": None, "source": "gene (AlphaFold)"}


def run_job(convo, vina, data_dir, venv, llm=None, progress=lambda m: None):
    """Run the whole docking pipeline for one chat request. See module docstring
    for the return contract. `convo` is the chat's conversation dict (disease /
    target / ligand_objs / n_ligands / tier)."""
    from agents.target_finder import find_targets
    from agents.ligand_scout import find_ligands
    from pipeline import dock_pipeline
    from brain import write_report
    from viz import serialize_viz
    import pandas as pd

    c = dict(convo or {})
    tier = c.get("tier") or "Standard"

    # resolve a disease into its top target (Open Targets) if we don't have one
    if not c.get("target") and c.get("disease"):
        progress(f"Finding the top target for {c['disease']}…")
        try:
            _, tl = find_targets(c["disease"], 5)
            if tl:
                c["target"] = tl[0]["symbol"]
        except Exception:
            pass
    if not c.get("target"):
        return {"ok": False, "tier": tier,
                "say_text": "I couldn't pin down a target — tell me a gene, PDB ID, or disease."}

    tgt = build_target(c, data_dir)

    if c.get("ligand_objs"):
        ligands = c["ligand_objs"]
    else:
        n = c.get("n_ligands") or 3
        progress(f"Scouting {n} ligands for {tgt['gene']}…")
        try:
            _, ligs = find_ligands(tgt["gene"], limit=n)
        except Exception:
            ligs = []
        ligands = [{"label": l["chembl_id"], "smiles": l["smiles"]} for l in ligs]

    # Final gate before anything native touches these. The chat app already
    # screens what the USER typed, but scouted ligands arrive straight from
    # ChEMBL and have never been checked — and this function is also the entry
    # point for the subprocess worker, so this is the one place guaranteed to
    # run on every docking path.
    import ligand_check as lc
    ligands, rejected = lc.screen(ligands)
    skipped_note = ("\n\n" + lc.rejection_message(rejected)) if rejected else ""

    if not ligands:
        base = (f"I couldn't find ligands to dock against **{tgt['gene']}**. "
                f"Scouting works for gene/protein targets, not raw PDB IDs — "
                f"tell me a specific ligand, e.g. *“dock {tgt['gene']} with aspirin”*.")
        if rejected:
            # Be precise: we DID have candidates, they were all undockable.
            base = (f"None of the ligands could be docked against **{tgt['gene']}**.")
        return {"ok": False, "tier": tier, "say_text": base + skipped_note}

    rows, viz, meta = dock_pipeline(tgt, ligands, vina, data_dir, venv, status=progress)

    rdf = pd.DataFrame(rows)
    num = pd.to_numeric(rdf["Best affinity (kcal/mol)"], errors="coerce")
    rdf = rdf.assign(_s=num).sort_values("_s").drop(columns="_s").reset_index(drop=True)
    sorted_rows = rdf.to_dict(orient="records")

    meta_store = {k: meta.get(k) for k in
                  ("gene", "pocket", "exhaustiveness", "replicas", "validation", "reliability_by")}

    # narrative report on the best hit
    top = rdf.iloc[0]
    if str(top["Best affinity (kcal/mol)"]) != "FAILED":
        def _sp(v):
            return [x for x in str(v).split("; ") if x and x != "-"]
        _rel = (meta.get("reliability_by") or {}).get(top["Ligand"], {})
        rep = write_report({"target": meta["gene"], "ligand": top["Ligand"],
                            "affinity": float(top["Best affinity (kcal/mol)"]),
                            "estimated_ki": top.get("Est. Ki"),
                            "ligand_efficiency": top.get("Ligand efficiency"),
                            "reliability": top.get("Reliability"),
                            "reliability_reason": _rel.get("reason"),
                            "total_interactions": top["Total interactions"],
                            "n_hbonds": int(top["H-bonds"]), "hbond_residues": _sp(top["H-bond residues"]),
                            "n_hydrophobic": int(top["Hydrophobic"]),
                            "interacting_residues": _sp(top["All interacting residues"])},
                           llm, tier)
        msd = top.get("Mean ± SD (kcal/mol)", "—")
        rep_note = (f" (mean ± SD {msd}, confidence {top.get('Confidence','—')})"
                    if msd and msd != "—" else "")
        val = meta.get("validation")
        val_note = ""
        if val:
            verdict = "<2 Å — setup validated" if val["passed"] else ">2 Å — interpret with care"
            val_note = (f" Setup validation: native ligand {val['resname']} redocked to "
                        f"{val['rmsd']} Å RMSD ({verdict}).")
        say_text = (f"Done. Best hit **{top['Ligand']}** at **{top['Best affinity (kcal/mol)']} "
                    f"kcal/mol**{rep_note} against {meta['gene']} "
                    f"[exhaustiveness {meta.get('exhaustiveness','?')}, {meta.get('replicas','?')} replica(s)]."
                    f"{val_note} Full results & 3D pose are below.\n\n{rep}")
    else:
        say_text = "The docking didn't produce a valid pose — see the results below."

    # a ligand that was screened out must be accounted for even on a good run,
    # so the results table is never quietly shorter than what the user asked for
    return {"ok": True, "rows": sorted_rows, "meta": meta_store,
            "viz": serialize_viz(viz), "say_text": say_text + skipped_note, "tier": tier}
