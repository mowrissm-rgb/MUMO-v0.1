# MUMO Docking Engine (Phase 1 POC)
# Multi-Agent Drug Discovery & Development AI Platform
# Author: Antigravity AI Partner & Mowriss

import os
import sys
import re
import shutil
import subprocess
from rdkit import Chem
from rdkit.Chem import AllChem
from meeko import MoleculePreparation, PDBQTWriterLegacy


def _resolve_executable(name, hint_dir=None):
    """
    Find a command-line tool across operating systems.
    Order:
      (1) on the system PATH,
      (2) next to the Python interpreter (conda/venv 'bin' or 'Scripts' folder) —
          this is where pip/conda console scripts like mk_prepare_receptor live,
      (3) inside the optional hint_dir.
    Checks both 'name' and 'name.exe'. Works on Windows (local) and Linux (cloud).
    """
    found = shutil.which(name)
    if found:
        return found
    search_dirs = [os.path.dirname(sys.executable)]
    if hint_dir:
        search_dirs.append(hint_dir)
    for d in search_dirs:
        for candidate in (os.path.join(d, name), os.path.join(d, name + ".exe")):
            if os.path.exists(candidate):
                return candidate
    return None

def clean_protein_pdb(input_path, output_path):
    """
    Cleans a protein PDB file by:
    1. Identifying which chains contain standard protein amino acids.
    2. Excluding chains that contain non-standard residues (which are typically co-crystallized inhibitors, like Chain C in 6LU7).
    3. Excluding water molecules (HOH/WAT) and other crystallization agents.
    """
    print(f"[Prep] Cleaning protein PDB file: {input_path}")
    
    STANDARD_AMINOS = {
        "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE",
        "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL"
    }
    
    SOLVENTS_AND_SALTS = {
        "HOH", "WAT", "SOL", "TIP", "DOD", "CL", "NA", "SO4", "PO4", "ACT", "GOL", "EDT", "DMS"
    }
    
    # First pass: analyze chains to find standard protein chains and non-standard ligand chains
    chain_residues = {}
    with open(input_path, 'r') as infile:
        for line in infile:
            if line.startswith("ATOM") or line.startswith("HETATM"):
                res_name = line[17:20].strip()
                chain_id = line[21]
                if chain_id not in chain_residues:
                    chain_residues[chain_id] = set()
                chain_residues[chain_id].add(res_name)
                
    # Identify valid protein chains (must have standard aminos and no non-standard ligands)
    valid_chains = []
    dropped_chains = []
    for chain_id, residues in chain_residues.items():
        # Check if the chain contains any actual ligand/inhibitor residues
        non_standard = residues - STANDARD_AMINOS - SOLVENTS_AND_SALTS
        
        # If it has standard protein residues and does not contain non-standard residues, it's a valid protein chain
        if (residues & STANDARD_AMINOS) and not non_standard:
            valid_chains.append(chain_id)
        else:
            dropped_chains.append((chain_id, residues))
            
    print(f"[Prep] Identified protein chains to keep: {valid_chains}")
    for chain_id, residues in dropped_chains:
        print(f"[Prep] Dropping chain '{chain_id}' because it contains non-standard residues or solvents: {list(residues)}")
        
    if not valid_chains:
        # Fallback: if all chains have some non-standard residues, keep chains with any standard amino acids
        print("[Warning] No pure standard protein chains found. Keeping chains with any standard amino acids.")
        valid_chains = [chain_id for chain_id, residues in chain_residues.items() if residues & STANDARD_AMINOS]
        if not valid_chains:
            raise ValueError("The PDB file does not contain any standard protein chains.")
            
    # Second pass: write only standard protein ATOM records
    atom_count = 0
    with open(input_path, 'r') as infile, open(output_path, 'w') as outfile:
        for line in infile:
            if line.startswith("ATOM"):
                res_name = line[17:20].strip()
                chain_id = line[21]
                if chain_id in valid_chains and res_name in STANDARD_AMINOS:
                    outfile.write(line)
                    atom_count += 1
            elif line.startswith("TER") or line.startswith("END"):
                # Retain chain termination and structure end markers
                outfile.write(line)
                
    print(f"[Prep] Cleaned protein saved to: {output_path} ({atom_count} atoms written)")

def prepare_receptor(cleaned_pdb_path, output_pdbqt_path, venv_bin_dir):
    """
    Converts a cleaned PDB receptor into the PDBQT format required by AutoDock Vina.
    Uses Meeko's mk_prepare_receptor tool to add atom types and gasteiger charges.
    """
    print(f"[Prep] Preparing receptor using Meeko...")
    # Call Meeko as a Python module ('python -m meeko.cli.mk_prepare_receptor').
    # This is bulletproof across OSes — no need to locate a console-script file,
    # which Meeko names inconsistently (e.g. 'mk_prepare_receptor.py').
    output_dir = os.path.dirname(output_pdbqt_path)
    output_basename = os.path.join(output_dir, "temp_receptor")

    cmd = [
        sys.executable, "-m", "meeko.cli.mk_prepare_receptor",
        "--read_pdb", cleaned_pdb_path,
        "-o", output_basename,
        "-p",                      # Write PDBQT file
        "--allow_bad_res",         # skip residues with missing atoms instead of failing
        "--default_altloc", "A",   # pick conformation 'A' where atoms have alternates
    ]

    print(f"[Exec] Running command: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        # Meeko prints its real error to stdout; show both streams so we can see it.
        details = (result.stdout or "") + "\n" + (result.stderr or "")
        details = details.strip()[-600:] or "(no output captured)"
        print("[Error] Receptor preparation failed!")
        print(details)
        raise RuntimeError(f"Receptor preparation failed: {details}")
    
    # Meeko writes output as <output_basename>.pdbqt
    expected_output = f"{output_basename}.pdbqt"
    if os.path.exists(expected_output):
        if os.path.exists(output_pdbqt_path):
            os.remove(output_pdbqt_path)
        os.rename(expected_output, output_pdbqt_path)
        print(f"[Prep] Prepared receptor saved to: {output_pdbqt_path}")
    else:
        raise FileNotFoundError(f"Expected prepared receptor file not found: {expected_output}")

def _mol_from_smiles_at_ph(smiles, ph=7.4):
    """
    Protonate a SMILES at physiological pH using dimorphite-dl (Apache-2.0), returning
    an RDKit mol with explicit hydrogens and the correct formal charges (e.g. -COOH ->
    -COO-, -NH2 -> -NH3+ at pH 7.4). Returns None on any failure so the caller can fall
    back to the plain RDKit path. (Replaces the GPL OpenBabel path — patent-clean.)
    """
    try:
        from dimorphite_dl import protonate_smiles
        variants = protonate_smiles(smiles, ph_min=ph, ph_max=ph, precision=1.0)
        if not variants:
            return None
        m = Chem.MolFromSmiles(variants[0])       # dominant protonation state at this pH
        if m is None:
            return None
        return Chem.AddHs(m)
    except Exception:
        return None


def prepare_ligand(smiles, output_pdbqt_path, ph=7.4, n_confs=8, seed=42):
    """
    Convert a SMILES into a docking-ready PDBQT, with industrial-grade preparation:
      1. PROTONATE at physiological pH (default 7.4) so acids/bases carry the right
         charge — correct hydrogen bonds and salt bridges. (OpenBabel; RDKit fallback)
      2. Generate SEVERAL 3D conformers with ETKDGv3 and keep the LOWEST-ENERGY one
         (MMFF94) — a better, more reproducible starting geometry than a single embed.
      3. Meeko assigns Vina atom types, Gasteiger charges and rotatable bonds.
    """
    print(f"[Prep] Preparing ligand '{smiles}' (protonated at pH {ph})...")

    mol = _mol_from_smiles_at_ph(smiles, ph)
    if mol is None:                                   # fallback: plain RDKit prep
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise ValueError(f"Invalid SMILES string provided: {smiles}")
        mol = Chem.AddHs(mol)

    # ETKDGv3 multi-conformer embedding (deterministic via fixed seed)
    params = AllChem.ETKDGv3()
    params.randomSeed = seed
    conf_ids = list(AllChem.EmbedMultipleConfs(mol, numConfs=max(1, n_confs), params=params))
    if not conf_ids:
        print("[Warning] ETKDG embedding failed. Trying robust random-coords embedding...")
        if AllChem.EmbedMolecule(mol, useRandomCoords=True, randomSeed=seed) != 0:
            raise RuntimeError("Failed to generate 3D coordinates for the ligand.")
        conf_ids = [0]

    # MMFF94-optimise every conformer and keep the lowest-energy geometry
    best_cid = conf_ids[0]
    try:
        results = AllChem.MMFFOptimizeMoleculeConfs(mol)      # [(converged, energy), ...]
        energies = [(cid, e) for cid, (_conv, e) in zip(conf_ids, results)]
        best_cid = min(energies, key=lambda t: t[1])[0]
    except Exception:
        print("[Warning] Conformer optimisation skipped; using the first conformer.")

    # Keep ONLY the best conformer for Meeko
    best_mol = Chem.Mol(mol)
    best_mol.RemoveAllConformers()
    best_mol.AddConformer(mol.GetConformer(best_cid), assignId=True)

    preparator = MoleculePreparation()
    mol_setups = preparator.prepare(best_mol)
    if not mol_setups:
        raise RuntimeError("Meeko preparation failed: No setups generated.")

    pdbqt_string, is_ok, error_msg = PDBQTWriterLegacy.write_string(mol_setups[0])
    if not is_ok:
        raise RuntimeError(f"Meeko writing to PDBQT string failed: {error_msg}")

    with open(output_pdbqt_path, 'w') as f:
        f.write(pdbqt_string)
    print(f"[Prep] Prepared ligand saved to: {output_pdbqt_path}")

def run_docking(vina_path, receptor_pdbqt, ligand_pdbqt, output_pdbqt, config_path,
                center, size, exhaustiveness=16, num_modes=9, energy_range=3.0,
                seed=42, cpu=None):
    """
    Writes a configuration file for AutoDock Vina and runs the docking simulation.
    - center / size: (x, y, z) of the search-box centre and dimensions.
    - exhaustiveness: search depth (Vina default 8; we default to 16 for accuracy).
    - num_modes / energy_range: how many poses to keep and the energy window.
    - seed: FIXED so a given input always reproduces the same result (reproducibility
      is an industrial-standard requirement).
    """
    print(f"[Dock] Creating Vina configuration file: {config_path}")

    # Grid Box settings: In drug discovery, the grid box center and size define the search space.
    # We restrict search to the active site to find the most therapeutic binding conformation.
    config_content = f"""receptor = {receptor_pdbqt}
ligand = {ligand_pdbqt}

center_x = {center[0]}
center_y = {center[1]}
center_z = {center[2]}

size_x = {size[0]}
size_y = {size[1]}
size_z = {size[2]}

exhaustiveness = {int(exhaustiveness)}
num_modes = {int(num_modes)}
energy_range = {energy_range}
seed = {int(seed)}
"""
    if cpu:
        config_content += f"cpu = {int(cpu)}\n"
    config_content += f"out = {output_pdbqt}\n"
    with open(config_path, 'w') as f:
        f.write(config_content)

    # If the given vina path doesn't exist, look for 'vina' on the PATH (cloud/Linux).
    if not os.path.exists(vina_path):
        vina_path = _resolve_executable("vina") or vina_path

    print(f"[Dock] Running AutoDock Vina...")
    cmd = [
        vina_path,
        "--config", config_path
    ]
    
    print(f"[Exec] Running command: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    # Save log file of the Vina run
    log_path = output_pdbqt.replace(".pdbqt", "_vina.log")
    with open(log_path, 'w') as f:
        f.write(result.stdout)
        f.write(result.stderr)
        
    if result.returncode != 0:
        print("[Error] AutoDock Vina execution failed!")
        print(result.stderr)
        raise RuntimeError(f"AutoDock Vina failed: {result.stderr}")
        
    print(f"[Dock] Docking completed successfully. Log saved to: {log_path}")
    return log_path

def parse_docking_results(log_path):
    """
    Parses the AutoDock Vina log file to extract the best binding affinity score.
    Binding affinity is measured in kcal/mol (kilocalories per mole of complex).
    A more negative score represents a stronger thermodynamic attraction (higher affinity)
    between the drug candidate and target.
    """
    scores = []
    print(f"[Results] Parsing docking scores from log: {log_path}")
    with open(log_path, 'r') as f:
        start_reading = False
        for line in f:
            if "mode |   affinity" in line:
                start_reading = True
                continue
            if start_reading and line.strip() == "":
                # If we've started reading and hit an empty line or end of table, stop.
                # However, make sure we have actually read some scores first.
                if scores:
                    break
            if start_reading:
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        mode = int(parts[0])
                        affinity = float(parts[1])
                        scores.append((mode, affinity))
                    except ValueError:
                        # Skip header separator lines (e.g. ----- or containing '|')
                        continue
                    
    if not scores:
        raise RuntimeError("No docking scores were parsed from the log file.")
        
    # The first mode is the best pose found by Vina
    best_mode, best_score = scores[0]
    print(f"[Results] Best Docking Score (Mode {best_mode}): {best_score} kcal/mol")
    return best_score, scores


def _extract_top_pose(multi_pdbqt, out_pdbqt):
    """Write the first (top-ranked) MODEL of a docked PDBQT to a single-model file
    (Vina's --score_only rejects multi-MODEL ligands). Falls back to the whole file
    if it isn't multi-model."""
    lines, inside = [], False
    for ln in open(multi_pdbqt):
        if ln.startswith("MODEL"):
            if inside:
                break
            inside = True
            continue
        if ln.startswith("ENDMDL"):
            break
        lines.append(ln)
    if not lines:
        lines = open(multi_pdbqt).readlines()
    with open(out_pdbqt, "w") as f:
        f.writelines(lines)
    return out_pdbqt


def score_pose(vina_path, receptor_pdbqt, pose_pdbqt, scoring="vinardo"):
    """Rescore ONE docked pose with a chosen scoring function (Vina --score_only).
    Used for CONSENSUS scoring — an independent second opinion on the top pose from a
    different scoring function. Returns the affinity (kcal/mol) float, or None."""
    if not os.path.exists(vina_path):
        vina_path = _resolve_executable("vina") or vina_path
    try:
        result = subprocess.run(
            [vina_path, "--receptor", receptor_pdbqt, "--ligand", pose_pdbqt,
             "--scoring", scoring, "--score_only", "--autobox"],
            capture_output=True, text=True, timeout=120)
        for ln in result.stdout.splitlines():
            if "Estimated Free Energy of Binding" in ln:
                m = re.search(r":\s*(-?\d+\.\d+)", ln)
                if m:
                    return round(float(m.group(1)), 3)
    except Exception:
        pass
    return None


def consensus_rescore(vina_path, receptor_pdbqt, best_out_pdbqt, vina_best,
                      second="vinardo"):
    """Consensus second opinion on the reported best pose. Rescore the top pose with a
    different scoring function and judge agreement. Returns
    {"vinardo": float|None, "consensus": str}."""
    vinardo = None
    try:
        top = _extract_top_pose(best_out_pdbqt,
                                best_out_pdbqt.replace(".pdbqt", "_top.pdbqt"))
        vinardo = score_pose(vina_path, receptor_pdbqt, top, scoring=second)
    except Exception:
        pass
    if vinardo is None:
        return {"vinardo": None, "consensus": "—"}
    # Vinardo runs weaker in magnitude than Vina; treat both-favourable as agreement.
    agree = (vina_best <= -5.0 and vinardo <= -3.5) or (vina_best > -5.0 and vinardo > -3.5)
    return {"vinardo": vinardo,
            "consensus": "Both functions agree" if agree else "Functions disagree — interpret with care"}


def pose_consistency(log_path, rmsd_threshold=2.0):
    """POSE CLUSTERING signal. Vina reports each pose's RMSD from the best pose; count
    how many of the returned poses land within `rmsd_threshold` Å of the best one. A
    binding mode that many poses converge on is far more reproducible/trustworthy than
    a lone best pose. Returns {n_poses, n_clustered, consistency (fraction), verdict}."""
    n_total, n_near, reading = 0, 0, False
    try:
        for ln in open(log_path):
            if "mode" in ln and "affinity" in ln:
                reading = True
                continue
            if reading:
                parts = ln.split()
                if len(parts) >= 4:
                    try:
                        int(parts[0]); rmsd_lb = float(parts[2])
                        n_total += 1
                        if rmsd_lb <= rmsd_threshold:
                            n_near += 1
                    except ValueError:
                        continue
                elif n_total > 0:
                    break
    except Exception:
        return {"n_poses": 0, "n_clustered": 0, "consistency": None, "verdict": "—"}
    frac = (n_near / n_total) if n_total else 0
    verdict = ("Tight — poses converge" if frac >= 0.5 else
               "Scattered poses" if n_total else "—")
    return {"n_poses": n_total, "n_clustered": n_near,
            "consistency": round(frac, 2) if n_total else None, "verdict": verdict}


def dock_with_replicas(vina_path, receptor_pdbqt, ligand_pdbqt, out_prefix, cfg_prefix,
                       center, size, exhaustiveness=16, n_replicas=1, base_seed=42,
                       num_modes=9):
    """
    Run Vina n_replicas times with DIFFERENT seeds to measure reproducibility/precision.
    Returns a dict:
      best_score : most-negative best affinity across replicas (the reported hit)
      modes      : all poses of that best replica
      out_pdbqt  : the best replica's output file (used for interactions + 3D view)
      mean, sd   : mean and standard deviation of the per-replica best affinity
      n          : number of replicas actually run
      confidence : "High"/"Medium"/"Lower" from the spread (or "Single run")
    """
    import statistics
    n_replicas = max(1, int(n_replicas))
    runs, bests = [], []
    for i in range(n_replicas):
        outp = f"{out_prefix}_r{i}.pdbqt"
        cfg = f"{cfg_prefix}_r{i}.txt"
        log = run_docking(vina_path, receptor_pdbqt, ligand_pdbqt, outp, cfg,
                          center, size, exhaustiveness=exhaustiveness,
                          num_modes=num_modes, seed=base_seed + i)
        best, modes = parse_docking_results(log)
        runs.append((best, modes, outp, log))
        bests.append(best)

    best_run = min(runs, key=lambda r: r[0])
    mean = sum(bests) / len(bests)
    sd = statistics.pstdev(bests) if len(bests) > 1 else 0.0
    if len(bests) == 1:
        confidence = "Single run"
    elif sd <= 0.5:
        confidence = "High"
    elif sd <= 1.0:
        confidence = "Medium"
    else:
        confidence = "Lower"

    # CONSENSUS scoring: independent second opinion (Vinardo) on the reported best pose
    cons = consensus_rescore(vina_path, receptor_pdbqt, best_run[2], best_run[0])
    # POSE CLUSTERING: how many of the returned poses converge on the best binding mode
    pc = pose_consistency(best_run[3])

    return {"best_score": best_run[0], "modes": best_run[1], "out_pdbqt": best_run[2],
            "mean": round(mean, 3), "sd": round(sd, 3), "n": len(bests),
            "confidence": confidence, "all_best": bests,
            "vinardo": cons["vinardo"], "consensus": cons["consensus"],
            "pose_consistency": pc["consistency"], "pose_verdict": pc["verdict"],
            "n_poses": pc["n_poses"], "n_clustered": pc["n_clustered"]}


def estimate_ki(delta_g, temperature=298.15):
    """Convert a docking binding free energy ΔG (kcal/mol) into an estimated
    binding constant Ki via ΔG = R·T·ln(Ki). Returns a friendly string with an
    auto-chosen unit (pM … M), or '—'. This is an ESTIMATE — Vina scores are
    approximate free energies, so treat Ki as an order-of-magnitude guide."""
    try:
        import math
        R = 1.98720425e-3            # gas constant, kcal/(mol·K)
        ki_molar = math.exp(float(delta_g) / (R * temperature))   # ΔG<0 → Ki<1 M
    except Exception:
        return "—"
    for factor, unit in ((1e12, "pM"), (1e9, "nM"), (1e6, "µM"), (1e3, "mM"), (1.0, "M")):
        val = ki_molar * factor
        if val < 1000:
            return f"{val:.2f} {unit}"
    return f"{ki_molar:.2e} M"


def ligand_efficiency(delta_g, n_heavy_atoms):
    """Ligand efficiency = −ΔG / (number of heavy atoms), in kcal/mol per heavy
    atom. It rewards potency achieved with a SMALL molecule; ~0.3 or higher is
    usually considered efficient. Returns a float, or None if unknown."""
    try:
        if n_heavy_atoms and int(n_heavy_atoms) > 0:
            return round(-float(delta_g) / int(n_heavy_atoms), 3)
    except Exception:
        pass
    return None


def reliability_assessment(res, validation=None):
    """Roll the independent quality signals — replica precision, Vina/Vinardo
    consensus, pose clustering, and (if available) native-redock RMSD — into ONE
    overall reliability verdict with a plain-language reason. Purely aggregates
    numbers already computed; adds no new docking work.
    Returns {"reliability": "High"|"Medium"|"Low", "reason": str}."""
    strong, avail, factors = 0, 0, []

    sd, n = res.get("sd"), res.get("n", 1)
    if n and n > 1:
        avail += 1
        if sd is not None and sd <= 0.5:
            strong += 1; factors.append("reproducible across replicas")
        elif sd is not None and sd <= 1.0:
            factors.append("moderate replica spread")
        else:
            factors.append("high replica spread")

    cons = (res.get("consensus") or "").lower()
    if cons and cons != "—":
        avail += 1
        if "disagree" in cons:            # check 'disagree' first — it contains 'agree'
            factors.append("scoring functions disagree")
        elif "agree" in cons:
            strong += 1; factors.append("two scoring functions agree")

    pc = res.get("pose_consistency")
    if pc is not None:
        avail += 1
        if pc >= 0.5:
            strong += 1; factors.append("poses converge on one binding mode")
        else:
            factors.append("poses are scattered")

    if validation:
        avail += 1
        if validation.get("passed"):
            strong += 1; factors.append(f"setup validated (native redock {validation.get('rmsd','?')} Å)")
        else:
            factors.append(f"native redock high ({validation.get('rmsd','?')} Å)")

    # verdict scaled to how many signals we actually had: mostly-strong = High
    if avail == 0:
        score = "Single run"
    elif strong >= max(3, avail):          # essentially all signals strong
        score = "High"
    elif strong >= 2 or (avail <= 2 and strong >= 1):
        score = "Medium"
    else:
        score = "Low"
    return {"reliability": score, "reason": "; ".join(factors) or "single run — limited signals"}


def validate_native_redock(raw_pdb_path, receptor_pdbqt, vina, center, size, data_dir,
                           exhaustiveness=16, seed=42):
    """
    GOLD-STANDARD validation. If the target structure carries a co-crystallised ligand,
    re-dock THAT ligand into the same box and measure how close the predicted pose is to
    the experimental one (heavy-atom RMSD, no alignment — same receptor frame).
    RMSD < 2.0 Å is the accepted "correct redocking" threshold — direct evidence the
    docking setup reproduces reality on this target.

    Returns {"rmsd": float, "resname": str, "passed": bool} or None if there is no usable
    co-crystal ligand or the check can't be completed (always non-fatal).
    """
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem, rdMolAlign
        from meeko import PDBQTMolecule, RDKitMolCreate

        NOT_LIG = {"HOH", "WAT", "SOL", "DOD", "TIP", "CL", "NA", "K", "MG", "CA", "ZN",
                   "MN", "SO4", "PO4", "ACT", "GOL", "EDO", "PEG", "DMS", "IOD", "BR",
                   "FMT", "NO3"}
        groups = {}
        with open(raw_pdb_path) as f:
            for ln in f:
                if ln.startswith("HETATM"):
                    resn = ln[17:20].strip()
                    if resn in NOT_LIG:
                        continue
                    groups.setdefault((resn, ln[21], ln[22:26].strip()), []).append(ln)
        if not groups:
            return None
        (resn, _, _), lines = max(groups.items(), key=lambda kv: len(kv[1]))
        if len(lines) < 6:
            return None

        native_block = "".join(lines)

        # The native ligand's bonds → SMILES: look it up in the RCSB chemical
        # component dictionary by its 3-letter code (no OpenBabel bond perception).
        smiles = _rcsb_ligand_smiles(resn)
        if not smiles:
            return None
        template = Chem.MolFromSmiles(smiles)
        if template is None:
            return None
        template = Chem.RemoveHs(template)

        native_noH = Chem.RemoveHs(Chem.MolFromPDBBlock(native_block, sanitize=False))
        native_fixed = AllChem.AssignBondOrdersFromTemplate(template, native_noH)

        # Re-dock the native ligand into the prepared receptor
        ligf = os.path.join(data_dir, "_native_lig.pdbqt")
        prepare_ligand(smiles, ligf, seed=seed)
        res = dock_with_replicas(vina, receptor_pdbqt, ligf,
                                 os.path.join(data_dir, "_native_out"),
                                 os.path.join(data_dir, "_native_cfg"),
                                 center, size, exhaustiveness=exhaustiveness,
                                 n_replicas=1, base_seed=seed)

        # Read the best docked pose via meeko (no OpenBabel)
        pmol = PDBQTMolecule.from_file(res["out_pdbqt"], skip_typing=True)
        docked_raw = RDKitMolCreate.from_pdbqt_mol(pmol)[0]
        docked_noH = Chem.RemoveHs(docked_raw)
        docked_fixed = AllChem.AssignBondOrdersFromTemplate(template, docked_noH)

        rmsd = rdMolAlign.CalcRMS(docked_fixed, native_fixed)    # no alignment: same box frame
        return {"rmsd": round(float(rmsd), 2), "resname": resn, "passed": bool(rmsd < 2.0)}
    except Exception as e:
        print(f"[Validate] native redock skipped: {e}")
        return None


def _rcsb_ligand_smiles(resname):
    """Fetch a ligand's canonical SMILES from the RCSB chemical component
    dictionary by its 3-letter PDB code — the permissive replacement for
    OpenBabel's bond perception. Returns a SMILES string or None."""
    try:
        import requests
        r = requests.get(f"https://data.rcsb.org/rest/v1/core/chemcomp/{resname}", timeout=20)
        if r.status_code != 200:
            return None
        desc = r.json().get("rcsb_chem_comp_descriptor", {})
        return desc.get("SMILES_stereo") or desc.get("SMILES")
    except Exception:
        return None


def main():
    """
    Main entry point for command-line execution.
    Demonstrates running a complete docking workflow.
    """
    print("=== MUMO Docking Engine PoC ===")
    
    # Simple defaults for demonstration
    # We expect files to be located in the 'data' directory
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base_dir, "data")
    bin_dir = os.path.join(base_dir, "bin")
    venv_bin_dir = os.path.join(base_dir, ".venv", "Scripts")
    
    # Ensure data directory exists
    os.makedirs(data_dir, exist_ok=True)
    
    # AutoDock Vina executable path
    vina_path = os.path.join(bin_dir, "vina.exe")
    
    # Let's check arguments or run a demo
    if len(sys.argv) < 3:
        print("\nUsage:")
        print("  python src/docking_engine.py <protein.pdb> <ligand_smiles> [center_x center_y center_z] [size_x size_y size_z]")
        print("\nExample (running with dummy data configuration):")
        print("  python src/docking_engine.py data/target.pdb \"CC(=O)Oc1ccccc1C(=O)O\" 15.0 20.0 15.0 20.0 20.0 20.0\n")
        return
        
    protein_pdb = sys.argv[1]
    ligand_smiles = sys.argv[2]
    
    # Grid Box Center (defaults to coordinates 0,0,0 if not provided)
    center = (0.0, 0.0, 0.0)
    if len(sys.argv) >= 6:
        center = (float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5]))
        
    # Grid Box Size (defaults to 20x20x20 Angstroms if not provided)
    size = (20.0, 20.0, 20.0)
    if len(sys.argv) >= 9:
        size = (float(sys.argv[6]), float(sys.argv[7]), float(sys.argv[8]))
        
    # Intermediate files
    protein_name = os.path.splitext(os.path.basename(protein_pdb))[0]
    cleaned_pdb = os.path.join(data_dir, f"{protein_name}_cleaned.pdb")
    receptor_pdbqt = os.path.join(data_dir, f"{protein_name}_prepared.pdbqt")
    ligand_pdbqt = os.path.join(data_dir, "ligand_prepared.pdbqt")
    output_pdbqt = os.path.join(data_dir, "docking_output.pdbqt")
    config_path = os.path.join(data_dir, "vina_config.txt")
    
    try:
        # Step 1: Clean protein PDB
        clean_protein_pdb(protein_pdb, cleaned_pdb)
        
        # Step 2: Prepare protein receptor PDBQT
        prepare_receptor(cleaned_pdb, receptor_pdbqt, venv_bin_dir)
        
        # Step 3: Prepare ligand PDBQT
        prepare_ligand(ligand_smiles, ligand_pdbqt)
        
        # Step 4: Run AutoDock Vina
        log_path = run_docking(
            vina_path=vina_path,
            receptor_pdbqt=receptor_pdbqt,
            ligand_pdbqt=ligand_pdbqt,
            output_pdbqt=output_pdbqt,
            config_path=config_path,
            center=center,
            size=size
        )
        
        # Step 5: Parse and output binding affinity
        best_score, all_scores = parse_docking_results(log_path)
        
        print("\n" + "="*40)
        print("DOCKING SIMULATION COMPLETED")
        print(f"Target: {protein_pdb}")
        print(f"Ligand SMILES: {ligand_smiles}")
        print(f"Best Binding Energy: {best_score} kcal/mol")
        print("="*40)
        
    except Exception as e:
        print(f"\n[Failure] An error occurred during the docking run: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
