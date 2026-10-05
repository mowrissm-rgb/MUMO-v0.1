"""Private reuse must gate execution and preserve scientific evidence."""
import copy
import importlib.util
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import test_docking_memory as fixtures
from test_docking_memory import manifest
import docking_memory as memory
import docking_jobs as jobs


def cache_entry(index=0):
    entry = fixtures.DockingMemoryTests().entry(memory)
    entry['manifest']['ligand_sha256'] = f'{index:064x}'
    entry['key'] = memory.pair_key(entry['manifest'])
    entry['row'].update(Ligand=f'L{index}', Target='T', Reliability='qualified')
    entry['viz'] = {'pdb': entry['artifacts']['selected_pose']['text'], 'ia': entry['interactions']}
    entry['target_meta'] = {'validation': {'passed': False}, 'reliability_by': {}}
    return entry


class CacheFlowTests(unittest.TestCase):
    def test_five_of_twenty_gate_then_fifteen_or_redock_twenty(self):
        self.assertTrue(hasattr(memory, 'plan_reuse'), 'Pair scheduling with explicit consent is missing')
        entries = [cache_entry(i) for i in range(5)]
        before = copy.deepcopy(entries)
        manifests = [cache_entry(i)['manifest'] for i in range(20)]
        plan = memory.plan_reuse(manifests, entries, 'alice')
        self.assertEqual(plan['hit_count'], 5)
        self.assertIsNone(memory.execution_keys(plan, None))
        self.assertEqual(len(memory.execution_keys(plan, 'reuse')), 15)
        self.assertEqual(len(memory.execution_keys(plan, 'redock')), 20)
        self.assertEqual(entries, before)
        self.assertEqual(memory.plan_reuse(manifests, entries, 'bob')['hit_count'], 0)

    def test_store_bounded_roundtrip_corrupt_owner_and_offline(self):
        self.assertIsNotNone(importlib.util.find_spec('docking_cache_store'), 'Authenticated cache adapter missing')
        from docking_cache_store import encode_entry, decode_entry, PrivateCacheStore
        entry = cache_entry()
        packed = encode_entry(entry)
        self.assertEqual(decode_entry(packed, 'alice', entry['key']), entry)
        self.assertIsNone(decode_entry(packed, 'bob', entry['key']))
        self.assertIsNone(decode_entry('invalid', 'alice', entry['key']))
        with self.assertRaises(ValueError):
            encode_entry(dict(entry, oversized='x'*1000), max_raw_bytes=100)
        class Offline:
            def table(self, name):
                raise RuntimeError('schema unavailable')
        store = PrivateCacheStore(Offline(), 'alice')
        self.assertEqual(store.candidates([entry['key']]), [])
        self.assertIn('fresh', store.notice.lower())
        self.assertFalse(store.save(entry))

    def test_stale_choice_reconnect_and_dead_waiter(self):
        self.assertTrue(hasattr(jobs, 'submit_reuse_choice'), 'Generation-scoped consent missing')
        with tempfile.TemporaryDirectory() as root:
            jd = jobs.job_dir(root, 'job')
            jobs._write_json(os.path.join(jd, 'spec.json'), {'job_id': 'job', 'conversation_id': 'chat', 'generation': 'new', 'owner_id': 'alice'})
            jobs._write_json(os.path.join(jd, 'status.json'), {'status': 'awaiting_reuse', 'generation': 'new', 'pid': os.getpid(), 'started': time.time()-60})
            self.assertFalse(jobs.submit_reuse_choice('job', 'old', 'reuse', 'alice', root))
            self.assertFalse(jobs.submit_reuse_choice('job', 'new', 'reuse', 'bob', root))
            self.assertTrue(jobs.is_running('job', root))
            self.assertEqual(jobs.find_for_conversations(['chat'], root)[0]['status'], 'awaiting_reuse')
            self.assertTrue(jobs.submit_reuse_choice('job', 'new', 'reuse', 'alice', root))
            self.assertFalse(jobs.submit_reuse_choice('job', 'new', 'redock', 'alice', root))
            self.assertEqual(jobs.read_reuse_choice(jd, 'new', 'alice'), 'reuse')
            self.assertIsNone(jobs.read_reuse_choice(jd, 'old', 'alice'))
            with patch('docking_jobs._pid_alive', return_value=False):
                self.assertEqual(jobs.read_status('job', root)['status'], 'error')

    def test_awaiting_blocks_duplicate_and_secrets_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            jd = jobs.job_dir(root, 'job')
            jobs._write_json(os.path.join(jd, 'status.json'), {'status': 'awaiting_reuse', 'pid': os.getpid(), 'started': time.time()})
            with patch('subprocess.Popen', return_value=types.SimpleNamespace(pid=os.getpid())):
                self.assertFalse(jobs.start('job', {}, jobs_dir=root))
            with self.assertRaises(ValueError):
                jobs.start('secret', {'convo': {'access_token': 'secret'}}, jobs_dir=root)

    def test_actual_prepared_inputs_are_hashed_before_execution(self):
        import pipeline
        self.assertTrue(hasattr(pipeline, 'prepared_manifest'), 'Actual prepared-input manifest missing')
        with tempfile.TemporaryDirectory() as root:
            receptor = Path(root)/'r.pdbqt'; ligand = Path(root)/'l.pdbqt'
            receptor.write_text('receptor coordinates')
            ligand.write_text('REMARK SMILES C[C@H](O)F\nROOT\n')
            target = {'accession': 'P00533', 'species': 9606, 'chains': ['A']}
            data = pipeline.prepared_manifest(target, str(receptor), str(ligand), [1,2,3], [20,20,20], 16, 3, 42, manifest()['versions'])
            self.assertIsNotNone(memory.pair_key(data))
            ligand.write_text('REMARK SMILES C[C@H](O)F\nchanged coordinates')
            changed = pipeline.prepared_manifest(target, str(receptor), str(ligand), [1,2,3], [20,20,20], 16, 3, 42, manifest()['versions'])
            self.assertNotEqual(memory.pair_key(data), memory.pair_key(changed))

    def test_batch_prepares_all_targets_before_consent_and_execution(self):
        import pipeline_core
        import inspect
        self.assertIn('cache_context', inspect.signature(pipeline_core.run_job).parameters,
                      'Server cache context has no batch integration')
        events = []
        def prep(target, ligands, vina, directory, venv, **kwargs):
            events.append(('prepare', target['gene'], directory))
            return {'ligands': [{'manifest': cache_entry(i)['manifest']} for i in range(10)], 'meta': {}}
        def execute(target, ligands, *args, **kwargs):
            events.append(('execute', target['gene']))
            return [{'Ligand': l['label'], 'SMILES': l['smiles'], 'Best affinity (kcal/mol)': 'FAILED'} for l in ligands], {}, {'gene': target['gene']}
        def choose(offer):
            self.assertEqual([e[0] for e in events], ['prepare', 'prepare'])
            self.assertEqual(offer['hit_count'], 10)
            events.append(('choice',))
            return 'reuse'
        with tempfile.TemporaryDirectory() as root, patch('pipeline.prepare_docking', side_effect=prep), patch('pipeline.dock_pipeline', side_effect=execute):
            result = pipeline_core.run_job({'target': ['T1', 'T2'], 'ligand_objs': [
                {'label': str(i), 'smiles': 'CCO'} for i in range(10)]}, 'vina', root, root,
                cache_context={'owner_id': 'alice', 'candidates': [cache_entry(i) for i in range(5)]}, reuse_decision=choose)
        self.assertEqual(len(result['rows']), 20)
        self.assertEqual([e[0] for e in events], ['prepare', 'prepare', 'choice', 'execute', 'execute'])
        self.assertNotEqual(events[0][2], events[1][2])

    def test_consent_timeout_executes_nothing_and_keeps_checkpoint(self):
        self.assertTrue(hasattr(jobs, 'await_reuse_choice'))
        with tempfile.TemporaryDirectory() as root:
            jd = jobs.job_dir(root, 'job')
            jobs._write_json(os.path.join(jd, 'checkpoint.json'), {'rows': [{'score': -6}]})
            with self.assertRaises(TimeoutError):
                jobs.await_reuse_choice(jd, 'gen', 'alice', {'hit_count': 5}, timeout=0)
            self.assertEqual(jobs.read_checkpoint('job', root)['rows'], [{'score': -6}])

    def test_biology_crash_keeps_full_docking_checkpoint(self):
        import dock_runner
        output = {'ok': True, 'rows': [{'Ligand': 'L', 'Best affinity (kcal/mol)': -6}], 'meta': {}, 'viz': {}}
        def biology(result, progress):
            raise RuntimeError('biology interrupted')
        with tempfile.TemporaryDirectory() as root:
            jd = jobs.job_dir(root, 'job')
            jobs._write_json(os.path.join(jd, 'spec.json'), {'job_id': 'job', 'jobs_dir': root,
                'convo': {}, 'vina': 'vina', 'data_dir': root, 'venv': root})
            with patch.dict(sys.modules, {'llm_client': types.SimpleNamespace(get_llm=lambda: None),
                    'pipeline_core': types.SimpleNamespace(run_job=lambda *a, **kw: copy.deepcopy(output)),
                    'docking_biology': types.SimpleNamespace(enrich_result=biology)}):
                self.assertEqual(dock_runner.main(os.path.join(jd, 'spec.json')), 1)
            self.assertEqual(jobs.read_checkpoint('job', root)['rows'], output['rows'])

    def test_ui_filters_owner_and_foreground_requires_choice(self):
        self.assertIsNotNone(importlib.util.find_spec('docking_reuse_ui'), 'Minimal integration helpers missing')
        from docking_reuse_ui import worker_cache_fields, foreground_cache_context
        entry = cache_entry()
        fields = worker_cache_fields('alice', [entry, dict(entry, owner_id='bob')])
        self.assertEqual(len(fields['cache_candidates']), 1)
        self.assertEqual(worker_cache_fields(None, [entry])['cache_candidates'], [])
        self.assertEqual(foreground_cache_context(fields)['owner_id'], 'alice')

    def test_worker_root_cache_entries_are_available_without_report_metadata_duplication(self):
        import dock_runner
        entry = cache_entry()
        output = {'ok': True, 'rows': [entry['row']], 'meta': {'gene': 'T'}, 'viz': {},
                  'cache_entries': [entry]}
        with tempfile.TemporaryDirectory() as root:
            jd = jobs.job_dir(root, 'job')
            spec = {'job_id': 'job', 'jobs_dir': root, 'owner_id': 'alice', 'generation': 'gen',
                    'convo': {}, 'vina': 'vina', 'data_dir': root, 'venv': root}
            jobs._write_json(os.path.join(jd, 'spec.json'), spec)
            with patch.dict(sys.modules, {'llm_client': types.SimpleNamespace(get_llm=lambda: None),
                    'pipeline_core': types.SimpleNamespace(run_job=lambda *a, **kw: copy.deepcopy(output)),
                    'docking_biology': types.SimpleNamespace(enrich_result=lambda r, progress: r)}):
                self.assertEqual(dock_runner.main(os.path.join(jd, 'spec.json')), 0)
            result = jobs.read_result('job', root)
            self.assertEqual(result.get('cache_entries'), [entry])
            self.assertNotIn('cache_entries', result['meta'])

    def test_compressed_bomb_and_partial_gzip_are_rejected(self):
        import base64, gzip
        from docking_cache_store import decode_entry
        bomb = base64.b64encode(gzip.compress(b' '*(16*1024*1024+1))).decode()
        self.assertIsNone(decode_entry(bomb, 'alice', 'a'*64))
        packed = base64.b64encode(gzip.compress(b'{}')[:-4]).decode()
        self.assertIsNone(decode_entry(packed, 'alice', 'a'*64))

    def test_actual_twenty_pair_engine_counts_and_immutable_cache(self):
        import hashlib
        import pipeline
        from docking_cache_store import encode_entry, decode_entry
        with tempfile.TemporaryDirectory() as root:
            receptor = Path(root)/'r.pdbqt'; receptor.write_text('receptor')
            source = Path(root)/'source.pdb'; source.write_text('source')
            atom = cache_entry()['artifacts']['selected_pose']['text']
            ligands, prepared_items, entries = [], [], []
            for i in range(20):
                ligand = Path(root)/f'c_lig_{i}.pdbqt'; ligand.write_text(f'REMARK SMILES C[C@H](O)F\n{atom}REMARK id {i}\n')
                entry = cache_entry(i)
                entry['manifest']['receptor_sha256'] = hashlib.sha256(receptor.read_bytes()).hexdigest()
                entry['manifest']['ligand_sha256'] = hashlib.sha256(ligand.read_bytes()).hexdigest()
                entry['key'] = memory.pair_key(entry['manifest'])
                ligands.append({'label': f'L{i}', 'smiles': 'C[C@H](O)F'})
                prepared_items.append({'index': i, 'path': str(ligand), 'manifest': entry['manifest']})
                if i < 5:
                    entries.append(decode_entry(encode_entry(entry), 'alice', entry['key']))
            original = copy.deepcopy(entries)
            plan = {'pdb_path': str(source), 'cleaned': str(source), 'receptor': str(receptor),
                    'center': [1,2,3], 'size': [20,20,20], 'pocket': 'test',
                    'eff_exh': 16, 'eff_rep': 3, 'seed': 42, 'rama': None,
                    'meta': {'reliability_by': {}, 'run_records': {}}, 'ligands': prepared_items}
            counts = []
            def engine(*args, **kwargs):
                counts.append(args[2])
                path = args[3]+'_r0.pdbqt'; Path(path).write_text(atom)
                return {'best_score': -6., 'modes': [(1, -6.)], 'out_pdbqt': path,
                        'n': 3, 'mean': -6., 'sd': 0., 'confidence': 'High', 'all_best': [-6]*3}
            interactions = {'status': 'verified', 'total_interactions': 0, 'n_hbonds': 0,
                'n_hydrophobic': 0, 'n_pistacking': 0, 'n_saltbridges': 0, 'n_halogen': 0,
                'hbond_residues': [], 'interacting_residues': [], 'artifacts': {}}
            with (patch('pipeline.dock_with_replicas', side_effect=engine),
                  patch('pipeline.prepare_receptor_context', return_value={}),
                  patch('pipeline.analyze_interactions', return_value=interactions)):
                checkpoints = []
                rows, viz, meta = pipeline.dock_pipeline({'gene': 'T'}, ligands, 'vina', root, '',
                    prepared=copy.deepcopy(plan), reuse_entries={e['key']: e for e in entries}, owner_id='alice',
                    checkpoint=lambda r,v,m: checkpoints.append(copy.deepcopy(r)))
                self.assertEqual(len(counts), 15)
                self.assertEqual(len(rows), 20)
                self.assertEqual(sum(r.get('Calculation origin') == 'reused' for r in rows), 5)
                self.assertEqual(len(checkpoints[-1]), 20)
                self.assertEqual(Path(viz['L0']['complex']).read_text(), atom)
                self.assertEqual(entries, original)
                counts.clear()
                redock_rows, _, _ = pipeline.dock_pipeline({'gene': 'T'}, ligands, 'vina', root, '',
                    prepared=copy.deepcopy(plan), reuse_entries={}, owner_id='alice')
                self.assertEqual(len(counts), 20)
                self.assertEqual(sum(r.get('Calculation origin') == 'new' for r in redock_rows), 20)
                # Mutated prepared input must be rejected even when an eligible hit exists.
                Path(prepared_items[0]['path']).write_text('changed coordinates')
                rows, _, _ = pipeline.dock_pipeline({'gene': 'T'}, ligands[:1], 'vina', root, '',
                    prepared=copy.deepcopy(plan), reuse_entries={e['key']: e for e in entries}, owner_id='alice')
                self.assertEqual(rows[0]['Best affinity (kcal/mol)'], 'FAILED')

    def test_cache_client_session_must_match_verified_owner(self):
        from docking_cache_store import PrivateCacheStore, encode_entry
        entry = cache_entry()
        class Client:
            def __init__(self, owner):
                self.auth = types.SimpleNamespace(get_user=lambda: types.SimpleNamespace(user=types.SimpleNamespace(id=owner)))
                self.filters = {}; self.column = ''; self.inserted = []
            def table(self, name): return self
            def select(self, columns): self.column = columns; return self
            def eq(self, field, value): self.filters[field] = value; return self
            def limit(self, value): return self
            def execute(self):
                if self.column == 'pair_key':
                    return types.SimpleNamespace(data=[{'pair_key': entry['key']}])
                return types.SimpleNamespace(data=[{'pair_key': entry['key'], 'evidence': encode_entry(entry)}])
            def upsert(self, payload, **kwargs): self.inserted.append(payload); return self
        wrong = Client('bob')
        store = PrivateCacheStore(wrong, 'alice')
        self.assertEqual(store.candidates(), [])
        self.assertFalse(store.save(entry))
        self.assertEqual(wrong.inserted, [])
        correct = Client('alice')
        store = PrivateCacheStore(correct, 'alice')
        self.assertEqual(store.candidates(), [entry])
        self.assertTrue(store.save(entry))
        self.assertEqual(correct.inserted[0]['owner_id'], 'alice')


if __name__ == '__main__':
    unittest.main()
