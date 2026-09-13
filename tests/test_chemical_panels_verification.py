import unittest
from unittest.mock import patch
from src.agents import admet, metabolism


class ChemicalVerification(unittest.TestCase):
    def test_alert_failure_does_not_claim_zero_alerts(self):
        self.assertIsNone(admet._alert_count(admet.Chem.MolFromSmiles('CCO'), 'NOT_A_CATALOG'))

    def test_rule_panel_records_chemical_identity_and_prediction_scope(self):
        out = admet.druglikeness('CCO')
        self.assertEqual(out['_verification']['canonical_smiles'], 'CCO')
        self.assertEqual(out['_verification']['method'], 'RDKit descriptors and heuristic rules')

    def test_ml_rejects_invalid_values_without_losing_valid_endpoint(self):
        class Model:
            def predict(self, smiles):
                return {'AMES': 0.2, 'hERG': float('nan'), 'DILI': 1.2,
                        'PPBR_AZ': 'bad', 'AMES_extra': .9}
        with patch.object(admet, '_get_admet_model', return_value=Model()):
            out = admet.admet_ml('CCO')
        self.assertEqual(out['Ames mutagenicity'], .2)
        self.assertNotIn('hERG blocker (cardiotox)', out)
        self.assertNotIn('DILI (liver injury)', out)
        self.assertEqual(out['_verification']['status'], 'partial')
        self.assertEqual(out['_verification']['endpoints']['DILI (liver injury)']['status'], 'failed')

    def test_ml_unavailable_is_explicit_and_not_rule_replacement(self):
        with patch.object(admet, '_get_admet_model', side_effect=ImportError('absent')):
            out = admet.admet_ml('CCO')
        self.assertIn('_error', out)
        self.assertEqual(out['_verification']['status'], 'unavailable')
        self.assertNotIn('GI absorption (pred.)', out)

    def test_invalid_input_never_reaches_ml(self):
        with patch.object(admet, '_get_admet_model', side_effect=AssertionError('called')):
            out = admet.admet_ml('not a smiles')
        self.assertEqual(out['_verification']['status'], 'failed')

    def test_metabolites_have_rule_evidence_and_prediction_label(self):
        out = metabolism.predict_metabolites('CCO', depth=1)
        self.assertTrue(out['metabolites'])
        self.assertEqual(out['_verification']['result_kind'], 'prediction')
        for product in out['metabolites']:
            self.assertEqual(product['result_kind'], 'predicted metabolite')
            self.assertTrue(product['rule_smarts'])
            self.assertTrue(product['structure_validated'])

    def test_rule_execution_failure_is_not_empty_success(self):
        with patch.object(metabolism, 'ALL_RULES', [('bad', 'bad reaction', .2, '', 'I')]):
            out = metabolism.predict_metabolites('CCO', depth=1)
        self.assertEqual(out['_verification']['status'], 'failed')
        self.assertTrue(out['_verification']['rule_failures'])

    def test_missing_route_intermediate_does_not_invent_root_edge(self):
        product = {'smiles': 'CC=O', 'parent': 'CCO', 'name': 'oxidation'}
        route = metabolism.route_to_root({'parent': 'CO', 'metabolites': [product]}, product)
        self.assertEqual(route, [('CCO', None), ('CC=O', 'oxidation')])


if __name__ == '__main__':
    unittest.main()
