import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))

from validation.harness import count_statuses
from validation.checks import quill


class HarnessTests(unittest.TestCase):
    def test_errors_stay_in_the_denominator(self):
        items = [{'item': 'a', 'status': 'PASS'}, {'item': 'b', 'status': 'ERROR'},
                 {'item': 'c', 'status': 'INCONCLUSIVE'}]
        counts = count_statuses(items)
        self.assertEqual(counts['PASS'], 1)
        self.assertEqual(sum(counts.values()), 3)

    def test_unknown_status_is_rejected(self):
        with self.assertRaises(ValueError):
            count_statuses([{'item': 'a', 'status': 'MAYBE'}])


class QuillComparatorTests(unittest.TestCase):
    def test_numbers_compare_numerically(self):
        self.assertTrue(quill._same('180.2', 180.2))
        self.assertTrue(quill._same('3', 3))
        self.assertFalse(quill._same('180.3', 180.2))

    def test_strings_compare_exactly(self):
        self.assertTrue(quill._same('Pass', 'Pass'))
        self.assertFalse(quill._same('pass', 'Pass'))

    def test_missing_value_must_say_unavailable(self):
        self.assertTrue(quill._missing_ok('Not calculated'))
        for bad in ('None', 'nan', '0', ''):
            self.assertFalse(quill._missing_ok(bad))




class NexusHelperTests(unittest.TestCase):
    def test_single_channel_combines_to_itself(self):
        from validation.checks import nexus
        record = {c: 0.0 for c in nexus.CHANNELS}
        record['escore'] = 0.9
        self.assertAlmostEqual(nexus.combined_from_channels(record), 0.9, places=9)

    def test_two_channels_raise_the_total(self):
        from validation.checks import nexus
        record = {c: 0.0 for c in nexus.CHANNELS}
        record['escore'] = record['tscore'] = 0.5
        self.assertGreater(nexus.combined_from_channels(record), 0.5)




class ReportMissingValueTests(unittest.TestCase):
    def test_kv_table_never_prints_none_or_nan(self):
        from docx import Document
        import report_writer
        doc = Document()
        table = report_writer._add_kv_table(doc, [('a', None), ('b', float('nan')), ('c', 1.5), ('d', 'Pass')])
        cells = [row.cells[1].text for row in table.rows]
        self.assertEqual(cells, ['Not calculated', 'Not calculated', '1.5', 'Pass'])




class FateHelperTests(unittest.TestCase):
    def test_verdict_counts(self):
        from validation.checks import fate
        self.assertEqual(fate.verdict_count('Drug-like (passes Ro5)'), 0)
        self.assertEqual(fate.verdict_count('1 Ro5 violation'), 1)
        self.assertEqual(fate.verdict_count('3 Ro5 violations'), 3)

    def test_rules_catch_a_wrong_label(self):
        from validation.checks import fate
        from agents.admet import druglikeness
        dl = {k: v for k, v in druglikeness('CC(=O)Oc1ccccc1C(=O)O').items() if not k.startswith('_')}
        self.assertTrue(all(fate.check_rules(dl).values()))
        dl['Veber'] = 'Fail'
        self.assertFalse(fate.check_rules(dl)['veber'])

    def test_wrapper_cases_all_pass_offline(self):
        from validation.checks import fate
        failed = [name for name, ok, _ in fate.wrapper_cases() if not ok]
        self.assertEqual(failed, [])




class CompassHelperTests(unittest.TestCase):
    def test_equal_rankings_pass(self):
        from validation.checks import compass
        ind = [('A', 0.9), ('B', 0.8), ('C', 0.7)]
        self.assertTrue(compass.tie_aware_equal(ind[:2], ind))

    def test_tied_scores_may_swap_order(self):
        from validation.checks import compass
        ind = [('A', 0.9), ('B', 0.8), ('C', 0.8)]
        self.assertTrue(compass.tie_aware_equal([('A', 0.9), ('C', 0.8), ('B', 0.8)], ind))

    def test_page_boundary_may_cut_a_tie_group(self):
        from validation.checks import compass
        ind = [('A', 0.9), ('B', 0.8), ('C', 0.8)]
        self.assertTrue(compass.tie_aware_equal([('A', 0.9), ('C', 0.8)], ind))

    def test_different_ids_or_scores_fail(self):
        from validation.checks import compass
        ind = [('A', 0.9), ('B', 0.8), ('C', 0.7)]
        self.assertFalse(compass.tie_aware_equal([('A', 0.9), ('X', 0.8)], ind))
        self.assertFalse(compass.tie_aware_equal([('A', 0.9), ('B', 0.79)], ind))




class FluxHelperTests(unittest.TestCase):
    def test_auc_perfect_inverse_and_ties(self):
        from validation.checks import flux
        self.assertEqual(flux.roc_auc([0.9, 0.8, 0.2, 0.1], [1, 1, 0, 0]), 1.0)
        self.assertEqual(flux.roc_auc([0.1, 0.2, 0.8, 0.9], [1, 1, 0, 0]), 0.0)
        self.assertEqual(flux.roc_auc([0.5, 0.5, 0.5, 0.5], [1, 0, 1, 0]), 0.5)
        self.assertIsNone(flux.roc_auc([0.1, 0.2], [1, 1]))

    def test_structure_key_ignores_stereo_and_salts(self):
        from validation.checks import flux
        self.assertEqual(flux.structure_key('C[C@H](N)C(=O)O'), flux.structure_key('C[C@@H](N)C(=O)O'))
        self.assertEqual(flux.structure_key('CCO.[Na+].[Cl-]'), flux.structure_key('CCO'))
        self.assertIsNone(flux.structure_key('not a smiles'))

    def test_aspirin_to_salicylic_acid_is_a_hit(self):
        from validation.checks import flux
        from agents.metabolism import predict_metabolites
        pred = predict_metabolites('CC(=O)Oc1ccccc1C(=O)O')
        keys = {flux.structure_key(m['smiles']) for m in pred['metabolites']}
        self.assertIn(flux.structure_key('O=C(O)c1ccccc1O'), keys)

    def test_bootstrap_is_seeded(self):
        from validation.checks import flux
        data = [([0.9, 0.1], [1, 0]), ([0.8, 0.3, 0.2], [1, 0, 0])]
        self.assertEqual(flux.bootstrap_auc(data, 50, 1), flux.bootstrap_auc(data, 50, 1))




class FluxEmptyInputTests(unittest.TestCase):
    def test_empty_and_blank_smiles_return_an_error_record(self):
        from agents.metabolism import predict_metabolites
        for bad in ('', '   ', None):
            out = predict_metabolites(bad)
            self.assertIn('_error', out, repr(bad))
            self.assertEqual(out['_verification']['status'], 'failed')


if __name__ == "__main__":
    unittest.main()
