import sys
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from target_names import canonical_gene
from agents import target_analyst as ta

PDB = ('HEADER    TEST\n'
       'ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00 90.00           C\n'
       'ATOM      2  CA  GLY A   2       4.000   5.000   6.000  1.00 90.00           C\nEND\n')

class Response:
    def __init__(self, data=None, content=b'', status=200):
        self.data, self.content, self.status_code = data, content, status
    def json(self):
        return self.data
    def raise_for_status(self):
        if self.status_code >= 400:
            raise ta.requests.HTTPError(str(self.status_code))

class TargetResolutionTests(unittest.TestCase):
    def test_alphafold_rejects_metadata_for_a_different_protein(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(ta, 'database_get', side_effect=[
                Response([{'uniprotAccession': 'P04637', 'pdbUrl': 'https://alphafold.ebi.ac.uk/files/model.pdb'}]),
                Response(content=PDB.encode())]):
            with self.assertRaisesRegex(ValueError, 'identity'):
                ta.download_alphafold('P05231', tmp)

    def test_linked_processed_chains_and_nearby_ligand_survive_first_model_selection(self):
        protein = PDB.replace(' A   1', ' L   1').replace(' A   2', ' H   2')
        ligand = 'HETATM    3  C1  BEN B   9       2.000   3.000   4.000  1.00 90.00           C\n'
        ensemble = 'MODEL        1\n' + protein + ligand + 'ENDMDL\nMODEL        2\n' + protein.replace('1.000', '9.000') + 'ENDMDL\n'
        def get(url, **kwargs):
            if 'uniprotkb' in url:
                return Response({'uniProtKBCrossReferences': [{'database': 'PDB', 'id': '1ALU',
                                'properties': [{'key': 'Chains', 'value': 'L=1-36, H=37-295'}]}]})
            return Response(content=ensemble.encode())
        with tempfile.TemporaryDirectory() as tmp, patch.object(ta, 'database_get', side_effect=get):
            path, pdb_id, chain = ta.download_linked_pdb('P05231', tmp)
            text = Path(path).read_text()
            self.assertEqual(chain, 'L,H')
            self.assertEqual(sum(line.startswith('ATOM') for line in text.splitlines()), 2)
            self.assertIn(ligand.strip(), text)
            self.assertNotIn('9.000', text)

    def test_il6_common_names_are_the_same_gene(self):
        for name in ['IL-6', 'IL–6', 'interleukin-6', 'IL6']:
            self.assertEqual(canonical_gene(name), 'IL6')

    def test_nfkb_family_requests_are_not_silently_assigned_a_subunit(self):
        for name in ['NF-κB', 'NF-kB', 'NF-kappa-B']:
            with self.assertRaisesRegex(ValueError, 'RELA.*NFKB1'):
                canonical_gene(name)
        self.assertEqual(canonical_gene('NF-κB p65'), 'RELA')
        self.assertEqual(canonical_gene('NF-κB p50'), 'NFKB1')

    def test_known_protein_is_prepared_from_pdb_when_alphafold_is_unavailable(self):
        def get(url, **kwargs):
            if 'uniprotkb/search' in url:
                return Response({'results': [{'primaryAccession': 'P05231'}]})
            if 'alphafold' in url:
                return Response([], status=404)
            if 'uniprotkb/P05231.json' in url:
                return Response({'uniProtKBCrossReferences': [{'database': 'PDB', 'id': '1ALU',
                                 'properties': [{'key': 'Chains', 'value': 'A=1-212'}]}]})
            if '1ALU.pdb' in url:
                return Response(content=PDB.encode())
            raise AssertionError(url)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'MUMO_STRUCTURE_CACHE': tmp}), patch.object(ta, 'database_get', side_effect=get):
            try:
                result = ta.analyze_target('IL-6', tmp)
            except Exception as exc:
                self.fail(f'PDB fallback did not prepare target: {exc}')
            self.assertEqual(result['accession'], 'P05231')
            self.assertEqual(result['structure_source'], 'RCSB PDB')
            self.assertEqual(result['pdb_id'], '1ALU')
            self.assertTrue(Path(result['pdb_path']).is_file())

    def test_alphafold_does_not_save_html_as_a_structure(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(ta, 'database_get', side_effect=[
                Response([{'uniprotAccession': 'P05231', 'pdbUrl': 'https://alphafold.ebi.ac.uk/files/model.pdb'}]),
                Response(content=b'<html>temporarily unavailable</html>')]):
            with self.assertRaises(ValueError):
                ta.download_alphafold('P05231', tmp)
            self.assertFalse((Path(tmp) / 'AF_P05231.pdb').exists())

    def test_verified_cached_alphafold_structure_survives_network_outage(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(ta, 'database_get', side_effect=[Response([{'uniprotAccession': 'P05231', 'pdbUrl': 'https://alphafold.ebi.ac.uk/files/model.pdb'}]), Response(content=PDB.encode())]):
                original = ta.download_alphafold('P05231', tmp)
            with patch.object(ta, 'database_get', side_effect=ta.requests.ConnectionError('offline')):
                try:
                    cached = ta.download_alphafold('P05231', tmp)
                except Exception as exc:
                    self.fail(f'Previously validated structure was not reused: {exc}')
                self.assertEqual(cached, original)

    def test_repeat_target_resolution_uses_verified_identity_during_outage(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(ta, 'database_get', return_value=Response({'results': [{'primaryAccession': 'P05231'}]})):
                try:
                    accession = ta.gene_to_uniprot('IL-6', cache_dir=tmp)
                except TypeError:
                    self.fail('Target identity has no reusable cache')
            with patch.object(ta, 'database_get', side_effect=ta.requests.ConnectionError('offline')):
                self.assertEqual(ta.gene_to_uniprot('IL6', cache_dir=tmp), accession)

    def test_uniprot_accession_is_not_searched_as_a_gene(self):
        def get(url, **kwargs):
            if url.endswith('/P05231.json'):
                return Response({'primaryAccession': 'P05231', 'organism': {'taxonId': 9606},
                                 'entryType': 'UniProtKB reviewed (Swiss-Prot)'})
            return Response({'results': []})
        with patch.object(ta, 'database_get', side_effect=get):
            try:
                result = ta.gene_to_uniprot('P05231')
            except Exception as exc:
                self.fail(f'Explicit accession not resolved: {exc}')
            self.assertEqual(result, 'P05231')

    def test_cached_pdb_can_be_reused_without_uniprot_being_online(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'PDB_P05231_1ALU_A.pdb'
            ta._save_structure(path, PDB.encode(), 'P05231', 'RCSB PDB',
                               'https://files.rcsb.org/download/1ALU.pdb', pdb_id='1ALU', chain='A')
            with patch.object(ta, 'database_get', side_effect=ta.requests.ConnectionError('offline')):
                try:
                    result = ta.download_linked_pdb('P05231', tmp)
                except Exception as exc:
                    self.fail(f'Cached PDB was blocked by network outage: {exc}')
                self.assertEqual(result, (str(path), '1ALU', 'A'))

if __name__ == '__main__':
    unittest.main()
