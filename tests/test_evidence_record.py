import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import brain


class ReportEvidenceTests(unittest.TestCase):
    def test_missing_score_is_unavailable_not_weak_binding(self):
        text = brain.write_report({'ligand': 'x'})
        self.assertIn('unavailable', text.lower())
        self.assertNotIn('weak', text)

    def test_report_does_not_accept_invented_llm_results(self):
        class FabricatingModel:
            def chat(self, *args, **kwargs):
                return 'Experimentally proven: 900 hydrogen bonds'
        text = brain.write_report({'affinity': -6, 'ligand': 'x', 'n_hbonds': None}, FabricatingModel())
        self.assertNotIn('900', text)
        self.assertIn('unavailable', text.lower())
        self.assertIn('prediction', text.lower())
