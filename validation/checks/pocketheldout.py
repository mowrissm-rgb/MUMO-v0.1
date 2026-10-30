"""Atlas pocket held-out check: the unchanged detector on complexes chosen by a fixed rule.

Protocol: validation/PROTOCOL.md, version 1.4.
"""
import time

from validation.checks import atlas
from validation.checks.pose import wilson


def run(manifest, ctx):
    from agents import target_analyst as ta

    client = atlas.Client()
    thr = manifest['dcc_threshold_angstrom']
    variant = manifest['descriptive_variant']
    items, rows = [], []
    for cx in manifest['complexes']:
        name = f"P:{cx['pdb']}/{cx['ligand']}"
        try:
            protein, lig, n_lig = atlas.parse_complex(client.pdb_text(cx['pdb']), cx['ligand'])
            started = time.time()
            pockets = ta.detect_pockets(protein)
            seconds = round(time.time() - started, 2)
            centroid = tuple(sum(a[i] for a in protein) / len(protein) for i in range(3))
            base_d = atlas.dist(centroid, lig)
            var = ta.detect_pockets(protein, **variant['kwargs'])
            var_d = atlas.dist(var[0]['center'], lig) if var else None
            if not pockets:
                rows.append({'pdb': cx['pdb'], 'found': False, 'top1': False, 'top3': False,
                             'baseline': base_d <= thr, 'variant': var_d is not None and var_d <= thr})
                items.append({'item': name, 'status': 'FAIL', 'details': {'outcome': 'no pocket returned',
                                                                          'baseline_dcc': round(base_d, 2)}})
                continue
            d = [atlas.dist(p['center'], lig) for p in pockets]
            size = pockets[0]['size'][0]
            inside = all(abs(c - l) <= size / 2 for c, l in zip(pockets[0]['center'], lig))
            row = {'pdb': cx['pdb'], 'found': True, 'top1': d[0] <= thr, 'top3': min(d[:3]) <= thr,
                   'baseline': base_d <= thr, 'variant': var_d is not None and var_d <= thr,
                   'dcc': d[0], 'n_atoms': len(protein), 'n_lig': n_lig, 'inside': inside}
            rows.append(row)
            items.append({'item': name, 'status': 'PASS' if row['top1'] else 'FAIL', 'details': {
                'dcc': round(d[0], 2), 'baseline_dcc': round(base_d, 2), 'best_of_top3': round(min(d[:3]), 2),
                'n_pockets': len(pockets), 'box_size': size, 'ligand_centroid_inside_box': inside,
                'variant_dcc': None if var_d is None else round(var_d, 2), 'seconds': seconds,
                'ligand_heavy_atoms': n_lig, 'protein_atoms': len(protein)}})
        except Exception as exc:  # errors stay in the denominator
            rows.append({'pdb': cx['pdb'], 'found': False, 'top1': False, 'top3': False, 'baseline': False,
                         'variant': False, 'error': True})
            items.append({'item': name, 'status': 'ERROR', 'details': {'error': f'{type(exc).__name__}: {exc}'}})

    n = len(rows)
    ok = sum(r['top1'] for r in rows)
    base = sum(r['baseline'] for r in rows)
    found = sum(r['found'] for r in rows)
    lo, hi = wilson(ok, n)
    criteria = [
        {'id': 'PH1', 'description': f"unchanged detector success rate >= {manifest['min_success_rate']}",
         'passed': ok / n >= manifest['min_success_rate'], 'value': f'{ok}/{n} = {ok / n:.2f} (Wilson 95% CI {lo:.2f}-{hi:.2f})'},
        {'id': 'PH2', 'description': 'strictly more successes than the protein-centroid baseline',
         'passed': ok > base, 'value': f'{ok}/{n} detector vs {base}/{n} centroid'},
        {'id': 'PH3', 'description': f"a pocket is returned for >= {manifest['min_coverage']} of complexes",
         'passed': found / n >= manifest['min_coverage'], 'value': f'{found}/{n}'},
    ]
    extras = {'n': n, 'success_top1': ok, 'success_top3': sum(r['top3'] for r in rows), 'baseline_successes': base,
              'variant_burial_R_14_successes': sum(r['variant'] for r in rows), 'wilson_95': [lo, hi],
              'box_contains_ligand_centroid': sum(bool(r.get('inside')) for r in rows),
              'development_summary': manifest['development_summary'],
              'note': 'No default was changed after the development comparison; the variant is descriptive only.'}
    return items, criteria, extras
