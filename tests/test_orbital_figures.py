"""Real rendering contracts: no dropped compounds or invented surfaces."""
import io
import copy
import sys
import unittest
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
try:
    import orbital_figures
except ModuleNotFoundError:
    orbital_figures = None


class OrbitalFigureTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(orbital_figures, 'Genuine orbital rendering is not implemented')

    def test_contact_sheets_keep_seven_compounds_on_two_sheets(self):
        # Omitting the last page, or accepting energy PNGs as surfaces, breaks this.
        image = Image.new('RGB', (100, 100), 'blue')
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        entries = [{'label': f'Compound {i}', 'surface_png': buffer.getvalue()}
                   for i in range(7)]
        sheets = orbital_figures.contact_sheets(entries)
        self.assertEqual([s['labels'] for s in sheets],
                         [[f'Compound {i}' for i in range(6)], ['Compound 6']])
        self.assertEqual(len(sheets), 2)
        for sheet in sheets:
            self.assertEqual(Image.open(io.BytesIO(sheet['png'])).size, (1860, 2540))

    def test_gap_connector_is_between_distinct_orbital_views_without_changing_values(self):
        self.assertTrue(hasattr(orbital_figures, 'compose_pair'),
                        'Separated orbital views with a gap connector are not implemented')
        values = {'homo_ev': -11.3751, 'lumo_ev': -7.8683, 'gap_ev': 3.5068}
        before = copy.deepcopy(values)
        images = {'lumo': Image.new('RGB', (620, 360), '#4573d2'),
                  'homo': Image.new('RGB', (620, 360), '#e85465')}
        png = orbital_figures.compose_pair(images, values, 'Aspirin')
        panel = Image.open(io.BytesIO(png)).convert('RGB')
        self.assertEqual(panel.size, (620, 1270))
        self.assertEqual(panel.getpixel((310, 200)), (69, 115, 210))
        self.assertEqual(panel.getpixel((310, 760)), (232, 84, 101))
        self.assertLess(max(panel.getpixel((130, 430))), 80)  # top cap
        self.assertLess(max(panel.getpixel((130, 530))), 80)  # bottom cap
        self.assertLess(max(panel.getpixel((175, 438))), 80)  # dotted stem
        self.assertEqual(panel.getpixel((175, 446)), (255, 255, 255))  # gap in stem
        self.assertEqual(values, before)

    def test_approved_bright_palette_preserves_surface_isovalues(self):
        html = orbital_figures.surface_html('1\nxyz\nH 0 0 0', 'real cube')
        for color in ('#00d94f', '#ffe000', '#ffad00', '#ff173c', '#2457ff',
                      '#ff991f', '#36b5ff'):
            self.assertIn(color, html)
        self.assertIn('isoval:0.03', html)
        self.assertIn('isoval:-0.03', html)

    def test_energy_diagram_is_not_promoted_to_a_surface(self):
        self.assertEqual(orbital_figures.contact_sheets([
            {'label': 'aspirin', 'png': b'energy diagram'}]), [])

    def test_html_contains_actual_cube_and_both_phases_without_script_injection(self):
        html = orbital_figures.surface_html('1\nxyz\nH 0 0 0', 'real cube </script>')
        self.assertNotIn('real cube </script>', html)
        self.assertIn('real cube', html)
        self.assertIn('isoval:0.03', html)
        self.assertIn('isoval:-0.03', html)

    def test_missing_wavefunction_returns_unavailable_without_fake_images(self):
        result = orbital_figures.compute_surfaces({'homo_ev': -4., 'lumo_ev': -1.})
        self.assertEqual(result['status'], 'unavailable')
        self.assertNotIn('homo_cube', result)

    def test_qm_report_has_two_surface_pages_for_seven_named_compounds(self):
        from docx import Document
        import report_writer
        buffer = io.BytesIO()
        Image.new('RGB', (460, 680), 'blue').save(buffer, format='PNG')
        entries = [{'label': f'Ligand {i}', 'smiles': 'CC', 'surface_png': buffer.getvalue(),
                    'qm': {'homo_ev': -5., 'lumo_ev': -2., 'gap_ev': 3.}} for i in range(7)]
        doc = Document(io.BytesIO(report_writer.build_qm_docx({'entries': entries})))
        self.assertEqual(len(doc.inline_shapes), 2)
        text = '\n'.join(p.text for p in doc.paragraphs)
        self.assertIn('Ligand 6', text)
        self.assertIn('Orbital phase', text)


if __name__ == '__main__':
    unittest.main()
