import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import docking_ui_bridge as bridge


class DockingUIBridgeTests(unittest.TestCase):
    def setUp(self):
        enabled = patch.dict('os.environ', {'MUMO_PRIVATE_CACHE_ENABLED': '1'})
        enabled.start()
        self.addCleanup(enabled.stop)

    def test_disabled_release_never_reads_or_writes_private_cache(self):
        with patch.dict('os.environ', {'MUMO_PRIVATE_CACHE_ENABLED': '0'}), \
             patch('docking_reuse_ui.load_worker_cache_fields') as load, \
             patch('docking_reuse_ui.persist_completed_pairs') as save:
            fields = bridge.cache_fields(object(), {'id': 'alice'})
            worker = bridge.save_cache_async(object(), {'id': 'alice'},
                                             {'ok': True, 'cache_entries': ['evidence']})
        load.assert_not_called()
        save.assert_not_called()
        self.assertEqual(fields['cache_candidates'], [])
        self.assertIsNone(fields['owner_id'])
        self.assertIsNone(worker)

    def test_offer_requires_matching_authenticated_owner(self):
        self.assertTrue(hasattr(bridge, 'may_view_offer'))
        self.assertTrue(bridge.may_view_offer({'owner_id': 'alice'}, {'id': 'alice'}))
        self.assertFalse(bridge.may_view_offer({'owner_id': 'alice'}, {'id': 'bob'}))
        self.assertFalse(bridge.may_view_offer({'owner_id': None}, None))

    def test_anonymous_user_never_loads_private_evidence(self):
        with patch('docking_reuse_ui.load_worker_cache_fields') as load:
            result = bridge.cache_fields(object(), None)
        load.assert_not_called()
        self.assertIsNone(result['owner_id'])
        self.assertEqual(result['cache_candidates'], [])

    def test_authenticated_load_and_cache_outage(self):
        client = object()
        with patch('docking_reuse_ui.load_worker_cache_fields', side_effect=RuntimeError('offline')) as load:
            result = bridge.cache_fields(client, {'id': 'alice'})
        load.assert_called_once_with(client, 'alice')
        self.assertEqual(result['owner_id'], 'alice')
        self.assertEqual(result['cache_candidates'], [])
        self.assertIn('fresh', result['cache_notice'])

    def test_history_keeps_provenance_but_not_duplicated_cache_coordinates(self):
        original = {'ok': True, 'rows': [{'Calculation origin': 'reused'}], 'meta': {
            'cache_entries': ['large'], 'cache': {'reused_pairs': 1},
            'per_target': {'EGFR': {'cache_entries': ['large'], 'validation': {'passed': False}}}}}
        result = bridge.public_result(original)
        self.assertNotIn('cache_entries', result['meta'])
        self.assertNotIn('cache_entries', result['meta']['per_target']['EGFR'])
        self.assertEqual(result['meta']['cache']['reused_pairs'], 1)
        self.assertEqual(original['meta']['cache_entries'], ['large'])

    def test_cache_save_uses_captured_owner_and_never_anonymous_or_partial(self):
        result = {'ok': True, 'cache_entries': ['evidence'], 'meta': {}}
        outcomes = []
        with patch('docking_reuse_ui.persist_completed_pairs', return_value={'saved_pairs': 1}) as save:
            worker = bridge.save_cache_async('client', {'id': 'alice'}, result, outcomes.append)
            worker.join(3)
            save.assert_called_once_with('client', 'alice', result)
            self.assertEqual(outcomes, [{'saved_pairs': 1}])
            self.assertIsNone(bridge.save_cache_async('client', None, result))
            self.assertIsNone(bridge.save_cache_async('client', {'id': 'alice'}, dict(result, partial=True)))
        self.assertNotIn('cache_entries', bridge.public_result(result))
