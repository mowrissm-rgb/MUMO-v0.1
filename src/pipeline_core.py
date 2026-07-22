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


def structure_validation(target, data_dir, progress=lambda m: None):
    """Fetch a target's structure and run backbone-geometry validation on it.

    Deliberately reuses docking's OWN structure path — build_target then
    resolve_receptor then clean_protein_pdb — so the geometry reported is for
    exactly the structure that would be docked, not a separately-fetched copy
    that might differ (a different AlphaFold version, say). Validating a
    different structure than the one you dock would be worse than not
    validating at all.

    Returns the ramachandran.compute() result with a "gene"/"source" added,
    or {"_error": ...}.
    """
    import os as _os
    import ramachandran
    from pipeline import resolve_receptor
    from docking_engine import clean_protein_pdb

    name = target[0] if isinstance(target, list) else target
    name = str(name or "").strip()
    if not name:
        return {"_error": "No target given."}

    progress(f"Fetching the {name} structure…")
    tgt = build_target({"target": name}, data_dir)
    pdb_path, _c, _s, pocket = resolve_receptor(tgt, data_dir)
    cleaned = _os.path.join(data_dir, "rama_cleaned.pdb")
    clean_protein_pdb(pdb_path, cleaned)

    progress("Measuring backbone torsion angles…")
    with open(cleaned) as f:
        res = ramachandran.compute(f.read())
    if res.get("_error"):
        return res
    res["gene"] = tgt.get("gene", name)
    res["source"] = tgt.get("source") or pocket
    return res


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

    # One request can name SEVERAL targets ("dock luteolin against CFTR and
    # EGFR"). Docking each in turn and merging the rows gives ONE ranked table
    # across the whole set, which is the actual question a multi-target screen
    # asks — running them as separate jobs would produce N reports the user then
    # has to compare by hand.
    targets = c["target"] if isinstance(c["target"], list) else [c["target"]]
    targets = [str(t).strip() for t in targets if str(t or "").strip()]
    multi = len(targets) > 1

    # Ligands are scouted against the FIRST named target and then docked against
    # all of them, so this only needs the target's name — building the structure
    # happens inside the loop, where a failure is caught per target instead of
    # taking the whole screen down.
    primary = targets[0]

    if c.get("ligand_objs"):
        ligands = c["ligand_objs"]
    else:
        n = c.get("n_ligands") or 3
        progress(f"Scouting {n} ligands for {primary}…")
        try:
            _, ligs = find_ligands(primary, limit=n)
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
        base = (f"I couldn't find ligands to dock against **{primary}**. "
                f"Scouting works for gene/protein targets, not raw PDB IDs — "
                f"tell me a specific ligand, e.g. *“dock {primary} with aspirin”*.")
        if rejected:
            # Be precise: we DID have candidates, they were all undockable.
            base = (f"None of the ligands could be docked against **{primary}**.")
        return {"ok": False, "tier": tier, "say_text": base + skipped_note}

    rows, viz, meta = [], {}, None
    failed_targets = []
    for n_t, name in enumerate(targets):
        try:
            if multi:
                progress(f"Preparing target {name} ({n_t + 1} of {len(targets)})…")
            t_obj = build_target(dict(c, target=name), data_dir)
        except Exception as e:
            # one unreachable target must not sink the whole screen
            failed_targets.append(f"{name} ({e})")
            continue
        if multi:
            progress(f"Docking against {t_obj['gene']} ({n_t + 1} of {len(targets)})…")
        t_rows, t_viz, t_meta = dock_pipeline(t_obj, ligands, vina, data_dir, venv,
                                              status=progress)
        for r in t_rows:
            # tag every row so a merged table stays readable, and key the viz by
            # target+ligand so the same ligand docked twice doesn't collide
            r["Target"] = t_obj["gene"]
            rows.append(r)
        for lab, entry in (t_viz or {}).items():
            viz[f"{t_obj['gene']} · {lab}" if multi else lab] = entry
        meta = meta or t_meta
        if multi and t_meta:
            meta = dict(meta)
            meta.setdefault("per_target", {})[t_obj["gene"]] = {
                k: t_meta.get(k) for k in ("pocket", "validation", "reliability_by",
                                           "ramachandran")}

    if not rows:
        note = ("; ".join(failed_targets)) or "no poses were produced"
        return {"ok": False, "tier": tier,
                "say_text": f"The docking didn't produce any results — {note}." + skipped_note}

    meta = dict(meta or {})
    if multi:
        meta["gene"] = " + ".join(t for t in
                                  dict.fromkeys(r["Target"] for r in rows))
        meta["targets"] = list(dict.fromkeys(r["Target"] for r in rows))
    if failed_targets:
        skipped_note += ("\n\nCouldn't prepare: " + "; ".join(failed_targets) + ".")

    rdf = pd.DataFrame(rows)
    num = pd.to_numeric(rdf["Best affinity (kcal/mol)"], errors="coerce")
    rdf = rdf.assign(_s=num).sort_values("_s").drop(columns="_s").reset_index(drop=True)
    sorted_rows = rdf.to_dict(orient="records")

    meta_store = {k: meta.get(k) for k in
                  ("gene", "pocket", "exhaustiveness", "replicas", "validation",
                   "reliability_by", "targets", "per_target", "ramachandran")
                  if k in meta}

    # narrative report on the best hit
    top = rdf.iloc[0]
    if str(top["Best affinity (kcal/mol)"]) != "FAILED":
        def _sp(v):
            return [x for x in str(v).split("; ") if x and x != "-"]
        # reliability_by is rebuilt fresh per target and keyed by plain ligand
        # label, so the SAME ligand name has a different entry under each
        # target. meta["reliability_by"] only ever holds the FIRST target's
        # dict (see below) — using it for a winner from any OTHER target would
        # silently attach that other target's reliability data to this one, not
        # just omit it. per_target keeps every target's dict separately.
        top_target = top.get("Target")
        if top_target:
            _rel = (meta.get("per_target", {}).get(top_target, {})
                   .get("reliability_by") or {}).get(top["Ligand"], {})
        else:
            _rel = (meta.get("reliability_by") or {}).get(top["Ligand"], {})
        # on a multi-target screen the write-up is about the winning PAIR, so
        # name the target that hit actually came from, not the joined label
        rep = write_report({"target": top_target or meta.get("gene"),
                            "ligand": top["Ligand"],
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
