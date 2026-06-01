# MUMO Docking Engine (Phase 1 POC)
# Multi-Agent Drug Discovery & Development AI Platform
# Author: Antigravity AI Partner & Mowriss

import os
import sys
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

def prepare_ligand(smiles, output_pdbqt_path):
    """
    Converts a ligand from a text-based SMILES string into a 3D structure in PDBQT format.
    1. SMILES is converted to a 2D molecule structure.
    2. Explicit hydrogens are added (crucial for hydrogen bonds, which act as molecular 'handshakes').
    3. A 3D shape is generated (embedded) and optimized (minimized) using a chemical force field (MMFF94).
    4. Meeko formats the 3D molecule with Vina atom types and rotatable bonds.
    """
    print(f"[Prep] Converting SMILES '{smiles}' to 3D structure...")
    
    # Read SMILES string
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES string provided: {smiles}")
        
    # Add explicit hydrogens (PDB structures of ligands need hydrogens for docking physics)
    mol = Chem.AddHs(mol)
    
    # Generate 3D coordinates using distance geometry
    embed_status = AllChem.EmbedMolecule(mol, randomSeed=42)
    if embed_status != 0:
        print("[Warning] Standard 3D embedding failed. Trying robust embedding parameters...")
        embed_status = AllChem.EmbedMolecule(mol, useRandomCoords=True, randomSeed=42)
        if embed_status != 0:
            raise RuntimeError("Failed to generate 3D coordinates for the ligand.")
            
    # Optimize the structure to find the lowest energy (most natural) conformation
    optimization_status = AllChem.MMFFOptimizeMolecule(mol)
    if optimization_status != 0:
        print("[Warning] Force field optimization did not fully converge. Docking will still proceed.")
        
    # Prepare the ligand for AutoDock Vina using Meeko
    preparator = MoleculePreparation()
    mol_setups = preparator.prepare(mol)
    
    if not mol_setups:
        raise RuntimeError("Meeko preparation failed: No setups generated.")
        
    # Write to PDBQT format
    pdbqt_string, is_ok, error_msg = PDBQTWriterLegacy.write_string(mol_setups[0])
    if not is_ok:
        raise RuntimeError(f"Meeko writing to PDBQT string failed: {error_msg}")
        
    with open(output_pdbqt_path, 'w') as f:
        f.write(pdbqt_string)
        
    print(f"[Prep] Prepared ligand saved to: {output_pdbqt_path}")

def run_docking(vina_path, receptor_pdbqt, ligand_pdbqt, output_pdbqt, config_path, center, size):
    """
    Writes a configuration file for AutoDock Vina and runs the docking simulation.
    - center: tuple of (x, y, z) representing the center coordinates of the search space box.
    - size: tuple of (x, y, z) representing the dimensions of the search space box.
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

out = {output_pdbqt}
"""
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
