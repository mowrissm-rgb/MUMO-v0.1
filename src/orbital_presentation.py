"""Shared scientific presentation for ADME and standalone orbital workflows."""
import hashlib
import json

PRESENTATION_VERSION = 'verified-surfaces-2'


def resolve_input_ligand(value, convo):
    """An uploaded, parsed structure takes precedence over a name database search."""
    for obj in convo.get('ligand_objs') or []:
        if obj.get('smiles') and value in (obj.get('label'), obj.get('smiles')):
            return obj['smiles'], obj.get('label') or str(value)
    from agents.admet import resolve_ligand
    return resolve_ligand(value)


def admet_entries(result):
    if result.get('batch'):
        return result['batch']
    entry = dict(result.get('orbital_entry') or {})
    entry.update(label=result.get('lig_label') or 'Unnamed compound',
                 smiles=result.get('lig_smiles') or '', qm=result.get('qm'))
    return [entry] if entry['qm'] else []


def prepare_admet_surfaces(result, browser):
    from orbital_figures import prepare_entry
    entries = admet_entries(result)
    for entry in entries:
        if entry.get('qm') and not entry['qm'].get('_error'):
            prepare_entry(entry, browser)
    if not result.get('batch') and entries:
        result['orbital_entry'] = entries[0]
    return entries


def _serializable(value):
    if isinstance(value, bytes):
        return {'sha256': hashlib.sha256(value).hexdigest()}
    if isinstance(value, dict):
        return {str(k): _serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serializable(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def report_cache_key(kind, result):
    content = json.dumps(_serializable(result), sort_keys=True, ensure_ascii=True, allow_nan=False)
    digest = hashlib.sha256(content.encode()).hexdigest()
    return f'{kind}_{PRESENTATION_VERSION}_{digest}'


def render_orbital_entries(entries, ui):
    """Never present the legacy energy-only chart as a molecular surface."""
    for entry in entries:
        q = entry.get('qm') or {}
        if not q or q.get('_error'):
            continue
        ui.markdown(f"**{entry['label']} — Orbit**")
        cols = ui.columns(3)
        for col, label, field in zip(cols, ('HOMO', 'LUMO', 'Gap'), ('homo_ev', 'lumo_ev', 'gap_ev')):
            col.metric(label, f"{q[field]:.2f} eV")
        if entry.get('surface_png') and entry.get('surface_status') == 'verified':
            ui.image(entry['surface_png'], use_container_width=True)
            ui.caption('Calculated orbital surfaces. Red and blue represent opposite phases, not charge.')
        else:
            ui.info('Orbital surfaces unavailable: ' + entry.get('surface_error',
                    'No verified wavefunction image was recorded for this run. Numerical energies are retained.'))
        ui.caption(f"SMILES: {entry.get('smiles', '')}")

