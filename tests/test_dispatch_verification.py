import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import dispatch
from services import registry


class IntentVerificationTests(unittest.TestCase):
    def test_confirmation_without_pending_action_never_guesses(self):
        self.assertEqual(dispatch.plan({'action': 'dock'}, {'target': '1ABC', 'ligand': 'CCO'}, 'yes'), [])

    def test_confirmation_uses_pending_identity_over_model(self):
        self.assertEqual(dispatch.plan({'action': 'dock'}, {'target': '1ABC', 'ligand': 'CCO'}, 'yes', pending_actions=['qm']), ['qm'])

    def test_explicit_request_cannot_gain_unrequested_calculation(self):
        self.assertEqual(dispatch.plan({'action': 'dock'}, {'target': '1ABC', 'ligand': 'CCO'}, 'calculate HOMO LUMO'), ['qm'])

    def test_unavailable_does_not_assert_storage_or_other_health(self):
        message = registry.unavailable('qm')
        self.assertNotIn('saved', message)
        self.assertNotIn('running normally', message)

