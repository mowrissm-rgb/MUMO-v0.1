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
