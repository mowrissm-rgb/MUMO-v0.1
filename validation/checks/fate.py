"""Fate check: drug-likeness panel fidelity and ADMET-AI wrapper behaviour.

Protocol: validation/PROTOCOL.md, section "Fate: drug-likeness panel fidelity".
ADMET-AI accuracy is NOT tested here; F3 uses a stub model.
"""
import json
import math
import re
import time

import requests

PROPS = ('MolecularWeight,HeavyAtomCount,TPSA,HBondDonorCount,HBondAcceptorCount,'
         'RotatableBondCount,XLogP')


class Client:
    def __init__(self, base):
        self.base, self.requests = base, 0

    def properties(self, smiles):
        url = f'{self.base}/compound/smiles/property/{PROPS}/JSON'
        for attempt in range(4):
            self.requests += 1
            time.sleep(0.3)  # PubChem asks for at most 5 requests per second
            try:
                resp = requests.post(url, data={'smiles': smiles}, timeout=60)
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 3:
                    raise
            else:
                if resp.status_code not in (429, 500, 502, 503, 504) or attempt == 3:
                    resp.raise_for_status()
                    return resp.json()['PropertyTable']['Properties'][0]
            time.sleep(1.0 * (2 ** attempt))


def _num(value):
    return None if value in (None, '') else float(value)


def expected_ro5(dl):
    """Lipinski 1997 violations from MUMO's own reported descriptors."""
    return sum([dl['MW (g/mol)'] > 500, dl['LogP'] > 5,
                dl['H-bond donors'] > 5, dl['H-bond acceptors'] > 10])


def verdict_count(verdict):
    if verdict.startswith('Drug-like'):
        return 0
    match = re.match(r'(\d+) Ro5 violation', verdict)
    return int(match.group(1)) if match else None


def check_rules(dl):
    """F2: published-definition recomputation. Returns dict of check -> bool."""
    n = expected_ro5(dl)
    label = 'Pass' if n == 0 else f'{n} violation(s)'
    tpsa, logp, rotb = dl['TPSA (Å²)'], dl['LogP'], dl['Rotatable bonds']
    return {
        'lipinski': dl['Lipinski (Ro5)'] == label,
        'veber': dl['Veber'] == ('Pass' if rotb <= 10 and tpsa <= 140 else 'Fail'),
        'egan': dl['Egan'] == ('Pass' if tpsa <= 131.6 and logp <= 5.88 else 'Fail'),
        'verdict': verdict_count(dl['Verdict']) == n,
    }


def ghose_readings(dl, smiles):
    """Descriptive: Ghose outcome counting heavy atoms (MUMO) vs all atoms incl. H (as recalled)."""
    from rdkit import Chem
    mol = Chem.MolFromSmiles(smiles)
    heavy, total = mol.GetNumHeavyAtoms(), Chem.AddHs(mol).GetNumAtoms()
    base = (160 <= dl['MW (g/mol)'] <= 480 and -0.4 <= dl['LogP'] <= 5.6
            and 40 <= dl['Molar refractivity'] <= 130)
    return {'mumo_label': dl['Ghose'], 'heavy_atoms_reading': 'Pass' if base and 20 <= heavy <= 70 else 'Fail',
            'all_atoms_reading': 'Pass' if base and 20 <= total <= 70 else 'Fail',
            'heavy_atoms': heavy, 'total_atoms': total}


def compare_pubchem(dl, pc, tol):
    """F1 hard criteria plus descriptive differences."""
    mw_diff = abs(dl['MW (g/mol)'] - _num(pc['MolecularWeight']))
    heavy_equal = dl['Heavy atoms'] == int(pc['HeavyAtomCount'])
    desc = {
        'TPSA': (dl['TPSA (Å²)'], _num(pc.get('TPSA'))),
        'HBD': (dl['H-bond donors'], _num(pc.get('HBondDonorCount'))),
        'HBA': (dl['H-bond acceptors'], _num(pc.get('HBondAcceptorCount'))),
        'RotB': (dl['Rotatable bonds'], _num(pc.get('RotatableBondCount'))),
        'LogP_vs_XLogP': (dl['LogP'], _num(pc.get('XLogP'))),
    }
    diffs = {k: (None if b is None else round(abs(a - b), 4)) for k, (a, b) in desc.items()}
    return {'mw_ok': mw_diff <= tol, 'heavy_ok': heavy_equal, 'mw_diff': round(mw_diff, 4),
            'diffs': diffs, 'cid': pc.get('CID')}


# ── F3: wrapper behaviour with a stub model ─────────────────────────────────────
def _stub_frame(overrides=None, drop=None):
    import pandas as pd
    from agents import admet
    row = {sub: (0.123456 if kind == 'prob' else 1.23456) for _l, sub, kind in admet._ADMET_PANEL}
    row.update(overrides or {})
    for key in drop or []:
        row.pop(key)
    return pd.DataFrame([row])


class _Stub:
    def __init__(self, frame=None, error=None):
        self.frame, self.error = frame, error

    def predict(self, smiles=None):
        if self.error:
            raise self.error
        return self.frame


def wrapper_cases():
    """Yield (name, passed, detail). Patches and restores admet._get_admet_model."""
    from agents import admet
    panel = admet._ADMET_PANEL
    first_prob = next((l, s) for l, s, k in panel if k == 'prob')
    first_reg = next((l, s) for l, s, k in panel if k == 'reg')
    original = admet._get_admet_model
    probe = 'CCO'

    def run(stub, smiles=probe):
        admet._get_admet_model = lambda: stub
        try:
            return admet.admet_ml(smiles)
        finally:
            admet._get_admet_model = original

    cases = []
    out = run(_Stub(_stub_frame()))
    ok = (out['_verification']['status'] == 'verified'
          and sum(1 for k in out if not k.startswith('_')) == len(panel)
          and all(out[l] == (0.123 if k == 'prob' else 1.23) for l, _s, k in panel))
    cases.append(('F3.1 all valid', ok, out['_verification']['status']))

    out = run(_Stub(_stub_frame({first_prob[1]: 1.7})))
    ev = out['_verification']['endpoints'][first_prob[0]]
    cases.append(('F3.2 probability 1.7 rejected',
                  first_prob[0] not in out and ev['status'] == 'failed'
                  and out['_verification']['status'] == 'partial', ev['status']))

    out = run(_Stub(_stub_frame({first_reg[1]: float('nan')})))
    ev = out['_verification']['endpoints'][first_reg[0]]
    cases.append(('F3.3 NaN rejected', first_reg[0] not in out and ev['status'] == 'failed',
                  ev['status']))

    out = run(_Stub(_stub_frame(drop=[first_reg[1]])))
    ev = out['_verification']['endpoints'][first_reg[0]]
    cases.append(('F3.4 missing column',
                  first_reg[0] not in out and ev['status'] == 'missing'
                  and out['_verification']['status'] == 'partial', ev['status']))

    try:
        out = run(_Stub(_stub_frame()), smiles='not a smiles')
        cases.append(('F3.5 invalid SMILES', '_error' in out
                      and out['_verification']['status'] == 'failed', out.get('_error')))
    except Exception as exc:
        cases.append(('F3.5 invalid SMILES', False, f'raised {type(exc).__name__}'))

    try:
        out = run(_Stub(error=RuntimeError('boom')))
        cases.append(('F3.6 model raises', out.get('_error', '').startswith('ADMET-AI unavailable')
                      and out['_verification']['status'] == 'unavailable', out.get('_error')))
    except Exception as exc:
        cases.append(('F3.6 model raises', False, f'raised {type(exc).__name__}'))
    return cases


def run(manifest, ctx):
    from agents.admet import druglikeness
    try:
        import admet_ai  # noqa: F401
        admet_ai_installed = True
    except ImportError:
        admet_ai_installed = False

    client = Client(manifest['pubchem'])
    tol, repeats = manifest['mw_tolerance_da'], manifest['repeats']
    items, f1, f2, f4 = [], [], [], []
    descriptive = {'pubchem_diffs': {}, 'ghose': {}}

    for drug in manifest['drugs']:
        name, smiles = drug['name'], drug['smiles']
        details = {}
        try:
            first = druglikeness(smiles)
            dl = {k: v for k, v in first.items() if not k.startswith('_')}
            runs = [json.dumps(druglikeness(smiles), sort_keys=True, default=str) for _ in range(repeats - 1)]
            same = all(r == json.dumps(first, sort_keys=True, default=str) for r in runs)
            f4.append(same)
            rules = check_rules(dl)
            f2.append(all(rules.values()))
            details.update(f4_identical=same, f2=rules)
            descriptive['ghose'][name] = ghose_readings(dl, smiles)
            cmp = compare_pubchem(dl, client.properties(smiles), tol)
            f1.append(cmp['mw_ok'] and cmp['heavy_ok'])
            details['f1'] = {k: cmp[k] for k in ('mw_ok', 'heavy_ok', 'mw_diff', 'cid')}
            descriptive['pubchem_diffs'][name] = cmp['diffs']
            ok = cmp['mw_ok'] and cmp['heavy_ok'] and all(rules.values()) and same
            items.append({'item': name, 'status': 'PASS' if ok else 'FAIL', 'details': details})
        except Exception as exc:  # errors stay in the denominator
            for bucket in (f1, f2, f4):
                if len(bucket) < len(items) + 1:
                    bucket.append(False)
            details['error'] = f'{type(exc).__name__}: {exc}'
            items.append({'item': name, 'status': 'ERROR', 'details': details})

    f3 = []
    try:
        for case_name, passed, detail in wrapper_cases():
            f3.append(passed)
            items.append({'item': case_name, 'status': 'PASS' if passed else 'FAIL',
                          'details': {'observed': str(detail)}})
    except Exception as exc:
        f3.append(False)
        items.append({'item': 'F3 wrapper cases', 'status': 'ERROR',
                      'details': {'error': f'{type(exc).__name__}: {exc}'}})

    n = len(manifest['drugs'])
    criteria = [
        {'id': 'F1', 'description': 'MW within tolerance and heavy atoms equal to PubChem (100% of drugs)',
         'passed': len(f1) == n and all(f1), 'value': f'{sum(f1)}/{n} drugs'},
        {'id': 'F2', 'description': 'Lipinski, Veber, Egan and Verdict match published definitions (100%)',
         'passed': len(f2) == n and all(f2), 'value': f'{sum(f2)}/{n} drugs'},
        {'id': 'F3', 'description': 'ADMET-AI wrapper behaves as specified on 6 stub cases',
         'passed': len(f3) == 6 and all(f3), 'value': f'{sum(f3)}/6 cases'},
        {'id': 'F4', 'description': f'druglikeness identical across {repeats} runs (100% of drugs)',
         'passed': len(f4) == n and all(f4), 'value': f'{sum(f4)}/{n} drugs'},
    ]

    def stats(key):
        vals = [d[key] for d in descriptive['pubchem_diffs'].values() if d.get(key) is not None]
        return ({'n': len(vals), 'mean_abs_diff': round(sum(vals) / len(vals), 4),
                 'max_abs_diff': max(vals), 'exact_agreement': sum(v == 0 for v in vals) / len(vals)}
                if vals else None)

    ghose = descriptive['ghose']
    extras = {
        'admet_ai_installed': admet_ai_installed,
        'admet_ai_accuracy_tested': False,
        'pubchem_requests': client.requests,
        'pubchem_vs_mumo': {k: stats(k) for k in ('TPSA', 'HBD', 'HBA', 'RotB', 'LogP_vs_XLogP')},
        'ghose_heavy_vs_all_atoms_disagreements': sorted(
            n_ for n_, g in ghose.items() if g['heavy_atoms_reading'] != g['all_atoms_reading']),
        'ghose_mumo_label_differs_from_all_atoms_reading': sorted(
            n_ for n_, g in ghose.items() if g['mumo_label'] != g['all_atoms_reading']),
        'per_drug_pubchem_diffs': descriptive['pubchem_diffs'],
    }
    return items, criteria, extras
