import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import verification


class RecordTests(unittest.TestCase):
    def test_nonfinite_docking_score_is_rejected_before_export(self):
        with self.assertRaises(ValueError):
            verification.validate_docking_result({'best_score':float('nan'), 'modes':[(1,float('nan'))], 'n':1})

    def test_missing_pose_is_not_successful_docking(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'empty.pdbqt'; p.write_text('END\n')
            with self.assertRaises(ValueError):
                verification.validate_docking_result({'best_score':-6,'modes':[(1,-6)],'n':1,'out_pdbqt':str(p)})

    def test_invalid_box_rejected(self):
        for center, size in [([0, 0, float('nan')], [10, 10, 10]), ([0, 0, 0], [-1, 10, 10])]:
            with self.assertRaises(ValueError):
                verification.validate_box(center, size)

    def test_artifact_tampering_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'pose.sdf'
            p.write_text('original\n')
            evidence = verification.capture_artifacts({'pose': {'path': str(p)}})
            self.assertTrue(verification.verify_artifacts(evidence))
            evidence['pose']['text'] = 'changed'
            self.assertFalse(verification.verify_artifacts(evidence))

    def test_partial_record_retains_success_and_failure(self):
        record = verification.run_record('docking', {'smiles': 'CCO'}, {},
            {'docking': {'status': 'verified', 'score': -6}, 'interactions': {'status': 'failed', 'reason': 'engine error'}})
        self.assertEqual(record['status'], 'partial')
        self.assertEqual(record['steps']['docking']['score'], -6)
