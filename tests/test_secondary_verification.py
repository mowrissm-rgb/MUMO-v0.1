import math
import unittest
from unittest.mock import patch
from src import ramachandran as rama


def peptide(chain_middle='A'):
    rows = []
    coords = [(0, 0, 0), (1, 0, 0), (1, 1, 0),
              (2, 1, 0), (2, 2, 1), (3, 2, 1),
              (3, 3, 1), (4, 3, 2), (5, 3, 2)]
    for i, xyz in enumerate(coords):
        residue = i // 3 + 1
        chain = chain_middle if residue == 2 else 'A'
        rows.append(f'ATOM  {i+1:5d} {("N", "CA", "C")[i%3]:^4s} ALA {chain}{residue:4d}    '
                    f'{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}  1.00 20.00           C')
    return '\n'.join(rows)


class RamaVerification(unittest.TestCase):
    def test_verdict_reports_scoring_coverage_not_structure_trust(self):
        result = rama.compute(peptide())
        verdict = rama.verdict(result)
        self.assertIn('1/3', verdict)
        self.assertIn('unscored', verdict)

    def test_ter_boundary_is_not_bridged(self):
        rows = peptide().splitlines()
        self.assertIn('_error', rama.compute('\n'.join(rows[:3] + ['TER'] + rows[3:])))

    def test_unknown_proline_omega_is_not_assumed_trans(self):
        rows = peptide().splitlines()
        rows = [r for i, r in enumerate(rows) if i != 1]
        rows = [r[:17] + 'PRO' + r[20:] if r[22:26].strip() == '2' else r for r in rows]
        result = rama.compute('\n'.join(rows))
        self.assertIn('_error', result)
        self.assertTrue(any('omega' in r['reason'] for r in result['unscored']))

    def test_does_not_join_close_different_chains(self):
        result = rama.compute(peptide('B'))
        self.assertIn('_error', result)

    def test_invalid_torsion_is_undefined(self):
        self.assertIsNone(rama.dihedral((math.nan, 0, 0), (1, 0, 0), (1, 1, 0), (1, 1, 1)))

    def test_scored_residue_retains_evidence_and_unscored_residues(self):
        result = rama.compute(peptide())
        self.assertEqual(result['n_scored'], 1)
        self.assertEqual(len(result['unscored']), 2)
        self.assertEqual(len(result['_verification']['input_sha256']), 64)
        self.assertEqual(len(result['_verification']['reference_sha256']), 64)
        self.assertEqual(result['points'][0]['coordinates']['CA'], (2., 2., 1.))

    def test_unavailable_reference_returns_explicit_failure(self):
        with patch.object(rama, '_grids', side_effect=OSError('missing reference')):
            result = rama.compute(peptide())
        self.assertIn('_error', result)
        self.assertEqual(result['_verification']['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()

