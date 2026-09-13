import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from verification import capture_artifacts
from report_writer import build_structure_zip, _add_results_discussion
from viz import serialize_viz, rehydrate_viz

class ExportIntegrationTests(unittest.TestCase):
    def test_saved_export_preserves_prepared_bytes_and_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'complex.pdb'; p.write_text('REMARK canonical pose\nEND\n')
            ligand = Path(tmp)/'ligand.sdf'; ligand.write_text('canonical chemical graph\n')
            evidence = capture_artifacts({'complex': str(p), 'ligand': str(ligand)})
            v = {'lig': {'complex': str(p), 'ia': {'status': 'qualified'},
                         'artifact_texts': evidence, 'verification': {'run_id': 'test-run'}}}
            saved = rehydrate_viz(serialize_viz(v), tmp)
            content = build_structure_zip({'viz': saved, 'meta': {'gene': 'T'}})
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                name = next(n for n in z.namelist() if n.endswith('/ligand.sdf'))
                self.assertEqual(z.read(name), ligand.read_bytes())
                record = next(n for n in z.namelist() if n.endswith('/run_record.json'))
                self.assertEqual(json.loads(z.read(record))['run_id'], 'test-run')
            saved['lig']['artifact_texts']['ligand']['text'] = 'tampered'
            with self.assertRaises(ValueError):
                build_structure_zip({'viz': saved, 'meta': {'gene': 'T'}})

    def test_report_uses_replica_count_and_rejects_model_invention(self):
        from docx import Document
        class Model:
            def chat(self,*a,**k): return 'Invented 800 interactions'
        doc=Document()
        _add_results_discussion(doc, ['T'], lambda t:[{'Ligand':'L'}], lambda row:-6,
                                {'replicas':3,'exhaustiveness':16},Model(),[])
        text='\n'.join(p.text for p in doc.paragraphs)
        self.assertIn('3 docking replica(s)',text)
        self.assertNotIn('800',text)
        self.assertNotIn('single docking replica',text)
