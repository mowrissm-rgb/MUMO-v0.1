import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def row(target, ligand, score, smiles='CCO', status='verified'):
    return {'Target': target, 'Ligand': ligand, 'Best affinity (kcal/mol)': score,
            'SMILES': smiles, 'Interaction status': status, 'Reliability': 'Low'}


class DockingBiologyTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('docking_biology'),
                             'Integrated docking biology is missing')
        import docking_biology
        return docking_biology

    def test_selection_is_within_target_retains_ties_and_rejects_missing_evidence(self):
        biology = self.module()
        rows = [row('EGFR', 'A', -6), row('EGFR', 'B', -6), row('EGFR', 'C', -5),
                row('CDK4', 'D', -4), row('CDK4', 'unprofiled', -12, status='unavailable'),
                row('CDK4', 'failed', 'FAILED'), row('CDK4', 'nan', float('nan'))]
        selected = biology.select_candidates(rows)
        self.assertEqual([r['Ligand'] for r in selected['EGFR']], ['A', 'B'])
        self.assertEqual([r['Ligand'] for r in selected['CDK4']], ['D'])
        self.assertEqual(selected['EGFR'][0]['Reliability'], 'Low')

    def test_adme_calculates_identical_chemistry_once_and_keeps_model_failure(self):
        biology = self.module()
        calls = []
        def descriptors(smiles):
            calls.append(smiles)
            return {'MW (g/mol)': 46.069, '_verification': {'status': 'verified'}}
        def unavailable(smiles):
            raise RuntimeError('model unavailable')
        report = biology.analyze_lead_adme([row('EGFR', 'ethanol', -6),
             row('CDK4', 'ethyl alcohol', -4, 'OCC'), row('HER2', 'failed', 'FAILED')],
             descriptor=descriptors, model=unavailable)
        self.assertEqual(calls, ['CCO'])
        self.assertEqual(len(report['compounds']), 1)
        self.assertEqual(report['compounds'][0]['targets'], ['EGFR', 'CDK4'])
        self.assertEqual(report['compounds'][0]['descriptors']['MW (g/mol)'], 46.069)
        self.assertEqual(report['compounds'][0]['ml']['status'], 'unavailable')
        self.assertIn('HER2', report['no_candidate'])

    def test_failed_records_and_boolean_scores_are_not_candidates(self):
        failed = row('EGFR', 'failed', -12)
        failed['Verification status'] = 'failed'
        rows = [failed, row('EGFR', 'boolean', True), row('EGFR', 'complete', -6)]
        selected = self.module().select_candidates(rows)
        self.assertEqual([r['Ligand'] for r in selected['EGFR']], ['complete'])

    def test_empty_structure_is_not_sent_to_adme_engines(self):
        calls = []
        def calculate(smiles):
            calls.append(smiles)
            return {}
        report = self.module().analyze_lead_adme(
            [row('EGFR', 'unknown', -6, '')], descriptor=calculate, model=calculate)
        self.assertEqual(calls, [])
        self.assertEqual(report['compounds'], [])
        self.assertEqual(len(report['errors']), 1)

    def test_string_groups_verified_species_and_lists_unmapped_targets(self):
        biology = self.module()
        calls = []
        def network(ids, species, limit):
            calls.append((ids, species, limit))
            if species == 10090:
                raise RuntimeError('STRING down')
            return {'resolved': [{'queryItem': 'P00533', 'preferredName': 'EGFR'}],
                    'partners': [], 'enrichment': [], 'network_svg': '<svg/>',
                    'input': ['EGFR'], 'species': species}
        report = biology.collect_string({'EGFR': {'accession': 'P00533', 'species': 9606},
            'HER2': {'accession': 'P04626', 'species': 9606},
            'mouse': {'accession': 'Q01279', 'species': 10090}, '1XYZ': {}}, analyze=network)
        self.assertEqual(calls, [(['P00533', 'P04626'], 9606, 20), (['Q01279'], 10090, 20)])
        self.assertEqual(report['groups'][0]['unmapped'], ['HER2'])
        self.assertEqual(report['groups'][1]['status'], 'unavailable')
        self.assertIn('1XYZ', report['unmapped'])
        self.assertIn('enrichment_scope', report['groups'][0])

    def test_network_with_wrong_species_is_not_reported_as_valid(self):
        biology = self.module()
        def wrong_species(ids, species, limit):
            return {'resolved': [{'queryItem': 'P00533', 'ncbiTaxonId': 10090,
                    'stringId': '10090.ENSMUSP00000020122', 'preferredName': 'Egfr'}],
                    'partners': [], 'enrichment': [], 'network_svg': '<svg/>'}
        report = biology.collect_string({'EGFR': {'accession': 'P00533', 'species': 9606}},
                                       analyze=wrong_species)
        self.assertEqual(report['groups'][0]['status'], 'unavailable')
        self.assertNotIn('result', report['groups'][0])

    def test_optional_biology_failure_keeps_completed_docking_results(self):
        biology = self.module()
        self.assertTrue(hasattr(biology, 'enrich_result'), 'Result enrichment is missing')
        result = {'ok': True, 'rows': [row('EGFR', 'ethanol', -6)],
                  'meta': {'gene': 'EGFR', 'exhaustiveness': 16}, 'viz': {'ethanol': {'pdb': 'atoms'}}}
        with patch.object(biology, 'collect_string', side_effect=RuntimeError('network down')), \
             patch.object(biology, 'analyze_lead_adme', side_effect=RuntimeError('model down')):
            enriched = biology.enrich_result(result)
        self.assertEqual(enriched['rows'], result['rows'])
        self.assertEqual(enriched['viz'], result['viz'])
        self.assertEqual(enriched['meta']['exhaustiveness'], 16)
        self.assertEqual(enriched['meta']['biology']['string']['status'], 'unavailable')
        self.assertEqual(enriched['meta']['biology']['adme']['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
