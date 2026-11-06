"""Choose the held-out complexes for the Interactions re-test (protocol v1.5) and write the manifest.

The rule is fixed in validation/PROTOCOL.md v1.5. This script only selects; it never runs MUMO.
"""
import json
import random
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from crystal_additives import NOT_LIGAND  # noqa: E402

SEED, N_TARGET, MIN_HEAVY, MAX_HEAVY = 20261031, 30, 15, 45
QUERY = json.loads((ROOT / 'validation/manifests/pocketheldout.json').read_text())['selection']['query']
DEVELOPMENT = {c['pdb'] for c in json.loads((ROOT / 'validation/manifests/interactions.json').read_text())['complexes']}


def heavy_atoms_of_first_residue(text, code):
    key, n = None, 0
    for line in text.splitlines():
        if line.startswith('ENDMDL'):
            break
        if line.startswith('HETATM') and line[17:20].strip() == code:
            k = (line[21], line[22:26].strip(), line[26].strip())
            key = key or k
            element = (line[76:78].strip() or line[12:16].strip()[:1]).upper()
            if k == key and element != 'H':
                n += 1
    return n


def main():
    hits = requests.post('https://search.rcsb.org/rcsbsearch/v2/query', json=QUERY, timeout=120).json()
    ids = sorted(h['identifier'] for h in hits['result_set'])
    print('query hits', len(ids))
    random.Random(SEED).shuffle(ids)
    chosen, skipped = [], []
    for pdb in ids:
        if pdb in DEVELOPMENT:
            skipped.append((pdb, 'development entry'))
            continue
        try:
            entry = requests.get(f'https://data.rcsb.org/rest/v1/core/entry/{pdb}', timeout=60).json()
            eid = entry['rcsb_entry_container_identifiers']['non_polymer_entity_ids'][0]
            ent = requests.get(f'https://data.rcsb.org/rest/v1/core/nonpolymer_entity/{pdb}/{eid}', timeout=60).json()
            code = ent['pdbx_entity_nonpoly']['comp_id']
            if code in NOT_LIGAND:
                skipped.append((pdb, f'additive {code}'))
                continue
            text = requests.get(f'https://files.rcsb.org/download/{pdb}.pdb', timeout=120).text
            n = heavy_atoms_of_first_residue(text, code)
            if not MIN_HEAVY <= n <= MAX_HEAVY:
                skipped.append((pdb, f'{code} has {n} heavy atoms'))
                continue
            chosen.append({'pdb': pdb, 'ligand': code, 'heavy_atoms': n})
        except Exception as exc:  # an entry that cannot be described is skipped before anything is run
            skipped.append((pdb, f'{type(exc).__name__}'))
        if len(chosen) == N_TARGET:
            break
    manifest = {
        'workflow': 'Interactions held-out',
        'protocol_version': '1.5',
        'source': 'RCSB PDB entries chosen by a fixed query and a seeded sample (see PROTOCOL.md v1.5); PLIP 3.0.0 as comparator',
        'licence': 'CC0 (PDB); PLIP is GPL-2.0 (comparator only, not shipped with MUMO)',
        'selection': {'seed': SEED, 'query_hits': len(ids), 'query': QUERY, 'skipped_before_selection': skipped},
        'ph': 7.4,
        'complexes': chosen,
        'hbond_min_precision': 0.6,
        'hbond_min_recall': 0.6,
        'any_contact_min_jaccard': 0.4,
        'max_precision_loss': 0.05,
        'bootstrap_seed': SEED,
        'bootstrap_resamples': 2000,
    }
    out = ROOT / 'validation/manifests/interactionsheldout.json'
    out.write_text(json.dumps(manifest, indent=1))
    print('chosen', len(chosen), 'skipped', len(skipped), '->', out)
    for c in chosen:
        print(c['pdb'], c['ligand'], c['heavy_atoms'])


if __name__ == '__main__':
    main()
