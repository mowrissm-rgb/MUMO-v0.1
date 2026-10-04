import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


class RendererAssetsTests(unittest.TestCase):
    def test_local_library_integrity_and_no_external_orbital_script(self):
        from renderer_assets import graphics_script
        from orbital_figures import surface_html
        script = graphics_script()
        self.assertGreater(len(script), 400000)
        self.assertTrue(script.startswith('<script>'))
        html = surface_html('0\nfixture\n', '')
        self.assertNotIn('<script src=', html)
        self.assertIn(script, html)
