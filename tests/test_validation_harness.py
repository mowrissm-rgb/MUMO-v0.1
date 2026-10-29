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


if __name__ == '__main__':
    unittest.main()
