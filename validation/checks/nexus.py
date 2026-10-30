"""Nexus check: fidelity of agents.string_analyst to the STRING REST API.

Protocol: validation/PROTOCOL.md, section "Nexus: STRING retrieval fidelity".
Ground truth comes from independent STRING calls made here: POST requests,
STRING IDs as identifiers, and resolution through UniProt accessions.
"""
import time
import xml.etree.ElementTree as ET

import requests

API = 'https://string-db.org/api'
CHANNELS = ('nscore', 'fscore', 'pscore', 'ascore', 'escore', 'dscore', 'tscore')
PRIOR = 0.041
SCORE_TOL = 1e-9


class Client:
    def __init__(self):
        self.requests = 0

    def post(self, method, data):
        for attempt in range(4):
            self.requests += 1
            try:
                resp = requests.post(f'{API}/json/{method}', data=data, timeout=60)
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 3:
                    raise
            else:
                if resp.status_code not in (429, 500, 502, 503, 504) or attempt == 3:
                    resp.raise_for_status()
                    return resp.json()
            time.sleep(1.0 * (2 ** attempt))


def _ids(items):
    return '\r'.join(items)


def resolve_by_uniprot(client, uniprots, species):
    rows = client.post('get_string_ids', {'identifiers': _ids(uniprots), 'species': species,
                                          'limit': 1, 'echo_query': 1})
    return {row['queryItem']: row['stringId'] for row in rows}


def independent_partners(client, string_ids, species, limit):
    return client.post('interaction_partners', {'identifiers': _ids(string_ids),
                                                'species': species, 'limit': limit})


def independent_enrichment(client, string_ids, species):
    return client.post('enrichment', {'identifiers': _ids(string_ids), 'species': species})


def combined_from_channels(record):
    """STRING's prior-corrected combination of channel scores (diagnostic only)."""
    prod = 1.0
    for channel in CHANNELS:
        corrected = max(0.0, (record[channel] - PRIOR) / (1 - PRIOR))
        prod *= 1 - corrected
    total = 1 - prod
    return total + PRIOR * (1 - total)


def _pair(rec):
    return (rec['stringId_A'], rec['stringId_B'])


def _scores_equal(a, b):
    return all(abs(a[k] - b[k]) <= SCORE_TOL for k in ('score',) + CHANNELS)


def _enr_key(row):
    return (row.get('category'), row.get('term'), row.get('fdr'), row.get('number_of_genes'))


def check_item(client, item, species, limit, analyze):
    genes, uniprots = item['genes'], item['uniprot']
    query = genes[0] if len(genes) == 1 else list(genes)
    result = analyze(query, species=species, limit=limit)
    checks, problems = {}, {}

    # N1: STRING IDs from gene symbols (Nexus) vs from UniProt accessions (independent)
    truth = resolve_by_uniprot(client, uniprots, species)
    nexus = {row['queryItem']: row['stringId'] for row in result['resolved']}
    expected = {gene: truth.get(uni) for gene, uni in zip(genes, uniprots)}
    checks['N1'] = nexus == expected and None not in expected.values()
    if not checks['N1']:
        problems['N1'] = {'nexus': nexus, 'independent_via_uniprot': expected}
    query_ids = [expected[g] for g in genes if expected[g]]

    # N2: partner list equals the independent call
    ind = independent_partners(client, query_ids, species, limit)
    mine = result['partners']
    same_pairs = [_pair(r) for r in mine] == [_pair(r) for r in ind]
    same_scores = same_pairs and all(_scores_equal(a, b) for a, b in zip(mine, ind))
    checks['N2'] = bool(same_scores)
    if not checks['N2']:
        problems['N2'] = {'n_nexus': len(mine), 'n_independent': len(ind),
                          'pairs_equal': same_pairs}

    # N3: integrity
    n3 = {}
    n3['a_scores_and_self'] = (all(0.0 <= r['score'] <= 1.0 for r in mine)
                               and all(r['stringId_A'] != r['stringId_B'] for r in mine))
    n3['b_count'] = len(mine) == len(ind)
    enr_ids = list(dict.fromkeys(query_ids + [r['stringId_B'] for r in ind[:12]]))
    ind_enr = independent_enrichment(client, enr_ids, species) if len(enr_ids) > 2 else []
    n3['c_enrichment'] = [_enr_key(r) for r in result['enrichment']] == [_enr_key(r) for r in ind_enr]
    try:
        svg = result['network_svg']
        n3['d_svg'] = bool(svg) and ET.fromstring(svg) is not None
    except ET.ParseError:
        n3['d_svg'] = False
    checks['N3'] = all(n3.values())
    if not checks['N3']:
        problems['N3'] = {k: v for k, v in n3.items() if not v}

    # diagnostics, no verdict
    diag = {'descending': all(a['score'] >= b['score'] for a, b in zip(ind, ind[1:])) if len(genes) == 1 else None,
            'channel_formula_max_abs_diff': max((abs(combined_from_channels(r) - r['score']) for r in ind),
                                                default=None),
            'channel_formula_within_0.002': (sum(abs(combined_from_channels(r) - r['score']) <= 0.002
                                                 for r in ind) / len(ind)) if ind else None,
            'n_partners': len(ind), 'n_enrichment_terms': len(ind_enr)}
    status = 'PASS' if all(checks.values()) else 'FAIL'
    return status, {'checks': checks, 'problems': problems, 'diagnostics': diag}


def run(manifest, ctx):
    from agents import string_analyst

    client = Client()
    species, limit = manifest['species'], manifest['limit']
    items, per_check = [], {'N1': [], 'N2': [], 'N3': []}

    try:
        version = client.post('version', {})[0].get('string_version')
    except Exception as exc:
        version = f'unavailable: {exc}'

    for item in manifest['items']:
        try:
            status, details = check_item(client, item, species, limit, string_analyst.analyze_string)
            for key in per_check:
                per_check[key].append(details['checks'][key])
        except Exception as exc:  # errors stay in the denominator
            status, details = 'ERROR', {'error': f'{type(exc).__name__}: {exc}'}
            for key in per_check:
                per_check[key].append(False)
        items.append({'item': item['name'], 'status': status, 'details': details})

    n4 = []
    for fault in manifest['faults']:
        try:
            string_analyst.analyze_string(fault['input'], species=species, limit=limit)
            status, details = 'FAIL', {'outcome': 'no exception raised'}
        except ValueError as exc:
            status, details = 'PASS', {'outcome': f'ValueError: {exc}'}
        except Exception as exc:
            status, details = 'FAIL', {'outcome': f'{type(exc).__name__}: {exc}'}
        n4.append(status == 'PASS')
        items.append({'item': fault['name'], 'status': status, 'details': details})

    n = len(manifest['items'])
    criteria = [
        {'id': 'N1', 'description': 'STRING IDs from gene symbols equal IDs via UniProt (100% of items)',
         'passed': all(per_check['N1']), 'value': f"{sum(per_check['N1'])}/{n} items"},
        {'id': 'N2', 'description': 'partner list equals independent STRING call (100% of items)',
         'passed': all(per_check['N2']), 'value': f"{sum(per_check['N2'])}/{n} items"},
        {'id': 'N3', 'description': 'score range, count, enrichment and SVG integrity (100% of items)',
         'passed': all(per_check['N3']), 'value': f"{sum(per_check['N3'])}/{n} items"},
        {'id': 'N4', 'description': 'bad input raises ValueError (2 of 2)',
         'passed': all(n4) and len(n4) == 2, 'value': f'{sum(n4)}/{len(n4)} faults'},
    ]
    diags = {i['item']: i['details']['diagnostics'] for i in items if 'diagnostics' in i['details']}
    within = [d['channel_formula_within_0.002'] for d in diags.values()
              if d['channel_formula_within_0.002'] is not None]
    extras = {'string_version': version, 'http_requests_independent': client.requests,
              'channel_formula_mean_fraction_within_0.002': (sum(within) / len(within)) if within else None,
              'per_item_diagnostics': diags}
    return items, criteria, extras
