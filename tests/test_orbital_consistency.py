import io
import sys
import unittest
import zipfile
import ast
import types
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


class OrbitalConsistencyTests(unittest.TestCase):
    def test_failed_new_calculation_does_not_keep_previous_result_visible(self):
        class State(dict):
            __getattr__ = dict.__getitem__
            __setattr__ = dict.__setitem__
        state = State(results={'kind': 'qm', 'entries': ['old molecule']}, panel_open=True)
        source = Path(__file__).resolve().parents[1] / 'src/mumo_chat.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_run_sync_action')
        scope = {'ss': state, '_capability_ok': lambda capability: False}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
        scope['_run_sync_action']('qm', {'ligand': 'CCO'})
        self.assertIsNone(state.results)
        self.assertFalse(state.panel_open)

    def test_file_plus_adme_request_does_not_fall_back_to_docking(self):
        from rdkit import Chem
        class State(dict):
            __getattr__ = dict.__getitem__
            __setattr__ = dict.__setitem__
        state = State(convo={'target': 'IL6'})
        runs = []
        scope = {'ss': state, 'say': lambda message: None, 'MAX_UPLOAD_BYTES': 100000,
                 '_run_plan': lambda *args: runs.append(args)}
        source = Path(__file__).resolve().parents[1] / 'src/mumo_chat.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name in {'_handle_upload', '_upload_ligand_objs'}]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), scope)
        molecule = Chem.MolFromSmiles('CCO')
        molecule.SetProp('_Name', 'Ethanol file')
        uploaded = types.SimpleNamespace(name='ethanol.mol', getvalue=lambda: Chem.MolToMolBlock(molecule).encode())
        scope['_handle_upload']([uploaded], 'run Fate on this compound')
        self.assertEqual(runs[0][0], ['analyze'])
        self.assertEqual(runs[0][1]['ligand_objs'][0]['smiles'], 'CCO')
        self.assertIsNone(state.upload_pending)

    def test_uploaded_compound_uses_its_smiles_and_name(self):
        import orbital_presentation as presentation
        self.assertTrue(hasattr(presentation, 'resolve_input_ligand'))
        with patch('agents.admet.resolve_ligand', side_effect=AssertionError('Must not replace an uploaded structure')):
            result = presentation.resolve_input_ligand('Uploaded ethanol',
                {'ligand_objs': [{'label': 'Uploaded ethanol', 'smiles': 'CCO'}]})
        self.assertEqual(result, ('CCO', 'Uploaded ethanol'))

    def result(self):
        return {'kind': 'admet', 'lig_label': 'Ethanol', 'lig_smiles': 'CCO',
                'qm': {'homo_ev': -7.0, 'lumo_ev': -1.0, 'gap_ev': 6.0,
                       'method': 'GFN2-xTB'}, 'druglikeness': {}}

    def test_admet_docx_embeds_verified_surface_instead_of_old_chart(self):
        from PIL import Image
        import report_writer
        png = io.BytesIO()
        Image.new('RGB', (20, 30), 'red').save(png, format='PNG')
        r = self.result()
        r['orbital_entry'] = {'label': 'Ethanol', 'smiles': 'CCO', 'qm': r['qm'],
                              'surface_png': png.getvalue(), 'surface_status': 'verified'}
        with patch('viz_string.orbital_png', side_effect=AssertionError('Legacy energy chart called')):
            document = report_writer.build_admet_docx(r)
        with zipfile.ZipFile(io.BytesIO(document)) as package:
            images = [package.read(name) for name in package.namelist() if name.startswith('word/media/')]
            self.assertTrue(images)
            sheet = Image.open(io.BytesIO(images[0])).convert('RGB')
            self.assertEqual(sheet.getpixel((310, 440)), (255, 0, 0))
            self.assertIn('Ethanol', package.read('word/document.xml').decode())

    def test_report_key_changes_with_structure_energies_and_image(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('orbital_presentation'))
        from orbital_presentation import report_cache_key
        r = self.result()
        first = report_cache_key('qm', r)
        self.assertEqual(first, report_cache_key('qm', dict(r)))
        r['lig_smiles'] = 'CC'
        self.assertNotEqual(first, report_cache_key('qm', r))
        second = report_cache_key('qm', r)
        r['qm']['homo_ev'] = -8.0
        self.assertNotEqual(second, report_cache_key('qm', r))
        third = report_cache_key('qm', r)
        r['orbital_entry'] = {'surface_png': b'new-calculated-image'}
        self.assertNotEqual(third, report_cache_key('qm', r))

    def test_batch_preparation_keeps_each_ligand_and_does_not_duplicate_first(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('orbital_presentation'))
        from orbital_presentation import prepare_admet_surfaces, admet_entries
        r = self.result()
        r['batch'] = [{'label': 'Ethanol', 'smiles': 'CCO', 'qm': r['qm']},
                      {'label': 'Methane', 'smiles': 'C', 'qm': dict(r['qm'])}]
        def prepare(entry, browser):
            entry['surface_png'] = entry['label'].encode()
            entry['surface_status'] = 'verified'
        with patch('orbital_figures.prepare_entry', side_effect=prepare):
            prepare_admet_surfaces(r, object())
        self.assertEqual([e['surface_png'] for e in admet_entries(r)], [b'Ethanol', b'Methane'])
