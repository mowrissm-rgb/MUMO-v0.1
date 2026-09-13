import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import viz


class ExportPersistenceTests(unittest.TestCase):
    def test_persistence_keeps_full_source_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'pose.pdb'
            source.write_text('REMARK source evidence\nEND\n')
            entry = {'complex': str(source), 'ia': {'status': 'verified'},
                     'artifact_texts': {'ligand.sdf': 'chemical graph\n'},
                     'verification': {'status': 'partial'}}
            stored = viz.serialize_viz({'lig': entry})
            self.assertEqual(stored['lig']['pdb'], source.read_text())
            restored = viz.rehydrate_viz(stored, tmp)['lig']
            self.assertEqual(restored['artifact_texts'], entry['artifact_texts'])
            self.assertEqual(restored['verification'], entry['verification'])
