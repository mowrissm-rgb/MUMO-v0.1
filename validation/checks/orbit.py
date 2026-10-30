"""Orbit check: GFN2-xTB orbital energies, state handling and agreement with DFT (QM9).

Protocol: validation/PROTOCOL.md, section "Orbit: GFN2-xTB orbital energies".
Orbital surface rendering is NOT tested here.
"""
import csv
import math
import os
import random
import re
import statistics
import subprocess
import tempfile
import time
from pathlib import Path


def parse_molden(text):
    """[(energy_Eh, occupation)] for every MO in a Molden file, in file order."""
    mos, energy = [], None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('Ene='):
            energy = float(line.split('=')[1])
        elif line.startswith('Occup=') and energy is not None:
            mos.append((energy, float(line.split('=')[1])))
            energy = None
    return mos


def frontier(mos):
    """(homo_Eh, lumo_Eh, n_occupied) from a Molden orbital list; occupied means occupation > 0.5."""
    occ = [e for e, o in mos if o > 0.5]
    virt = [e for e, o in mos if o <= 0.5]
    if not occ or not virt:
        raise ValueError('no occupied or no virtual orbital in Molden data')
    return max(occ), min(virt), len(occ)


def pearson(x, y):
    if len(x) < 3:
        return None
    mx, my = statistics.fmean(x), statistics.fmean(y)
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy) if sx and sy else None


def spearman(x, y):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    return pearson(ranks(x), ranks(y))


def error_stats(pred, truth):
    errs = [p - t for p, t in zip(pred, truth)]
    return {'n': len(errs), 'mae': statistics.fmean(abs(e) for e in errs),
            'rmse': math.sqrt(statistics.fmean(e * e for e in errs)),
            'bias': statistics.fmean(errs), 'pearson': pearson(pred, truth), 'spearman': spearman(pred, truth)}


def run_xtb(xtb, xyz, charge, uhf):
    with tempfile.TemporaryDirectory(prefix='orbit_ref_') as tmp:
        Path(tmp, 'mol.xyz').write_text(xyz, encoding='ascii')
        proc = subprocess.run([xtb, 'mol.xyz', '--gfn', '2', '--sp', '--chrg', str(charge),
                               '--uhf', str(uhf), '--molden'], cwd=tmp, capture_output=True,
                              text=True, encoding='utf-8', errors='replace', timeout=300)
        if proc.returncode != 0:
            raise RuntimeError(f'reference xtb exited with {proc.returncode}')
        return Path(tmp, 'molden.input').read_text(encoding='utf-8', errors='replace'), proc.stdout


def run(manifest, ctx):
    from agents import qm_analyst
    from validation.harness import ROOT, sha256_file

    xtb = str(ROOT / manifest['xtb_binary'])
    qm9_path = ROOT / manifest['qm9_file']
    xtb_sha, qm9_sha = sha256_file(xtb), sha256_file(qm9_path)
    if xtb_sha != manifest['xtb_expected_sha256']:
        raise RuntimeError(f'xtb hash {xtb_sha} differs from the frozen protocol')
    if qm9_sha != manifest['qm9_expected_sha256']:
        raise RuntimeError(f'QM9 hash {qm9_sha} differs from the frozen protocol')
    os.environ['MUMO_XTB'] = xtb
    timeout, ha = manifest['timeout_seconds'], manifest['hartree_to_ev']

    items, o1, o2, o3 = [], [], [], []
    # ── Part O ──
    for drug in manifest['drugs']:
        name, smiles = drug['name'], drug['smiles']
        try:
            first = qm_analyst.orbitals(smiles, timeout=timeout)
            if '_error' in first:
                raise RuntimeError(first['_error'])
            molden, _ = run_xtb(xtb, first['evidence']['xyz'], first['charge'], first['unpaired_electrons'])
            homo, lumo, n_occ = frontier(parse_molden(molden))
            c1 = (abs(first['homo_eh'] - homo) <= 1e-4 and abs(first['lumo_eh'] - lumo) <= 1e-4
                  and abs(first['gap_ev'] - (lumo - homo) * ha) <= 1e-3)
            kept = parse_molden(first.get('molden', '')) if first.get('molden') else []
            kept_occ = sum(1 for _, o in kept if o > 0.5)
            c2 = (first['homo_index'] == first['electron_count'] // 2 == n_occ
                  and first['lumo_index'] == first['homo_index'] + 1 and kept_occ == first['homo_index'])
            second = qm_analyst.orbitals(smiles, timeout=timeout)
            c3 = all(first[k] == second.get(k) for k in ('homo_ev', 'lumo_ev', 'gap_ev'))
            o1.append(c1)
            o2.append(c2)
            o3.append(c3)
            items.append({'item': f'O:{name}', 'status': 'PASS' if (c1 and c2 and c3) else 'FAIL', 'details': {
                'o1_fidelity': c1, 'o2_indices_molden': c2, 'o3_repeatable': c3,
                'homo_ev': first['homo_ev'], 'lumo_ev': first['lumo_ev'], 'gap_ev': first['gap_ev'],
                'mumo_homo_index': first['homo_index'], 'electrons': first['electron_count'],
                'kept_molden_occupied': kept_occ}})
        except Exception as exc:  # errors stay in the denominator
            for bucket in (o1, o2, o3):
                bucket.append(False)
            items.append({'item': f'O:{name}', 'status': 'ERROR',
                          'details': {'error': f'{type(exc).__name__}: {exc}'}})

    # ── Part Q ──
    q = []
    for case in manifest['state_cases']:
        saved = os.environ.get('MUMO_XTB')
        if case.get('xtb_override'):
            os.environ['MUMO_XTB'] = case['xtb_override']
        try:
            out = qm_analyst.orbitals(case['smiles'], timeout=timeout, **case['kwargs'])
            if case['expect'] == 'error':
                ok, detail = isinstance(out, dict) and '_error' in out, out.get('_error', 'no error record')
            else:
                finite = all(isinstance(out.get(k), (int, float)) and math.isfinite(out[k])
                             for k in ('homo_ev', 'lumo_ev', 'gap_ev'))
                ok = out.get('status') == 'verified' and finite
                detail = out.get('status') if ok else out.get('_error', f"status {out.get('status')}")
                if ok and 'net_charge' in case:
                    match = re.search(r'net charge\s+(-?\d+)', out['evidence']['stdout'])
                    ok = bool(match) and int(match.group(1)) == case['net_charge']
                    detail = f"xtb net charge {match.group(1) if match else 'not found'}"
        except Exception as exc:
            ok, detail = False, f'raised {type(exc).__name__}: {exc}'
        finally:
            if saved is not None:
                os.environ['MUMO_XTB'] = saved
        q.append(ok)
        items.append({'item': case['name'], 'status': 'PASS' if ok else 'FAIL',
                      'details': {'expected': case['expect'], 'observed': str(detail)[:200]}})

    # ── Part G ──
    with open(qm9_path, newline='', encoding='utf-8') as fh:
        rows = list(csv.DictReader(fh))
    rng = random.Random(manifest['seed'])
    sample = [rows[i] for i in rng.sample(range(len(rows)), manifest['qm9_sample_size'])]
    pred = {'homo': [], 'lumo': [], 'gap': []}
    truth = {'homo': [], 'lumo': [], 'gap': []}
    failed, started = [], time.time()
    for row in sample:
        try:
            out = qm_analyst.orbitals(row['smiles'], timeout=timeout)
            if '_error' in out:
                raise RuntimeError(out['_error'])
        except Exception as exc:
            failed.append({'mol_id': row['mol_id'], 'smiles': row['smiles'], 'reason': str(exc)[:120]})
            continue
        for key, col in (('homo', 'homo_ev'), ('lumo', 'lumo_ev'), ('gap', 'gap_ev')):
            pred[key].append(out[col])
            truth[key].append(float(row[key]) * ha)
    seconds = round(time.time() - started, 1)
    n_total, n_done = len(sample), len(pred['gap'])
    coverage = n_done / n_total
    stats = {k: error_stats(pred[k], truth[k]) for k in pred} if n_done >= 3 else {}
    baseline = None
    if n_done >= 3:
        mean_gap = statistics.fmean(truth['gap'])
        baseline = statistics.fmean(abs(t - mean_gap) for t in truth['gap'])
    items.append({'item': 'G:qm9_sample', 'status': 'PASS' if (coverage >= manifest['min_coverage']
                  and stats and (stats['gap']['pearson'] or 0) >= manifest['min_gap_pearson']) else 'FAIL',
                  'details': {'n_sampled': n_total, 'n_computed': n_done, 'coverage': coverage,
                              'seconds': seconds, 'failed': failed}})

    n = len(manifest['drugs'])
    gap_r = stats['gap']['pearson'] if stats else None
    criteria = [
        {'id': 'O1', 'description': 'MUMO HOMO/LUMO/gap equal xTB Molden values (20 of 20)',
         'passed': len(o1) == n and all(o1), 'value': f'{sum(o1)}/{n}'},
        {'id': 'O2', 'description': 'orbital indices and captured Molden consistent (20 of 20)',
         'passed': len(o2) == n and all(o2), 'value': f'{sum(o2)}/{n}'},
        {'id': 'O3', 'description': 'repeat runs identical (20 of 20)',
         'passed': len(o3) == n and all(o3), 'value': f'{sum(o3)}/{n}'},
        {'id': 'Q1', 'description': 'state and failure handling as specified (8 of 8)',
         'passed': len(q) == 8 and all(q), 'value': f'{sum(q)}/8'},
        {'id': 'G1', 'description': f"QM9 coverage >= {manifest['min_coverage']} and gap Pearson r >= {manifest['min_gap_pearson']}",
         'passed': coverage >= manifest['min_coverage'] and gap_r is not None and gap_r >= manifest['min_gap_pearson'],
         'value': f"coverage {coverage:.3f} ({n_done}/{n_total}); gap r {None if gap_r is None else round(gap_r, 3)}"},
    ]
    extras = {'xtb_sha256': xtb_sha, 'qm9_sha256': qm9_sha, 'xtb_version': '6.7.1pre',
              'qm9_vs_mumo_ev': stats, 'gap_mean_predictor_mae_ev': baseline,
              'qm9_failed': failed, 'qm9_seconds': seconds,
              'not_tested': ['orbital surface rendering', 'excitation energies', 'large or charged drug-like systems vs DFT']}
    return items, criteria, extras
