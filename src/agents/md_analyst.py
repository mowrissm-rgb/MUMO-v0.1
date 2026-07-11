"""
MUMO Agent — Molecular Simulation (pose refinement + short relaxation)
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

WHAT THIS DOES (plain English)
------------------------------
Docking gives a single best-guess pose. This agent takes that docked complex and
runs REAL molecular-mechanics physics on it with OpenMM (MIT-licensed):

    1. Energy-minimise the complex  → relieves steric clashes, settles the pose.
    2. A short relaxation (a few ps of dynamics at 300 K, protein lightly
       restrained) → checks the ligand doesn't immediately fly out of the pocket.
    3. Report: the potential-energy drop (how much strain was relieved) and how
       far the ligand moved (small = the docked pose was already sensible).

This is a FAST, free-CPU-friendly *precursor* to full molecular dynamics — same
OpenMM stack, so it upgrades to a long GPU trajectory (real "does it stay bound
over time" + RMSD drift + MM-GBSA) once GPU compute is available. It is NOT a
substitute for production MD, and the report says so.

Everything is permissive/patent-clean: OpenMM (MIT), OpenFF (MIT), RDKit (BSD).
Never raises — returns {"_error": ...} so the rest of MUMO keeps working.
"""

import os

# Availability probe (heavy MD stack may be absent on a stripped build).
MD_AVAILABLE = True
_MD_IMPORT_ERROR = ""
try:
    import openmm  # noqa: F401
except Exception as _e:                      # pragma: no cover
    MD_AVAILABLE = False
    _MD_IMPORT_ERROR = f"{type(_e).__name__}: {_e}"


def _ligand_offmol(lig_rdkit):
    """RDKit ligand (with explicit Hs + a 3D conformer) → an OpenFF Molecule with
    fast Gasteiger charges (good enough for a short refinement; AM1-BCC/GPU comes
    with full MD later)."""
    from openff.toolkit import Molecule
    from rdkit import Chem
    m = Chem.AddHs(lig_rdkit, addCoords=True) if lig_rdkit.GetNumAtoms() == \
        Chem.RemoveHs(lig_rdkit).GetNumAtoms() else lig_rdkit
    off = Molecule.from_rdkit(m, allow_undefined_stereo=True)
    try:
        off.assign_partial_charges("gasteiger")
    except Exception:
        pass
    return off


def run_stability_md(receptor_pdb, lig_rdkit, out_dir, relax_ps=2.0,
                     min_iters=800, restrain_k=5.0, temperature=300.0,
                     status=lambda m: None):
    """
    Minimise + briefly relax the docked complex and summarise pose stability.

    receptor_pdb : cleaned protein PDB path.
    lig_rdkit    : the docked ligand as an RDKit mol (correct bonds + 3D pose).
    out_dir      : where to write the refined complex PDB.

    Returns a dict (never raises):
      {gene?, energy_initial, energy_minimized, energy_drop, lig_rmsd_min,
       lig_rmsd_relax, verdict, relax_ps, refined_pdb, note}  or  {"_error": ...}
    """
    if not MD_AVAILABLE:
        return {"_error": f"Molecular simulation unavailable ({_MD_IMPORT_ERROR})."}
    try:
        return _run(receptor_pdb, lig_rdkit, out_dir, relax_ps, min_iters,
                    restrain_k, temperature, status)
    except Exception as e:
        return {"_error": f"Simulation could not run: {type(e).__name__}: {e}"}


def _run(receptor_pdb, lig_rdkit, out_dir, relax_ps, min_iters, restrain_k,
         temperature, status):
    import numpy as np
    from openmm import app, unit, LangevinMiddleIntegrator, CustomExternalForce, Platform
    from openmmforcefields.generators import SystemGenerator

    status("Preparing the protein…")
    protein = app.PDBFile(receptor_pdb)
    modeller = app.Modeller(protein.topology, protein.positions)
    modeller.deleteWater()

    status("Parameterising the ligand (this can take a moment)…")
    off_lig = _ligand_offmol(lig_rdkit)
    lig_top = off_lig.to_topology().to_openmm()
    lig_pos = off_lig.conformers[0].to_openmm()

    # Force fields: Amber14 protein + OpenFF "Sage" small-molecule, in VACUUM
    # (gas-phase). SMIRNOFF (OpenFF) types the ligand by SMARTS — no AmberTools/
    # antechamber — and the ligand already carries Gasteiger charges, so no AM1-BCC
    # backend either. We deliberately skip implicit solvent: assigning GB radii to an
    # arbitrary small molecule is fragile, and for a short clash-relief refinement
    # gas-phase is robust and sufficient. Solvent arrives with the full-MD/GPU upgrade.
    system_generator = SystemGenerator(
        forcefields=["amber14-all.xml"],
        small_molecule_forcefield="openff_unconstrained-2.0.0",
        molecules=[off_lig],
        forcefield_kwargs={"constraints": app.HBonds},
    )

    status("Building the protein–ligand system…")
    modeller.addHydrogens(system_generator.forcefield, pH=7.4)
    n_protein = modeller.topology.getNumAtoms()
    modeller.add(lig_top, lig_pos)                       # append the ligand
    lig_indices = list(range(n_protein, modeller.topology.getNumAtoms()))

    system = system_generator.create_system(modeller.topology)

    # lightly restrain protein backbone so we watch the LIGAND settle, not the
    # whole protein drift (also keeps a truncated/implicit system well-behaved)
    restraint = CustomExternalForce("0.5*k*((x-x0)^2+(y-y0)^2+(z-z0)^2)")
    restraint.addGlobalParameter("k", restrain_k * unit.kilocalories_per_mole / unit.angstrom**2)
    for p in ("x0", "y0", "z0"):
        restraint.addPerParticleParameter(p)
    positions = modeller.positions
    for atom in modeller.topology.atoms():
        if atom.name in ("CA", "C", "N") and atom.index < n_protein:
            pos = positions[atom.index]
            restraint.addParticle(atom.index, [pos.x, pos.y, pos.z])
    system.addForce(restraint)

    integrator = LangevinMiddleIntegrator(
        temperature * unit.kelvin, 1.0 / unit.picosecond, 0.002 * unit.picoseconds)
    try:
        platform = Platform.getPlatformByName("CPU")
        sim = app.Simulation(modeller.topology, system, integrator, platform)
    except Exception:
        sim = app.Simulation(modeller.topology, system, integrator)
    sim.context.setPositions(positions)

    def _energy():
        return sim.context.getState(getEnergy=True).getPotentialEnergy().value_in_unit(
            unit.kilocalories_per_mole)

    def _lig_xyz():
        st = sim.context.getState(getPositions=True)
        p = st.getPositions(asNumpy=True).value_in_unit(unit.angstrom)
        return np.asarray(p)[lig_indices]

    e0 = _energy()
    lig0 = _lig_xyz()

    status("Energy-minimising the complex…")
    sim.minimizeEnergy(maxIterations=int(min_iters))
    e_min = _energy()
    lig_min = _lig_xyz()
    rmsd_min = float(np.sqrt(((lig_min - lig0) ** 2).sum(axis=1).mean()))

    rmsd_relax = None
    if relax_ps and relax_ps > 0:
        status(f"Relaxing for {relax_ps} ps (short dynamics)…")
        sim.context.setVelocitiesToTemperature(temperature * unit.kelvin)
        sim.step(int(relax_ps / 0.002))
        lig_relax = _lig_xyz()
        rmsd_relax = float(np.sqrt(((lig_relax - lig_min) ** 2).sum(axis=1).mean()))

    # write the refined complex (protein + ligand, minimised/relaxed)
    refined = os.path.join(out_dir, "md_refined_complex.pdb")
    with open(refined, "w") as f:
        app.PDBFile.writeFile(sim.topology,
                              sim.context.getState(getPositions=True).getPositions(), f)

    drift = rmsd_relax if rmsd_relax is not None else rmsd_min
    verdict = ("Stable — the ligand held its pose" if drift < 1.5 else
               "Mostly stable — small shift" if drift < 3.0 else
               "Unstable — the ligand moved substantially")

    return {
        "energy_initial": round(e0, 1),
        "energy_minimized": round(e_min, 1),
        "energy_drop": round(e0 - e_min, 1),
        "lig_rmsd_min": round(rmsd_min, 2),
        "lig_rmsd_relax": round(rmsd_relax, 2) if rmsd_relax is not None else None,
        "verdict": verdict,
        "relax_ps": relax_ps,
        "refined_pdb": refined,
        "note": ("Fast gas-phase pose refinement + short relaxation (protein restrained) "
                 "— a lightweight precursor to full solvated molecular dynamics."),
    }
