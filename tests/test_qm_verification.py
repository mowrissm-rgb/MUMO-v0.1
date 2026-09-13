import importlib.util
import pathlib
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('qm_under_test', pathlib.Path(__file__).parents[1] / 'src/agents/qm_analyst.py')
qm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qm)
GOOD = ' 1 2.000 -0.400000 -10.8846 (HOMO)\n 2 -0.100000 -2.7211 (LUMO)\n HL-Gap 0.300000 Eh 8.1635 eV\n TOTAL ENERGY -5.0 Eh\n normal termination of xtb\n'

class ExecutionTests(unittest.TestCase):
    def run_output(self, output=GOOD, code=0):
        # Only external engine and RDKit preparation are substituted here.
        with patch.object(qm, 'xtb_path', return_value='xtb'), patch.object(qm, 'prepare_xyz', return_value=('2\nfixture\nH 0 0 0\nH 0 0 0.74\n', 2)), patch.object(qm, '_electronic_state', return_value={'charge': 0, 'unpaired_electrons': 0, 'canonical_smiles': '[H][H]'}, create=True), patch.object(qm.subprocess, 'run', return_value=subprocess.CompletedProcess([], code, output, '')):
            return qm.orbitals('[H][H]')

    def test_failed_process_cannot_publish_parsed_numbers(self):
        result = self.run_output(code=1)
        self.assertIn('_error', result)
        self.assertNotIn('homo_ev', result)

    def test_missing_termination_is_not_verified(self):
        self.assertIn('_error', self.run_output(GOOD.replace('normal termination of xtb', '')))

    def test_nonconvergence_is_failure_even_with_numbers(self):
        self.assertIn('_error', self.run_output(GOOD + 'SCC NOT CONVERGED'))

    def test_inconsistent_gap_rejected(self):
        self.assertIn('_error', self.run_output(GOOD.replace('8.1635 eV', '2.0000 eV')))

    def test_invalid_optional_energy_is_not_silently_omitted(self):
        self.assertIn('_error', self.run_output(GOOD.replace('-5.0 Eh', 'NaN Eh')))

    def test_orbital_diagram_includes_virtual_lumo(self):
        levels = self.run_output()['levels']
        self.assertEqual([level['label'] for level in levels], ['HOMO', 'LUMO'])

    def test_gap_hartree_units_are_checked(self):
        self.assertIn('_error', self.run_output(GOOD.replace('0.300000 Eh', '0.900000 Eh')))

    def test_success_preserves_evidence_and_prediction_status(self):
        result = self.run_output()
        self.assertEqual(result.get('status'), 'verified')
        self.assertEqual(result['evidence']['stdout'], GOOD)
        self.assertIn('--sp', result['evidence']['command'])
        self.assertEqual(result['charge'], 0)
        self.assertEqual(result['result_kind'], 'prediction')

    def test_interpretation_distinguishes_orbital_gap_from_measurement(self):
        interpretation = self.run_output()['interpretation']
        self.assertIn('prediction', interpretation)
        self.assertIn('excitation', interpretation)
        self.assertNotIn('relatively inert', interpretation)

@unittest.skipUnless(importlib.util.find_spec('rdkit'), 'RDKit unavailable')
class ChemistryTests(unittest.TestCase):
    def test_charge_inferred_and_mismatch_rejected(self):
        self.assertEqual(qm._electronic_state('[NH4+]', None, None)['charge'], 1)
        with self.assertRaises(ValueError):
            qm._electronic_state('[NH4+]', 0, None)

    def test_radical_requires_explicit_spin_and_parity(self):
        with self.assertRaises(ValueError):
            qm._electronic_state('[CH3]', None, None)
        with self.assertRaises(ValueError):
            qm._electronic_state('[CH3]', None, 0)
        self.assertEqual(qm._electronic_state('[CH3]', None, 1)['unpaired_electrons'], 1)

    def test_nonconverged_mmff_is_not_optimized_geometry(self):
        with patch('rdkit.Chem.AllChem.MMFFOptimizeMolecule', return_value=1):
            with self.assertRaises(ValueError):
                qm.prepare_xyz('CCO')

if __name__ == '__main__':
    unittest.main()
