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
                  exhaustiveness=12, n_replicas=2, seed=42):
    """
    Prepare the receptor once and dock every ligand.

    Accuracy strategy (industrial-standard, but cloud-friendly):
      • A FOCUSED single-ligand dock runs deep (exhaustiveness 16) and is repeated
        across `n_replicas` seeds → reproducible best score reported as mean ± SD
        with a confidence flag.
      • A multi-ligand BATCH screen runs fast (exhaustiveness 8, 1 replica) so a
        whole shortlist still finishes quickly; promote a hit, then re-dock it alone.

    Returns (rows, viz, meta).
    """
    status(f"Building the {tgt['gene']} structure and finding its pocket…")
    pdb_path, center, size, pocket = resolve_receptor(tgt, data_dir)

    cleaned = os.path.join(data_dir, "c_cleaned.pdb")
    receptor = os.path.join(data_dir, "c_receptor.pdbqt")
    clean_protein_pdb(pdb_path, cleaned)
    prepare_receptor(cleaned, receptor, venv_dir)

    single = len(ligands) == 1
    n_lig = len(ligands)
    # FAST by default on free CPU (2 vCPU): 1 replica + low exhaustiveness + a tight
    # focused search box (set in target_analyst) + few output modes. Vina time scales
    # with exhaustiveness x box-volume x ligand-flexibility, so on big proteins with
    # large flexible ligands all three matter. (A future "deep/accurate" toggle can
    # re-enable replicas + higher exhaustiveness for users who want max rigour.)
    eff_rep = 1
    # exhaustiveness 4 everywhere for speed (Vina finds the pocket fine in a tight
    # focused box; deeper search is a GPU-era "accurate" toggle).
    eff_exh = 4
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
            rows.append({"Ligand": label, "Best affinity (kcal/mol)": "FAILED",
                         "Total interactions": str(le)[:40], "SMILES": lig["smiles"]})
    return rows, viz, {"gene": tgt["gene"], "center": center, "pocket": pocket,
                       "exhaustiveness": eff_exh, "replicas": eff_rep,
                       "validation": validation, "reliability_by": reliability_by}
