"""Interactions held-out check: the donor-hydrogen orientation fix on complexes not used to design it.

Protocol: validation/PROTOCOL.md, version 1.5. Each complex is analysed twice with the same preparation:
once with the orientation step switched off (the code before the fix) and once with it on (the shipped code).
"""
import os
import random
import tempfile
from pathlib import Path

from validation.checks import interactions as vi

TYPES = vi.TYPES


def _analyse(ia, cleaned, pdbqt, out_complex, smiles):
    res = ia.analyze_interactions(cleaned, pdbqt, out_complex, ligand_smiles=smiles)
    bypassed = False
    if res.get('status') == 'failed' and 'chemical identity' in (res.get('note') or ''):
        bypassed = True  # same pre-declared handling as protocol addendum 0.9a
        res = ia.analyze_interactions(cleaned, pdbqt, out_complex, ligand_smiles=None)
    if res.get('status') not in ('qualified', 'partial'):
        raise RuntimeError(f"MUMO analysis status {res.get('status')}: {res.get('note')}")
    return res, bypassed


def _hbond_counts(mumo, plip):
    return len(mumo & plip), len(mumo - plip), len(plip - mumo)  # tp, fp, fn


def _rates(tp, fp, fn):
    return (tp / (tp + fp) if tp + fp else None), (tp / (tp + fn) if tp + fn else None)


def run(manifest, ctx):
    import docking_engine as de
    from agents import interaction_analyst as ia
    from validation.checks.pose import fetch_pdb

    work = Path(tempfile.mkdtemp(prefix='interactions_heldout_'))
    real_orient = ia._orient_donor_hydrogens
    items, rows = [], []
    any_inter = any_union = 0
    on = [0, 0, 0]
    off = [0, 0, 0]
    for cx in manifest['complexes']:
        pdb, code = cx['pdb'], cx['ligand']
        name = f'IH:{pdb}/{code}'
        details, plip = {}, None
        try:
            folder = work / pdb
            folder.mkdir(exist_ok=True)
            raw = fetch_pdb(pdb, folder / f'{pdb}.pdb')
            text = Path(raw).read_text()
            cleaned = str(folder / f'{pdb}_clean.pdb')
            de.clean_protein_pdb(str(raw), cleaned)
            smiles = de._rcsb_ligand_smiles(code)
            pdbqt = str(folder / f'{code}_xtal.pdbqt')
            vi.build_crystal_pdbqt(text, code, smiles, manifest['ph'], pdbqt, de)
            (chain, resnum, _icode), _lines = vi.first_ligand_residue(text, code)
            plip, _water = vi.plip_contacts(str(raw), code, chain, resnum)
            try:
                ia._orient_donor_hydrogens = lambda *a, **k: []  # the code before the fix
                res_off, b_off = _analyse(ia, cleaned, pdbqt, os.path.join(folder, 'off.pdb'), smiles)
            finally:
                ia._orient_donor_hydrogens = real_orient
            res_on, b_on = _analyse(ia, cleaned, pdbqt, os.path.join(folder, 'on.pdb'), smiles)
            m_on, m_off = vi.mumo_contacts(res_on), vi.mumo_contacts(res_off)
            c_on = _hbond_counts(m_on['H-bond'], plip['H-bond'])
            c_off = _hbond_counts(m_off['H-bond'], plip['H-bond'])
            allm, allp = set().union(*m_on.values()), set().union(*plip.values())
            any_inter += len(allm & allp)
            any_union += len(allm | allp)
            rows.append({'pdb': pdb, 'on': c_on, 'off': c_off})
            details.update(plip_hbond_residues=len(plip['H-bond']), mumo_on=c_on, mumo_off=c_off,
                           identity_guard_bypassed=b_on or b_off)
            status = 'PASS'
        except Exception as exc:  # errors stay in the denominators; PLIP contacts still count when PLIP ran
            details['error'] = f'{type(exc).__name__}: {exc}'
            status = 'ERROR'
            if plip is not None:
                c = (0, 0, len(plip['H-bond']))
                rows.append({'pdb': pdb, 'on': c, 'off': c, 'error': True})
                any_union += len(set().union(*plip.values()))
        items.append({'item': name, 'status': status, 'details': details})

    for r in rows:
        for i in range(3):
            on[i] += r['on'][i]
            off[i] += r['off'][i]
    p_on, r_on = _rates(*on)
    p_off, r_off = _rates(*off)
    jac = any_inter / any_union if any_union else None

    rng = random.Random(manifest['bootstrap_seed'])
    gains = []
    for _ in range(manifest['bootstrap_resamples']):
        pick = [rows[rng.randrange(len(rows))] for _ in rows]
        tp_on, fn_on = sum(r['on'][0] for r in pick), sum(r['on'][2] for r in pick)
        tp_off, fn_off = sum(r['off'][0] for r in pick), sum(r['off'][2] for r in pick)
        if tp_on + fn_on and tp_off + fn_off:
            gains.append(tp_on / (tp_on + fn_on) - tp_off / (tp_off + fn_off))
    gains.sort()
    ci = (gains[int(0.025 * len(gains))], gains[int(0.975 * len(gains)) - 1]) if gains else (None, None)

    fmt = lambda v: None if v is None else round(v, 3)
    criteria = [
        {'id': 'IH1', 'description': f"H-bond precision and recall of the shipped code >= {manifest['hbond_min_precision']} (pooled, vs PLIP)",
         'passed': p_on is not None and r_on is not None and p_on >= manifest['hbond_min_precision'] and r_on >= manifest['hbond_min_recall'],
         'value': f'precision {fmt(p_on)}, recall {fmt(r_on)} (tp {on[0]}, fp {on[1]}, fn {on[2]})'},
        {'id': 'IH2', 'description': 'orientation finds strictly more PLIP H-bonds than the code before the fix',
         'passed': on[0] > off[0], 'value': f'true positives {on[0]} vs {off[0]}; recall {fmt(r_on)} vs {fmt(r_off)}'},
        {'id': 'IH3', 'description': f"precision does not fall by more than {manifest['max_precision_loss']}",
         'passed': p_on is not None and p_off is not None and p_on >= p_off - manifest['max_precision_loss'],
         'value': f'precision {fmt(p_on)} vs {fmt(p_off)}'},
        {'id': 'IH4', 'description': f"any-contact Jaccard >= {manifest['any_contact_min_jaccard']}",
         'passed': jac is not None and jac >= manifest['any_contact_min_jaccard'], 'value': f'{fmt(jac)}'},
    ]
    extras = {'n_complexes': len(manifest['complexes']), 'n_rows': len(rows),
              'recall_gain_bootstrap_95': [fmt(ci[0]), fmt(ci[1])],
              'before_fix': {'precision': fmt(p_off), 'recall': fmt(r_off), 'tp_fp_fn': off},
              'after_fix': {'precision': fmt(p_on), 'recall': fmt(r_on), 'tp_fp_fn': on},
              'not_tested': ['docked poses', 'experimental truth', 'water bridges']}
    return items, criteria, extras
