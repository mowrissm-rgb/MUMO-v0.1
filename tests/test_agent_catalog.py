import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


class AgentCatalogTests(unittest.TestCase):
    def test_scientific_words_are_not_agent_invocations(self):
        import dispatch
        slots = {'target': 'EGFR', 'ligand': 'aspirin'}
        self.assertEqual(dispatch.plan({}, slots, 'Show the best pose'), [])
        self.assertEqual(dispatch.plan({}, slots, 'Check alpha helix content of EGFR'), [])
        self.assertEqual(dispatch.plan({}, slots, 'Run Fate and show the best pose'), ['analyze'])

    def test_named_agent_requests_reach_the_existing_scientific_action(self):
        import dispatch
        for name, action, slots in [('Orbit', 'qm', {'ligand': 'aspirin'}),
                                     ('Fate', 'analyze', {'ligand': 'aspirin'}),
                                     ('Nexus', 'string', {'target': 'IL6'}),
                                     ('Flux', 'metabolism', {'ligand': 'aspirin'})]:
            with self.subTest(name=name):
                self.assertEqual(dispatch.plan({}, slots, f'run {name} now'), [action])

    def test_every_existing_capability_has_a_named_agent(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('agent_catalog'))
        from agent_catalog import AGENTS, agent_for
        from services.registry import OWNER
        for action in list(OWNER) + ['analyze', 'alignment', 'target', 'scout']:
            self.assertIn(agent_for(action), [a['name'] for a in AGENTS])
        self.assertEqual(agent_for('dock'), 'Pose')
        self.assertEqual(agent_for('admet'), 'Fate')
        self.assertEqual(agent_for('qm'), 'Orbit')
        self.assertEqual(agent_for('report'), 'Quill')
        self.assertTrue(all('MUMO' not in a['name'].upper() for a in AGENTS))

