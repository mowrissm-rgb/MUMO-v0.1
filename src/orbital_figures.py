"""Genuine frontier-orbital surfaces; failures never become decorative lobes."""
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile

ATOM_COLORS = {'C': '#00d94f', 'H': '#ffe000', 'S': '#ffad00',
               'O': '#ff173c', 'N': '#2457ff'}

def compute_surfaces(q, python=None, timeout=120):
    """Evaluate captured wavefunctions in an isolated interpreter, not Streamlit."""
    if not q.get('molden'):
        return {'status': 'unavailable', 'error': 'No orbital wavefunction was recorded.'}
    python = python or os.environ.get('MUMO_QM_PYTHON', '/opt/qmenv/bin/python')
    if not Path(python).is_file():
        return {'status': 'unavailable', 'error': 'The isolated orbital-surface engine is not installed.'}
    try:
        with tempfile.TemporaryDirectory(prefix='mumo-surfaces-') as folder:
            root = Path(folder)
            (root / 'orbitals.molden').write_text(q['molden'], encoding='utf-8')
            (root / 'reference.json').write_text(json.dumps(q, allow_nan=False), encoding='utf-8')
            env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
            proc = subprocess.run(
                [str(python), str(Path(__file__).with_name('orbital_worker.py')),
                 '--molden', str(root / 'orbitals.molden'),
                 '--reference', str(root / 'reference.json'), '--output-dir', str(root)],
                capture_output=True, text=True, timeout=timeout, env=env)
            manifest = root / 'manifest.json'
            if not manifest.is_file():
                raise ValueError(f'Orbital worker failed ({proc.returncode}): {proc.stderr[-300:]}')
            result = json.loads(manifest.read_text(encoding='utf-8'))
            if result.get('status') != 'verified' or proc.returncode:
                return {'status': 'failed', 'error': result.get('error', 'Orbital validation failed.')}
            for name in ('homo_cube', 'lumo_cube'):
                filename = result.get(name)
                if not filename or Path(filename).name != filename:
                    raise ValueError('Worker supplied an invalid cube filename.')
                cube = root / filename
                if not cube.is_file() or cube.stat().st_size > 20_000_000:
                    raise ValueError('Cube output is missing or exceeds the size limit.')
                result[name] = cube.read_text(encoding='utf-8')
            return result
    except Exception as exc:
        return {'status': 'failed', 'error': f'{type(exc).__name__}: {exc}'}


def surface_html(xyz, cube):
    """Both signs of a computed wavefunction at a common 0.03 a.u. isovalue."""
    from renderer_assets import graphics_script
    def safe(value):
        return json.dumps(value).replace('<', '\\u003c')
    styles = '\n'.join(
        "viewer.setStyle({elem:" + json.dumps(element) + "},{stick:{radius:0.10,color:"
        + json.dumps(color) + "},sphere:{scale:0.26,color:" + json.dumps(color) + "}});"
        for element, color in ATOM_COLORS.items())
    return f'''<html><body style="margin:0;background:white">
<div id="orbital" style="width:620px;height:360px"></div>
{graphics_script()}
<script>
const viewer=$3Dmol.createViewer(document.getElementById('orbital'),{{backgroundColor:'white'}});
viewer.addModel({safe(xyz)},'xyz');
viewer.setStyle({{}},{{stick:{{radius:0.10}},sphere:{{scale:0.26}}}});
{styles}
const data=new $3Dmol.VolumeData({safe(cube)},'cube');
viewer.addIsosurface(data,{{isoval:0.03,color:'#ff991f',alpha:0.78,smoothness:1}});
viewer.addIsosurface(data,{{isoval:-0.03,color:'#36b5ff',alpha:0.78,smoothness:1}});
viewer.zoomTo(); viewer.zoom(1.10); viewer.rotate(12,'x'); viewer.rotate(10,'y'); viewer.render();
window.__mumoOrbitalReady=true;
</script></body></html>'''


def _font(size):
    from PIL import ImageFont
    for name in ('DejaVuSans.ttf', 'arial.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def render_pair(q, label, surfaces, browser):
    """Identical camera for LUMO/HOMO, energy and compound name beneath each pair."""
    from PIL import Image
    if surfaces.get('status') != 'verified':
        raise ValueError(surfaces.get('error', 'No verified orbital surfaces.'))
    images = {}
    for name in ('lumo', 'homo'):
        # A new page avoids a stale ready flag or redeclared global script
        # variables making the second orbital silently render blank.
        page = browser.new_page(viewport={'width': 620, 'height': 360}, device_scale_factor=2)
        try:
            page.set_content(surface_html(q['evidence']['xyz'], surfaces[name + '_cube']))
            page.wait_for_function('window.__mumoOrbitalReady === true', timeout=20000)
            images[name] = Image.open(io.BytesIO(page.locator('#orbital').screenshot())).convert('RGB').resize(
                (620, 360), Image.Resampling.LANCZOS)
        finally:
            page.close()
    return compose_pair(images, q, label)


def compose_pair(images, q, label):
    """Separate orbital views with a dotted capital-I energy-gap connector."""
    from PIL import Image, ImageDraw
    panel = Image.new('RGB', (620, 1270), 'white')
    draw = ImageDraw.Draw(panel)
    panel.paste(images['lumo'], (0, 0))
    panel.paste(images['homo'], (0, 560))
    draw.text((310, 372), f"LUMO {q['lumo_ev']:.3f} eV", font=_font(40), fill='#161616', anchor='mt')
    draw.line((125, 430, 225, 430), fill='#333333', width=3)
    draw.line((125, 530, 225, 530), fill='#333333', width=3)
    for y in range(438, 525, 12):
        draw.line((175, y, 175, min(y + 4, 525)), fill='#333333', width=3)
    draw.text((390, 438), 'HOMO–LUMO gap', font=_font(28), fill='#555555', anchor='mt')
    draw.text((390, 480), f"{q['gap_ev']:.3f} eV", font=_font(40), fill='#161616', anchor='mt')
    draw.text((310, 938), f"HOMO {q['homo_ev']:.3f} eV", font=_font(40), fill='#161616', anchor='mt')
    # Wrap long scientific names rather than silently dropping their identity.
    words, lines, current = label.split(), [], ''
    for word in words:
        candidate = (current + ' ' + word).strip()
        if draw.textlength(candidate, font=_font(34)) > 585 and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    lines.append(current)
    if len(lines) > 2:
        raise ValueError('Compound name needs a wider panel; it cannot fit without truncation.')
    for i, line in enumerate(lines):
        draw.text((310, 995 + i * 38), line, font=_font(34), fill='black', anchor='mt')
    draw.line((35, 1075, 585, 1075), fill='#dddddd', width=1)
    labels = [('C', 'carbon'), ('H', 'hydrogen'), ('S', 'sulfur'),
              ('O', 'oxygen'), ('N', 'nitrogen')]
    positions = [(45, 1100), (235, 1100), (440, 1100), (130, 1145), (335, 1145)]
    for (element, name), (x, y) in zip(labels, positions):
        draw.ellipse((x, y + 4, x + 16, y + 20), fill=ATOM_COLORS[element])
        draw.text((x + 24, y), f'{element}: {name}', font=_font(20), fill='#333333')
    draw.text((310, 1200), 'Orange / blue: opposite orbital phases',
              font=_font(20), fill='#555555', anchor='mt')
    draw.text((310, 1230), 'Color key lists elements; not all occur in each compound.',
              font=_font(17), fill='#666666', anchor='mt')
    output = io.BytesIO()
    panel.save(output, format='PNG')
    return output.getvalue()


def prepare_entry(entry, browser):
    """Attach genuine images to the same ligand result used by panel and report."""
    try:
        surfaces = compute_surfaces(entry['qm'])
        entry['surface_status'] = surfaces['status']
        if surfaces['status'] != 'verified':
            entry['surface_error'] = surfaces.get('error', 'Surface calculation failed.')
            return
        entry['surface_png'] = render_pair(entry['qm'], entry['label'], surfaces, browser)
        entry['surface_evidence'] = {k: v for k, v in surfaces.items()
                                     if k not in ('homo_cube', 'lumo_cube')}
    except Exception as exc:
        entry['surface_status'] = 'failed'
        entry['surface_error'] = f'{type(exc).__name__}: {exc}'


def contact_sheets(entries, compact=False):
    """Six verified surface panels per sheet, preserving input order and all names."""
    from PIL import Image
    valid = [e for e in entries if e.get('surface_png')]
    sheets = []
    for offset in range(0, len(valid), 6):
        batch = valid[offset:offset + 6]
        columns = min(3, len(batch)) if compact else 3
        rows = (len(batch) + columns - 1) // columns if compact else 2
        image = Image.new('RGB', (620 * columns, 1270 * rows), 'white')
        for i, entry in enumerate(batch):
            panel = Image.open(io.BytesIO(entry['surface_png'])).convert('RGB')
            panel.thumbnail((620, 1270))
            x, y = (i % columns) * 620, (i // columns) * 1270
            image.paste(panel, (x + (620 - panel.width) // 2, y + (1270 - panel.height) // 2))
        output = io.BytesIO()
        image.save(output, format='PNG')
        sheets.append({'png': output.getvalue(), 'labels': [e['label'] for e in batch]})
    return sheets
