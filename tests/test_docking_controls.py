"""Execute the actual chat control function without starting Streamlit or docking."""
import ast
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / 'src'
sys.path.insert(0, str(SRC))
import docking_jobs as jobs


class Rerun(Exception):
    pass


class State(dict):
    def __getattr__(self, key):
        return self.get(key)
    def __setattr__(self, key, value):
        self[key] = value


class Controls:
    def __init__(self, choice):
        self.choice = choice
        self.messages = []
    def status(self, *args, **kwargs):
        return self
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def write(self, text):
        self.messages.append(text)
    caption = warning = write
    def columns(self, count):
        return [self] * count
    def button(self, label, **kwargs):
        return label == self.choice and not kwargs.get('disabled')
    def rerun(self):
        raise Rerun()


class DockingControlsTests(unittest.TestCase):
    def render(self, root, owner, choice):
        tree = ast.parse((SRC/'mumo_chat.py').read_text(encoding='utf-8'))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == '_render_job_progress')
        controls = Controls(choice)
        namespace = {'ss': State(active_conversation_id='chat', job_id='job'), 'st': controls,
                     'authdb': types.SimpleNamespace(current_user=lambda: owner)}
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'mumo_chat.py', 'exec'), namespace)
        with patch.object(jobs, 'default_jobs_dir', return_value=root):
            if owner and owner['id'] == 'alice' and choice:
                with self.assertRaises(Rerun):
                    namespace['_render_job_progress']()
            else:
                self.assertTrue(namespace['_render_job_progress']())
        return controls

    def prepare(self, root):
        jd = jobs.job_dir(root, 'job')
        jobs._write_json(os.path.join(jd, 'spec.json'),
                        {'generation': 'current', 'owner_id': 'alice'})
        jobs._write_json(os.path.join(jd, 'status.json'), {'status': 'awaiting_reuse',
            'generation': 'current', 'owner_id': 'alice', 'pid': os.getpid(), 'started': time.time(),
            'reuse_offer': {'hit_count': 5, 'total_pairs': 20,
                            'matches': [{'source_run_id': 'original-run', 'created_at': 'original-date'}]}})
        return jd

    def test_real_ui_buttons_record_current_choice_and_show_counts(self):
        for label, action in [('Reuse matching results', 'reuse'), ('Redock all pairs', 'redock')]:
            with self.subTest(action=action), tempfile.TemporaryDirectory() as root:
                jd = self.prepare(root)
                controls = self.render(root, {'id': 'alice'}, label)
                self.assertEqual(jobs.read_reuse_choice(jd, 'current', 'alice'), action)
                self.assertTrue(any('5 matching' in text and '20 requested' in text for text in controls.messages))

    def test_other_account_never_sees_original_run_identity_or_submits_choice(self):
        with tempfile.TemporaryDirectory() as root:
            jd = self.prepare(root)
            controls = self.render(root, {'id': 'bob'}, 'Reuse matching results')
            self.assertIsNone(jobs.read_reuse_choice(jd, 'current', 'alice'))
            self.assertFalse(any('original-run' in text for text in controls.messages))

    def test_no_choice_leaves_worker_waiting_without_automatic_execution(self):
        with tempfile.TemporaryDirectory() as root:
            jd = self.prepare(root)
            self.render(root, {'id': 'alice'}, None)
            self.assertIsNone(jobs.read_reuse_choice(jd, 'current', 'alice'))
            self.assertEqual(jobs.read_status('job', root)['status'], 'awaiting_reuse')
