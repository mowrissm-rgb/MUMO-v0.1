import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import dispatch
from services import registry


class WorkflowNameChains(unittest.TestCase):
    def test_second_named_workflow_after_one_verb_is_recognised(self):
        self.assertEqual(dispatch.requested_actions('run Flux and Orbit on paracetamol'), ['metabolism', 'qm'])

    def test_the_order_the_user_gave_is_kept(self):
        self.assertEqual(dispatch.requested_actions('run Orbit and Flux on paracetamol'), ['qm', 'metabolism'])
        self.assertEqual(dispatch.requested_actions('run Atlas, Pose then Fate on 1HSG'),
                         ['ramachandran', 'dock', 'analyze'])

    def test_pose_and_helix_as_ordinary_words_still_do_nothing(self):
        for text in ('the ligand adopts a favourable pose', 'the alpha helix near the active site is flexible',
                     'check the pose and the helix'):
            self.assertEqual(dispatch.requested_actions(text), [], text)


class Negation(unittest.TestCase):
    def test_negated_request_does_nothing(self):
        for text in ('do not dock anything yet', "don't run ADMET", 'never dock this', 'skip the docking step'):
            self.assertEqual(dispatch.requested_actions(text), [], text)

    def test_only_the_negated_action_is_dropped(self):
        self.assertEqual(dispatch.requested_actions("dock aspirin into COX-2 and don't run ADME"), ['dock'])

    def test_plain_requests_are_unaffected(self):
        self.assertEqual(dispatch.requested_actions('dock aspirin into COX-2'), ['dock'])
        self.assertEqual(dispatch.requested_actions('run ADMET for aspirin'), ['analyze'])


class UnsupportedCues(unittest.TestCase):
    def test_a_cue_must_start_a_word(self):
        self.assertEqual(dispatch.unsupported_request('dock aspirin into the chamber of the enzyme'), '')

    def test_protein_synthesis_is_not_synthesis_planning(self):
        self.assertEqual(dispatch.unsupported_request('blast the protein synthesis elongation factor EEF2'), '')

    def test_real_out_of_scope_requests_are_still_flagged(self):
        for text in ('run a 100 ns MD simulation', 'compute MM-GBSA binding free energy', 'perform DFT on aspirin',
                     'how to make aspirin step by step', 'please synthesize aspirin', 'plan a synthesis route for ibuprofen',
                     'design a clinical trial for aspirin'):
            self.assertNotEqual(dispatch.unsupported_request(text), '', text)


class RegistryAlias(unittest.TestCase):
    def test_every_routed_action_has_an_owner(self):
        for action in dispatch.REAL_ACTIONS:
            self.assertIsNotNone(registry.owner_of(action), action)

    def test_analyze_belongs_to_the_chemistry_specialist(self):
        self.assertEqual(registry.owner_of('analyze'), registry.owner_of('admet'))


if __name__ == '__main__':
    unittest.main()
