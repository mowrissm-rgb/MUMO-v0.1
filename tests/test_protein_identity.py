import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


class ProteinIdentityTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('protein_identity'),
                             'Coordinate identity extraction is missing')
        import protein_identity
        return protein_identity

    def test_alphafold_title_and_taxonomy_identify_the_actual_uploaded_structure(self):
        identity = self.module().extract_identity(
            'TITLE     ALPHAFOLD MONOMER PREDICTION FOR CYCLIN DEPENDENT KINASE\n'
            'TITLE    2 (P11802)\nSOURCE    ORGANISM_TAXID: 9606;\n')
        self.assertEqual(identity['accession'], 'P11802')
        self.assertEqual(identity['species'], 9606)
        self.assertEqual(identity['pdb_id'], '')

    def test_multispecies_metadata_does_not_default_to_human(self):
        identity = self.module().extract_identity(
            'TITLE     ALPHAFOLD (P11802)\n'
            'SOURCE    ORGANISM_TAXID: 9606;\nSOURCE    ORGANISM_TAXID: 10090;\n')
        self.assertIsNone(identity['species'])

    def test_unrelated_title_text_is_not_interpreted_as_a_uniprot_identifier(self):
        identity = self.module().extract_identity('TITLE     TARGET EXPERIMENT (P11802)\n')
        self.assertEqual(identity['accession'], '')

    def test_dbref_mapping_follows_retained_receptor_chain(self):
        lines = []
        for chain, accession in [('A', 'P00533'), ('B', 'P04626')]:
            line = [' '] * 80
            line[:6] = 'DBREF '
            line[12] = chain
            line[26:32] = 'UNP   '
            line[33:41] = accession.ljust(8)
            lines.append(''.join(line))
        text = '\n'.join(lines)
        self.assertEqual(self.module().extract_identity(text, chains=['A'])['accession'], 'P00533')
        self.assertEqual(self.module().extract_identity(text)['accession'], '')


if __name__ == '__main__':
    unittest.main()
