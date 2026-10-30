"""Flux held-out check: do rules added from development misses generalise?

Protocol: validation/PROTOCOL.md, version 1.3. One run, two rule sets (old and new)
on drugs that were never examined while the rules were chosen.
"""
import json
import random
import time

from validation.checks import flux


def build_heldout(client, development_drugs):
    """Drugs with one-step edges from non-human or unspecified-species records, outside the development set."""
    records = client.all_pages('metabolism.json', {'limit': 1000}, 'metabolisms')
    edges = [r for r in records if r.get('organism') != 'Homo sapiens' and r.get('drug_chembl_id')
             and r.get('metabolite_chembl_id') and r.get('substrate_chembl_id') == r['drug_chembl_id']
             and r['drug_chembl_id'] not in development_drugs]
    ids = sorted({r['drug_chembl_id'] for r in edges} | {r['metabolite_chembl_id'] for r in edges})
    smiles = {}
    for i in range(0, len(ids), 50):
        data = client.get(f'{flux.API}/molecule.json',
                          {'molecule_chembl_id__in': ','.join(ids[i:i + 50]), 'limit': 1000})
        for m in data['molecules']:
            smiles[m['molecule_chembl_id']] = (m.get('molecule_structures') or {}).get('canonical_smiles')
    drugs, organisms, dropped = {}, {}, 0
    for r in edges:
        d = r['drug_chembl_id']
        parent = flux.largest_fragment_smiles(smiles.get(d))
        key = flux.structure_key(smiles.get(r['metabolite_chembl_id']))
        if parent is None or key is None:
            dropped += 1
            continue
        entry = drugs.setdefault(d, {'name': r.get('substrate_name') or d, 'smiles': parent, 'refs': {}})
        organisms.setdefault(d, set()).add(r.get('organism') or 'unspecified')
        if key != flux.structure_key(parent):
            entry['refs'].setdefault(key, r.get('metabolite_name') or r['metabolite_chembl_id'])
    drugs = {d: v for d, v in drugs.items() if v['refs']}
    return drugs, {d: sorted(organisms[d]) for d in drugs}, dropped, len(records), len(edges)


def evaluate(drugs, settings, top_k, rules_label, with_integrity=False):
    """Run predictions for every drug; returns per-drug dicts."""
    from agents.metabolism import MAX_METABOLITES, predict_metabolites
    rows = {}
    for drug_id, info in sorted(drugs.items()):
        try:
            pred = predict_metabolites(info['smiles'], **settings)
            if '_error' in pred:
                raise RuntimeError(pred['_error'])
            mets = pred['metabolites']
            keys = [flux.structure_key(m['smiles']) for m in mets]
            refs = info['refs']
            hit = {k for k in keys if k in refs}
            row = {'n_refs': len(refs), 'hits': len(hit), 'hits_top': len({k for k in keys[:top_k] if k in refs}),
                   'n_pred': len(mets), 'ceiling': pred['n_generated'] >= MAX_METABOLITES,
                   'scores': [m['score'] for m in mets], 'labels': [int(k in refs) for k in keys],
                   'hit_rules': [m['name'] for m, k in zip(mets, keys) if k in refs]}
            if with_integrity:
                repeat = predict_metabolites(info['smiles'], **settings)
                row['integrity'] = flux.integrity(pred, flux.structure_key(info['smiles']), repeat)
            rows[drug_id] = row
        except Exception as exc:  # errors stay in the denominator
            rows[drug_id] = {'error': f'{type(exc).__name__}: {exc}', 'n_refs': len(info['refs']), 'hits': 0,
                             'hits_top': 0, 'n_pred': 0, 'ceiling': False, 'scores': [], 'labels': [], 'hit_rules': []}
    return rows


def recall(rows, key='hits'):
    refs = sum(r['n_refs'] for r in rows.values())
    return sum(r[key] for r in rows.values()) / refs if refs else 0.0


def auc_with_ci(rows, resamples, seed):
    data = [(r['scores'], r['labels']) for r in rows.values() if sum(r['labels']) > 0 and 'error' not in r]
    if not data:
        return None, None, None
    scores = [s for sc, _ in data for s in sc]
    labels = [l for _, lb in data for l in lb]
    lo, hi, _ = flux.bootstrap_auc(data, resamples, seed)
    return flux.roc_auc(scores, labels), lo, hi


def paired_gain_ci(old, new, resamples, seed):
    """Paired bootstrap over drugs of (new recall - old recall)."""
    ids = sorted(old)
    rng = random.Random(seed)
    diffs = []
    for _ in range(resamples):
        pick = [ids[rng.randrange(len(ids))] for _ in ids]
        refs = sum(old[i]['n_refs'] for i in pick)
        if refs == 0:
            continue
        diffs.append((sum(new[i]['hits'] for i in pick) - sum(old[i]['hits'] for i in pick)) / refs)
    diffs.sort()
    return diffs[int(0.025 * len(diffs))], diffs[min(len(diffs) - 1, int(0.975 * len(diffs)))]


def run(manifest, ctx):
    from agents import metabolism
    from agents.metabolism import predict_metabolites
    from validation.harness import ROOT, sha256_file, write_json

    client = flux.Client()
    dev_path = ROOT / manifest['development_snapshot']
    dev = json.loads(dev_path.read_text(encoding='utf-8'))['drugs']
    held, organisms, dropped, n_records, n_edges = build_heldout(client, set(dev))
    snapshot = ctx['out_dir'] / 'heldout_snapshot.json'
    write_json(snapshot, {'drugs': held, 'organisms': organisms})

    settings, top_k = manifest['flux_settings'], manifest['top_k']
    new_rules = list(metabolism.ALL_RULES)
    old_rules = [r for r in new_rules if r[0] not in set(manifest['new_rule_names'])]
    if len(old_rules) != len(new_rules) - len(manifest['new_rule_names']):
        raise RuntimeError('new rule names in the manifest do not match the rule list')

    try:
        metabolism.ALL_RULES = old_rules
        old_held = evaluate(held, settings, top_k, 'old')
        old_dev = evaluate(dev, settings, top_k, 'old')
        metabolism.ALL_RULES = new_rules
        started = time.time()
        new_held = evaluate(held, settings, top_k, 'new', with_integrity=True)
        seconds = round(time.time() - started, 1)
        new_dev = evaluate(dev, settings, top_k, 'new')
    finally:
        metabolism.ALL_RULES = new_rules

    r_old, r_new = recall(old_held), recall(new_held)
    t_old, t_new = recall(old_held, 'hits_top'), recall(new_held, 'hits_top')
    lo_gain, hi_gain = paired_gain_ci(old_held, new_held, manifest['bootstrap_resamples'], manifest['seed'])
    auc_new, auc_lo, auc_hi = auc_with_ci(new_held, manifest['bootstrap_resamples'], manifest['seed'])
    auc_old, _, _ = auc_with_ci(old_held, manifest['bootstrap_resamples'], manifest['seed'])

    integrity_ok = [all(r['integrity'].values()) if 'integrity' in r else False for r in new_held.values()]
    items = []
    for drug_id, row in sorted(new_held.items()):
        name = f"{drug_id} {held[drug_id]['name']}"
        if 'error' in row:
            items.append({'item': name, 'status': 'ERROR', 'details': {'error': row['error']}})
        else:
            ok = all(row['integrity'].values())
            items.append({'item': name, 'status': 'PASS' if ok else 'FAIL', 'details': {
                'n_refs': row['n_refs'], 'hits_old': old_held[drug_id]['hits'], 'hits_new': row['hits'],
                'n_pred_old': old_held[drug_id]['n_pred'], 'n_pred_new': row['n_pred'],
                'integrity': row['integrity'], 'organisms': organisms[drug_id]}})
    faults = []
    for fault in manifest['faults']:
        try:
            out = predict_metabolites(fault['smiles'], **fault['kwargs'])
            ok = isinstance(out, dict) and '_error' in out
            detail = 'error record' if ok else 'no error record'
        except Exception as exc:
            ok, detail = False, f'raised {type(exc).__name__}: {exc}'
        faults.append(ok)
        items.append({'item': fault['name'], 'status': 'PASS' if ok else 'FAIL', 'details': {'outcome': detail}})

    n = len(held)
    criteria = [
        {'id': 'FH1', 'description': f"held-out recall gain >= {manifest['min_recall_gain']} and paired 95% CI above 0",
         'passed': (r_new - r_old) >= manifest['min_recall_gain'] and lo_gain > 0,
         'value': f'old {r_old:.3f}, new {r_new:.3f}, gain {r_new - r_old:+.3f}, 95% CI [{lo_gain:+.3f}, {hi_gain:+.3f}]'},
        {'id': 'FH2', 'description': 'new-rule score AUC lower bound above 0.5',
         'passed': auc_lo is not None and auc_lo > 0.5,
         'value': f'AUC {None if auc_new is None else round(auc_new, 3)} [{None if auc_lo is None else round(auc_lo, 3)}, {None if auc_hi is None else round(auc_hi, 3)}] (old {None if auc_old is None else round(auc_old, 3)})'},
        {'id': 'FH3', 'description': f"top-{top_k} recall not more than {manifest['max_top_k_loss']} below the old rules",
         'passed': t_new >= t_old - manifest['max_top_k_loss'], 'value': f'old {t_old:.3f}, new {t_new:.3f}'},
        {'id': 'FH4', 'description': 'integrity on every held-out drug and 3 of 3 fault inputs',
         'passed': n > 0 and len(integrity_ok) == n and all(integrity_ok) and all(faults) and len(faults) == 3,
         'value': f'{sum(integrity_ok)}/{n} drugs; faults {sum(faults)}/{len(faults)}'},
    ]

    def split_recall(rows, group):
        sel = {d: r for d, r in rows.items() if (organisms[d] == ['unspecified']) == (group == 'unspecified')}
        return recall(sel) if sel else None
    new_rule_hits = {}
    for r in new_held.values():
        for rule in r['hit_rules']:
            if rule in manifest['new_rule_names']:
                new_rule_hits[rule] = new_rule_hits.get(rule, 0) + 1
    extras = {
        'chembl_records': n_records, 'candidate_edges': n_edges, 'dropped_edges': dropped, 'heldout_drugs': n,
        'heldout_refs': sum(r['n_refs'] for r in new_held.values()),
        'heldout': {'recall_old': r_old, 'recall_new': r_new, 'top_k_old': t_old, 'top_k_new': t_new,
                    'auc_old': auc_old, 'auc_new': auc_new},
        'development_not_evidence': {'recall_old': recall(old_dev), 'recall_new': recall(new_dev),
                                     'top_k_old': recall(old_dev, 'hits_top'), 'top_k_new': recall(new_dev, 'hits_top')},
        'mean_predictions': {'old': sum(r['n_pred'] for r in old_held.values()) / n,
                             'new': sum(r['n_pred'] for r in new_held.values()) / n},
        'ceiling_drugs': {'old': sum(r['ceiling'] for r in old_held.values()),
                          'new': sum(r['ceiling'] for r in new_held.values())},
        'recall_by_group_new': {g: split_recall(new_held, g) for g in ('unspecified', 'named')},
        'recall_by_group_old': {g: split_recall(old_held, g) for g in ('unspecified', 'named')},
        'new_rule_hits_on_heldout': new_rule_hits,
        'heldout_snapshot': {'file': snapshot.name, 'sha256': sha256_file(snapshot)},
        'new_rules_seconds': seconds,
    }
    return items, criteria, extras
