"""Pose check: native redocking, reproducibility and replica bookkeeping.

Protocol: validation/PROTOCOL.md, section "Pose: native redocking,
reproducibility and bookkeeping". Scoring power, screening power and the
ProLIF interaction analysis are NOT tested here.
"""
import math
import os
import re
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

import requests

RCSB = 'https://files.rcsb.org/download'


def fetch_pdb(pdb, dest):
    for attempt in range(4):
        try:
            resp = requests.get(f'{RCSB}/{pdb}.pdb', timeout=120)
            if resp.status_code not in (429, 500, 502, 503, 504) or attempt == 3:
                resp.raise_for_status()
                Path(dest).write_text(resp.text)
                return dest
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 3:
                raise
        time.sleep(1.0 * (2 ** attempt))


def wilson(k, n, z=1.96):
    if n == 0:
        return None, None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return centre - half, centre + half


def check_replica_report(res):
    """D3: internal consistency of dock_with_replicas output. Returns dict of check -> bool."""
    bests = res['all_best']
    scores = [m[1] for m in res['modes']]
    sd = statistics.pstdev(bests) if len(bests) > 1 else 0.0
    expected_conf = ('Single run' if len(bests) == 1 else 'High' if sd <= 0.5
                     else 'Medium' if sd <= 1.0 else 'Lower')
    def finite(v):
        return isinstance(v, (int, float)) and math.isfinite(v)
    return {
        'best_is_min': res['best_score'] == min(bests),
        'mean_sd': abs(res['mean'] - round(sum(bests) / len(bests), 3)) < 1e-9
                   and abs(res['sd'] - round(sd, 3)) < 1e-9,
        'confidence_rule': res['confidence'] == expected_conf,
        'modes_sorted': all(a <= b for a, b in zip(scores, scores[1:])) and bool(scores)
                        and abs(scores[0] - res['best_score']) < 1e-9,
        'vinardo_finite': finite(res.get('vinardo')) and finite(res.get('consensus')),
    }


def vina_score_only(vina, receptor, pose, center, size):
    cmd = [vina, '--receptor', receptor, '--ligand', pose, '--score_only',
           '--center_x', str(center[0]), '--center_y', str(center[1]), '--center_z', str(center[2]),
           '--size_x', str(size[0]), '--size_y', str(size[1]), '--size_z', str(size[2])]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    match = re.search(r'Estimated Free Energy of Binding\s*:\s*(-?\d+\.\d+)', out.stdout)
    return float(match.group(1)) if match else None


def run(manifest, ctx):
    import docking_engine as de
    from agents.target_analyst import auto_grid_from_pdb
    from validation.harness import ROOT, sha256_file

    vina = str(ROOT / manifest['vina_binary'])
    vina_sha = sha256_file(vina)
    if vina_sha != manifest['vina_expected_sha256']:
        raise RuntimeError(f'Vina binary hash {vina_sha} differs from the frozen protocol')
    import setup_env
    version = setup_env.vina_version(vina)
    if version is None or '.'.join(map(str, version)) != manifest['vina_expected_version']:
        raise RuntimeError(f'Vina version {version} differs from the frozen protocol')

    venv_dir = str(ROOT / '.venv' / 'Scripts')
    work = Path(tempfile.mkdtemp(prefix='pose_validation_'))
    exh, seed, reps = manifest['exhaustiveness'], manifest['seed'], manifest['n_replicas']
    threshold = manifest['rmsd_threshold_angstrom']
    items, prepared = [], {}

    def prepare(pdb):
        if pdb in prepared:
            return prepared[pdb]
        folder = work / pdb
        folder.mkdir(exist_ok=True)
        raw = fetch_pdb(pdb, folder / f'{pdb}.pdb')
        cleaned, receptor = str(folder / f'{pdb}_clean.pdb'), str(folder / f'{pdb}_rec.pdbqt')
        de.clean_protein_pdb(str(raw), cleaned)
        de.prepare_receptor(cleaned, receptor, venv_dir)
        center, size, source = auto_grid_from_pdb(str(raw))
        prepared[pdb] = (str(raw), receptor, center, size, source, str(folder))
        return prepared[pdb]

    def redock(pdb):
        raw, receptor, center, size, _src, folder = prepare(pdb)
        return de.validate_native_redock(raw, receptor, vina, center, size, folder,
                                         exhaustiveness=exh, seed=seed, n_replicas=reps)

    # ── D1 ──
    successes, first_rmsd, wrong_ligand = 0, {}, []
    for cx in manifest['complexes']:
        pdb, expected = cx['pdb'], cx['ligand']
        try:
            started = time.time()
            result = redock(pdb)
            seconds = round(time.time() - started, 1)
            if result is None:
                items.append({'item': f'D1:{pdb}', 'status': 'FAIL', 'details': {
                    'outcome': 'validate_native_redock returned None (skipped)', 'seconds': seconds,
                    'box_source': prepared[pdb][4]}})
                continue
            first_rmsd[pdb] = result['rmsd']
            right = result['resname'] == expected
            ok = right and result['rmsd'] < threshold
            successes += ok
            if not right:
                wrong_ligand.append(f"{pdb}: chose {result['resname']}, expected {expected}")
            items.append({'item': f'D1:{pdb}', 'status': 'PASS' if ok else 'FAIL', 'details': {
                'rmsd': result['rmsd'], 'chosen_ligand': result['resname'], 'expected_ligand': expected,
                'seconds': seconds, 'box_source': prepared[pdb][4]}})
        except Exception as exc:  # errors stay in the denominator
            items.append({'item': f'D1:{pdb}', 'status': 'ERROR',
                          'details': {'error': f'{type(exc).__name__}: {exc}'}})

    # ── D2 / D3 ──
    d2, d3, score_only_diffs = [], [], {}
    for pdb in manifest['repeat_subset']:
        expected = next(c['ligand'] for c in manifest['complexes'] if c['pdb'] == pdb)
        try:
            again = redock(pdb)
            same = again is not None and pdb in first_rmsd and again['rmsd'] == first_rmsd[pdb]
            d2.append(bool(same))
            items.append({'item': f'D2:{pdb}', 'status': 'PASS' if same else 'FAIL', 'details': {
                'first_rmsd': first_rmsd.get(pdb), 'second_rmsd': None if again is None else again['rmsd']}})
        except Exception as exc:
            d2.append(False)
            items.append({'item': f'D2:{pdb}', 'status': 'ERROR',
                          'details': {'error': f'{type(exc).__name__}: {exc}'}})
        try:
            raw, receptor, center, size, _src, folder = prepare(pdb)
            smiles = de._rcsb_ligand_smiles(expected)
            ligf = os.path.join(folder, 'd3_lig.pdbqt')
            de.prepare_ligand(smiles, ligf, seed=seed)
            res = de.dock_with_replicas(vina, receptor, ligf, os.path.join(folder, 'd3_out'),
                                        os.path.join(folder, 'd3_cfg'), center, size,
                                        exhaustiveness=exh, n_replicas=reps, base_seed=seed)
            checks = check_replica_report(res)
            d3.append(all(checks.values()))
            try:
                score_only_diffs[pdb] = round(abs(vina_score_only(vina, receptor, res['out_pdbqt'], center, size)
                                                  - res['best_score']), 3)
            except Exception:
                score_only_diffs[pdb] = None
            items.append({'item': f'D3:{pdb}', 'status': 'PASS' if all(checks.values()) else 'FAIL',
                          'details': {'checks': checks, 'best_score': res['best_score'], 'all_best': res['all_best'],
                                      'sd': res['sd'], 'confidence': res['confidence'],
                                      'vinardo': res['vinardo'], 'consensus': res['consensus']}})
        except Exception as exc:
            d3.append(False)
            items.append({'item': f'D3:{pdb}', 'status': 'ERROR',
                          'details': {'error': f'{type(exc).__name__}: {exc}'}})

    # ── D4 ──
    d4 = []
    def fault(name, fn):
        try:
            passed, detail = fn()
        except Exception as exc:
            passed, detail = False, f'unexpected {type(exc).__name__}: {exc}'
        d4.append(passed)
        items.append({'item': name, 'status': 'PASS' if passed else 'FAIL', 'details': {'outcome': detail}})

    def no_ligand():
        raw, receptor, center, size, _s, folder = prepare(manifest['no_ligand_structure'])
        out = de.validate_native_redock(raw, receptor, vina, center, size, folder,
                                        exhaustiveness=exh, seed=seed, n_replicas=1)
        return out is None, 'returned None' if out is None else f'returned {out}'

    def bad_smiles():
        try:
            de.prepare_ligand('not a smiles', str(work / 'bad.pdbqt'))
        except ValueError as exc:
            return True, f'ValueError: {exc}'
        return False, 'no ValueError'

    def missing_ligand_file():
        raw, receptor, center, size, _s, folder = prepare(manifest['repeat_subset'][0])
        try:
            log = de.run_docking(vina, receptor, str(work / 'does_not_exist.pdbqt'),
                                 str(work / 'o.pdbqt'), str(work / 'c.txt'), center, size,
                                 exhaustiveness=1)
        except Exception as exc:
            return True, f'{type(exc).__name__}'
        return False, f'returned {log!r} without raising'

    fault('D4a:no_ligand_structure', no_ligand)
    fault('D4b:invalid_smiles', bad_smiles)
    fault('D4c:missing_ligand_file', missing_ligand_file)

    n = len(manifest['complexes'])
    rate = successes / n
    lo, hi = wilson(successes, n)
    criteria = [
        {'id': 'D1', 'description': f"redocking success (RMSD < {threshold} A, expected ligand) rate >= {manifest['min_success_rate']}",
         'passed': rate >= manifest['min_success_rate'],
         'value': f'{successes}/{n} = {rate:.2f} (Wilson 95% CI {lo:.2f}-{hi:.2f})'},
        {'id': 'D2', 'description': 'identical RMSD on repeat (3 of 3)',
         'passed': len(d2) == 3 and all(d2), 'value': f'{sum(d2)}/3'},
        {'id': 'D3', 'description': 'replica report internally consistent (3 of 3)',
         'passed': len(d3) == 3 and all(d3), 'value': f'{sum(d3)}/3'},
        {'id': 'D4', 'description': 'bad input fails safely (3 of 3)',
         'passed': len(d4) == 3 and all(d4), 'value': f'{sum(d4)}/3'},
    ]
    extras = {'vina_version': '.'.join(map(str, version)), 'vina_sha256': vina_sha,
              'vina_bytes': os.path.getsize(vina), 'cpu_count': os.cpu_count(),
              'settings': {'exhaustiveness': exh, 'seed': seed, 'n_replicas': reps},
              'wrong_ligand_chosen': wrong_ligand, 'score_only_abs_diff_by_complex': score_only_diffs,
              'excluded_by_rule': manifest['excluded_by_rule'],
              'success_rate': rate, 'wilson_95': [lo, hi],
              'not_tested': ['scoring power', 'screening power', 'cross-docking', 'AlphaFold/apo targets',
                             'ProLIF interaction analysis']}
    return items, criteria, extras
