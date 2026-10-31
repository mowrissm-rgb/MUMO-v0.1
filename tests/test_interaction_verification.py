import importlib.util
from pathlib import Path
import unittest
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('interaction_analyst', Path(__file__).parents[1] / 'src/agents/interaction_analyst.py')
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)

class InteractionVerification(unittest.TestCase):
    def test_unavailable_is_not_no_contacts(self):
        result = agent._empty_result('missing dependency')
        self.assertIsNone(result['n_hbonds'])
        self.assertEqual(result['status'], 'unavailable')

    def test_missing_global_atom_mapping_is_rejected(self):
        residue = SimpleNamespace(chain='A', name='SER', number=195)
        # A residue-local index cannot safely address the protein conformer.
        class Residue:
            chain='A'; name='SER'; number=195
        ifp = {(None, Residue()): {'HBDonor': [{'indices': {'ligand': [0], 'protein': [0]}}]}}
        with self.assertRaises(ValueError):
            agent._collect_interactions(ifp, None, None)

    def test_distance_only_contacts_never_become_hbonds(self):
        self.assertEqual(agent._geometric_hbonds(None, [], []), [])

if __name__ == '__main__':
    unittest.main()

class PreparedExport(unittest.TestCase):
    def test_export_api_exists(self):
        self.assertTrue(callable(getattr(agent, '_export_prepared', None)))

@unittest.skipUnless(agent.INTERACTIONS_AVAILABLE, 'RDKit and ProLIF required')
class ChemicalFixtures(unittest.TestCase):
    def test_export_preserves_explicit_hydrogens_charge_and_bonds(self):
        import tempfile
        from rdkit import Chem
        from rdkit.Chem import AllChem
        ligand = Chem.AddHs(Chem.MolFromSmiles('C[NH3+]'))
        protein = Chem.AddHs(Chem.MolFromSmiles('CC(=O)[O-]'))
        AllChem.EmbedMolecule(ligand, randomSeed=7)
        AllChem.EmbedMolecule(protein, randomSeed=8)
        with tempfile.TemporaryDirectory() as directory:
            lig, prot, files = agent._export_prepared(ligand, protein, str(Path(directory)/'complex.pdb'))
            self.assertEqual(lig.GetNumAtoms(), 8)
            self.assertEqual(Chem.GetFormalCharge(lig), 1)
            self.assertEqual(Chem.GetFormalCharge(prot), -1)
            self.assertTrue(any(b.GetBondTypeAsDouble() == 2 for b in prot.GetBonds()))
            self.assertTrue(all(Path(a['path']).exists() for a in files.values()))

    def test_export_accepts_ligands_with_unspecified_stereo(self):
        # Found by the Pose-interactions validation. A SMILES with an unlabelled stereocentre or
        # double bond gives a pose with no stereo flags; the SDF reload perceives stereo from the
        # 3D coordinates, and the export check used to call that a chemical change.
        import tempfile
        from rdkit import Chem
        from rdkit.Chem import AllChem
        protein = Chem.AddHs(Chem.MolFromSmiles('CC(=O)[O-]'))
        AllChem.EmbedMolecule(protein, randomSeed=8)
        for smiles in ('CC(C)Cc1ccc(cc1)C(C)C(=O)O',                    # unlabelled stereocentre
                       'CCC(=C(c1ccccc1)c1ccc(O)cc1)c1ccccc1'):         # unlabelled double bond
            ligand = Chem.AddHs(Chem.MolFromSmiles(smiles))
            AllChem.EmbedMolecule(ligand, randomSeed=7)
            self.assertTrue(all(int(a.GetChiralTag()) == 0 for a in ligand.GetAtoms()), smiles)
            with tempfile.TemporaryDirectory() as directory:
                lig, _prot, files = agent._export_prepared(ligand, protein, str(Path(directory)/'complex.pdb'))
                self.assertEqual(lig.GetNumAtoms(), ligand.GetNumAtoms(), smiles)

    def _methanol_and_acceptor(self, distance=2.7):
        """Methanol (donor) and formaldehyde (acceptor) with the acceptor 2.7 A from the hydroxyl
        oxygen, perpendicular to the C-O bond and on the side OPPOSITE to where the hydrogen now
        points: reachable by turning the hydroxyl, but wrong as built."""
        import numpy as np
        from rdkit import Chem
        from rdkit.Chem import AllChem
        from rdkit.Geometry import Point3D
        ligand = Chem.AddHs(Chem.MolFromSmiles('CO'))
        AllChem.EmbedMolecule(ligand, randomSeed=5)
        acceptor = Chem.AddHs(Chem.MolFromSmiles('C=O'))
        AllChem.EmbedMolecule(acceptor, randomSeed=6)
        lc, ac = ligand.GetConformer(), acceptor.GetConformer()
        o = next(a for a in ligand.GetAtoms() if a.GetSymbol() == 'O')
        h = next(n for n in o.GetNeighbors() if n.GetAtomicNum() == 1)
        c = next(n for n in o.GetNeighbors() if n.GetAtomicNum() == 6)
        po, ph = np.array(lc.GetAtomPosition(o.GetIdx())), np.array(lc.GetAtomPosition(h.GetIdx()))
        axis = po - np.array(lc.GetAtomPosition(c.GetIdx()))
        axis = axis / np.linalg.norm(axis)
        h_vec = ph - po
        h_perp = h_vec - np.dot(h_vec, axis) * axis
        away = -h_perp / np.linalg.norm(h_perp)
        ao = next(a for a in acceptor.GetAtoms() if a.GetSymbol() == 'O').GetIdx()
        shift = (po + distance * away) - np.array(ac.GetAtomPosition(ao))
        for i in range(acceptor.GetNumAtoms()):
            ac.SetAtomPosition(i, Point3D(*(np.array(ac.GetAtomPosition(i)) + shift)))
        return ligand, acceptor, o.GetIdx(), h.GetIdx(), ao

    @staticmethod
    def _dha_angle(ligand, acceptor, o, h, ao):
        import math
        import numpy as np
        lc, ac = ligand.GetConformer(), acceptor.GetConformer()
        d, hh, a = (np.array(lc.GetAtomPosition(o)), np.array(lc.GetAtomPosition(h)),
                    np.array(ac.GetAtomPosition(ao)))
        u, v = d - hh, a - hh
        return math.degrees(math.acos(float(np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v)))))

    def test_hydroxyl_hydrogen_is_turned_toward_a_nearby_acceptor(self):
        # Found by the Pose-interactions validation: 8 of 11 missed H-bonds were within 3.5 A but
        # the donor hydrogen pointed the wrong way, so ProLIF's angle test rejected them.
        import numpy as np
        ligand, acceptor, o, h, ao = self._methanol_and_acceptor()
        before = self._dha_angle(ligand, acceptor, o, h, ao)
        lc = ligand.GetConformer()
        bond_before = float(np.linalg.norm(np.array(lc.GetAtomPosition(o)) - np.array(lc.GetAtomPosition(h))))
        self.assertLess(before, 100.0)
        self.assertEqual(agent._orient_donor_hydrogens(ligand, acceptor), 1)
        after = self._dha_angle(ligand, acceptor, o, h, ao)
        bond_after = float(np.linalg.norm(np.array(lc.GetAtomPosition(o)) - np.array(lc.GetAtomPosition(h))))
        self.assertGreaterEqual(after, 130.0)               # ProLIF's donor-hydrogen-acceptor minimum
        self.assertAlmostEqual(bond_before, bond_after, places=6)   # bond length untouched

    def test_hydrogens_are_not_moved_when_no_acceptor_is_near(self):
        ligand, acceptor, o, h, ao = self._methanol_and_acceptor(distance=6.0)
        from rdkit.Geometry import Point3D  # noqa: F401
        before = [tuple(ligand.GetConformer().GetAtomPosition(i)) for i in range(ligand.GetNumAtoms())]
        self.assertEqual(agent._orient_donor_hydrogens(ligand, acceptor), 0)
        after = [tuple(ligand.GetConformer().GetAtomPosition(i)) for i in range(ligand.GetNumAtoms())]
        self.assertEqual(before, after)

    def test_planar_nh_is_never_rotated(self):
        from rdkit import Chem
        from rdkit.Chem import AllChem
        mol = Chem.AddHs(Chem.MolFromSmiles('CC(=O)Nc1ccccc1'))      # amide N-H and aniline-type N
        AllChem.EmbedMolecule(mol, randomSeed=3)
        names = {mol.GetAtomWithIdx(d).GetSymbol() for d, _a, _h in agent._rotatable_donor_groups(mol)}
        self.assertNotIn('N', names)

    def test_run_uses_a_copy_of_the_shared_receptor(self):
        source = (Path(__file__).parents[1] / 'src/agents/interaction_analyst.py').read_text(encoding='utf-8')
        self.assertIn('prot_work = Chem.Mol(ctx["prot_mol"])', source)

    def test_acceptor_acceptor_proximity_is_not_hbond(self):
        from rdkit import Chem
        from rdkit.Geometry import Point3D
        mol = Chem.MolFromSmiles('CC=O')
        conf = Chem.Conformer(3)
        for i, xyz in enumerate(((0,0,0),(1,0,0),(2,0,0))): conf.SetAtomPosition(i, Point3D(*xyz))
        mol.AddConformer(conf)
        polar = [{'resn':'ASP','resi':1,'chain':'A','name':'OD1','charge':0,'xyz':(2,2.8,0)}]
        self.assertEqual(agent._geometric_hbonds(mol, polar, []), [])

    def test_prolif_requires_donor_hydrogen_angle(self):
        from rdkit import Chem
        from rdkit.Geometry import Point3D
        import prolif
        def water(points, residue):
            mol = Chem.AddHs(Chem.MolFromSmiles('O'))
            conformer = Chem.Conformer(3)
            for index, xyz in enumerate(points):
                conformer.SetAtomPosition(index, Point3D(*xyz))
                info = Chem.AtomPDBResidueInfo()
                info.SetName(('O' if index == 0 else 'H'+str(index)).rjust(4))
                info.SetResidueName(residue); info.SetResidueNumber(1); info.SetChainId('A')
                mol.GetAtomWithIdx(index).SetMonomerInfo(info)
            mol.AddConformer(conformer)
            return mol
        receptor = water(((2.8,0,0),(3.8,0,0),(2.8,1,0)), 'SER')
        donor = water(((0,0,0),(1,0,0),(0,1,0)), 'LIG')
        fp = prolif.Fingerprint(['HBDonor'], count=True)
        positive = fp.generate(prolif.Molecule.from_rdkit(donor), prolif.Molecule.from_rdkit(receptor), metadata=True)
        records = agent._collect_interactions(positive, donor.GetConformer(), receptor.GetConformer())
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['protein_atom_indices'], [0])
        self.assertAlmostEqual(records[0]['distance'], 2.8)
        donor.GetConformer().SetAtomPosition(1, Point3D(-1,0,0))
        negative = fp.generate(prolif.Molecule.from_rdkit(donor), prolif.Molecule.from_rdkit(receptor), metadata=True)
        self.assertEqual(agent._collect_interactions(negative, donor.GetConformer(), receptor.GetConformer()), [])

    def test_complete_run_uses_saved_artifacts_and_evidence(self):
        import tempfile, json
        from unittest.mock import patch
        from rdkit import Chem
        from rdkit.Chem import AllChem
        ligand = Chem.AddHs(Chem.MolFromSmiles('CCO'))
        receptor = Chem.AddHs(Chem.MolFromSmiles('CC(=O)O'))
        AllChem.EmbedMolecule(ligand, randomSeed=3)
        AllChem.EmbedMolecule(receptor, randomSeed=4)
        for atom in receptor.GetAtoms():
            info = Chem.AtomPDBResidueInfo()
            info.SetName(atom.GetSymbol().rjust(4)); info.SetResidueName('GLU')
            info.SetResidueNumber(7); info.SetChainId('B'); atom.SetMonomerInfo(info)
        with tempfile.TemporaryDirectory() as directory:
            protein_path = str(Path(directory)/'protein.pdb')
            pose_path = str(Path(directory)/'pose.pdbqt')
            Chem.MolToPDBFile(receptor, protein_path)
            Path(pose_path).write_text('decoder boundary fixture')
            ctx = {'prot_mol': receptor, 'source_sha256': agent._sha256(protein_path)}
            with patch.object(agent, '_ligand_mol_from_pose', return_value=ligand):
                result = agent.analyze_interactions(protein_path, pose_path, str(Path(directory)/'complex.pdb'), receptor_ctx=ctx)
            self.assertEqual(result['status'], 'qualified', result.get('note'))
            self.assertEqual(result['total_interactions'], len(result['records']))
            saved = json.loads(Path(result['artifacts']['interaction_evidence']['path']).read_text())
            self.assertTrue(saved['checks']['analysis_uses_reloaded_artifacts'])
            self.assertEqual(len(saved['records']), result['total_interactions'])
