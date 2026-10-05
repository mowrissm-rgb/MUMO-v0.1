import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import pipeline_core


class DockingModeTests(unittest.TestCase):
    def run_mode(self, mode=None):
        captured = []

        def docking(target, ligands, *args, **kwargs):
            captured.append(kwargs)
            rows = [{'Ligand': lig['label'], 'SMILES': lig['smiles'],
                     'Best affinity (kcal/mol)': 'FAILED',
                     'Total interactions': None} for lig in ligands]
            return rows, {}, {'gene': target['gene']}

        request = {'target': ['EGFR', 'CDK4'], 'ligand_objs': [
            {'label': str(i), 'smiles': 'CCO'} for i in range(61)]}
        if mode is not None:
            request['docking_mode'] = mode
        checkpoints = []
        with tempfile.TemporaryDirectory() as tmp, patch(
                'pipeline.dock_pipeline', side_effect=docking):
            result = pipeline_core.run_job(request, 'vina', tmp, tmp,
                                          checkpoint=checkpoints.append)
        return result, captured, checkpoints

    def test_selected_mode_reaches_every_target_without_batch_downgrade(self):
        for mode, depth in [('Medium', 8), ('Standard', 16), ('High', 32)]:
            with self.subTest(mode=mode):
                result, calls, checkpoints = self.run_mode(mode)
                self.assertEqual(len(result['rows']), 122)
                for call in calls:
                    self.assertEqual(call.get('exhaustiveness'), depth)
                    self.assertEqual(call.get('n_replicas'), 3)
                    self.assertEqual(call.get('seed'), 42)
                self.assertEqual(result['meta']['docking_mode'], mode)
                self.assertEqual(result['meta']['exhaustiveness'], depth)
                self.assertEqual(result['meta']['replicas'], 3)
                for target in ['EGFR', 'CDK4']:
                    self.assertEqual(result['meta']['per_target'][target]['docking_mode'], mode)
                self.assertEqual(checkpoints[-1]['meta']['docking_mode'], mode)

    def test_missing_mode_is_standard(self):
        result, calls, _ = self.run_mode()
        self.assertEqual(calls[0].get('exhaustiveness'), 16)
        self.assertEqual(result['meta']['docking_mode'], 'Standard')

    def test_unknown_mode_stops_before_preparation(self):
        with self.assertRaisesRegex(ValueError, 'mode'):
            self.run_mode('turbo')


if __name__ == '__main__':
    unittest.main()
