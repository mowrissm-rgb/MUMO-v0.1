"""Guard against scientific mismatches and cross-owner calculation reuse."""
import copy
import hashlib
import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def manifest():
    return {'schema_version': 1, 'receptor_sha256': 'a' * 64,
            'ligand_sha256': 'b' * 64,
            'target_identity': {'accession': 'P00533', 'species': 9606, 'chains': ['A']},
            'chemical_state': {'isomeric_smiles': 'C[C@H](O)F', 'charge': 0, 'ph': 7.4},
            'grid': {'center': [1., 2., 3.], 'size': [20., 20., 20.]},
            'protocol': {'scoring': 'vina', 'exhaustiveness': 16, 'seeds': [42, 43, 44]},
            'settings': {'preparation': {'ph': 7.4, 'seed': 42, 'n_confs': 4, 'max_rot': 10},
                         'interactions': {'method': 'ProLIF'},
                         'docking': {'num_modes': 6, 'energy_range': 3.0, 'cpu': 'auto'}},
            'versions': {'vina': '1.2.5', 'rdkit': '2025.09.1', 'meeko': '0.6.1',
                         'prolif': '2.0.3', 'preparation': 'v1', 'interactions': 'v1'}}


class DockingMemoryTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('docking_memory'),
                             'Exact private reuse validation is missing')
        import docking_memory
        return docking_memory

    def test_same_manifest_order_does_not_change_key(self):
        memory = self.module()
        data = manifest()
        key = memory.pair_key(data)
        self.assertRegex(key, r'^[0-9a-f]{64}$')
        self.assertEqual(memory.pair_key(dict(reversed(list(data.items())))), key)

    def test_complete_qualified_interactions_preserve_qualifiers(self):
        memory = self.module()
        entry = self.entry(memory)
        entry['interactions'].update(status='qualified', note='Hydrogen geometry not optimized',
            records=[], verification={'status': 'qualified', 'rejected_records': [],
                'source_pose_sha256': entry['artifacts']['selected_pose']['sha256'],
                'checks': {'export_reload': 'passed', 'analysis_uses_reloaded_artifacts': True}})
        self.assertTrue(memory.eligible_entry(entry, 'alice', entry['key']))
        entry['interactions']['verification']['rejected_records'] = [{'reason': 'invalid geometry'}]
        self.assertFalse(memory.eligible_entry(entry, 'alice', entry['key']))

    def test_settings_missing_and_failed_rows_are_ineligible(self):
        memory = self.module()
        data = manifest(); del data['settings']
        self.assertIsNone(memory.pair_key(data))
        entry = self.entry(memory); entry['row']['Verification status'] = 'failed'
        self.assertFalse(memory.eligible_entry(entry, 'alice', entry['key']))

    def test_each_prepared_input_or_setting_change_is_a_miss(self):
        memory = self.module()
        original = manifest()
        key = memory.pair_key(original)
        edits = [('receptor_sha256', None, 'c'*64), ('ligand_sha256', None, 'c'*64),
                 ('target_identity', 'accession', 'P04626'),
                 ('target_identity', 'chains', ['B']), ('target_identity', 'species', 10090),
                 ('chemical_state', 'isomeric_smiles', 'C[C@@H](O)F'),
                 ('chemical_state', 'charge', 1), ('chemical_state', 'ph', 6.0),
                 ('grid', 'center', [2., 2., 3.]), ('grid', 'size', [21., 20., 20.]),
                 ('protocol', 'scoring', 'vinardo'), ('protocol', 'exhaustiveness', 32),
                 ('protocol', 'seeds', [43, 44, 45])]
        edits += [('versions', name, 'different') for name in original['versions']]
        for field, nested, value in edits:
            with self.subTest(field=field, nested=nested):
                changed = copy.deepcopy(original)
                if nested:
                    changed[field][nested] = value
                else:
                    changed[field] = value
                self.assertNotEqual(memory.pair_key(changed), key)

    def test_missing_unknown_and_malformed_inputs_never_have_keys(self):
        memory = self.module()
        for section in manifest():
            data = manifest()
            del data[section]
            self.assertIsNone(memory.pair_key(data))

    def test_corrupt_version_shape_and_invalid_chemistry_are_misses(self):
        memory = self.module()
        for versions in [None, [], '1.2.5']:
            data = manifest(); data['versions'] = versions
            self.assertIsNone(memory.pair_key(data))
        data = manifest(); data['chemical_state']['isomeric_smiles'] = 'invalid'
        self.assertIsNone(memory.pair_key(data))
        data = manifest(); data['chemical_state']['charge'] = 1
        self.assertIsNone(memory.pair_key(data))
        for unknown in [None, '', 'unknown', 'unavailable']:
            data = manifest()
            data['versions']['vina'] = unknown
            self.assertIsNone(memory.pair_key(data))
        for grid in [None, {'center': [float('nan'), 0, 0], 'size': [1, 1, 1]},
                     {'center': [0, 0, 0], 'size': [0, 1, 1]}]:
            data = manifest(); data['grid'] = grid
            self.assertIsNone(memory.pair_key(data))

    def entry(self, memory):
        atom = 'ATOM      1  C   LIG A   1       1.000   2.000   3.000  1.00  0.00           C\n'
        artifact = {'text': atom, 'sha256': hashlib.sha256(atom.encode()).hexdigest()}
        entry = {'owner_id': 'alice', 'key': memory.pair_key(manifest()), 'manifest': manifest(),
                'source_run_id': 'original-1', 'created_at': '2026-10-05T00:00:00+00:00',
                'row': {'Best affinity (kcal/mol)': -6., 'SMILES': 'C[C@H](O)F'},
                'artifacts': {'selected_pose': artifact},
                'replicas': [{'seed': seed, 'score': score, 'pose': artifact, 'log': 'completed'}
                             for seed, score in [(42, -5.8), (43, -6.), (44, -5.9)]],
                'interactions': {'status': 'verified', 'total_interactions': 0}}
        for replica in entry['replicas']:
            replica['log'] = f"mode |   affinity\n1 {replica['score']} 0 0\n"
            replica['log_sha256'] = hashlib.sha256(replica['log'].encode()).hexdigest()
            replica['config'] = (f"seed = {replica['seed']}\nexhaustiveness = 16\nnum_modes = 6\nenergy_range = 3.0\n"
                "center_x = 1\ncenter_y = 2\ncenter_z = 3\nsize_x = 20\nsize_y = 20\nsize_z = 20\n")
            replica['config_sha256'] = hashlib.sha256(replica['config'].encode()).hexdigest()
        return entry

    def test_corrupt_logs_and_config_cannot_be_reused(self):
        memory = self.module()
        for field in ['log', 'log_sha256', 'config', 'config_sha256']:
            entry = self.entry(memory)
            entry['replicas'][0][field] = 'corrupt'
            self.assertFalse(memory.eligible_entry(entry, 'alice', entry['key']))
        entry = self.entry(memory)
        entry['replicas'][0]['config'] = entry['replicas'][0]['config'].replace('seed = 42', 'seed = 100')
        entry['replicas'][0]['config_sha256'] = hashlib.sha256(entry['replicas'][0]['config'].encode()).hexdigest()
        self.assertFalse(memory.eligible_entry(entry, 'alice', entry['key']))

    def test_entry_requires_same_owner_complete_evidence_and_unchanged_atoms(self):
        memory = self.module()
        entry = self.entry(memory)
        original = copy.deepcopy(entry)
        key = entry['key']
        self.assertTrue(memory.eligible_entry(entry, 'alice', key))
        self.assertEqual(entry, original)
        self.assertFalse(memory.eligible_entry(entry, 'bob', key))
        self.assertFalse(memory.eligible_entry(entry, None, key))
        self.assertFalse(memory.eligible_entry(entry, 'alice', '0'*64))
        for score in ['FAILED', None, float('nan'), float('inf'), -7.]:
            changed = copy.deepcopy(entry)
            changed['row']['Best affinity (kcal/mol)'] = score
            self.assertFalse(memory.eligible_entry(changed, 'alice', key))
        for field in ['replicas', 'artifacts', 'source_run_id', 'created_at', 'manifest']:
            changed = copy.deepcopy(entry); changed.pop(field)
            self.assertFalse(memory.eligible_entry(changed, 'alice', key))
        changed = copy.deepcopy(entry)
        changed['artifacts']['selected_pose']['text'] += 'changed'
        self.assertFalse(memory.eligible_entry(changed, 'alice', key))
        changed = copy.deepcopy(entry); changed['replicas'].pop()
        self.assertFalse(memory.eligible_entry(changed, 'alice', key))
        changed = copy.deepcopy(entry); changed['interactions']['status'] = 'unavailable'
        self.assertFalse(memory.eligible_entry(changed, 'alice', key))


if __name__ == '__main__':
    unittest.main()
