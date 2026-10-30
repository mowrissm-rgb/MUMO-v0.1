"""Scout check: ChEMBL target resolution and ligand retrieval fidelity.

Protocol: validation/PROTOCOL.md, section "Scout: ChEMBL retrieval fidelity".
Ground truth comes from independent ChEMBL queries made here, by a different
route from agents.ligand_scout (UniProt accession lookup; pChEMBL threshold
instead of ordered query).
"""
import time

import requests

HOST = 'https://www.ebi.ac.uk'
API = f'{HOST}/chembl/api/data'
HEADERS = {'Accept': 'application/json'}


class Client:
    def __init__(self):
        self.requests = 0

    def get(self, url, params=None):
        for attempt in range(4):
            self.requests += 1
            try:
                resp = requests.get(url, params=params, headers=HEADERS, timeout=60)
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 3:
                    raise
            else:
                if resp.status_code not in (429, 500, 502, 503, 504) or attempt == 3:
                    resp.raise_for_status()
                    return resp.json()
            time.sleep(1.0 * (2 ** attempt))

    def pages(self, path, params, key, cap):
        """Collect up to cap records; returns (records, truncated)."""
        records, url, query = [], f'{API}/{path}', dict(params)
        while url:
            data = self.get(url, query)
            records.extend(data.get(key, []))
            if len(records) >= cap:
                return records[:cap], bool(data['page_meta'].get('next'))
            nxt = data['page_meta'].get('next')
            url, query = (f'{HOST}{nxt}' if nxt else None), None
        return records, False


def true_target_ids(client, uniprot):
    data = client.get(f'{API}/target.json', {
        'target_components__accession': uniprot,
        'target_type': 'SINGLE PROTEIN', 'organism': 'Homo sapiens', 'limit': 20})
    return {t['target_chembl_id'] for t in data.get('targets', [])}


def _f(value):
    return None if value in (None, '') else float(value)


def check_ligands(client, target_id, ligands, limit, min_pchembl, cap):
    """Return (status, details) for checks (a)-(e)."""
    from rdkit import Chem
    problems = {}
    ids = [l['chembl_id'] for l in ligands]
    pch = [_f(l['pchembl']) for l in ligands]

    if len(set(ids)) != len(ids):
        problems['c_unique'] = 'duplicate molecules returned'
    if any(p is None for p in pch) or any(a < b for a, b in zip(pch, pch[1:]) if a is not None and b is not None):
        problems['b_order'] = f'pChEMBL not descending or missing: {pch}'
    bad_smiles = [l['chembl_id'] for l in ligands if Chem.MolFromSmiles(l['smiles']) is None]
    if bad_smiles:
        problems['d_smiles'] = f'unparseable SMILES: {bad_smiles}'

    # (a) independent per-molecule records on this target
    best, flagged = {}, []
    if ids:
        rows, _ = client.pages('activity.json', {
            'target_chembl_id': target_id, 'molecule_chembl_id__in': ','.join(ids),
            'pchembl_value__gte': min_pchembl, 'limit': 1000}, 'activities', cap)
        for row in rows:
            p = _f(row.get('pchembl_value'))
            mid = row['molecule_chembl_id']
            if p is not None and (mid not in best or p > best[mid][0]):
                best[mid] = (p, row.get('data_validity_comment'))
        for lig, p in zip(ligands, pch):
            record = best.get(lig['chembl_id'])
            if record is None:
                problems.setdefault('a_potency', []).append(f"{lig['chembl_id']}: no independent record >= {min_pchembl}")
            elif p is None or abs(record[0] - p) > 1e-9:
                problems.setdefault('a_potency', []).append(
                    f"{lig['chembl_id']}: scout {p} != independent max {record[0]}")
            if record and record[1]:
                flagged.append(lig['chembl_id'])

    # (e) completeness against a threshold query (different route from Scout's ordered query)
    full = len(ligands) == limit
    params = {'target_chembl_id': target_id, 'limit': 1000}
    if full:
        params['pchembl_value__gt'] = ligands[-1]['pchembl']
    else:
        params['pchembl_value__gte'] = min_pchembl
    pool, truncated = client.pages('activity.json', params, 'activities', cap)
    if truncated:
        return 'INCONCLUSIVE', {'reason': f'independent pool exceeds cap {cap}',
                                'problems': problems}
    expected = {row['molecule_chembl_id'] for row in pool if row.get('pchembl_value') not in (None, '')}
    missing = sorted(expected - set(ids))
    if missing:
        problems['e_complete'] = f'{len(missing)} molecules above the cutoff missing, e.g. {missing[:5]}'

    details = {'n_returned': len(ligands), 'top_pchembl': pch[0] if pch else None,
               'independent_pool_molecules': len(expected),
               'data_validity_flagged': flagged, 'problems': problems}
    return ('FAIL' if problems else 'PASS'), details


def run(manifest, ctx):
    from agents import ligand_scout

    client = Client()
    limit, min_p, cap = manifest['limit'], manifest['min_pchembl'], manifest['independent_pool_cap']
    items, s1_passed, s1_rows = [], 0, []
    try:
        status = client.get(f'{API}/status.json')
        release = status.get('chembl_db_version')
    except Exception as exc:
        release = f'unavailable: {exc}'

    for target in manifest['targets']:
        gene, uniprot = target['gene'], target['uniprot']
        row = {'gene': gene, 'uniprot': uniprot}
        try:
            truth = true_target_ids(client, uniprot)
            resolved, name = ligand_scout.find_target_id(gene)
            row.update(resolved=resolved, name=name, truth=sorted(truth),
                       s1=bool(resolved in truth))
            if not row['s1']:
                items.append({'item': gene, 'status': 'FAIL', 'details': {
                    'stage': 'S1', 'reason': 'resolved target not in UniProt ground truth', **row}})
                s1_rows.append(row)
                continue
            s1_passed += 1
            _, ligands = ligand_scout.find_ligands(gene, limit=limit, min_pchembl=min_p)
            status_s2, details = check_ligands(client, resolved, ligands, limit, min_p, cap)
            items.append({'item': gene, 'status': status_s2,
                          'details': {'stage': 'S2', **row, **details}})
        except Exception as exc:
            row['error'] = f'{type(exc).__name__}: {exc}'
            items.append({'item': gene, 'status': 'ERROR', 'details': row})
        s1_rows.append(row)

    s2_items = [i for i in items if i['details'].get('stage') == 'S2'
                or (i['status'] == 'ERROR' and i['details'].get('s1'))]
    s2_pass = sum(1 for i in s2_items if i['status'] == 'PASS')
    n = len(manifest['targets'])
    criteria = [
        {'id': 'S1', 'description': 'at least 9 of 10 targets resolve to the UniProt-matched human target',
         'passed': s1_passed >= 9, 'value': f'{s1_passed}/{n} resolved correctly'},
        {'id': 'S2', 'description': 'every S1-passing target satisfies checks (a)-(e)',
         'passed': s1_passed > 0 and s2_pass == s1_passed,
         'value': f'{s2_pass}/{s1_passed} S1-passing targets pass'},
    ]
    extras = {'chembl_release': release, 'http_requests': client.requests,
              'target_resolution': s1_rows,
              'flagged_ligand_counts': {i['item']: len(i['details'].get('data_validity_flagged', []))
                                        for i in items if 'data_validity_flagged' in i['details']}}
    return items, criteria, extras
