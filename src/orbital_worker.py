"""Isolated Molden conversion. Native libraries are imported only by conversion."""
import argparse
import hashlib
import json
import math
import os
import re
import signal
import tempfile
from pathlib import Path

EH_TO_EV = 27.211386245988
ENERGY_TOLERANCE_EV = 0.02
# Initial tested xTB support is main-group H-Ar. Transition-metal core conventions
# require separate validation rather than inference from the nuclear charge.
VALENCE = {1: 1, 2: 2, 3: 1, 4: 2, 5: 3, 6: 4, 7: 5, 8: 6, 9: 7, 10: 8,
           11: 1, 12: 2, 13: 3, 14: 4, 15: 5, 16: 6, 17: 7, 18: 8}


def limit_resources():
    """Apply fixed caps in the isolated CLI process, never the calling application."""
    for variable in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[variable] = '1'
    if os.name == 'posix':
        import resource
        for kind, soft, hard in ((resource.RLIMIT_AS, 2 * 1024 ** 3, 2 * 1024 ** 3),
                                 (resource.RLIMIT_CPU, 180, 185)):
            previous_soft, previous_hard = resource.getrlimit(kind)
            if previous_hard != resource.RLIM_INFINITY:
                hard = min(hard, previous_hard)
            soft = min(soft, hard)
            if previous_soft != resource.RLIM_INFINITY:
                soft = min(soft, previous_soft)
            resource.setrlimit(kind, (soft, hard))
        def expired(signum, frame):
            raise TimeoutError('Isolated orbital worker exceeded its 180-second resource limit.')
        signal.signal(signal.SIGXCPU, expired)
        signal.signal(signal.SIGALRM, expired)
        signal.alarm(180)


def _strict_molden(text):
    """Reject sparse/ambiguous data before PySCF can silently fill MO entries."""
    sections = {}
    section = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('['):
            match = re.match(r'\[([^]]+)\]', line)
            if not match:
                raise ValueError('Malformed Molden section.')
            section = match[1].upper()
            if section in sections:
                raise ValueError('Duplicate Molden sections are unsupported.')
            sections[section] = [line]
        elif section:
            sections[section].append(line)
    for required in ('MOLDEN FORMAT', 'ATOMS', 'GTO', 'MO'):
        if required not in sections:
            raise ValueError(f'Missing Molden {required} section.')
    atoms = sections['ATOMS'][1:]
    if not 1 <= len(atoms) <= 256:
        raise ValueError('Atom resource limit exceeded.')
    # xTB exports separate, single-contraction s/p/d shells.
    nao = 0
    angular_max = 0
    spherical = any(s.startswith('5D') for s in sections)
    basis_atoms = []
    lines = iter(sections['GTO'][1:])
    for line in lines:
        fields = line.split()
        if len(fields) == 2 and fields[0].isdigit():
            basis_atoms.append(int(fields[0]))
            continue
        if len(fields) != 3 or fields[0].lower() not in ('s', 'p', 'd'):
            raise ValueError('Unsupported Molden basis shell (only s/p/d supported).')
        angular = {'s': 0, 'p': 1, 'd': 2}[fields[0].lower()]
        angular_max = max(angular_max, angular)
        nprim = int(fields[1])
        if not 1 <= nprim <= 32 or not math.isfinite(float(fields[2])) or float(fields[2]) <= 0:
            raise ValueError('Invalid or oversized Gaussian contraction.')
        for _ in range(nprim):
            primitive = next(lines, '').replace('D', 'E').replace('d', 'e').split()
            if len(primitive) != 2:
                raise ValueError('Malformed Gaussian primitive.')
            exponent, coefficient = map(float, primitive)
            if exponent <= 0 or not all(map(math.isfinite, (exponent, coefficient))):
                raise ValueError('Non-finite or invalid Gaussian primitive.')
        nao += 2 * angular + 1 if spherical else (angular + 1) * (angular + 2) // 2
    if basis_atoms != list(range(1, len(atoms) + 1)) or not 1 <= nao <= 1024:
        raise ValueError('Basis atom order/count or AO resource limit invalid.')
    orbitals = []
    current = None
    for line in sections['MO'][1:]:
        if '=' in line:
            key, value = [x.strip() for x in line.split('=', 1)]
            key = key.lower()
            if key == 'sym':
                current = {'coefficients': {}}
                orbitals.append(current)
            if current is None or key not in ('sym', 'ene', 'spin', 'occup') or key in current:
                raise ValueError('Malformed orbital metadata.')
            current[key] = value
        else:
            fields = line.replace('D', 'E').replace('d', 'e').split()
            if current is None or len(fields) != 2:
                raise ValueError('Malformed orbital coefficient.')
            index, value = int(fields[0]), float(fields[1])
            if index in current['coefficients'] or not math.isfinite(value):
                raise ValueError('Duplicate or non-finite orbital coefficient.')
            current['coefficients'][index] = value
    if not 2 <= len(orbitals) <= 1024:
        raise ValueError('Missing orbital coefficients or MO resource limit exceeded.')
    for orbital in orbitals:
        if set(orbital['coefficients']) != set(range(1, nao + 1)):
            raise ValueError('Incomplete orbital coefficient coverage; zero filling forbidden.')
        if any(key not in orbital for key in ('ene', 'spin', 'occup')):
            raise ValueError('Incomplete orbital metadata.')
        for key in ('ene', 'occup'):
            orbital[key] = float(orbital[key].replace('D', 'E').replace('d', 'e'))
            if not math.isfinite(orbital[key]):
                raise ValueError('Non-finite orbital metadata.')
        if orbital['spin'].lower() != 'alpha':
            raise ValueError('Only closed-shell Alpha spatial orbitals are supported.')
    return {'nao': nao, 'orbitals': orbitals, 'angular_max': angular_max,
            'spherical': spherical, 'atom_lines': atoms}


def convert(molden_path, reference, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        if reference.get('unpaired_electrons') != 0:
            raise ValueError('Only closed-shell orbital surfaces are supported.')
        if reference.get('status') != 'verified':
            raise ValueError('A verified numerical reference is required.')
        molden_path = Path(molden_path)
        if molden_path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError('Molden file exceeds the 64 MiB limit.')
        data = molden_path.read_bytes()
        parsed = _strict_molden(data.decode('utf-8'))
        digest = hashlib.sha256(data).hexdigest()
        if reference.get('molden_sha256') is not None and reference['molden_sha256'] != digest:
            raise ValueError('Molden SHA256 disagrees with the captured reference.')
        result = _evaluate(molden_path, reference, parsed, output_dir)
        result['molden_sha256'] = digest
    except Exception as exc:
        result = {'status': 'error', 'error': str(exc)}
    (output_dir / 'manifest.json').write_text(json.dumps(result), encoding='utf-8')
    return result


def _evaluate(molden_path, reference, parsed, output_dir):
    """Evaluate captured coefficients, never run a replacement SCF calculation."""
    import numpy as np
    import pyscf
    from pyscf import lib, gto
    from pyscf.tools import molden, cubegen
    lib.num_threads(1)
    mol, energies, coefficients, occupations, _, spins = molden.load(str(molden_path), verbose=0)
    mol.max_memory = 512
    charge = reference.get('charge')
    if type(charge) is not int:
        raise ValueError('Reference integer charge is required.')
    # Molden has no molecular charge field. A neutral-reader spin fallback is
    # not the captured state; occupations and valence count validate that below.
    mol.charge = charge
    mol.spin = 0
    model = reference.get('occupation_model', 'xtb-valence')
    if model == 'xtb-valence':
        if parsed['angular_max'] > 1:
            raise ValueError('xTB d/spherical basis mapping has not been validated; surfaces unavailable.')
        # xTB 6.7.1 printmold writes basis%cont verbatim. slaterToGauss(...,
        # norm=.true.) has already multiplied these weights by Cartesian
        # primitive normalization. PySCF expects weights of normalized
        # primitives and would otherwise apply the exponent-dependent factor
        # twice. Divide it out in the BASIS, preserving captured MO coefficients.
        # Radial gto_norm differs from Cartesian norm by a shell-constant factor;
        # PySCF's contracted-shell normalization cancels that factor for s/p.
        # Sources: grimme-lab/xtb v6.7.1 src/{printmold,slater}.f90 and
        # src/xtb/basisset.f90. No tolerance widening or MO renormalization.
        mol.basis = {}
        mol._basis = {
            symbol: [[shell[0]] + [[p[0], p[1] / float(gto.gto_norm(shell[0], p[0]))]
                                   for p in shell[1:]] for shell in shells]
            for symbol, shells in mol._basis.items()
        }
        mol.build(0, 0)
    if not isinstance(coefficients, np.ndarray) or coefficients.ndim != 2:
        raise ValueError('Unsupported spin-resolved orbital coefficients.')
    nmo = len(parsed['orbitals'])
    if (coefficients.shape != (parsed['nao'], nmo) or mol.nao_nr() != parsed['nao']
            or np.shape(energies) != (nmo,) or np.shape(occupations) != (nmo,)
            or not all(np.isfinite(v).all() for v in (coefficients, energies, occupations))):
        raise ValueError('Malformed loaded coefficient/energy/occupation dimensions.')
    if any(s.lower() != 'alpha' for s in spins) or mol.spin != 0:
        raise ValueError('Only closed-shell orbitals are supported.')
    if not np.all(np.isclose(occupations, 0, atol=1e-6, rtol=0) |
                  np.isclose(occupations, 2, atol=1e-6, rtol=0)):
        raise ValueError('Fractional/open-shell occupations are unsupported.')
    occupied = np.flatnonzero(occupations > 1)
    virtual = np.flatnonzero(occupations < 1)
    if not len(occupied) or not len(virtual) or np.any(np.diff(energies) < -1e-10):
        raise ValueError('Missing or unordered occupied/virtual orbitals.')
    homo = int(occupied[-1])
    lumo = int(virtual[0])
    if lumo != homo + 1 or not np.array_equal(occupied, np.arange(homo + 1)):
        raise ValueError('Unsupported noncontiguous frontier orbital indices.')
    for index in (homo, lumo):
        neighbors = np.delete(energies, index)
        if np.any(np.abs(neighbors - energies[index]) < 1e-5):
            raise ValueError('A degenerate frontier orbital is unsupported.')
    for name, index in (('homo', homo), ('lumo', lumo)):
        if type(reference.get(name + '_index')) is not int or reference[name + '_index'] != index + 1:
            raise ValueError(f'{name.upper()} index disagrees with 1-based xTB stdout.')
        expected = reference.get(name + '_ev')
        if (not isinstance(expected, (int, float)) or not math.isfinite(expected)
                or abs(energies[index] * EH_TO_EV - expected) > ENERGY_TOLERANCE_EV):
            raise ValueError(f'{name.upper()} energy disagrees with reference by more than 0.02 eV.')
    xyz = reference.get('evidence', {}).get('xyz', reference.get('xyz'))
    if not isinstance(xyz, str):
        raise ValueError('Reference XYZ geometry is required.')
    xyz_lines = xyz.strip().splitlines()
    if len(xyz_lines) < 3 or int(xyz_lines[0]) != mol.natm or len(xyz_lines) != mol.natm + 2:
        raise ValueError('Reference atom count disagrees with Molden.')
    coordinates = []
    for index, line in enumerate(xyz_lines[2:]):
        fields = line.split()
        raw = parsed['atom_lines'][index].split()
        if (len(fields) != 4 or len(raw) != 6 or fields[0] != mol.atom_pure_symbol(index)
                or int(raw[1]) != index + 1 or int(raw[2]) != mol.atom_charge(index)):
            raise ValueError('Reference atom identities/order disagree with Molden.')
        coordinates.append([float(v) for v in fields[1:]])
    coordinates = np.asarray(coordinates)
    if not np.isfinite(coordinates).all() or not np.allclose(
            coordinates, mol.atom_coords(unit='Angstrom'), atol=1e-5, rtol=0):
        raise ValueError('Molden coordinates disagree with reference XYZ (Angstrom).')
    nuclear = sum(int(mol.atom_charge(i)) for i in range(mol.natm))
    if model == 'all-electron':
        expected_electrons = nuclear - charge
    elif model == 'xtb-valence':
        try:
            expected_electrons = sum(VALENCE[int(mol.atom_charge(i))] for i in range(mol.natm)) - charge
        except KeyError as exc:
            raise ValueError('Unsupported xTB core/valence convention for this element.') from exc
    else:
        raise ValueError('Unsupported occupation model.')
    occupation_total = float(occupations.sum())
    if abs(occupation_total - expected_electrons) > 1e-5:
        raise ValueError('Valence occupation total disagrees with reference charge/state.')
    if reference.get('electron_count', nuclear - charge) != nuclear - charge:
        raise ValueError('Full electron count disagrees with reference atoms/charge.')
    # molden.load defaults to a neutral Mole; its nelectron is NOT the xTB
    # occupation count. No SCF or density evaluation uses that default here.
    overlap = mol.intor('int1e_ovlp')
    frontier = coefficients[:, [homo, lumo]]
    gram = frontier.T @ overlap @ frontier
    if not np.isfinite(gram).all() or not np.allclose(gram, np.eye(2), atol=1e-3, rtol=0):
        raise ValueError(f'Orbital normalization/orthogonality check failed: C.T*S*C={gram.tolist()}')
    all_gram = coefficients.T @ overlap @ coefficients
    maximum_norm_error = float(np.max(np.abs(all_gram - np.eye(nmo))))
    if not math.isfinite(maximum_norm_error) or maximum_norm_error > 1e-3:
        raise ValueError('Full captured orbital normalization/orthogonality check failed.')
    # Keep coefficients unchanged: no ad hoc renormalization can repair a wrong
    # primitive convention or spherical/cartesian mapping.
    bohr_coordinates = mol.atom_coords()
    dimensions = np.clip(np.ceil((np.ptp(bohr_coordinates, axis=0) + 8) / 0.35).astype(int) + 1, 24, 80)
    cube = cubegen.Cube(mol, nx=int(dimensions[0]), ny=int(dimensions[1]), nz=int(dimensions[2]), margin=4.0)
    grid = cube.get_coords()
    values = np.empty((len(grid), 2))
    for start in range(0, len(grid), 2048):
        ao = mol.eval_gto('GTOval_cart' if mol.cart else 'GTOval_sph', grid[start:start + 2048])
        values[start:start + 2048] = ao @ frontier
    stats = {}
    for column, name in enumerate(('homo', 'lumo')):
        field = values[:, column]
        if not np.isfinite(field).all() or field.min() >= -1e-6 or field.max() <= 1e-6:
            raise ValueError(f'{name.upper()} grid is empty, non-finite, or lacks both orbital phases.')
        stats[name] = {'minimum': float(field.min()), 'maximum': float(field.max())}
    with tempfile.TemporaryDirectory(prefix='.orbital-', dir=output_dir) as staged:
        for column, name in enumerate(('homo', 'lumo')):
            destination = Path(staged) / (name + '.cube')
            cube.write(values[:, column].reshape(tuple(dimensions)), str(destination),
                       comment=f'Captured orbital {name.upper()}; amplitude, coordinates in Bohr')
            os.replace(destination, output_dir / destination.name)
    return {'status': 'verified', 'homo_cube': 'homo.cube', 'lumo_cube': 'lumo.cube',
            'homo_index': homo, 'lumo_index': lumo,
            'homo_ev': float(energies[homo] * EH_TO_EV), 'lumo_ev': float(energies[lumo] * EH_TO_EV),
            'energy_tolerance_ev': ENERGY_TOLERANCE_EV, 'coordinate_tolerance_angstrom': 1e-5,
            'valence_electron_count': int(round(occupation_total)), 'full_electron_count': nuclear - charge,
            'occupation_model': model, 'charge': charge, 'unpaired_electrons': 0,
            'grid_dimensions': dimensions.tolist(), 'grid_units': 'Bohr',
            'field_kind': 'signed orbital amplitude', 'grid_statistics': stats,
            'normalization_matrix': gram.tolist(), 'normalization_tolerance': 1e-3,
            'maximum_orthonormality_error': maximum_norm_error,
            'basis_convention': ('xTB primitive normalization removed before PySCF basis construction'
                                 if model == 'xtb-valence' else 'standard Molden normalized primitives'),
            'surface_representation': 'Exported Gaussian basis and captured MO coefficients',
            'pyscf_version': pyscf.__version__,
            'method': 'Captured Molden coefficients evaluated with PySCF; no replacement SCF',
            'checks': ['complete finite coefficients', 'closed-shell occupations',
                       'reference atom identities and geometry', 'charge and valence occupation',
                       'stdout frontier indices', 'nondegenerate frontier', 'orbital energies within 0.02 eV',
                       'C.T*S*C normalization and orthogonality', 'finite signed nonempty bounded cube grid']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--molden', required=True)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    try:
        limit_resources()
        if Path(args.reference).stat().st_size > 64 * 1024 * 1024:
            raise ValueError('Reference JSON exceeds the 64 MiB limit.')
        reference = json.loads(Path(args.reference).read_text(encoding='utf-8-sig'))
    except Exception as exc:
        output = Path(args.output_dir)
        output.mkdir(parents=True, exist_ok=True)
        result = {'status': 'error', 'error': f'Cannot initialize worker/reference: {exc}'}
        (output / 'manifest.json').write_text(json.dumps(result), encoding='utf-8')
    else:
        result = convert(args.molden, reference, args.output_dir)
    print(json.dumps(result))
    return 0 if result['status'] == 'verified' else 1


if __name__ == '__main__':
    raise SystemExit(main())
