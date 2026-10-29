"""Flux check: predicted metabolites against ChEMBL's literature-curated human metabolism.

Protocol: validation/PROTOCOL.md, section "Flux: metabolite prediction against
literature-curated metabolism".
"""
import json
import random
import time

import requests

HOST = 'https://www.ebi.ac.uk'
API = f'{HOST}/chembl/api/data'


class Client:
    def __init__(self):
        self.requests = 0

    def get(self, url, params=None):
        for attempt in range(4):
            self.requests += 1
            try:
                resp = requests.get(url, params=params, headers={'Accept': 'application/json'}, timeout=120)
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 3:
                    raise
            else:
                if resp.status_code not in (429, 500, 502, 503, 504) or attempt == 3:
                    resp.raise_for_status()
                    return resp.json()
            time.sleep(1.0 * (2 ** attempt))

    def all_pages(self, path, params, key):
        records, url, query = [], f'{API}/{path}', dict(params)
        while url:
            data = self.get(url, query)
            records.extend(data[key])
            nxt = data['page_meta'].get('next')
            url, query = (f'{HOST}{nxt}' if nxt else None), None
        return records


def structure_key(smiles):
    """First InChIKey block of the largest fragment, or None."""
    from rdkit import Chem
    from rdkit.Chem.MolStandardize import rdMolStandardize
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return None
    try:
        mol = rdMolStandardize.LargestFragmentChooser().choose(mol)
        return Chem.MolToInchiKey(mol)[:14]
    except Exception:
        return None


def largest_fragment_smiles(smiles):
    from rdkit import Chem
    from rdkit.Chem.MolStandardize import rdMolStandardize
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return None
    return Chem.MolToSmiles(rdMolStandardize.LargestFragmentChooser().choose(mol))


def roc_auc(scores, labels):
    """Mann-Whitney AUC with midranks; None if one class is empty."""
    pos = sum(labels)
    neg = len(labels) - pos
    if pos == 0 or neg == 0:
        return None
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        mid = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = mid
        i = j + 1
    rank_sum = sum(r for r, lab in zip(ranks, labels) if lab)
    return (rank_sum - pos * (pos + 1) / 2) / (pos * neg)


def bootstrap_auc(per_drug, resamples, seed):
    """per_drug: list of (scores, labels). Resample drugs; returns (lo, hi, invalid)."""
    rng = random.Random(seed)
    aucs, invalid = [], 0
    for _ in range(resamples):
        sample = [per_drug[rng.randrange(len(per_drug))] for _ in per_drug]
        scores = [s for sc, _ in sample for s in sc]
        labels = [l for _, lb in sample for l in lb]
        auc = roc_auc(scores, labels)
        if auc is None:
            invalid += 1
        else:
            aucs.append(auc)
    aucs.sort()
    if not aucs:
        return None, None, invalid
    return aucs[int(0.025 * len(aucs))], aucs[min(len(aucs) - 1, int(0.975 * len(aucs)))], invalid


def build_reference(client):
    """Return (drugs, dropped, release): drugs maps drug id -> {name, smiles, refs{key: name}}."""
    records = client.all_pages('metabolism.json', {'limit': 1000}, 'metabolisms')
    human = [r for r in records if r.get('organism') == 'Homo sapiens']
    edges = [r for r in human if r.get('drug_chembl_id') and r.get('metabolite_chembl_id')
             and r.get('substrate_chembl_id') == r['drug_chembl_id']]
    ids = sorted({r['drug_chembl_id'] for r in edges} | {r['metabolite_chembl_id'] for r in edges})
    smiles = {}
    for i in range(0, len(ids), 50):
        data = client.get(f'{API}/molecule.json',
                          {'molecule_chembl_id__in': ','.join(ids[i:i + 50]), 'limit': 1000})
        for m in data['molecules']:
            struct = m.get('molecule_structures') or {}
            smiles[m['molecule_chembl_id']] = struct.get('canonical_smiles')
    drugs, dropped = {}, []
    for r in edges:
        d = r['drug_chembl_id']
        parent = largest_fragment_smiles(smiles.get(d))
        key = structure_key(smiles.get(r['metabolite_chembl_id']))
        if parent is None or key is None:
            dropped.append({'drug': d, 'metabolite': r['metabolite_chembl_id'],
                            'reason': 'drug structure missing' if parent is None else 'metabolite structure missing'})
            continue
        entry = drugs.setdefault(d, {'name': r.get('substrate_name') or d, 'smiles': parent, 'refs': {}})
        if key != structure_key(parent):
            entry['refs'].setdefault(key, r.get('metabolite_name') or r['metabolite_chembl_id'])
    drugs = {d: v for d, v in drugs.items() if v['refs']}
    return drugs, dropped, len(records), len(human), len(edges)


def integrity(pred, parent_key, repeat):
    """X3 (a)-(e): returns dict of check -> bool."""
    from rdkit import Chem
    mets = pred['metabolites']
    smis = [m['smiles'] for m in mets]
    scores = [m['score'] for m in mets]
    return {
        'a_parse': all(Chem.MolFromSmiles(s) is not None for s in smis),
        'b_unique': len(set(smis)) == len(smis) and pred['parent'] not in smis,
        'c_scores': all(0 < s <= 1 for s in scores) and all(a >= b for a, b in zip(scores, scores[1:])),
        'd_generation': all(m['generation'] == len(m['pathway']) for m in mets),
        'e_repeatable': json.dumps(pred, sort_keys=True, default=str)
                        == json.dumps(repeat, sort_keys=True, default=str),
    }


def run(manifest, ctx):
    from agents.metabolism import MAX_METABOLITES, predict_metabolites
    from validation.harness import sha256_file, write_json

    client = Client()
    settings, top_k = manifest['flux_settings'], manifest['top_k']
    drugs, dropped, n_all, n_human, n_edges = build_reference(client)
    try:
        release = client.get(f'{API}/status.json').get('chembl_db_version')
    except Exception as exc:
        release = f'unavailable: {exc}'
    snapshot = ctx['out_dir'] / 'reference_snapshot.json'
    write_json(snapshot, {'chembl_release': release, 'drugs': drugs, 'dropped': dropped})

    items, x3_ok = [], []
    totals = {'refs': 0, 'hit_all': 0, 'hit_topk': 0}
    pooled, per_drug_auc_data = [], []
    rule_hits, gen_hits, misses, summaries = {}, {1: 0, 2: 0}, [], []
    ceiling = []

    for drug_id, info in sorted(drugs.items()):
        name = f"{drug_id} {info['name']}"
        try:
            started = time.time()
            pred = predict_metabolites(info['smiles'], **settings)
            seconds = round(time.time() - started, 2)
            if '_error' in pred:
                raise RuntimeError(pred['_error'])
            repeat = predict_metabolites(info['smiles'], **settings)
            checks = integrity(pred, structure_key(info['smiles']), repeat)
            x3_ok.append(all(checks.values()))

            mets = pred['metabolites']
            keys = [structure_key(m['smiles']) for m in mets]
            refs = info['refs']
            hit_refs = {k for k in keys if k in refs}
            topk_refs = {k for k in keys[:top_k] if k in refs}
            totals['refs'] += len(refs)
            totals['hit_all'] += len(hit_refs)
            totals['hit_topk'] += len(topk_refs)
            labels = [int(k in refs) for k in keys]
            if hit_refs:
                per_drug_auc_data.append(([m['score'] for m in mets], labels))
            for m, k in zip(mets, keys):
                if k in refs:
                    rule_hits[m['name']] = rule_hits.get(m['name'], 0) + 1
                    gen_hits[m['generation']] = gen_hits.get(m['generation'], 0) + 1
            for k, ref_name in refs.items():
                if k not in hit_refs:
                    misses.append({'drug': name, 'metabolite': ref_name})
            if pred['n_generated'] >= MAX_METABOLITES:
                ceiling.append(name)
            summaries.append({'drug': name, 'n_reference': len(refs), 'n_predicted': len(mets),
                              'hits_all': len(hit_refs), 'hits_top_k': len(topk_refs), 'seconds': seconds})
            items.append({'item': name, 'status': 'PASS' if all(checks.values()) else 'FAIL',
                          'details': {'x3': checks, **summaries[-1]}})
        except Exception as exc:  # errors stay in the denominator
            x3_ok.append(False)
            totals['refs'] += len(info['refs'])
            items.append({'item': name, 'status': 'ERROR',
                          'details': {'error': f'{type(exc).__name__}: {exc}', 'n_reference': len(info['refs'])}})

    x4 = []
    for fault in manifest['faults']:
        try:
            out = predict_metabolites(fault['smiles'], **fault['kwargs'])
            passed = isinstance(out, dict) and '_error' in out
            details = {'outcome': 'error record' if passed else 'no error record returned'}
        except Exception as exc:
            passed, details = False, {'outcome': f'raised {type(exc).__name__}: {exc}'}
        x4.append(passed)
        items.append({'item': fault['name'], 'status': 'PASS' if passed else 'FAIL', 'details': details})

    micro = totals['hit_all'] / totals['refs'] if totals['refs'] else 0.0
    micro_k = totals['hit_topk'] / totals['refs'] if totals['refs'] else 0.0
    macro = (sum(s['hits_all'] / s['n_reference'] for s in summaries) / len(summaries)) if summaries else None
    pooled_scores = [s for sc, _ in per_drug_auc_data for s in sc]
    pooled_labels = [l for _, lb in per_drug_auc_data for l in lb]
    auc = roc_auc(pooled_scores, pooled_labels)
    lo, hi, invalid = (bootstrap_auc(per_drug_auc_data, manifest['x2_bootstrap_resamples'], manifest['seed'])
                       if per_drug_auc_data else (None, None, 0))

    n_drugs = len(drugs)
    criteria = [
        {'id': 'X1', 'description': f"micro recall of reference metabolites >= {manifest['x1_min_micro_recall']}",
         'passed': micro >= manifest['x1_min_micro_recall'],
         'value': f"{totals['hit_all']}/{totals['refs']} = {micro:.3f} (top {top_k}: {micro_k:.3f}; macro {macro if macro is None else round(macro, 3)})"},
        {'id': 'X2', 'description': 'bootstrap 95% CI lower bound of score AUC above 0.5',
         'passed': lo is not None and lo > 0.5,
         'value': f"AUC {None if auc is None else round(auc, 3)}, 95% CI [{None if lo is None else round(lo, 3)}, {None if hi is None else round(hi, 3)}] over {len(per_drug_auc_data)} drugs"},
        {'id': 'X3', 'description': 'output integrity (a)-(e) on 100% of drugs',
         'passed': n_drugs > 0 and len(x3_ok) == n_drugs and all(x3_ok), 'value': f'{sum(x3_ok)}/{n_drugs} drugs'},
        {'id': 'X4', 'description': 'bad input returns an error record, never raises (3 of 3)',
         'passed': len(x4) == 3 and all(x4), 'value': f'{sum(x4)}/{len(x4)} faults'},
    ]
    extras = {
        'chembl_release': release, 'http_requests': client.requests,
        'reference_snapshot': {'file': snapshot.name, 'sha256': sha256_file(snapshot)},
        'chembl_metabolism_records': n_all, 'human_records': n_human, 'one_step_edges': n_edges,
        'drugs_evaluated': n_drugs, 'dropped_edges': len(dropped),
        'recall': {'micro_all': micro, 'micro_top_k': micro_k, 'macro_all': macro,
                   'reference_metabolites': totals['refs'], 'hits_all': totals['hit_all'],
                   'hits_top_k': totals['hit_topk'], 'top_k': top_k},
        'auc_pooled': auc, 'auc_ci': [lo, hi], 'auc_bootstrap_invalid': invalid,
        'hits_by_rule': dict(sorted(rule_hits.items(), key=lambda kv: -kv[1])),
        'hits_by_generation': gen_hits, 'ceiling_reached': ceiling,
        'missed_reference_metabolites': misses, 'per_drug': summaries,
    }
    return items, criteria, extras
