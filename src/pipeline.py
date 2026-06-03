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
from agents.interaction_analyst import analyze_interactions
from docking_engine import (clean_protein_pdb, prepare_receptor,
                            prepare_ligand, run_docking, parse_docking_results)


def resolve_receptor(tgt, data_dir):
    """Get (pdb_path, center, size, pocket) for a target: user PDB or gene→AlphaFold."""
    if tgt.get("pdb_path"):
        return tgt["pdb_path"], tgt["center"], tgt["size"], tgt.get("source", "user PDB")
    info = analyze_target(tgt["gene"], data_dir)
    return info["pdb_path"], info["center"], info["size"], info["pocket_source"]


def dock_pipeline(tgt, ligands, vina, data_dir, venv_dir, status=lambda m: None):
    """
    Prepare the receptor once and dock every ligand.
    Returns (rows, viz) where:
      rows = list of result dicts (one per ligand)
      viz  = {ligand_label: {complex path, interaction lines/residues}}
    """
    status(f"🎯 Building the {tgt['gene']} structure and finding its pocket…")
    pdb_path, center, size, pocket = resolve_receptor(tgt, data_dir)

    cleaned = os.path.join(data_dir, "c_cleaned.pdb")
    receptor = os.path.join(data_dir, "c_receptor.pdbqt")
    clean_protein_pdb(pdb_path, cleaned)
    prepare_receptor(cleaned, receptor, venv_dir)
    status(f"⚗️ Receptor ready ({pocket}). Docking {len(ligands)} ligand(s)…")

    rows, viz = [], {}
    for k, lig in enumerate(ligands):
        label = lig["label"]
        status(f"⚙️ Docking {label} ({k+1}/{len(ligands)})…")
        try:
            ligf = os.path.join(data_dir, f"c_lig_{k}.pdbqt")
            outp = os.path.join(data_dir, f"c_out_{k}.pdbqt")
            cfg  = os.path.join(data_dir, f"c_cfg_{k}.txt")
            cmplx = os.path.join(data_dir, f"c_complex_{k}.pdb")
            prepare_ligand(lig["smiles"], ligf)
            logp = run_docking(vina, receptor, ligf, outp, cfg, center, size)
            best, modes = parse_docking_results(logp)
            ia = analyze_interactions(cleaned, outp, cmplx)
            rows.append({
                "Ligand": label, "SMILES": lig["smiles"],
                "Best affinity (kcal/mol)": best, "Poses": len(modes),
                "Total interactions": ia["total_interactions"], "H-bonds": ia["n_hbonds"],
                "H-bond residues": "; ".join(ia["hbond_residues"]) or "-",
                "Hydrophobic": ia["n_hydrophobic"], "Pi-stack": ia["n_pistacking"],
                "Salt bridges": ia["n_saltbridges"], "Halogen": ia["n_halogen"],
                "All interacting residues": "; ".join(ia["interacting_residues"]) or "-",
            })
            viz[label] = {"complex": cmplx,
                          "ia": {"lines": ia["lines"], "residue_numbers": ia["residue_numbers"]}}
        except Exception as le:
            rows.append({"Ligand": label, "SMILES": lig["smiles"],
                         "Best affinity (kcal/mol)": "FAILED", "Poses": 0,
                         "Total interactions": str(le)[:40]})
    return rows, viz, {"gene": tgt["gene"], "center": center, "pocket": pocket}
