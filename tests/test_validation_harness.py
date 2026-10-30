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




class AtlasHelperTests(unittest.TestCase):
    def test_angle_difference_wraps(self):
        from validation.checks import atlas
        self.assertAlmostEqual(atlas.angle_diff(179.9, -179.9), 0.2, places=6)
        self.assertEqual(atlas.angle_diff(10, 10), 0)

    def test_report_parser_keeps_model1_blank_altcode_only(self):
        from validation.checks import atlas
        xml = ('<r><ModelledSubgroup model="1" chain="A" resnum="5" icode=" " resname="ALA" altcode=" " '
               'phi="-60.0" psi="-40.0" rama="Favored"/>'
               '<ModelledSubgroup model="1" chain="A" resnum="6" icode=" " resname="ALA" altcode="B" '
               'phi="-60.0" psi="-40.0" rama="Favored"/>'
               '<ModelledSubgroup model="2" chain="A" resnum="7" icode=" " resname="ALA" altcode=" " '
               'phi="-60.0" psi="-40.0" rama="Allowed"/></r>')
        self.assertEqual(list(atlas.report_residues(xml)), [('A', 5, '', 'ALA')])

    def test_ligand_centroid_uses_first_residue_heavy_atoms(self):
        from validation.checks import atlas
        text = ('HETATM    1  C1  LIG A   1       0.000   0.000   0.000  1.00  0.00           C\n'
                'HETATM    2  C2  LIG A   1       2.000   0.000   0.000  1.00  0.00           C\n'
                'HETATM    3  H1  LIG A   1      50.000   0.000   0.000  1.00  0.00           H\n'
                'HETATM    4  C1  LIG B   1     100.000   0.000   0.000  1.00  0.00           C\n')
        _, centroid, n = atlas.parse_complex(text, 'LIG')
        self.assertEqual((centroid, n), ((1.0, 0.0, 0.0), 2))

    def test_short_structure_gives_error_record(self):
        import ramachandran
        from validation.checks import atlas
        self.assertIn('_error', ramachandran.compute(atlas.minimal_pdb(2)))
        self.assertIn('_error', ramachandran.compute(''))




class PoseHelperTests(unittest.TestCase):
    def test_wilson_interval_brackets_the_rate(self):
        from validation.checks import pose
        lo, hi = pose.wilson(6, 11)
        self.assertLess(lo, 6 / 11)
        self.assertGreater(hi, 6 / 11)
        self.assertEqual(pose.wilson(0, 0), (None, None))

    def _report(self, **override):
        res = {'best_score': -7.1, 'all_best': [-7.1, -6.9, -6.8], 'mean': -6.933, 'sd': 0.125,
               'confidence': 'High', 'modes': [(1, -7.1), (2, -6.5), (3, -6.0)],
               'vinardo': -8.0, 'consensus': 'Both functions agree'}
        res.update(override)
        return res

    def test_consistent_report_passes_every_check(self):
        from validation.checks import pose
        self.assertTrue(all(pose.check_replica_report(self._report()).values()))

    def test_each_inconsistency_is_caught(self):
        from validation.checks import pose
        self.assertFalse(pose.check_replica_report(self._report(best_score=-6.9))['best_is_min'])
        self.assertFalse(pose.check_replica_report(self._report(sd=0.9))['mean_sd'])
        self.assertFalse(pose.check_replica_report(self._report(confidence='Lower'))['confidence_rule'])
        self.assertFalse(pose.check_replica_report(self._report(modes=[(1, -6.0), (2, -7.1)]))['modes_sorted'])
        self.assertFalse(pose.check_replica_report(self._report(vinardo=None))['vinardo_and_label'])
        self.assertFalse(pose.check_replica_report(self._report(consensus='unavailable (x)'))['vinardo_and_label'])




class GhoseAtomCountTests(unittest.TestCase):
    def test_ghose_counts_hydrogens_not_heavy_atoms(self):
        from agents.admet import druglikeness
        dl = druglikeness('CC(=O)Oc1ccccc1C(=O)O')   # aspirin: 13 heavy atoms, 21 atoms with H
        self.assertEqual(dl['Heavy atoms'], 13)
        self.assertEqual(dl['Ghose'], 'Pass')


class LigandSelectionTests(unittest.TestCase):
    def _pdb(self, path):
        def het(serial, resn, resseq, n, x0):
            return ''.join(f"HETATM{serial + i:5d}  C{i + 1:<2d} {resn} A{resseq:4d}    {x0 + i:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00  0.00           C\n"
                           for i in range(n))
        protein = ''.join(f"ATOM  {i + 1:5d}  CA  ALA A{i + 1:4d}    {float(i):8.3f}{0.0:8.3f}{0.0:8.3f}  1.00  0.00           C\n"
                          for i in range(5))
        Path(path).write_text(protein + het(100, 'CLR', 301, 28, 50.0) + het(200, 'LIG', 302, 10, 80.0))

    def test_cholesterol_is_not_picked_as_the_ligand(self):
        import tempfile
        from agents.target_analyst import auto_grid_from_pdb
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'x.pdb'
            self._pdb(path)
            self.assertIn("'LIG'", auto_grid_from_pdb(str(path))[2])

    def test_both_code_paths_share_one_exclusion_list(self):
        from agents import target_analyst
        import crystal_additives
        self.assertIs(target_analyst._NOT_LIGAND, crystal_additives.NOT_LIGAND)
        source = (ROOT / 'src' / 'docking_engine.py').read_text(encoding='utf-8')
        self.assertIn('from crystal_additives import NOT_LIGAND', source)
        for code in ('HEM', 'CLR', 'HOH', 'NAG'):
            self.assertIn(code, crystal_additives.NOT_LIGAND)



class OrbitHelperTests(unittest.TestCase):
    MOLDEN = chr(10).join([
        "[MO]", "Sym= a", "Ene= -0.7", "Spin= Alpha", "Occup= 2.0", "1 0.1",
        "Sym= a", "Ene= -0.4", "Spin= Alpha", "Occup= 2.0", "1 0.1",
        "Sym= a", "Ene= 0.1", "Spin= Alpha", "Occup= 0.0", "1 0.1"])

    def test_molden_frontier_orbitals(self):
        from validation.checks import orbit
        mos = orbit.parse_molden(self.MOLDEN)
        self.assertEqual(mos, [(-0.7, 2.0), (-0.4, 2.0), (0.1, 0.0)])
        self.assertEqual(orbit.frontier(mos), (-0.4, 0.1, 2))
        with self.assertRaises(ValueError):
            orbit.frontier([(-0.5, 2.0)])

    def test_correlations_and_error_stats(self):
        from validation.checks import orbit
        self.assertAlmostEqual(orbit.pearson([1, 2, 3, 4], [2, 4, 6, 8]), 1.0)
        self.assertAlmostEqual(orbit.spearman([1, 2, 3, 4], [1, 8, 27, 64]), 1.0)
        self.assertAlmostEqual(orbit.pearson([1, 2, 3], [3, 2, 1]), -1.0)
        st = orbit.error_stats([1.0, 2.0, 4.0], [1.0, 3.0, 3.0])
        self.assertAlmostEqual(st["mae"], 2 / 3)
        self.assertAlmostEqual(st["bias"], 0.0)


class XtbEncodingTests(unittest.TestCase):
    def test_xtb_output_is_decoded_as_utf8_not_the_windows_codepage(self):
        import os
        from unittest import mock
        from agents import qm_analyst
        seen = {}

        def fake_run(cmd, **kwargs):
            seen.update(kwargs)
            raise RuntimeError("stop after capturing the call")

        with mock.patch.dict(os.environ, {"MUMO_XTB": "xtb-stub"}):
            with mock.patch.object(qm_analyst.subprocess, "run", fake_run):
                out = qm_analyst.orbitals("CCO")
        self.assertIn("_error", out)
        self.assertEqual(seen.get("encoding"), "utf-8")
        self.assertEqual(seen.get("errors"), "replace")


if __name__ == "__main__":
    unittest.main()
