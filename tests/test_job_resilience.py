import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import docking_jobs as jobs


class JobResilienceTests(unittest.TestCase):
    def test_failed_launch_without_pid_cannot_remain_running_forever(self):
        with tempfile.TemporaryDirectory() as tmp:
            jd = jobs.job_dir(tmp, 'run')
            jobs.update_status(jd, status='running', pid=None, started=time.time()-30)
            self.assertEqual(jobs.read_status('run', tmp)['status'], 'error')

    def test_large_checkpoint_is_losslessly_compressed(self):
        payload = {'ok': True, 'partial': True, 'rows': [{'Ligand': 'aspirin'}],
                   'viz': {'aspirin': {'pdb': 'ATOM coordinates\n' * 100000}}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, 'checkpoint.json')
            jobs._write_json(str(path), payload)
            self.assertLess(path.stat().st_size, 100000)
            self.assertEqual(jobs._read_json(str(path)), payload)

    def test_compressed_history_restores_every_coordinate_and_numeric_value(self):
        import auth_store
        payload = {'runs': [{'run_id': 'r1', 'rows': [{'Ligand': 'aspirin', 'score': -6.12}],
                           'viz': {'aspirin': {'pdb': 'ATOM coordinates\n' * 10000}}}]}
        if not hasattr(auth_store, '_pack_results'):
            self.fail('large result uploads are not compressed')
        stored = auth_store._pack_results(payload)
        self.assertLess(len(str(stored)), len(str(payload)) // 10)
        self.assertEqual(auth_store._unpack_results(stored), payload)
        self.assertEqual(auth_store._merge_runs(stored, {'run_id': 'r2', 'rows': [2]})['runs'][1],
                         payload['runs'][0])

    def test_new_run_never_recovers_checkpoint_or_persistence_from_previous_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            jd = jobs.job_dir(tmp, 'run')
            jobs.update_status(jd, status='done', consumed=True)
            for name in ('checkpoint.json', 'persist.json', 'worker_persist.json'):
                jobs._write_json(os.path.join(jd, name), {'old': True})
            with patch('subprocess.Popen', return_value=types.SimpleNamespace(pid=os.getpid())):
                jobs.start('run', {'job_id': 'run'}, jobs_dir=tmp)
            self.assertIsNone(jobs.read_checkpoint('run', tmp))
            for name in ('persist.json', 'worker_persist.json'):
                self.assertFalse(Path(jd, name).exists())

    def test_history_update_with_no_authorized_row_is_not_success(self):
        import auth_store
        class Query:
            def table(self, *a): return self
            def select(self, *a): return self
            def eq(self, *a): return self
            def single(self): return self
            def update(self, *a): return self
            def execute(self): return types.SimpleNamespace(data=[])
        saved, error = auth_store.save_results_with(Query(), 'conv', {'rows': []})
        self.assertFalse(saved)
        self.assertIsNotNone(error)

    def test_repeat_history_save_of_same_run_does_not_duplicate_it(self):
        import auth_store
        merged = auth_store._merge_runs({'runs': [{'run_id': 'same', 'rows': [1]}]},
                                       {'run_id': 'same', 'rows': [2]})
        self.assertEqual(len(merged['runs']), 1)
        self.assertEqual(merged['runs'][0]['rows'], [2])

    def test_logged_in_history_save_returns_before_slow_database(self):
        import auth_store
        import threading
        released, entered, completed = threading.Event(), threading.Event(), threading.Event()
        def slow(*args):
            entered.set()
            released.wait(3)
            return False, 'network timeout'
        if not hasattr(auth_store, 'save_results_async'):
            self.fail('history persistence still blocks the result display')
        try:
            with patch.object(auth_store, 'save_results_with', side_effect=slow):
                worker = auth_store.save_results_async(object(), 'conv', {'rows': []},
                                                       lambda *args: completed.set())
                self.assertTrue(entered.wait(1))
                self.assertFalse(completed.is_set())
                released.set()
                worker.join(2)
                self.assertTrue(completed.is_set())
        finally:
            released.set()

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux process-state regression')
    def test_exited_unreaped_worker_is_not_alive(self):
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        try:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                state = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0]
                if state == 'Z':
                    break
                time.sleep(0.01)
            self.assertEqual(state, 'Z')
            self.assertFalse(jobs._pid_alive(pid))
        finally:
            os.waitpid(pid, 0)

    def test_published_result_recovers_done_status_after_worker_dies(self):
        with tempfile.TemporaryDirectory() as tmp:
            jd = jobs.job_dir(tmp, 'run')
            jobs.update_status(jd, status='running', pid=123, started=time.time()-30)
            jobs._write_json(os.path.join(jd, 'result.json'), {'ok': True, 'rows': []})
            with patch.object(jobs, '_pid_alive', return_value=False):
                self.assertEqual(jobs.read_status('run', tmp)['status'], 'done')

    def test_corrupted_result_does_not_hide_a_dead_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            jd = jobs.job_dir(tmp, 'run')
            jobs.update_status(jd, status='running', pid=123, started=time.time()-30)
            Path(jd, 'result.json').write_text('{broken')
            with patch.object(jobs, '_pid_alive', return_value=False):
                self.assertEqual(jobs.read_status('run', tmp)['status'], 'error')

    def test_worker_publishes_result_before_external_history_save(self):
        import dock_runner
        result = {'ok': True, 'rows': [{'Ligand': 'aspirin'}],
                  'meta': {'gene': 'EGFR'}, 'viz': {}, 'say_text': 'Done'}
        observed = []
        with tempfile.TemporaryDirectory() as tmp:
            jd = jobs.job_dir(tmp, 'run')
            spec = {'job_id': 'run', 'jobs_dir': tmp, 'convo': {},
                    'vina': 'vina', 'data_dir': tmp, 'venv': tmp, 'conversation_id': 'conv'}
            jobs._write_json(os.path.join(jd, 'spec.json'), spec)
            jobs.update_status(jd, status='running', pid=os.getpid(), started=time.time())
            def save(*args):
                observed.append(jobs.read_result('run', tmp))
                observed.append(jobs.read_status('run', tmp).get('status'))
                jobs.mark_consumed('run', tmp)
                return False, 'database unavailable'
            fake_auth = types.SimpleNamespace(standalone_client=lambda: object(), save_results_with=save)
            fake_llm = types.SimpleNamespace(get_llm=lambda: None)
            fake_core = types.SimpleNamespace(run_job=lambda *a, **k: result)
            with patch.dict(sys.modules, {'auth_store': fake_auth, 'llm_client': fake_llm,
                                         'pipeline_core': fake_core}):
                self.assertEqual(dock_runner.main(os.path.join(jd, 'spec.json')), 0)
            self.assertIsNotNone(observed[0], 'completed result was withheld during history save')
            self.assertEqual(observed[1], 'done')
            self.assertTrue(jobs.read_status('run', tmp).get('consumed'))
            self.assertFalse(jobs.read_status('run', tmp).get('persisted'))

    def test_checkpoint_is_kept_when_worker_raises_after_completed_pair(self):
        import dock_runner
        partial = {'ok': True, 'partial': True, 'rows': [{'Target': 'EGFR', 'Ligand': 'aspirin'}],
                   'meta': {'gene': 'EGFR', 'expected_pairs': 2}, 'viz': {}, 'say_text': 'Partial'}
        def run(*args, **kwargs):
            if 'checkpoint' in kwargs:
                kwargs['checkpoint'](partial)
            raise RuntimeError('worker interrupted')
        with tempfile.TemporaryDirectory() as tmp:
            jd = jobs.job_dir(tmp, 'run')
            jobs._write_json(os.path.join(jd, 'spec.json'), {'job_id': 'run', 'jobs_dir': tmp,
                'convo': {}, 'vina': 'vina', 'data_dir': tmp, 'venv': tmp})
            with patch.dict(sys.modules, {
                'llm_client': types.SimpleNamespace(get_llm=lambda: None),
                'pipeline_core': types.SimpleNamespace(run_job=run)}):
                self.assertEqual(dock_runner.main(os.path.join(jd, 'spec.json')), 1)
            recovered = jobs._read_json(os.path.join(jd, 'checkpoint.json'))
            self.assertIsNotNone(recovered, 'completed pair was lost')
            self.assertEqual(recovered['rows'][0]['Ligand'], 'aspirin')
            self.assertEqual(jobs.read_status('run', tmp)['status'], 'error')

    def test_vina_timeout_is_bounded_and_never_returns_an_incomplete_score(self):
        import subprocess
        import docking_engine
        def stuck(cmd, **kwargs):
            self.assertGreater(kwargs.get('timeout', 0), 0, 'Vina has no time limit')
            raise subprocess.TimeoutExpired(cmd, kwargs['timeout'], output='unfinished search')
        with tempfile.TemporaryDirectory() as tmp, patch('subprocess.run', side_effect=stuck):
            with self.assertRaisesRegex(RuntimeError, 'time limit'):
                docking_engine.run_docking(sys.executable, 'receptor', 'ligand',
                    os.path.join(tmp, 'pose.pdbqt'), os.path.join(tmp, 'vina.txt'),
                    [0, 0, 0], [20, 20, 20])
            self.assertTrue(Path(tmp, 'pose_vina.log').exists())

    def test_core_emits_checkpoint_before_next_ligand_can_crash(self):
        import pipeline_core
        snapshots = []
        row = {'Ligand': 'aspirin', 'SMILES': 'CC(=O)Oc1ccccc1C(=O)O',
               'Best affinity (kcal/mol)': -5.1}
        def dock(target, *args, **kwargs):
            callback = kwargs.get('checkpoint')
            if callback:
                callback([row], {}, {'gene': target['gene'], 'validation_pdb_text': 'EGFR coordinates'})
            raise SystemExit('simulate a later native crash')
        with tempfile.TemporaryDirectory() as tmp, patch('pipeline.dock_pipeline', side_effect=dock):
            try:
                pipeline_core.run_job({'target': ['EGFR', 'HER2'],
                    'ligand_objs': [{'label': 'aspirin', 'smiles': row['SMILES']},
                                    {'label': 'ethanol', 'smiles': 'CCO'}]},
                    'vina', tmp, tmp, checkpoint=snapshots.append)
            except TypeError:
                self.fail('run_job has no checkpoint support')
            except SystemExit:
                pass
        self.assertEqual(len(snapshots), 1)
        self.assertTrue(snapshots[0]['partial'])
        self.assertEqual(snapshots[0]['rows'][0]['Target'], 'EGFR')
        self.assertEqual(snapshots[0]['meta']['expected_pairs'], 4)
        self.assertEqual(snapshots[0]['meta']['per_target']['EGFR']['validation_pdb_text'], 'EGFR coordinates')


if __name__ == '__main__':
    unittest.main()
