"""Orbital provenance and conversion contracts; no invented scientific fixtures."""
import hashlib
import importlib.util
import json
import pathlib
import os
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('orbital_qm', ROOT / 'src/agents/qm_analyst.py')
qm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qm)
GOOD = (' 1 2.000 -0.400000 -10.8846 (HOMO)\n'
        ' 2 -0.100000 -2.7211 (LUMO)\n'
        ' HL-Gap 0.300000 Eh 8.1635 eV\n normal termination of xtb\n')
XYZ = '2\nfixture\nH 0 0 0\nH 0 0 0.74\n'


class CaptureTests(unittest.TestCase):
    def capture(self, molden=None, output=GOOD):
        def engine(cmd, cwd, **kwargs):
            # Only the external engine is replaced. File capture remains real.
            self.assertIn('--molden', cmd)
            if molden is not None:
                pathlib.Path(cwd, 'molden.input').write_bytes(molden)
            return subprocess.CompletedProcess(cmd, 0, output, '')
        with patch.object(qm, 'xtb_path', return_value='xtb'), \
                patch.object(qm, 'prepare_xyz', return_value=(XYZ, 2)), \
                patch.object(qm, '_electronic_state', return_value={
                    'charge': 0, 'unpaired_electrons': 0, 'electron_count': 2}), \
                patch.object(qm.subprocess, 'run', side_effect=engine):
            return qm.orbitals('[H][H]')

    def test_missing_export_keeps_verified_energies(self):
        # Removing --molden or treating export absence as numerical failure breaks this.
        result = self.capture()
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(result['surface_status'], 'unavailable')
        self.assertTrue(result['surface_error'])
        self.assertEqual(result['homo_index'], 1)  # stdout is 1-based

    def test_export_survives_temporary_directory_with_byte_hash(self):
        data = b'[Molden Format]\r\n[MO]\r\n'
        result = self.capture(data)
        self.assertEqual(result.get('surface_status'), 'captured')
        self.assertEqual(result['molden'], data.decode('utf-8'))
        self.assertEqual(result['molden_sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(result['lumo_index'], 2)

    def test_export_does_not_override_failed_engine(self):
        result = self.capture(b'[Molden Format]\n', GOOD.replace('normal termination of xtb', ''))
        self.assertIn('_error', result)
        self.assertNotEqual(result.get('status'), 'verified')

    def test_empty_export_is_unavailable(self):
        self.assertEqual(self.capture(b'').get('surface_status'), 'unavailable')


class WorkerFailureTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'linux', 'Linux isolated worker resource limits')
    def test_isolated_process_enforces_memory_cpu_and_threads(self):
        # Removing kernel limits or honoring oversubscribed thread settings breaks this.
        code = ("import importlib.util,resource,json,os; "
                f"s=importlib.util.spec_from_file_location('w',{str(ROOT / 'src/orbital_worker.py')!r}); "
                "w=importlib.util.module_from_spec(s); s.loader.exec_module(w); "
                "w.limit_resources(); "
                "print(json.dumps([resource.getrlimit(resource.RLIMIT_AS),"
                "resource.getrlimit(resource.RLIMIT_CPU),os.environ['OMP_NUM_THREADS']]))")
        process = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                                 env=dict(os.environ, OMP_NUM_THREADS='99'))
        self.assertEqual(process.returncode, 0, process.stderr)
        memory, cpu, threads = json.loads(process.stdout)
        self.assertLessEqual(memory[0], 2 * 1024 ** 3)
        self.assertLessEqual(cpu[0], 180)
        self.assertEqual(threads, '1')

    def run_worker(self, reference, molden='[Molden Format]\n[MO]\n'):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / 'reference.json').write_text(json.dumps(reference), encoding='utf-8')
            (root / 'input.molden').write_text(molden, encoding='utf-8')
            process = subprocess.run([sys.executable, str(ROOT / 'src/orbital_worker.py'),
                                      '--molden', str(root / 'input.molden'),
                                      '--reference', str(root / 'reference.json'),
                                      '--output-dir', str(root / 'out')], capture_output=True, text=True)
            manifest = root / 'out/manifest.json'
            self.assertTrue(manifest.exists(), process.stderr)
            result = json.loads(manifest.read_text())
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(result['status'], 'error')
            self.assertNotIn('homo_cube', result)
            self.assertFalse(list((root / 'out').glob('*.cube')))
            return result

    def test_open_shell_returns_error_json_without_native_import(self):
        self.assertIn('closed-shell', self.run_worker({'unpaired_electrons': 1})['error'])

    def test_unverified_reference_is_not_accepted(self):
        self.assertIn('verified', self.run_worker({'unpaired_electrons': 0})['error'])

    def test_malformed_coefficients_rejected_before_native_loading(self):
        # Sparse/missing MO data must not become PySCF zero-filled success.
        text = ('[Molden Format]\n[Atoms] Angs\nH 1 1 0 0 0\n[GTO]\n1 0\n'
                's 1 1.0\n1.0 1.0\n[MO]\nSym= A\nEne= -0.4\nSpin= Alpha\nOccup= 2\n')
        result = self.run_worker({'status': 'verified', 'unpaired_electrons': 0}, text)
        self.assertIn('coefficient', result['error'])


class WorkerNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if importlib.util.find_spec('pyscf') is None:
            raise unittest.SkipTest('PySCF unavailable; Linux runtime is managed by parent')
        from pyscf import gto, scf, lib
        from pyscf.tools import molden
        lib.num_threads(1)
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = pathlib.Path(cls.directory.name)
        # An actual RHF water wavefunction is a loader/evaluation fixture, not xTB evidence.
        mol = gto.M(atom='O 0 0 0; H 0 -0.757 0.587; H 0 0.757 0.587', basis='sto-3g', verbose=0)
        mf = scf.RHF(mol).run(conv_tol=1e-12)
        assert mf.converged
        molden.from_scf(mf, str(cls.root / 'water.molden'))
        cls.text = (cls.root / 'water.molden').read_text()
        cls.reference = {'status': 'verified', 'charge': 0, 'unpaired_electrons': 0,
                         'electron_count': 10, 'homo_index': 5, 'lumo_index': 6,
                         'homo_ev': float(mf.mo_energy[4] * 27.211386245988),
                         'lumo_ev': float(mf.mo_energy[5] * 27.211386245988),
                         'occupation_model': 'all-electron',
                         'evidence': {'xyz': '3\nRHF fixture\nO 0 0 0\nH 0 -0.757 0.587\nH 0 0.757 0.587\n'}}
        spec = importlib.util.spec_from_file_location('orbital_worker_test', ROOT / 'src/orbital_worker.py')
        cls.worker = importlib.util.module_from_spec(spec)
        if spec.loader is not None and (ROOT / 'src/orbital_worker.py').exists():
            spec.loader.exec_module(cls.worker)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def convert(self, ref=None, text=None):
        root = pathlib.Path(tempfile.mkdtemp(dir=self.root))
        self.addCleanup(__import__('shutil').rmtree, root)
        (root / 'input.molden').write_text(self.text if text is None else text)
        reference = dict(self.reference if ref is None else ref)
        reference['molden_sha256'] = hashlib.sha256((root / 'input.molden').read_bytes()).hexdigest()
        self.assertTrue(hasattr(self.worker, 'convert'), 'Conversion interface missing')
        return self.worker.convert(root / 'input.molden', reference, root / 'out'), root / 'out'

    def test_actual_wavefunction_produces_signed_cubes(self):
        # Empty placeholders, swapped indices, squared orbitals, or wrong units break this.
        result, out = self.convert()
        self.assertEqual(result['status'], 'verified')
        self.assertEqual((result['homo_index'], result['lumo_index']), (4, 5))
        self.assertEqual(result['energy_tolerance_ev'], 0.02)
        for key in ('homo_cube', 'lumo_cube'):
            lines = (out / result[key]).read_text().splitlines()
            natoms = abs(int(lines[2].split()[0]))
            dims = [int(lines[i].split()[0]) for i in (3, 4, 5)]
            values = [float(v) for line in lines[6 + natoms:] for v in line.split()]
            self.assertEqual(len(values), dims[0] * dims[1] * dims[2])
            self.assertLess(min(values), -1e-6)
            self.assertGreater(max(values), 1e-6)
            self.assertLessEqual(max(dims), 80)

    def test_wrong_geometry_rejected(self):
        ref = dict(self.reference, evidence={'xyz': self.reference['evidence']['xyz'].replace('-0.757', '-0.857')})
        result, out = self.convert(ref)
        self.assertEqual(result['status'], 'error')
        self.assertIn('coordinates', result['error'])
        self.assertFalse(list(out.glob('*.cube')))

    def test_wrong_atom_identity_rejected(self):
        ref = dict(self.reference, evidence={'xyz': self.reference['evidence']['xyz'].replace('O 0', 'N 0')})
        self.assertIn('atom', self.convert(ref)[0]['error'])

    def test_energy_disagreement_rejected(self):
        self.assertIn('energy', self.convert(dict(self.reference, homo_ev=self.reference['homo_ev'] + 0.021))[0]['error'])

    def test_malformed_coefficient_cannot_be_zero_filled(self):
        import re
        prefix, mos = self.text.split('[MO]', 1)
        broken = prefix + '[MO]' + re.sub(r'\n\s*1\s+[-+\d.eE]+\s*\n', '\n', mos, count=1)
        self.assertNotEqual(broken, self.text)
        self.assertIn('coefficient', self.convert(text=broken)[0]['error'])

    def test_reference_stdout_index_must_match(self):
        self.assertIn('index', self.convert(dict(self.reference, homo_index=4))[0]['error'])

    def test_degenerate_frontier_is_explicitly_unsupported(self):
        import re
        energies = re.findall(r'Ene=\s*([-+\d.eE]+)', self.text)
        text = self.text.replace('Ene= ' + energies[3], 'Ene= ' + energies[4])
        # Whitespace formatting belongs to the writer, so replace the exact matched span.
        matches = list(re.finditer(r'Ene=\s*([-+\d.eE]+)', self.text))
        text = self.text[:matches[3].start(1)] + energies[4] + self.text[matches[3].end(1):]
        self.assertIn('degenerate', self.convert(text=text)[0]['error'])

    def test_wrong_charge_and_valence_count_rejected(self):
        self.assertIn('occupation', self.convert(dict(self.reference, charge=2))[0]['error'])

    def test_missing_molden_is_error_json(self):
        result = self.worker.convert(self.root / 'absent', self.reference, self.root / 'missing-out')
        self.assertEqual(result['status'], 'error')
        self.assertTrue((self.root / 'missing-out/manifest.json').exists())

    def test_charged_closed_shell_uses_reference_not_loader_neutral_default(self):
        from pyscf import gto, scf
        from pyscf.tools import molden
        # Real closed-shell H3+ has odd nuclear count. Neutral Molden fallback spin=1
        # is a reader default, not evidence that this captured state is open-shell.
        mol = gto.M(atom='H 0 0 0; H 0 0 1.2; H 0.2 1.5 0.3', basis='sto-3g', charge=1, spin=0, verbose=0)
        mf = scf.RHF(mol).run(conv_tol=1e-12)
        self.assertTrue(mf.converged)
        path = self.root / 'h3-plus.molden'
        molden.from_scf(mf, str(path))
        ref = {'status': 'verified', 'charge': 1, 'unpaired_electrons': 0,
               'electron_count': 2, 'occupation_model': 'all-electron',
               'homo_index': 1, 'lumo_index': 2,
               'homo_ev': float(mf.mo_energy[0] * 27.211386245988),
               'lumo_ev': float(mf.mo_energy[1] * 27.211386245988),
               'evidence': {'xyz': '3\nH3+ fixture\nH 0 0 0\nH 0 0 1.2\nH 0.2 1.5 0.3\n'}}
        result, _ = self.convert(ref, path.read_text())
        # Its nodeless HOMO cannot satisfy the explicitly signed-grid contract;
        # conversion must reach that check, not misdiagnose the charge as spin.
        self.assertEqual(result['status'], 'error')
        self.assertIn('lacks both orbital phases', result['error'])

    def test_real_xtb_fixture_if_parent_provides_it(self):
        # Parent supplies the unchanged capture result and exported Molden from real xTB.
        fixture = os.environ.get('MUMO_ORBITAL_FIXTURE')
        if not fixture:
            self.skipTest('Parent real xTB fixture not supplied')
        reference = json.loads(pathlib.Path(fixture, 'reference.json').read_text())
        output = self.root / 'real-xtb-out'
        process = subprocess.run([sys.executable, str(ROOT / 'src/orbital_worker.py'),
                                  '--molden', str(pathlib.Path(fixture, 'molden.input')),
                                  '--reference', str(pathlib.Path(fixture, 'reference.json')),
                                  '--output-dir', str(output)], capture_output=True, text=True, timeout=190)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        result = json.loads((output / 'manifest.json').read_text())
        self.assertEqual(result['status'], 'verified', result)
        self.assertEqual(result['valence_electron_count'], 2 * reference['homo_index'])
        self.assertGreater(reference['electron_count'], result['valence_electron_count'])
        self.assertLess(result['maximum_orthonormality_error'], 1e-6)
        for name in ('homo', 'lumo'):
            self.assertLess(result['grid_statistics'][name]['minimum'], -1e-6)
            self.assertGreater(result['grid_statistics'][name]['maximum'], 1e-6)
