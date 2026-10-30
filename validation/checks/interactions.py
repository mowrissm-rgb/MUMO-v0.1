"""Interactions check: MUMO's ProLIF contacts against PLIP on crystal complexes.

Protocol: validation/PROTOCOL.md, section "Interactions: ProLIF contacts
against PLIP on crystal complexes". Docked poses and rendering are NOT tested.
"""
import math
import os
import tempfile
import time
from pathlib import Path

TYPES = ('H-bond', 'Hydrophobic', 'Pi-stack', 'Salt bridge', 'Halogen', 'Pi-cation')
PLIP_ATTRS = {
    'H-bond': ('hbonds_ldon', 'hbonds_pdon'),
    'Hydrophobic': ('hydrophobic_contacts',),
    'Pi-stack': ('pistacking',),
    'Salt bridge': ('saltbridge_lneg', 'saltbridge_pneg'),
    'Halogen': ('halogen_bonds',),
    'Pi-cation': ('pication_laro', 'pication_paro'),
}


def stub_inchikey():
    """PLIP 3.0 asks OpenBabel for an InChIKey this build cannot write; return '' for that call only."""
    from openbabel import pybel
    if getattr(pybel.Molecule.write, '_inchikey_stub', False):
        return
    original = pybel.Molecule.write

    def write(self, format='smi', filename=None, overwrite=False, opt=None):
        if format == 'inchikey':
            return ''
        return original(self, format, filename, overwrite, opt)
    write._inchikey_stub = True
    pybel.Molecule.write = write


def first_ligand_residue(text, code):
    """(chain, resnum, icode) of the first residue with this hetero code, and its HETATM lines."""
    key, lines = None, []
    for line in text.splitlines():
        if line.startswith('ENDMDL'):
            break
        if line.startswith('HETATM') and line[17:20].strip() == code:
            k = (line[21], line[22:26].strip(), line[26].strip())
            key = key or k
            if k == key:
                lines.append(line)
    if key is None:
        raise ValueError(f'ligand {code} not found')
    return key, lines


def plip_contacts(pdb_path, code, chain, resnum):
    stub_inchikey()
    from plip.structure.preparation import PDBComplex
    cx = PDBComplex()
    cx.load_pdb(str(pdb_path))
    cx.analyze()
    key = f'{code}:{chain}:{int(resnum)}'
    if key not in cx.interaction_sets:
        raise KeyError(f'PLIP produced no interaction set for {key}')
    s = cx.interaction_sets[key]
    out = {t: {(int(i.resnr), i.reschain) for a in attrs for i in getattr(s, a)}
           for t, attrs in PLIP_ATTRS.items()}
    return out, len(getattr(s, 'water_bridges', []))


def mumo_contacts(result):
    out = {t: set() for t in TYPES}
    for r in result.get('records') or []:
        if r['type'] in out:
            out[r['type']].add((int(r['resnr']), r['reschain']))
    return out


def build_crystal_pdbqt(raw_text, code, smiles, ph, out_path, de):
    from rdkit import Chem
    from rdkit.Chem import AllChem
    from meeko import MoleculePreparation, PDBQTWriterLegacy
    _key, lines = first_ligand_residue(raw_text, code)
    template = Chem.RemoveAllHs(de._mol_from_smiles_at_ph(smiles, ph))
    native = Chem.RemoveAllHs(Chem.MolFromPDBBlock(''.join(l + chr(10) for l in lines), sanitize=False))
    fixed = AllChem.AssignBondOrdersFromTemplate(template, native)
    molh = Chem.AddHs(fixed, addCoords=True)
    text, ok, err = PDBQTWriterLegacy.write_string(MoleculePreparation().prepare(molh)[0])
    if not ok:
        raise RuntimeError(f'Meeko PDBQT writing failed: {err}')
    Path(out_path).write_text(text)


def check_counts(res):
    """I3: counts and residue lists derived from the records."""
    recs = res['records']
    by = lambda t: [r for r in recs if r['type'] == t]
    uniq = lambda rs: list(dict.fromkeys(r['tag'] for r in rs))
    return (res['total_interactions'] == len(recs)
            and res['n_hbonds'] == len(by('H-bond')) and res['hbond_residues'] == uniq(by('H-bond'))
            and res['n_hydrophobic'] == len(by('Hydrophobic')) and res['hydrophobic_residues'] == uniq(by('Hydrophobic'))
            and res['n_pistacking'] == len(by('Pi-stack')) and res['n_saltbridges'] == len(by('Salt bridge'))
            and res['n_halogen'] == len(by('Halogen')) and res['n_pication'] == len(by('Pi-cation'))
            and res['interacting_residues'] == sorted({r['tag'] for r in recs}))


def hydrophobic_distance_errors(res, max_distance, tol):
    """I2: list of problems among single-atom hydrophobic records; also returns the eligible count."""
    problems, eligible = [], 0
    for r in res['records']:
        if r['type'] != 'Hydrophobic':
            continue
        if len(r['ligand_atom_indices']) != 1 or len(r['protein_atom_indices']) != 1:
            continue
        eligible += 1
        d = math.dist(r['lig_xyz'], r['prot_xyz'])
        if r['distance'] is None or abs(r['distance'] - d) > tol or r['distance'] > max_distance + tol:
            problems.append(f"{r['tag']}: recorded {r['distance']}, geometry {d:.3f}")
    return problems, eligible


def run(manifest, ctx):
    import docking_engine as de
    from agents import interaction_analyst as ia
    from validation.checks.pose import fetch_pdb

    work = Path(tempfile.mkdtemp(prefix='interactions_validation_'))
    ph, tol, max_hyd = manifest['ph'], manifest['distance_tolerance'], manifest['hydrophobic_max_distance']
    items, i2_problems, i2_eligible, i3 = [], [], 0, []
    tally = {t: {'tp': 0, 'fp': 0, 'fn': 0} for t in TYPES}
    any_inter, any_union = 0, 0
    per_complex, plip_water = {}, {}
    cache = {}

    def prepared(pdb, code):
        if pdb in cache:
            return cache[pdb]
        folder = work / pdb
        folder.mkdir(exist_ok=True)
        raw = fetch_pdb(pdb, folder / f'{pdb}.pdb')
        text = Path(raw).read_text()
        cleaned = str(folder / f'{pdb}_clean.pdb')
        de.clean_protein_pdb(str(raw), cleaned)
        smiles = de._rcsb_ligand_smiles(code)
        pdbqt = str(folder / f'{code}_xtal.pdbqt')
        build_crystal_pdbqt(text, code, smiles, ph, pdbqt, de)
        cache[pdb] = (str(raw), text, cleaned, smiles, pdbqt, str(folder))
        return cache[pdb]

    for cx in manifest['complexes']:
        pdb, code = cx['pdb'], cx['ligand']
        name = f'I:{pdb}/{code}'
        details, error = {}, None
        plip, mumo = None, None
        try:
            raw, text, cleaned, smiles, pdbqt, folder = prepared(pdb, code)
            (chain, resnum, _icode), _lines = first_ligand_residue(text, code)
            started = time.time()
            plip, n_water = plip_contacts(raw, code, chain, resnum)
            details['plip_seconds'] = round(time.time() - started, 1)
            plip_water[pdb] = n_water
            res = ia.analyze_interactions(cleaned, pdbqt, os.path.join(folder, f'{pdb}_complex.pdb'),
                                          ligand_smiles=smiles)
            if res.get('status') not in ('qualified', 'partial'):
                raise RuntimeError(f"MUMO analysis status {res.get('status')}: {res.get('note')}")
            mumo = mumo_contacts(res)
            counts_ok = check_counts(res)
            problems, eligible = hydrophobic_distance_errors(res, max_hyd, tol)
            i2_problems += [f'{pdb}: {p}' for p in problems]
            i2_eligible += eligible
            i3.append(counts_ok)
            details.update(counts_consistent=counts_ok, hydrophobic_records_checked=eligible,
                           mumo_status=res['status'], rejected=len(res.get('verification', {}).get('rejected_records', [])))
        except Exception as exc:  # errors stay in the denominator
            error = f'{type(exc).__name__}: {exc}'
            i3.append(False)
            details['error'] = error
        if plip is not None:
            m = mumo or {t: set() for t in TYPES}
            for t in TYPES:
                tally[t]['tp'] += len(m[t] & plip[t])
                tally[t]['fp'] += len(m[t] - plip[t])
                tally[t]['fn'] += len(plip[t] - m[t])
            allm = set().union(*m.values())
            allp = set().union(*plip.values())
            any_inter += len(allm & allp)
            any_union += len(allm | allp)
            per_complex[pdb] = {'plip': {t: len(plip[t]) for t in TYPES},
                                'mumo': {t: len(m[t]) for t in TYPES} if mumo is not None else None,
                                'only_plip_any': sorted(f'{r}{c}' for r, c in allp - allm)[:12],
                                'only_mumo_any': sorted(f'{r}{c}' for r, c in allm - allp)[:12]}
        ok = error is None and details.get('counts_consistent', False)
        items.append({'item': name, 'status': 'ERROR' if error else ('PASS' if ok else 'FAIL'), 'details': details})

    # ── I4 faults ──
    i4 = []
    first = manifest['complexes'][0]
    try:
        raw, text, cleaned, smiles, pdbqt, folder = prepared(first['pdb'], first['ligand'])
    except Exception as exc:
        cleaned = smiles = pdbqt = folder = None
        items.append({'item': 'fault:setup', 'status': 'ERROR', 'details': {'error': str(exc)}})

    def fault(name, call):
        try:
            res = call()
            ok = (isinstance(res, dict) and res.get('status') in ('failed', 'unavailable')
                  and res.get('total_interactions') is None and res.get('n_hbonds') is None)
            detail = f"status {res.get('status')}, total {res.get('total_interactions')}"
        except Exception as exc:
            ok, detail = False, f'raised {type(exc).__name__}: {exc}'
        i4.append(ok)
        items.append({'item': name, 'status': 'PASS' if ok else 'FAIL', 'details': {'outcome': detail}})

    if cleaned:
        fault('fault:missing_ligand_file', lambda: ia.analyze_interactions(
            cleaned, os.path.join(folder, 'does_not_exist.pdbqt'), os.path.join(folder, 'x.pdb'), ligand_smiles=smiles))
        fault('fault:smiles_mismatch', lambda: ia.analyze_interactions(
            cleaned, pdbqt, os.path.join(folder, 'y.pdb'), ligand_smiles=manifest['fault_smiles_mismatch']))

    def pr(t):
        c = tally[t]
        p = c['tp'] / (c['tp'] + c['fp']) if c['tp'] + c['fp'] else None
        r = c['tp'] / (c['tp'] + c['fn']) if c['tp'] + c['fn'] else None
        return p, r
    hb_p, hb_r = pr('H-bond')
    jac = any_inter / any_union if any_union else None
    n = len(manifest['complexes'])
    fmt = lambda v: None if v is None else round(v, 3)
    criteria = [
        {'id': 'I1', 'description': 'H-bond precision and recall >= 0.6; any-contact Jaccard >= 0.4 vs PLIP (pooled)',
         'passed': (hb_p is not None and hb_r is not None and hb_p >= manifest['hbond_min_precision']
                    and hb_r >= manifest['hbond_min_recall'] and jac is not None
                    and jac >= manifest['any_contact_min_jaccard']),
         'value': f'H-bond precision {fmt(hb_p)}, recall {fmt(hb_r)}; any-contact Jaccard {fmt(jac)}'},
        {'id': 'I2', 'description': 'hydrophobic record distances equal geometry and are within 4.5 A (100%, at least one record)',
         'passed': i2_eligible > 0 and not i2_problems,
         'value': f'{i2_eligible - len(i2_problems)}/{i2_eligible} records ok'},
        {'id': 'I3', 'description': 'counts and residue lists consistent with records (100% of complexes)',
         'passed': len(i3) == n and all(i3), 'value': f'{sum(i3)}/{n} complexes'},
        {'id': 'I4', 'description': 'bad input returns failed status with null counts (2 of 2)',
         'passed': len(i4) == 2 and all(i4), 'value': f'{sum(i4)}/{len(i4)}'},
    ]
    extras = {'plip_version': '3.0.0', 'per_type_precision_recall': {t: {'precision': fmt(pr(t)[0]), 'recall': fmt(pr(t)[1]),
              **tally[t]} for t in TYPES}, 'any_contact_jaccard': fmt(jac), 'per_complex': per_complex,
              'plip_water_bridges': plip_water, 'i2_problems': i2_problems[:20],
              'not_tested': ['docked poses', 'experimental truth', 'water bridges', '2D/3D rendering']}
    return items, criteria, extras
