"""
MUMO — Pipeline engine (UI-agnostic)
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

The actual docking pipeline, with NO Streamlit code, so any front-end (the chat
app, the old form app, or a future React backend) can call it. Progress is
reported through a `status(message)` callback the caller provides.
"""

import os
from agents.target_analyst import analyze_target
from agents.interaction_analyst import analyze_interactions, prepare_receptor_context
from docking_engine import (clean_protein_pdb, prepare_receptor,
                            prepare_ligand, dock_with_replicas, validate_native_redock,
                            estimate_ki, ligand_efficiency, reliability_assessment)


def resolve_receptor(tgt, data_dir):
    """Get (pdb_path, center, size, pocket) for a target: user PDB or gene→AlphaFold."""
    if tgt.get("pdb_path"):
        return tgt["pdb_path"], tgt["center"], tgt["size"], tgt.get("source", "user PDB")
    info = analyze_target(tgt["gene"], data_dir)
    return info["pdb_path"], info["center"], info["size"], info["pocket_source"]


def dock_pipeline(tgt, ligands, vina, data_dir, venv_dir, status=lambda m: None,
                  exhaustiveness=None, n_replicas=2, seed=42):
    """
    Prepare the receptor once and dock every ligand.

    Search depth (`exhaustiveness`) defaults to None, meaning "choose by screen
    size" — see the selection below. Passing a number overrides it outright.

    That override used to be a lie: the parameter existed, callers passed it,
    and the body ignored it in favour of a hard-coded value. A caller asking for
    a shallow 4 silently got the deep setting, which made the two impossible to
    compare and hid how slow a deep run really was.

    Returns (rows, viz, meta).
    """
    status(f"Building the {tgt['gene']} structure and finding its pocket…")
    pdb_path, center, size, pocket = resolve_receptor(tgt, data_dir)

    cleaned = os.path.join(data_dir, "c_cleaned.pdb")
    receptor = os.path.join(data_dir, "c_receptor.pdbqt")
    clean_protein_pdb(pdb_path, cleaned)

    # Does the search box actually contain the protein we are about to dock
    # into? The box is derived from the RAW structure (usually its co-crystal
    # ligand) while docking runs against the CLEANED one, so the two can drift
    # apart — and when they do, Vina reports 0.000 kcal/mol for every ligand
    # without erroring. That is how 1OYT produced twelve identical scores.
    # One cheap count turns a silent, screen-wide corruption into a clear stop.
    _bx, _by, _bz = center
    _hx, _hy, _hz = (s / 2.0 for s in size)
    _inside = 0
    with open(cleaned) as _f:
        for _ln in _f:
            if _ln.startswith("ATOM"):
                try:
                    _x = float(_ln[30:38]); _y = float(_ln[38:46]); _z = float(_ln[46:54])
                except ValueError:
                    continue
                if (abs(_x - _bx) <= _hx and abs(_y - _by) <= _hy
                        and abs(_z - _bz) <= _hz):
                    _inside += 1
    if _inside < 10:
        raise RuntimeError(
            f"The docking box for {tgt.get('gene', 'this target')} contains only "
            f"{_inside} receptor atoms, so no ligand could bind anywhere inside "
            f"it. The pocket and the prepared protein do not line up — usually "
            f"the chain carrying the binding site was removed during cleaning. "
            f"Docking was stopped rather than returning meaningless scores.")
    status(f"Pocket check: {_inside} receptor atoms inside the search box.")

    # Backbone-geometry (Ramachandran) validation of the receptor we are about
    # to dock into. Computed HERE because this is the only point where the full
    # protein exists on disk — the report later only has pocket-cropped
    # complexes, which can't give whole-structure statistics. It is pure
    # geometry on coordinates already read, so it costs effectively nothing,
    # and it answers the question every affinity in this run depends on: is
    # this structure trustworthy enough to dock into at all?
    rama = None
    try:
        import ramachandran as _rama
        with open(cleaned) as _f:
            rama = _rama.compute(_f.read())
        if rama.get("_error"):
            rama = None          # never let a validation aid break a docking run
    except Exception:
        rama = None
    dropped = prepare_receptor(cleaned, receptor, venv_dir) or []
    if dropped:
        # Say it out loud. Meeko has no templates for nucleotides/sugars, so a
        # protein-DNA entry like 1NFK only preps after they are removed — and
        # the user must know the receptor is protein-only before reading any
        # affinity from it.
        status(f"Note: {len(dropped)} residues had no chemical template "
               f"(usually DNA/RNA or sugar chains) and were removed from "
               f"{tgt['gene']} — docking against the protein only.")

    single = len(ligands) == 1
    n_lig = len(ligands)
    # Vina time scales with exhaustiveness x box-volume x ligand-flexibility, so
    # on a 2-vCPU free tier all three matter — but 4 was too shallow to be
    # defensible. Vina's own default is 8 and published work uses 16-32; at 4 the
    # search does not converge, which both adds run-to-run noise and blurs the
    # pocket-specific part of the score (measured across a 108-docking matrix:
    # only 7.7% of score variance came from WHICH TARGET it was).
    #
    # 16 is the publication-grade setting and is what a reported affinity should
    # be computed at. The cost is real and roughly linear — about 4x the runtime
    # of the old setting — so it is capped for very large screens, where the
    # point is to RANK a shortlist rather than to publish each number, and where
    # a 4x wait would otherwise make the run unusable on free CPU. Promote a hit
    # and re-dock it alone to get the deep number.
    eff_rep = 1
    if exhaustiveness is not None:
        eff_exh = int(exhaustiveness)          # explicit caller override
    elif n_lig <= 25:
        eff_exh = 16                           # publication-grade
    elif n_lig <= 60:
        eff_exh = 12
    else:
        eff_exh = 8                            # still Vina's own default, never below
    status(f"Receptor ready ({pocket}). Docking {n_lig} ligand(s) "
           f"— exhaustiveness {eff_exh}, {eff_rep} replica(s)…")

    # Prepare the receptor for interaction profiling ONCE (protonation + ProLIF
    # fingerprint), reused across every ligand — instead of re-protonating the
    # whole protein per ligand, which dominated multi-ligand runtime and, when it
    # failed under batch load, left ligands with no 2D/3D/zip data.
    receptor_ctx = prepare_receptor_context(cleaned)

    # Gold-standard validation: if the structure has a co-crystal ligand, redock it
    # and report RMSD to the real pose (only experimental complexes — not AlphaFold).
    # This is a WHOLE extra dock, so run it shallow (exhaustiveness 4) — it only needs
    # to confirm the setup, not to be publication-grade, and it must not double the
    # user's wait.
    validation = None
    if "co-crystal" in pocket.lower():
        status("Validating setup: re-docking the native co-crystal ligand…")
        validation = validate_native_redock(pdb_path, receptor, vina, center, size,
                                            data_dir, exhaustiveness=min(eff_exh, 4), seed=seed)

    rows, viz, reliability_by = [], {}, {}
    for k, lig in enumerate(ligands):
        label = lig["label"]
        status(f"Docking {label} ({k+1}/{len(ligands)})…")
        try:
            ligf = os.path.join(data_dir, f"c_lig_{k}.pdbqt")
            cmplx = os.path.join(data_dir, f"c_complex_{k}.pdb")
            prepare_ligand(lig["smiles"], ligf, seed=seed)
            res = dock_with_replicas(
                vina, receptor, ligf,
                os.path.join(data_dir, f"c_out_{k}"), os.path.join(data_dir, f"c_cfg_{k}"),
                center, size, exhaustiveness=eff_exh, n_replicas=eff_rep, base_seed=seed)
            best, modes, outp = res["best_score"], res["modes"], res["out_pdbqt"]
            ia = analyze_interactions(cleaned, outp, cmplx, ligand_smiles=lig["smiles"],
                                      receptor_ctx=receptor_ctx)

            # ── validation / statistics layer (#5): interpretable + aggregate metrics ──
            n_heavy = None
            try:
                from rdkit import Chem
                _m = Chem.MolFromSmiles(lig["smiles"])
                n_heavy = _m.GetNumHeavyAtoms() if _m else None
            except Exception:
                pass
            le = ligand_efficiency(best, n_heavy)
            rel = reliability_assessment(res, validation)
            reliability_by[label] = rel

            rows.append({
                "Ligand": label,
                "Best affinity (kcal/mol)": best,
                "Est. Ki": estimate_ki(best),
                "Ligand efficiency": le if le is not None else "—",
                "Vinardo (kcal/mol)": res.get("vinardo") if res.get("vinardo") is not None else "—",
                "Consensus": res.get("consensus", "—"),
                "Pose consistency": (f"{res.get('n_clustered', '?')}/{res.get('n_poses', '?')} poses"
                                     if res.get("n_poses") else "—"),
                "Mean ± SD (kcal/mol)": (f"{res['mean']} ± {res['sd']}" if eff_rep > 1 else "—"),
                "Confidence": res["confidence"],
                "Reliability": rel["reliability"],
                "Total interactions": ia["total_interactions"], "H-bonds": ia["n_hbonds"],
                "Hydrophobic": ia["n_hydrophobic"], "Pi-stack": ia["n_pistacking"],
                "Salt bridges": ia["n_saltbridges"], "Halogen": ia["n_halogen"],
                "H-bond residues": "; ".join(ia["hbond_residues"]) or "-",
                "All interacting residues": "; ".join(ia["interacting_residues"]) or "-",
                "SMILES": lig["smiles"],
            })
            viz[label] = {"complex": cmplx,
                          "ia": {"lines": ia["lines"], "residue_numbers": ia["residue_numbers"],
                                 "residues": ia.get("residues", []), "svg_2d": ia.get("svg_2d", "")}}
        except Exception as le:
            # MUMO attempts every ligand rather than pre-filtering, so a
            # molecule Vina genuinely cannot handle lands HERE. Name the real
            # reason where we can — an unsupported element is the common one —
            # so a FAILED row is informative instead of an opaque parse error.
            reason = str(le)[:60]
            try:
                import ligand_check as _lc
                bad = _lc.unsupported_elements(lig.get("smiles"))
                if bad:
                    names = ", ".join(_lc.UNSUPPORTED_ELEMENTS[b] for b in bad)
                    reason = f"contains {names} — AutoDock Vina has no parameters for it"
            except Exception:
                pass
            rows.append({"Ligand": label, "Best affinity (kcal/mol)": "FAILED",
                         "Total interactions": reason, "SMILES": lig["smiles"]})
    return rows, viz, {"gene": tgt["gene"], "center": center, "pocket": pocket,
                       "exhaustiveness": eff_exh, "replicas": eff_rep,
                       "validation": validation, "reliability_by": reliability_by,
                       "ramachandran": rama}
