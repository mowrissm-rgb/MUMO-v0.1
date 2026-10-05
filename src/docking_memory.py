"""Fail-closed cache contracts. No persistence or automatic reuse is enabled here.

The caller must supply an authenticated owner and an exact prepared-input
manifest; display names are deliberately not cache identities.
"""
import hashlib
import json
import math
import re
import copy
from datetime import datetime

from verification import validate_box

_DIGEST = re.compile(r'^[0-9a-f]{64}$')
_VERSIONS = {'vina', 'rdkit', 'meeko', 'prolif', 'preparation', 'interactions'}
_UNKNOWN = {'', 'unknown', 'unavailable', 'not recorded', 'none'}


def _known(value):
    return isinstance(value, str) and value.strip().lower() not in _UNKNOWN


def _finite(value):
    return not isinstance(value, bool) and math.isfinite(float(value))


def pair_key(manifest):
    """Return an exact key, or None when identity/settings cannot be established."""
    try:
        if manifest['schema_version'] != 1:
            return None
        for field in ('receptor_sha256', 'ligand_sha256'):
            if not _DIGEST.fullmatch(manifest[field]):
                return None
        identity = manifest['target_identity']
        if not _known(identity['accession']) or int(identity['species']) <= 0:
            return None
        if not identity['chains'] or not all(_known(c) for c in identity['chains']):
            return None
        state = manifest['chemical_state']
        if not _known(state['isomeric_smiles']) or type(state['charge']) is not int:
            return None
        from rdkit import Chem
        molecule = Chem.MolFromSmiles(state['isomeric_smiles'])
        if molecule is None or Chem.GetFormalCharge(molecule) != state['charge']:
            return None
        if not _finite(state['ph']) or not 0 <= float(state['ph']) <= 14:
            return None
        validate_box(manifest['grid']['center'], manifest['grid']['size'])
        protocol = manifest['protocol']
        if protocol['scoring'] not in ('vina', 'vinardo'):
            return None
        if protocol['exhaustiveness'] not in (8, 16, 32):
            return None
        seeds = protocol['seeds']
        if len(seeds) != 3 or len(set(seeds)) != 3 or not all(type(s) is int for s in seeds):
            return None
        versions = manifest['versions']
        if not _VERSIONS.issubset(versions) or not all(_known(v) for v in versions.values()):
            return None
        settings = manifest['settings']
        if not all(isinstance(settings[name], dict) and settings[name]
                   for name in ('preparation', 'interactions', 'docking')):
            return None
        raw = json.dumps(manifest, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=True, allow_nan=False).encode('utf-8')
        return hashlib.sha256(raw).hexdigest()
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        return None


def _valid_pose(artifact):
    text = artifact['text']
    if hashlib.sha256(text.encode('utf-8')).hexdigest() != artifact['sha256']:
        return False
    atoms = [line for line in text.splitlines() if line.startswith(('ATOM  ', 'HETATM'))]
    return bool(atoms) and all(_finite(line[a:b]) for line in atoms
                              for a, b in ((30, 38), (38, 46), (46, 54)))


def _valid_replica(replica, manifest):
    for field in ('log', 'config'):
        if hashlib.sha256(replica[field].encode()).hexdigest() != replica[field+'_sha256']:
            return False
    log = replica['log']
    if 'mode |' not in log or any(word in log.lower() for word in ('timeout', 'error:')):
        return False
    scores = re.findall(r'^\s*1\s+([-+0-9.eE]+)\s', log, re.M)
    if not scores or abs(float(scores[0])-float(replica['score'])) > .001:
        return False
    config = dict(line.split('=', 1) for line in replica['config'].splitlines() if '=' in line)
    config = {k.strip(): v.strip() for k,v in config.items()}
    expected = {'seed': replica['seed'], 'exhaustiveness': manifest['protocol']['exhaustiveness'],
                'num_modes': manifest['settings']['docking']['num_modes'],
                'energy_range': manifest['settings']['docking']['energy_range']}
    expected.update({f'center_{axis}': value for axis,value in zip('xyz', manifest['grid']['center'])})
    expected.update({f'size_{axis}': value for axis,value in zip('xyz', manifest['grid']['size'])})
    return all(_finite(config[k]) and float(config[k]) == float(value) for k,value in expected.items())


def eligible_entry(entry, owner_id, key):
    """Check evidence without mutating it; wrong owners and corrupt data are misses."""
    try:
        if not owner_id or entry['owner_id'] != owner_id or entry['key'] != key:
            return False
        manifest = entry['manifest']
        if pair_key(manifest) != key or not key or not _known(entry['source_run_id']):
            return False
        date = datetime.fromisoformat(entry['created_at'])
        if date.tzinfo is None:
            return False
        score = entry['row']['Best affinity (kcal/mol)']
        if not _finite(score):
            return False
        if entry['row'].get('Verification status') == 'failed':
            return False
        if entry['row']['SMILES'] != manifest['chemical_state'].get(
                'source_smiles', manifest['chemical_state']['isomeric_smiles']):
            return False
        replicas = entry['replicas']
        if [r['seed'] for r in replicas] != manifest['protocol']['seeds']:
            return False
        for replica in replicas:
            if not _finite(replica['score']) or not _known(replica['log']):
                return False
            if not _valid_replica(replica, manifest):
                return False
            if not _valid_pose(replica['pose']):
                return False
        if abs(float(score) - min(float(r['score']) for r in replicas)) > .001:
            return False
        pose = entry['artifacts']['selected_pose']
        if not _valid_pose(pose):
            return False
        winners = [r for r in replicas if abs(float(r['score']) - float(score)) <= .001]
        if not any(r['pose']['sha256'] == pose['sha256'] for r in winners):
            return False
        interactions = entry['interactions']
        if interactions['status'] not in ('verified', 'qualified'):
            return False
        if interactions['status'] == 'qualified':
            evidence = interactions['verification']
            if (evidence['status'] != 'qualified' or evidence['rejected_records']
                    or evidence['source_pose_sha256'] != pose['sha256']
                    or evidence['checks']['export_reload'] != 'passed'
                    or evidence['checks']['analysis_uses_reloaded_artifacts'] is not True):
                return False
            if len(interactions['records']) != interactions['total_interactions']:
                return False
        count = interactions['total_interactions']
        return type(count) is int and count >= 0
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        return False


def plan_reuse(manifests, candidates, owner_id):
    """Server-supplied owner/candidates only. Never consult LLM conversation fields."""
    keys = [pair_key(m) for m in manifests]
    hits = {}
    for entry in candidates or []:
        key = entry.get('key') if isinstance(entry, dict) else None
        if key in keys and eligible_entry(entry, owner_id, key):
            hits[key] = copy.deepcopy(entry)
    return {'keys': keys, 'hits': hits,
            'hit_count': sum(key in hits for key in keys), 'total_pairs': len(keys)}


def execution_keys(plan, choice):
    """None means consent is still required, even for missing pairs."""
    if plan['hit_count'] and choice not in ('reuse', 'redock'):
        return None
    return [key for key in plan['keys'] if choice != 'reuse' or key not in plan['hits']]
