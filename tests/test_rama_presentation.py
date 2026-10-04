import base64
import copy
import io
import re
import sys
import unittest
from pathlib import Path
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import ramachandran


class RamaPresentationTests(unittest.TestCase):
    def test_warm_reference_shading_does_not_change_residue_results(self):
        # A palette change must not rewrite classifications or counts.
        result = {'points': [{'phi': -60, 'psi': -45, 'region': 'favoured'}],
                  'counts': {'favoured': 1, 'allowed': 0, 'outlier': 0},
                  'pct': {'favoured': 100, 'allowed': 0, 'outlier': 0},
                  'n_scored': 1, 'by_class': {'general': 1}}
        before = copy.deepcopy(result)
        svg = ramachandran.plot_svg(result)
        self.assertEqual(result, before)
        png = base64.b64decode(re.search(r'data:image/png;base64,([^\"]+)', svg).group(1))
        pixels = set(Image.open(io.BytesIO(png)).convert('RGB').getdata())
        self.assertTrue(any(r > 180 and 60 < g < 180 and 60 < b < 180 for r, g, b in pixels),
                        'Favoured reference regions should be red shaded')
        self.assertTrue(any(r > 220 and g > 170 and b < 150 for r, g, b in pixels),
                        'Allowed reference regions should be yellow shaded')


if __name__ == '__main__':
    unittest.main()
