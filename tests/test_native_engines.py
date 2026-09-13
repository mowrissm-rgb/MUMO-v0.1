import os
import shutil
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from agents import qm_analyst


class NativeEngineTests(unittest.TestCase):
    @unittest.skipUnless(qm_analyst.xtb_available(), 'Actual xTB executable not installed locally')
    def test_actual_xtb_ethanol_single_point(self):
        result = qm_analyst.orbitals('CCO', timeout=120)
        self.assertNotIn('_error', result, result.get('_error'))
        self.assertEqual(result['charge'], 0)
        self.assertEqual(result['status'], 'verified')
        self.assertGreaterEqual(result['gap_ev'], 0)
        self.assertTrue(result['evidence']['stdout'])
