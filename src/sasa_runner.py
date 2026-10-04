"""Isolated FreeSASA worker; reads PDB and emits computed JSON on stdout."""
import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path


def calculate(pdb_text):
    import freesasa
    from importlib.metadata import version, PackageNotFoundError
    # Match Ramachandran's first-model / blank-or-A atom selection. Preserve
    # every retained chain and insertion code; do not re-number residues.
    lines, seen = [], set()
    for line in pdb_text.splitlines():
        if line.startswith('ENDMDL'):
            break
        if not line.startswith('ATOM  ') or len(line) < 54 or line[16] not in (' ', 'A'):
            continue
        key = (line[21:27], line[12:16])
        if key in seen:
            continue
        seen.add(key)
        lines.append(line[:16] + ' ' + line[17:])
    if not lines:
        raise ValueError('No protein ATOM coordinates found')
    with tempfile.TemporaryDirectory(prefix='mumo-sasa-selected-') as tmp:
        selected = Path(tmp) / 'selected.pdb'
        selected.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        structure = freesasa.Structure(str(selected), options={
            'hetatm': False, 'hydrogen': False, 'skip-unknown': True})
    result = freesasa.calc(structure, freesasa.Parameters({
        'algorithm': freesasa.LeeRichards, 'probe-radius': 1.4, 'n-slices': 20, 'n-threads': 1}))
    residues = []
    for chain, areas in result.residueAreas().items():
        for number, area in areas.items():
            row = {'chain': chain, 'residue': number, 'name': area.residueType,
                   'total': area.total, 'polar': area.polar, 'apolar': area.apolar}
            if any(not math.isfinite(row[k]) or row[k] < 0 for k in ('total', 'polar', 'apolar')):
                raise ValueError('Invalid FreeSASA area')
            if abs(row['total'] - row['polar'] - row['apolar']) > 1e-5:
                raise ValueError('FreeSASA polarity area mismatch')
            residues.append(row)
    if not residues or not math.isfinite(result.totalArea()) or result.totalArea() <= 0:
        raise ValueError('FreeSASA returned no usable areas')
    if abs(sum(r['total'] for r in residues) - result.totalArea()) > 1e-4:
        raise ValueError('FreeSASA residue total mismatch')
    try:
        engine_version = version('freesasa')
    except PackageNotFoundError:
        engine_version = 'unrecorded'
    return {'status': 'calculated', 'engine': 'FreeSASA', 'version': engine_version,
            'input_sha256': hashlib.sha256(pdb_text.encode('utf-8')).hexdigest(),
            'selected_atoms': structure.nAtoms(), 'units': 'angstrom squared',
            'algorithm': 'Lee-Richards', 'probe_radius_angstrom': 1.4,
            'slices': 20, 'classifier': 'FreeSASA default',
            'selection': 'first model; ATOM only; blank/A altloc; no hydrogen; all retained chains',
            'total_area': result.totalArea(), 'residues': residues}


if __name__ == '__main__':
    try:
        print(json.dumps(calculate(Path(sys.argv[1]).read_bytes().decode('utf-8'))))
    except Exception as exc:
        print(json.dumps({'status': 'failed', '_error': str(exc)}))
        sys.exit(1)
