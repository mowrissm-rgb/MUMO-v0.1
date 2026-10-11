import sys
import unittest
import ast
import types
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import target_names as names


class NFkBClarificationTests(unittest.TestCase):
    def load_chat_function(self, function, **globals_):
        source = Path(__file__).resolve().parents[1] / 'src/mumo_chat.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function)
        scope = dict(globals_)
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
        return scope[function]

    def test_actual_chat_plan_pauses_before_ligand_resolution(self):
        class State(dict):
            __getattr__ = dict.__getitem__
            __setattr__ = dict.__setitem__
        state, replies = State(), []
        run = self.load_chat_function('_run_plan', ss=state, say=replies.append)
        run(['dock'], {'target': 'NF-kB', 'ligand': 'aspirin'})
        self.assertIn('awaiting_nfkb', state)
        self.assertFalse(state.get('run_now', False))
        self.assertIn('NFKB2', replies[0])

    def test_actual_chat_choice_resumes_saved_batch_without_llm(self):
        class State(dict):
            __getattr__ = dict.__getitem__
            __setattr__ = dict.__setitem__
        state = State(messages=[], convo={}, awaiting_nfkb={'actions': ['dock'],
                     'convo': {'target': ['NF-kB', 'IL6'], 'ligand': 'aspirin'}})
        calls = []
        converse = self.load_chat_function('converse', ss=state, say=lambda x: None,
                   _persist=lambda *x: None, _run_plan=lambda *x: calls.append(x))
        brain = types.ModuleType('brain')
        brain.parse_intent = lambda *args: self.fail('The choice must not be guessed again')
        with patch.dict(sys.modules, {'brain': brain}):
            converse('p50')
        self.assertEqual(calls, [(['dock'], {'target': ['NFKB1', 'IL6'], 'ligand': 'aspirin'})])
        self.assertIsNone(state.awaiting_nfkb)

    def test_family_pauses_and_keeps_batch_and_ligands(self):
        self.assertTrue(hasattr(names, 'nfkb_clarification'))
        convo = {'target': ['IL-6', 'NF-κB'], 'ligand': ['aspirin', 'lupeol']}
        pending = names.nfkb_clarification(['dock', 'analyze'], convo)
        self.assertEqual(pending['convo'], convo)
        self.assertEqual(pending['actions'], ['dock', 'analyze'])
        for gene in ['RELA', 'NFKB1', 'NFKB2', 'RELB', 'REL']:
            self.assertIn(gene, pending['prompt'])

    def test_choice_resumes_only_ambiguous_target(self):
        self.assertTrue(hasattr(names, 'resume_nfkb_choice'))
        pending = {'actions': ['dock'], 'convo': {'target': ['IL-6', 'NF-kB'], 'ligand': 'aspirin'}}
        resumed = names.resume_nfkb_choice(pending, 'p65')
        self.assertEqual(resumed['convo']['target'], ['IL-6', 'RELA'])
        self.assertEqual(resumed['convo']['ligand'], 'aspirin')
        self.assertIsNone(names.resume_nfkb_choice(pending, 'explain p65 versus p50'))

    def test_explicit_pdb_does_not_pause_and_survives_model_substitution(self):
        self.assertTrue(hasattr(names, 'preserve_nfkb_request'))
        targets = names.preserve_nfkb_request(['IL-6', 'RELA'], 'dock IL-6 and NF-KB (1Nfk) with aspirin')
        self.assertEqual(targets, ['IL-6', '1NFK'])
        self.assertIsNone(names.nfkb_clarification(['dock'], {'target': targets}))

    def test_bare_family_cannot_be_silently_replaced_by_model(self):
        self.assertTrue(hasattr(names, 'preserve_nfkb_request'))
        self.assertEqual(names.preserve_nfkb_request('RELA', 'dock NF-kB with lupeol'), ['NF-κB'])

    def test_named_subunit_in_a_batch_is_not_overwritten_by_family_choice(self):
        self.assertEqual(names.preserve_nfkb_request(['RELA', 'NF-kB'],
                         'dock RELA and NF-kB with aspirin'), ['RELA', 'NF-κB'])

    def test_all_subunit_choices_are_supported(self):
        self.assertTrue(hasattr(names, 'resume_nfkb_choice'))
        pending = {'actions': ['dock'], 'convo': {'target': 'NF-κB'}}
        for choice, gene in [('p65', 'RELA'), ('p50', 'NFKB1'), ('p52', 'NFKB2'), ('RelB', 'RELB'), ('c-Rel', 'REL'), ('1NFK', '1NFK')]:
            self.assertEqual(names.resume_nfkb_choice(pending, choice)['convo']['target'], [gene])
