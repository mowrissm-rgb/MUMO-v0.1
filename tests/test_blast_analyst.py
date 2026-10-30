import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

spec = importlib.util.spec_from_file_location(
    'blast_analyst', Path(__file__).parents[1] / 'src/agents/blast_analyst.py')
blast = importlib.util.module_from_spec(spec)
spec.loader.exec_module(blast)

TAB = chr(9)


def row(acc, pident, length, evalue, bits, title='Protein OS=Homo sapiens OX=9606 GN=X PE=1 SV=1'):
    return TAB.join([f'sp|{acc}|{acc}_HUMAN', str(pident), str(length), str(evalue), str(bits), title])


class ParseTests(unittest.TestCase):
    def test_hits_are_ranked_by_bit_score_not_by_blast_order(self):
        # E-values underflow to 0 for strong matches, so BLAST's order among them is not by score
        text = chr(10).join([row('P2', 90.0, 300, 0.0, 580), row('P1', 100.0, 300, 0.0, 620),
                             row('P3', 70.0, 280, '1e-80', 300)])
        hits = blast._parse_blast_tab(text, max_hits=25)
        self.assertEqual([h['accession'] for h in hits], ['P1', 'P2', 'P3'])

    def test_best_alignment_per_subject_is_kept(self):
        text = chr(10).join([row('P1', 50.0, 40, '1e-5', 80), row('P1', 99.0, 300, 0.0, 600)])
        hits = blast._parse_blast_tab(text)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]['bit_score'], 600.0)

    def test_only_the_top_max_hits_are_returned(self):
        text = chr(10).join(row(f'P{i}', 60.0, 200, 0.0, 100 + i) for i in range(10))
        hits = blast._parse_blast_tab(text, max_hits=3)
        self.assertEqual([h['accession'] for h in hits], ['P9', 'P8', 'P7'])


class RunTests(unittest.TestCase):
    def test_blast_is_asked_for_far_more_hits_than_are_shown(self):
        seen = {}

        def fake_run(cmd, **kwargs):
            seen['cmd'] = cmd
            return SimpleNamespace(returncode=0, stdout=row('P1', 100.0, 300, 0.0, 600), stderr='')
        with mock.patch.object(blast.subprocess, 'run', fake_run):
            hits = blast.run_blastp('M' * 50, max_hits=25)
        limit = int(seen['cmd'][seen['cmd'].index('-max_target_seqs') + 1])
        self.assertGreaterEqual(limit, 1000)
        self.assertEqual(len(hits), 1)


class InputTests(unittest.TestCase):
    def test_empty_or_blank_query_is_a_value_error(self):
        for bad in ('', '   ', None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                blast.analyze_blast(bad)


if __name__ == '__main__':
    unittest.main()
