"""Build-time real aspirin calculation, surface rendering and report smoke test."""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from agents.qm_analyst import orbitals
from orbital_figures import compute_surfaces, render_pair
from report_writer import new_browser, build_qm_docx
from PIL import Image
from docx import Document

smiles = 'CC(=O)Oc1ccccc1C(=O)O'
q = orbitals(smiles)
if q.get('status') != 'verified':
    raise RuntimeError('Real aspirin calculation failed: ' + str(q.get('_error')))
surfaces = compute_surfaces(q)
if surfaces.get('status') != 'verified':
    raise RuntimeError('Real aspirin surface validation failed: ' + str(surfaces.get('error')))
pw, browser = new_browser()
try:
    png = render_pair(q, 'Aspirin', surfaces, browser)
finally:
    browser.close()
    pw.stop()
image = Image.open(io.BytesIO(png)).convert('RGB')
for name, top in [('LUMO', 20), ('HOMO', 470)]:
    pixels = image.crop((100, top, 620, top + 300)).getdata()
    colored = sum(1 for p in pixels if max(p) - min(p) > 25)
    if colored < 100:
        raise RuntimeError(name + ' rendered blank')
entry = {'label': 'Aspirin', 'smiles': smiles, 'qm': q, 'surface_png': png}
doc = Document(io.BytesIO(build_qm_docx({'entries': [entry]})))
if len(doc.inline_shapes) != 1:
    raise RuntimeError('Calculated image missing from report')
print('RELEASE SMOKE OK: real GFN2-xTB aspirin, validated cubes, both images, DOCX embedding')
