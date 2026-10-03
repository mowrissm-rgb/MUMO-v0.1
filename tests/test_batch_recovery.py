import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import pipeline_core
import auth_store
import docking_jobs
from brain import write_report
from agents.target_analyst import gene_to_uniprot


class BatchRecoveryTests(unittest.TestCase):
    def test_gene_alias_is_resolved_before_query(self):
        class Response:
            def raise_for_status(self): pass
            def json(self): return {'results': [{'primaryAccession': 'P03372'}]}
        with patch('agents.target_analyst.requests.get', return_value=Response()) as get:
            gene_to_uniprot('ER alpha')
        self.assertIn('gene_exact:ESR1', get.call_args.kwargs['params']['query'])

    def test_preparation_failure_keeps_successful_target(self):
        def dock(target, *args, **kwargs):
            if target['gene'] == 'BRCA2':
                raise FileNotFoundError('No AlphaFold model available for P51587.')
            row = {'Ligand': 'aspirin', 'Best affinity (kcal/mol)': -5.1,
                   'Total interactions': None, 'H-bonds': None, 'Hydrophobic': None,
                   'H-bond residues': '-', 'All interacting residues': '-',
                   'Interaction status': 'unavailable', 'Interaction note': 'ProLIF failed'}
            return [row], {}, {'gene': target['gene']}
        with tempfile.TemporaryDirectory() as tmp, patch('pipeline.dock_pipeline', side_effect=dock):
            result = pipeline_core.run_job({'target': ['BRCA2', 'EGFR'],
                'ligand_objs': [{'label': 'aspirin', 'smiles': 'CC(=O)Oc1ccccc1C(=O)O'}]},
                'vina', tmp, tmp)
        self.assertTrue(result['ok'])
        self.assertEqual(result['rows'][0]['Target'], 'EGFR')
        self.assertIn('BRCA2', result['say_text'])
        json.dumps(result, allow_nan=False)

    def test_history_missing_counts_remain_null(self):
        payload = auth_store._merge_runs(None, {'rows': [{'H-bonds': float('nan'), 'score': -5.1}],
                                               'meta': {'sd': float('inf')}})
        json.dumps(payload, allow_nan=False)
        self.assertIsNone(payload['runs'][0]['rows'][0]['H-bonds'])
        self.assertEqual(payload['runs'][0]['rows'][0]['score'], -5.1)

    def test_job_file_is_strict_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'result.json')
            docking_jobs._write_json(path, {'counts': [float('nan'), float('inf'), 0]})
            def invalid(value): raise ValueError(value)
            data = json.loads(Path(path).read_text(), parse_constant=invalid)
        self.assertEqual(data['counts'], [None, None, 0])

    def test_report_explains_missing_interactions(self):
        text = write_report({'affinity': -6, 'n_hbonds': float('nan'),
            'interaction_note': 'Receptor preparation failed', 'interaction_status': 'unavailable'})
        self.assertNotIn('nan', text)
        self.assertIn('Receptor preparation failed', text)

    def test_multiple_explicit_pdb_ids_in_one_target_string(self):
        from target_names import split_targets
        self.assertEqual(split_targets('Thrombin 1A46 Factor Xa 2P16 Plasmin 4DUH'),
                         ['1A46', '2P16', '4DUH'])

    def test_expected_ph_state_is_accepted_but_other_ligand_rejected(self):
        from rdkit import Chem
        from agents import interaction_analyst as ia
        from docking_engine import _mol_from_smiles_at_ph
        neutral = 'CC(=O)Oc1ccccc1C(=O)O'
        docked = _mol_from_smiles_at_ph(neutral)
        self.assertTrue(ia.pose_matches_ligand(docked, neutral))
        self.assertFalse(ia.pose_matches_ligand(docked, 'CCO'))

    def test_explicit_protein_hydrogens_are_not_counted_twice(self):
        from rdkit import Chem
        from rdkit.Chem import AllChem
        from agents.interaction_analyst import _protonate_protein
        mol = Chem.AddHs(Chem.MolFromSmiles('NC(=[NH2+])N'))
        AllChem.EmbedMolecule(mol, randomSeed=1)
        for atom in mol.GetAtoms():
            info = Chem.AtomPDBResidueInfo()
            info.SetResidueName('ARG'); info.SetResidueNumber(1); info.SetChainId('A')
            info.SetName(' NH2' if atom.GetFormalCharge() == 1 else f'{atom.GetSymbol()}{atom.GetIdx():03}'[:4])
            atom.SetMonomerInfo(info)
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'arginine.pdb')
            Chem.MolToPDBFile(mol, path)
            prepared = _protonate_protein(path)
        self.assertEqual(Chem.GetFormalCharge(prepared), 1)
        nitrogen = next(a for a in prepared.GetAtoms() if a.GetPDBResidueInfo().GetName().strip() == 'NH2')
        self.assertEqual(sum(a.GetAtomicNum() == 1 for a in nitrogen.GetNeighbors()), 2)

    def test_drug_site_is_selected_instead_of_heme_cofactor(self):
        from agents.target_analyst import auto_grid_from_pdb
        atoms = []
        for resn, count, x in [('HEM', 5, 100.0), ('NAG', 4, 90.0), ('ABC', 3, 0.0)]:
            for i in range(count):
                atoms.append(f'HETATM{len(atoms)+1:5d}  C1  {resn} A{1 if resn == "HEM" else 2:4d}    '
                             f'{x+i:8.3f}{0:8.3f}{0:8.3f}  1.00 20.00           C\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'cofactor.pdb'
            path.write_text(''.join(atoms))
            center, _, source = auto_grid_from_pdb(path)
        self.assertEqual(center, (1.0, 0.0, 0.0))
        self.assertIn('ABC', source)

    def test_export_verifies_graph_without_whole_protein_canonicalization(self):
        from rdkit import Chem
        from rdkit.Chem import AllChem
        from agents import interaction_analyst as ia
        mol = Chem.AddHs(Chem.MolFromSmiles('C[C@H](O)F'))
        AllChem.EmbedMolecule(mol, randomSeed=7)
        with tempfile.TemporaryDirectory() as tmp, patch.object(Chem, 'MolToSmiles',
                side_effect=RuntimeError('Whole protein canonicalization must not be required')):
            ligand, protein, artifacts = ia._export_prepared(mol, mol, str(Path(tmp) / 'complex.pdb'))
        self.assertEqual(ligand.GetNumAtoms(), 9)
        self.assertEqual(protein.GetNumAtoms(), 9)
        self.assertIn('protein_sdf', artifacts)

    def test_fast_residue_split_preserves_global_atom_indices(self):
        from rdkit import Chem
        from rdkit.Chem import AllChem
        from agents import interaction_analyst as ia
        mol = Chem.AddHs(Chem.MolFromSmiles('CCO'))
        AllChem.EmbedMolecule(mol, randomSeed=7)
        for atom in mol.GetAtoms():
            owner = atom.GetNeighbors()[0].GetIdx() if atom.GetAtomicNum() == 1 else atom.GetIdx()
            info = Chem.AtomPDBResidueInfo()
            info.SetName(atom.GetSymbol().rjust(4)); info.SetChainId('A')
            info.SetResidueName('ALA' if owner == 0 else 'SER')
            info.SetResidueNumber(1 if owner == 0 else 2)
            atom.SetMonomerInfo(info)
        with patch('prolif.molecule.split_mol_by_residues',
                   side_effect=RuntimeError('Slow whole-protein splitter')):
            prepared = ia.prolif_molecule(mol)
        self.assertEqual(prepared.GetNumAtoms(), 9)
        indices = sorted(a.GetUnsignedProp('mapindex') for r in prepared.residues.values()
                         for a in r.GetAtoms())
        self.assertEqual(indices, list(range(9)))


if __name__ == '__main__':
    unittest.main()
