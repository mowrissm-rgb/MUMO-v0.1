"""Compass check: disease resolution, ranking fidelity and sanity recall.

Protocol: validation/PROTOCOL.md, section "Compass: disease-to-target fidelity
and sanity recall". C3 is partly circular (Open Targets uses ChEMBL clinical
evidence); see the protocol.
"""
import time

import requests

OT = 'https://api.platform.opentargets.org/api/v4/graphql'
OLS = 'https://www.ebi.ac.uk/ols4/api/search'
CHEMBL = 'https://www.ebi.ac.uk/chembl/api/data'
NON_INDEPENDENT = {'clinical', 'literature'}

ASSOC_QUERY = """query($id:String!,$size:Int!){disease(efoId:$id){id name dbXRefs
 associatedTargets(page:{index:0,size:$size}){rows{score datatypeScores{id score}
 target{id approvedSymbol approvedName proteinIds{id source}}}}}}"""
TARGETS_QUERY = """query($ids:[String!]!){targets(ensemblIds:$ids){id approvedSymbol approvedName
 proteinIds{id source}}}"""
META_QUERY = "query{meta{apiVersion{x y z} dataVersion{year month iteration}}}"


class Client:
    def __init__(self):
        self.requests = 0

    def _retry(self, send):
        for attempt in range(4):
            self.requests += 1
            try:
                resp = send()
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 3:
                    raise
            else:
                if resp.status_code not in (429, 500, 502, 503, 504) or attempt == 3:
                    resp.raise_for_status()
                    return resp.json()
            time.sleep(1.0 * (2 ** attempt))

    def ot(self, query, variables=None):
        payload = self._retry(lambda: requests.post(
            OT, json={'query': query, 'variables': variables or {}}, timeout=60))
        if 'errors' in payload:
            raise RuntimeError(f"Open Targets error: {payload['errors']}")
        return payload['data']

    def get(self, url, params):
        return self._retry(lambda: requests.get(
            url, params=params, headers={'Accept': 'application/json'}, timeout=60))


def ols_exact_ids(client, name):
    data = client.get(OLS, {'q': name, 'exact': 'true', 'queryFields': 'label',
                            'ontology': 'efo,mondo', 'fieldList': 'short_form,label'})
    return {d['short_form'] for d in data['response']['docs']
            if d.get('label', '').lower() == name.lower()}


def swissprot(target):
    return {p['id'] for p in target.get('proteinIds') or [] if p['source'] == 'uniprot_swissprot'}


def tie_aware_equal(mine, independent):
    """mine/independent: lists of (ensembl_id, score). Compare scores in order, ID sets per score group."""
    if [round(s, 3) for _, s in mine] != [round(s, 3) for _, s in independent[:len(mine)]]:
        return False
    groups = {}
    for eid, score in independent:
        groups.setdefault(round(score, 3), set()).add(eid)
    mine_groups = {}
    for eid, score in mine:
        mine_groups.setdefault(round(score, 3), set()).add(eid)
    last = round(mine[-1][1], 3) if mine else None
    return all(ids <= groups[s] if s == last else ids == groups[s] for s, ids in mine_groups.items())


def chunks(items, n=50):
    items = list(items)
    for i in range(0, len(items), n):
        yield items[i:i + n]


def answer_key(client, disease_id, dbxrefs):
    """UniProt accessions of mechanism targets of phase-4 drugs for the disease (ChEMBL)."""
    queries = [{'efo_id': disease_id.replace('_', ':')}]
    queries += [{'mesh_id': x.split(':', 1)[1]} for x in dbxrefs if x.startswith('MESH:')]
    molecules = set()
    for q in queries:
        data = client.get(f'{CHEMBL}/drug_indication.json',
                          {**q, 'max_phase_for_ind': 4, 'limit': 1000})
        molecules |= {r['molecule_chembl_id'] for r in data['drug_indications']}
    targets = set()
    for part in chunks(sorted(molecules)):
        data = client.get(f'{CHEMBL}/mechanism.json',
                          {'molecule_chembl_id__in': ','.join(part), 'limit': 1000})
        targets |= {m['target_chembl_id'] for m in data['mechanisms'] if m.get('target_chembl_id')}
    accessions = set()
    for part in chunks(sorted(targets)):
        data = client.get(f'{CHEMBL}/target.json',
                          {'target_chembl_id__in': ','.join(part), 'limit': 1000})
        for t in data['targets']:
            accessions |= {c['accession'] for c in t.get('target_components') or [] if c.get('accession')}
    return accessions, len(molecules)


def check_disease(client, disease, limit, pool, find_id, find_targets):
    details, ok = {}, {}
    disease_id, _ = find_id(disease)
    details['resolved_id'] = disease_id
    ols = ols_exact_ids(client, disease)
    ok['C1'] = disease_id in ols
    details['ols_exact_ids'] = sorted(ols)
    if not disease_id:
        return ok, {'error': 'disease not resolved', **details}

    _, mine = find_targets(disease, limit=limit)
    info = client.ot(ASSOC_QUERY, {'id': disease_id, 'size': pool})['disease']
    rows = info['associatedTargets']['rows']
    mine_pairs = [(t['ensembl_id'], t['score']) for t in mine]
    ind_pairs = [(r['target']['id'], r['score']) for r in rows]
    entity = {t['id']: t for t in client.ot(TARGETS_QUERY, {'ids': [t['ensembl_id'] for t in mine]})['targets']}
    c2 = {'a_b_ranking': tie_aware_equal(mine_pairs, ind_pairs),
          'c_names': all(t['ensembl_id'] in entity
                         and entity[t['ensembl_id']]['approvedSymbol'] == t['symbol']
                         and entity[t['ensembl_id']]['approvedName'] == t['name'] for t in mine)}
    ok['C2'] = all(c2.values())
    details['C2'] = c2

    key, n_mol = answer_key(client, disease_id, info.get('dbXRefs') or [])
    top10 = set().union(*(swissprot(entity[t['ensembl_id']]) for t in mine if t['ensembl_id'] in entity))
    top25 = set().union(*(swissprot(r['target']) for r in rows[:25]))
    found = key & top10
    recovered_rows = [r for r in rows[:limit] if swissprot(r['target']) & key]
    details['C3'] = {
        'key_size': len(key), 'phase4_molecules': n_mol,
        'hit_at_10': bool(found) if key else None,
        'recall_at_10': round(len(found) / len(key), 3) if key else None,
        'recall_at_25': round(len(key & top25) / len(key), 3) if key else None,
        'found_symbols': sorted(r['target']['approvedSymbol'] for r in recovered_rows),
        'found_with_non_clinical_non_literature_evidence': sorted(
            r['target']['approvedSymbol'] for r in recovered_rows
            if any(d['id'] not in NON_INDEPENDENT and d['score'] > 0 for d in r['datatypeScores']))}
    ok['C3'] = (len(found) > 0) if key else None
    return ok, details


def run(manifest, ctx):
    from agents import target_finder

    client = Client()
    limit, pool = manifest['limit'], manifest['independent_pool']
    items, c1, c2, c3 = [], [], [], []
    empty_key = []
    try:
        meta = client.ot(META_QUERY)['meta']
        version = {'api': meta['apiVersion'], 'data': meta['dataVersion']}
    except Exception as exc:
        version = f'unavailable: {exc}'

    for disease in manifest['diseases']:
        try:
            ok, details = check_disease(client, disease, limit, pool,
                                        target_finder.find_disease_id, target_finder.find_targets)
            c1.append(ok['C1'])
            c2.append(bool(ok.get('C2')))
            if ok.get('C3') is None:
                empty_key.append(disease)
            else:
                c3.append(ok['C3'])
            applicable = [v for v in ok.values() if v is not None]
            status = 'PASS' if applicable and all(applicable) and 'error' not in details else 'FAIL'
        except Exception as exc:  # errors stay in the denominator
            c1.append(False)
            c2.append(False)
            c3.append(False)
            status, details = 'ERROR', {'error': f'{type(exc).__name__}: {exc}'}
        items.append({'item': disease, 'status': status, 'details': details})

    c4 = []
    for fault in manifest['faults']:
        try:
            target_finder.find_targets(fault['input'], limit=limit)
            status, details = 'FAIL', {'outcome': 'no exception raised'}
        except ValueError as exc:
            status, details = 'PASS', {'outcome': f'ValueError: {exc}'}
        except Exception as exc:
            status, details = 'FAIL', {'outcome': f'{type(exc).__name__}: {exc}'}
        c4.append(status == 'PASS')
        items.append({'item': fault['name'], 'status': status, 'details': details})

    n = len(manifest['diseases'])
    hit_rate = (sum(c3) / len(c3)) if c3 else 0.0
    criteria = [
        {'id': 'C1', 'description': 'resolved ID is an OLS exact-label match (at least 9 of 10)',
         'passed': sum(c1) >= 9, 'value': f'{sum(c1)}/{n} diseases'},
        {'id': 'C2', 'description': 'top-10 ranking, scores and names equal independent queries (100%)',
         'passed': len(c2) == n and all(c2), 'value': f'{sum(c2)}/{n} diseases'},
        {'id': 'C3', 'description': f"hit@10 against ChEMBL phase-4 mechanism targets (rate >= {manifest['hit_threshold']})",
         'passed': bool(c3) and hit_rate >= manifest['hit_threshold'],
         'value': f'{sum(c3)}/{len(c3)} diseases with a key (rate {hit_rate:.2f}); empty key: {empty_key}'},
        {'id': 'C4', 'description': 'bad input raises ValueError (3 of 3)',
         'passed': len(c4) == 3 and all(c4), 'value': f'{sum(c4)}/{len(c4)} faults'},
    ]
    extras = {'open_targets_version': version, 'http_requests_independent': client.requests,
              'circularity_note': 'C3 key is partly circular: Open Targets uses ChEMBL clinical evidence',
              'empty_key_diseases': empty_key}
    return items, criteria, extras
