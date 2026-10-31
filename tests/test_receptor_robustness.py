"""Receptor inputs that used to make the interaction analysis fail outright."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from agents import interaction_analyst as ia

# Arg36 of PDB 2B54 as deposited: its hydrogens sit at impossible distances (HE is 1.5 A from CZ),
# so RDKit bonds them and the residue ends up with five bonds on one atom.
ARG_WITH_BAD_HYDROGENS = '''\
ATOM    347  N   ARG A  36     117.528 -80.655 108.069  1.00 65.52           N
ATOM    348  CA  ARG A  36     117.493 -79.309 108.647  1.00 77.00           C
ATOM    349  C   ARG A  36     117.245 -79.337 110.124  1.00 83.39           C
ATOM    350  O   ARG A  36     116.467 -80.149 110.604  1.00 84.85           O
ATOM    351  CB  ARG A  36     116.455 -78.403 107.953  1.00 79.14           C
ATOM    352  CG  ARG A  36     115.075 -78.144 108.617  1.00 84.65           C
ATOM    353  CD  ARG A  36     114.030 -79.279 108.669  1.00 89.84           C
ATOM    354  NE  ARG A  36     113.029 -79.026 109.720  1.00 94.40           N
ATOM    355  CZ  ARG A  36     111.712 -79.298 109.560  1.00 96.05           C
ATOM    356  NH1 ARG A  36     110.891 -79.292 110.612  1.00 96.48           N
ATOM    357  NH2 ARG A  36     111.227 -79.580 108.357  1.00 96.53           N
ATOM    358  H   ARG A  36     117.023 -81.074 107.165  1.00 19.99           H
ATOM    359  HE  ARG A  36     111.751 -77.804 109.654  1.00 19.99           H
ATOM    360 HH11 ARG A  36     110.217 -79.092 110.717  1.00 19.99           H
ATOM    361 HH12 ARG A  36     110.259 -80.817 110.571  1.00 19.99           H
ATOM    362 HH21 ARG A  36     112.962 -80.885 108.363  1.00 19.99           H
ATOM    363 HH22 ARG A  36     111.801 -81.819 109.245  1.00 19.99           H
END
'''

TAG_RESIDUE = '''\
ATOM      1  N   ALA A  -8       0.000   0.000   0.000  1.00 20.00           N
ATOM      2  CA  ALA A  -8       1.458   0.000   0.000  1.00 20.00           C
ATOM      3  C   ALA A  -8       2.009   1.420   0.000  1.00 20.00           C
ATOM      4  O   ALA A  -8       1.251   2.390   0.000  1.00 20.00           O
ATOM      5  CB  ALA A  -8       1.988  -0.773  -1.207  1.00 20.00           C
END
'''


def _write(text):
    handle = tempfile.NamedTemporaryFile('w', suffix='.pdb', delete=False)
    handle.write(text)
    handle.close()
    return handle.name


@unittest.skipUnless(ia.INTERACTIONS_AVAILABLE, 'ProLIF unavailable')
class ReceptorRobustness(unittest.TestCase):
    def test_deposited_hydrogens_at_impossible_distances_do_not_stop_preparation(self):
        mol = ia._protonate_protein(_write(ARG_WITH_BAD_HYDROGENS))
        self.assertIsNotNone(mol)
        cz = next(a for a in mol.GetAtoms() if a.GetPDBResidueInfo().GetName().strip() == 'CZ')
        self.assertEqual(cz.GetDegree(), 3)  # NE, NH1, NH2 only, no stray hydrogen

    def test_a_receptor_that_fails_without_any_hydrogens_still_raises(self):
        heavy = ''.join(l for l in ARG_WITH_BAD_HYDROGENS.splitlines(True) if l[76:78].strip() != 'H')
        overbonded = heavy.replace('111.227 -79.580 108.357', '112.700 -79.300 109.700')  # NH2 on top of NE
        with self.assertRaises(ValueError):
            ia._protonate_protein(_write(overbonded))

    def test_negative_residue_numbers_survive_the_prolif_molecule(self):
        mol = ia._protonate_protein(_write(TAG_RESIDUE))
        offset = ia.residue_number_offset(mol)
        self.assertEqual(offset, 8)
        with self.assertRaises(OverflowError):
            ia.prolif_molecule(mol)  # the failure that used to end the analysis
        shifted = ia.prolif_molecule(mol, offset)
        self.assertEqual([int(r.resid.number) for r in shifted.residues.values()], [0])

    def test_reported_residue_number_is_the_one_in_the_file(self):
        from rdkit import Chem

        class Residue:
            chain = 'A'; name = 'ALA'; number = 0  # as ProLIF saw it after a shift of 8
        conf = Chem.Conformer(1)
        conf.SetAtomPosition(0, (0, 0, 0))
        metadata = {'parent_indices': {'ligand': [0], 'protein': [0]}, 'distance': 2.8}
        records = ia._collect_interactions({('LIG', Residue()): {'HBDonor': [metadata]}}, conf, conf, number_offset=8)
        self.assertEqual(records[0]['resnr'], -8)
        self.assertEqual(records[0]['tag'], 'ALA-8(A)')

    def test_no_offset_when_numbers_are_positive(self):
        mol = ia._protonate_protein(_write(TAG_RESIDUE.replace(' -8', '  8')))
        self.assertEqual(ia.residue_number_offset(mol), 0)


if __name__ == '__main__':
    unittest.main()
