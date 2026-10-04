import copy
import io
import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import viz


class DockingPresentationTests(unittest.TestCase):
    def test_full_ribbon_camera_controls_and_contact_legend_preserve_records(self):
        ia = {'lines': [{'type': 'H-bond', 'p1': [0, 0, 0], 'p2': [1, 2, 3],
                         'color': 'blue', 'label': 'TYR385(A) · 2.80 Å'}]}
        before = copy.deepcopy(ia)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'complex.pdb'
            path.write_text('END\n')
            html = viz.render_complex_html(str(path), ia)
            self.assertIn('Full protein', html)
            self.assertIn('Binding site', html)
            self.assertIn('Detected contacts', html)
            self.assertIn('#14a83d', html)
            self.assertIn('initialView="full"', html)
            pocket = viz.render_complex_html(str(path), ia, {'view_mode': 'binding'})
            self.assertIn('initialView="binding"', pocket)
        self.assertEqual(ia, before)

    def test_saturated_2d_colors_leave_geometry_and_labels_unchanged(self):
        self.assertTrue(hasattr(viz, 'brighten_2d_svg'))
        svg = '<svg><line x1="3.2" y1="9" stroke="#2e8b3d"/><text>TYR385(A)</text></svg>'
        result = viz.brighten_2d_svg(svg)
        self.assertEqual(result, svg.replace('#2e8b3d', '#14a83d'))

    def test_report_composes_full_and_binding_panels_without_dropping_one(self):
        import report_writer
        self.assertTrue(hasattr(report_writer, 'compose_pose_views'))
        pictures = []
        for color in ('#173b80', '#0b824e'):
            stream = io.BytesIO()
            Image.new('RGB', (900, 560), color).save(stream, format='PNG')
            pictures.append(stream.getvalue())
        result = Image.open(io.BytesIO(report_writer.compose_pose_views(*pictures)))
        self.assertEqual(result.size, (900, 1070))
        self.assertEqual(result.getpixel((450, 300)), (23, 59, 128))
        self.assertEqual(result.getpixel((450, 800)), (11, 130, 78))
