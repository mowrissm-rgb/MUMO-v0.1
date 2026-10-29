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


if __name__ == "__main__":
    unittest.main()
