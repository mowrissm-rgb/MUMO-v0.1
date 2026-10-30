"""Anchor check: gas-phase pose refinement bookkeeping, repeatability, failure handling, native vs decoy.

Protocol: validation/PROTOCOL.md, section "Anchor: gas-phase pose refinement
and short relaxation". Long solvated MD and binding free energies are NOT tested.
"""
import math
import os
import subprocess
import tempfile
import time
from pathlib import Path


def rmsd(a, b):
    return math.sqrt(sum(sum((x - y) ** 2 for x, y in zip(p, q)) for p, q in zip(a, b)) / len(a))


def decoy_coordinates(coords, axis, degrees, translation):
    """Rigid decoy: rotate about the axis through the centroid, then translate along the axis."""
    norm = math.sqrt(sum(v * v for v in axis))
    u = [v / norm for v in axis]
    c = [sum(p[i] for p in coords) / len(coords) for i in range(3)]
    cos, sin = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    out = []
    for p in coords:
        v = [p[i] - c[i] for i in range(3)]
        dot = sum(v[i] * u[i] for i in range(3))
        cross = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
        rot = [v[i] * cos + cross[i] * sin + u[i] * dot * (1 - cos) for i in range(3)]
        out.append(tuple(rot[i] + c[i] + translation * u[i] for i in range(3)))
    return out


def last_atoms(pdb_path, n):
    """(elements, coordinates) of the last n ATOM/HETATM records of a PDB file."""
    rows = []
    for line in Path(pdb_path).read_text().splitlines():
        if line.startswith(('ATOM', 'HETATM')):
            element = line[76:78].strip() or line[12:16].strip()[:1]
            rows.append((element.capitalize(), (float(line[30:38]), float(line[38:46]), float(line[46:54]))))
    tail = rows[-n:]
    return [e for e, _ in tail], [c for _, c in tail]


def verdict_for(drift):
    return 'Stable' if drift < 1.5 else 'Mostly stable' if drift < 3.0 else 'Unstable'


def check_report(res, relax_ps):
    """A2: internal consistency of one Anchor report. Returns dict of check -> bool."""
    drift = res['lig_rmsd_relax'] if res.get('lig_rmsd_relax') is not None else res['lig_rmsd_min']
    return {
        'energy_drop_formula': abs(res['energy_drop'] - (res['energy_initial'] - res['energy_minimized'])) <= 0.2,
        'energy_drop_nonnegative': res['energy_drop'] >= 0,
        'relax_ps': res['relax_ps'] == relax_ps,
        'verdict_rule': str(res['verdict']).startswith(verdict_for(drift)),
    }


def run(manifest, ctx):
    from rdkit import Chem
    from rdkit.Chem import AllChem
    import docking_engine as de
    from agents import md_analyst
    from validation.checks.interactions import first_ligand_residue
    from validation.checks.pose import fetch_pdb
    from validation.harness import ROOT, sha256_file

    md_python = ROOT / manifest['md_python']
    if not md_python.exists():
        raise RuntimeError('isolated MD environment not found: ' + str(md_python))
    os.environ['MUMO_MD_PYTHON'] = str(md_python)
    versions = subprocess.run([str(md_python), '-c',
        'import openmm, openff.toolkit, openmmforcefields, rdkit; '
        'print(openmm.__version__, openff.toolkit.__version__, openmmforcefields.__version__, rdkit.__version__)'],
        capture_output=True, text=True, timeout=300).stdout.strip()
    mm = ROOT / 'bin' / 'mamba' / 'micromamba.exe'
    mm_hash = sha256_file(mm) if mm.exists() else None
    if mm_hash != manifest['micromamba_sha256']:
        raise RuntimeError(f'micromamba hash {mm_hash} differs from the frozen protocol')

    work = Path(tempfile.mkdtemp(prefix='anchor_validation_'))
    relax, timeout, ph = manifest['relax_ps'], manifest['timeout_seconds'], manifest['ph']
    dec = manifest['decoy']
    items, a1, a2, b_drop, b_stable, native_results = [], [], [], [], [], {}

    def build(pdb, code):
        folder = work / pdb
        folder.mkdir(exist_ok=True)
        raw = fetch_pdb(pdb, folder / f'{pdb}.pdb')
        cleaned = str(folder / f'{pdb}_clean.pdb')
        de.clean_protein_pdb(str(raw), cleaned)
        _k, lines = first_ligand_residue(Path(raw).read_text(), code)
        smiles = de._rcsb_ligand_smiles(code)
        template = Chem.RemoveAllHs(de._mol_from_smiles_at_ph(smiles, ph))
        native = Chem.RemoveAllHs(Chem.MolFromPDBBlock(''.join(l + chr(10) for l in lines), sanitize=False))
        lig = Chem.AddHs(AllChem.AssignBondOrdersFromTemplate(template, native), addCoords=True)
        return cleaned, lig, folder

    def coords_of(mol):
        conf = mol.GetConformer()
        return [(conf.GetAtomPosition(i).x, conf.GetAtomPosition(i).y, conf.GetAtomPosition(i).z)
                for i in range(mol.GetNumAtoms())]

    def md(cleaned, lig, folder, tag):
        out = folder / tag
        out.mkdir(exist_ok=True)
        started = time.time()
        res = md_analyst.run_stability_md_isolated(cleaned, lig, str(out), relax_ps=relax, timeout=timeout)
        res['_seconds'] = round(time.time() - started, 1)
        return res

    for cx in manifest['complexes']:
        pdb, code = cx['pdb'], cx['ligand']
        name = f'A:{pdb}/{code}'
        try:
            cleaned, lig, folder = build(pdb, code)
            nat = md(cleaned, lig, folder, 'native')
            if '_error' in nat:
                raise RuntimeError('native run: ' + str(nat['_error'])[:200])
            native_results[pdb] = (cleaned, lig, folder, nat)
            # decoy
            decoy = Chem.Mol(lig)
            conf = decoy.GetConformer()
            for i, p in enumerate(decoy_coordinates(coords_of(lig), dec['axis'], dec['rotation_degrees'],
                                                    dec['translation_angstrom'])):
                conf.SetAtomPosition(i, p)
            dres = md(cleaned, decoy, folder, 'decoy')
            if '_error' in dres:
                raise RuntimeError('decoy run: ' + str(dres['_error'])[:200])

            n = lig.GetNumAtoms()
            elements, final = last_atoms(nat['refined_pdb'], n)
            same_elements = elements == [a.GetSymbol() for a in lig.GetAtoms()]
            total = rmsd(coords_of(lig), final) if same_elements else None
            lo = abs(nat['lig_rmsd_min'] - nat['lig_rmsd_relax']) - manifest['rmsd_tolerance']
            hi = nat['lig_rmsd_min'] + nat['lig_rmsd_relax'] + manifest['rmsd_tolerance']
            c1 = bool(same_elements and total is not None and lo <= total <= hi)
            c2n, c2d = check_report(nat, relax), check_report(dres, relax)
            c2 = all(c2n.values()) and all(c2d.values())
            drop_ok = nat['energy_drop'] < dres['energy_drop']
            stable = str(nat['verdict']).startswith('Stable')
            a1.append(c1)
            a2.append(c2)
            b_drop.append(drop_ok)
            b_stable.append(stable)
            items.append({'item': name, 'status': 'PASS' if (c1 and c2) else 'FAIL', 'details': {
                'a1_movement': c1, 'independent_input_to_final_rmsd': None if total is None else round(total, 3),
                'reported_min': nat['lig_rmsd_min'], 'reported_relax': nat['lig_rmsd_relax'],
                'a2_native': c2n, 'a2_decoy': c2d,
                'native_energy_drop': nat['energy_drop'], 'decoy_energy_drop': dres['energy_drop'],
                'native_verdict': str(nat['verdict'])[:30], 'decoy_verdict': str(dres['verdict'])[:30],
                'decoy_rmsd_min': dres['lig_rmsd_min'], 'decoy_rmsd_relax': dres['lig_rmsd_relax'],
                'seconds_native': nat['_seconds'], 'seconds_decoy': dres['_seconds']}})
        except Exception as exc:  # errors stay in the denominator
            for bucket in (a1, a2, b_drop, b_stable):
                bucket.append(False)
            items.append({'item': name, 'status': 'ERROR', 'details': {'error': f'{type(exc).__name__}: {exc}'}})

    # ── A3 repeatability ──
    a3, spreads = [], {}
    for pdb in manifest['repeat_subset']:
        try:
            cleaned, lig, folder, first = native_results[pdb]
            again = md(cleaned, lig, folder, 'repeat')
            if '_error' in again:
                raise RuntimeError(str(again['_error'])[:200])
            ok = (abs(first['energy_initial'] - again['energy_initial']) <= 0.1
                  and abs(first['energy_minimized'] - again['energy_minimized']) <= 0.1
                  and abs(first['lig_rmsd_min'] - again['lig_rmsd_min']) <= 0.01)
            spreads[pdb] = [first['lig_rmsd_relax'], again['lig_rmsd_relax']]
            a3.append(ok)
            items.append({'item': f'A3:{pdb}', 'status': 'PASS' if ok else 'FAIL', 'details': {
                'energy_minimized': [first['energy_minimized'], again['energy_minimized']],
                'lig_rmsd_min': [first['lig_rmsd_min'], again['lig_rmsd_min']],
                'lig_rmsd_relax': spreads[pdb]}})
        except Exception as exc:
            a3.append(False)
            items.append({'item': f'A3:{pdb}', 'status': 'ERROR', 'details': {'error': f'{type(exc).__name__}: {exc}'}})

    # ── A4 honest failure ──
    a4 = []

    def fault(name, call):
        try:
            res = call()
            ok = isinstance(res, dict) and '_error' in res
            detail = str(res.get('_error', 'no error record'))[:160] if isinstance(res, dict) else repr(res)
        except Exception as exc:
            ok, detail = False, f'raised {type(exc).__name__}: {exc}'
        a4.append(ok)
        items.append({'item': name, 'status': 'PASS' if ok else 'FAIL', 'details': {'outcome': detail}})

    first_pdb = next(iter(native_results), None)
    if first_pdb:
        cleaned, lig, folder, _ = native_results[first_pdb]
        fault('A4a:missing_receptor', lambda: md_analyst.run_stability_md_isolated(
            str(work / 'missing.pdb'), lig, str(folder / 'f1'), relax_ps=relax, timeout=timeout))
        noconf = Chem.AddHs(Chem.MolFromSmiles('CCO'))
        fault('A4b:ligand_without_conformer', lambda: md_analyst.run_stability_md_isolated(
            cleaned, noconf, str(folder / 'f2'), relax_ps=relax, timeout=timeout))

        def missing_env():
            saved = os.environ['MUMO_MD_PYTHON']
            os.environ['MUMO_MD_PYTHON'] = str(work / 'no_such_python.exe')
            try:
                return md_analyst.run_stability_md_isolated(cleaned, lig, str(folder / 'f3'),
                                                            relax_ps=relax, timeout=timeout)
            finally:
                os.environ['MUMO_MD_PYTHON'] = saved
        fault('A4c:missing_md_environment', missing_env)

    n = len(manifest['complexes'])
    need_drop = math.ceil(manifest['decoy_min_fraction'] * n)
    need_stable = math.ceil(manifest['stable_min_fraction'] * n)
    criteria = [
        {'id': 'A1', 'description': 'independent input-to-final ligand RMSD consistent with reported movements (100%)',
         'passed': len(a1) == n and all(a1), 'value': f'{sum(a1)}/{n}'},
        {'id': 'A2', 'description': 'energy, relax time and verdict consistent in native and decoy reports (100%)',
         'passed': len(a2) == n and all(a2), 'value': f'{sum(a2)}/{n}'},
        {'id': 'A3', 'description': 'deterministic quantities repeat (3 of 3)',
         'passed': len(a3) == 3 and all(a3), 'value': f'{sum(a3)}/3'},
        {'id': 'A4', 'description': 'bad input returns an error record, never raises (3 of 3)',
         'passed': len(a4) == 3 and all(a4), 'value': f'{sum(a4)}/{len(a4)}'},
        {'id': 'B1', 'description': f'native energy drop below decoy in >= {need_drop}/{n}, and native verdict Stable in >= {need_stable}/{n}',
         'passed': sum(b_drop) >= need_drop and sum(b_stable) >= need_stable,
         'value': f'energy drop smaller {sum(b_drop)}/{n}; Stable {sum(b_stable)}/{n}'},
    ]
    extras = {'package_versions_openmm_openff_ff_rdkit': versions, 'micromamba_sha256': mm_hash,
              'relax_spread_native_repeats': spreads, 'relax_ps': relax,
              'not_tested': ['long solvated MD', 'binding free energies', 'GPU', 'convergence']}
    return items, criteria, extras
