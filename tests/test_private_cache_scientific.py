"""Opt-in real 1x1 Standard/three-seed cache verification; no remote persistence."""
import copy
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


@unittest.skipUnless(os.environ.get('MUMO_CACHE_SCIENTIFIC') == '1', 'Opt-in real Vina cache smoke')
class PrivateCacheScientificTests(unittest.TestCase):
    def test_real_cold_then_full_hit_keeps_scores_coordinates_and_dates(self):
        import pipeline
        import docking_jobs
        from agents.target_analyst import auto_grid_from_pdb
        from docking_memory import eligible_entry
        from docking_cache_store import encode_entry, decode_entry
        source = 'D:/my vault/tmp/cdk4-completion-check/source.pdb'
        vina = 'C:/Users/Mowris/.gemini/antigravity/scratch/mumo/bin/vina.exe'
        center, size, pocket = auto_grid_from_pdb(source)
        target = {'gene': 'CDK4', 'pdb_path': source, 'center': center, 'size': size,
                  'source': pocket}
        ligands = [{'label': 'ethanol', 'smiles': 'CCO'}]
        root = Path(tempfile.mkdtemp(prefix='private-cache-smoke-', dir='D:/my vault/tmp'))
        cold, warm = root/'cold', root/'warm'
        cold.mkdir(); warm.mkdir()
        start = time.monotonic()
        cold_rows, cold_viz, cold_meta = pipeline.dock_pipeline(copy.deepcopy(target), ligands,
            vina, str(cold), '', exhaustiveness=16, n_replicas=3, seed=42, owner_id='local-test-owner')
        cold_seconds = time.monotonic()-start
        self.assertIsInstance(cold_rows[0]['Best affinity (kcal/mol)'], (float, int), cold_rows[0])
        self.assertEqual(cold_meta['accession'], 'P11802')
        self.assertEqual(cold_meta['species'], 9606)
        self.assertEqual(len(cold_meta['cache_entries']), 1, cold_meta.get('cache_notice'))
        entry = cold_meta['cache_entries'][0]
        self.assertTrue(eligible_entry(entry, 'local-test-owner', entry['key']))
        self.assertEqual([r['seed'] for r in entry['replicas']], [42, 43, 44])
        packed = encode_entry(entry)
        restored = decode_entry(packed, 'local-test-owner', entry['key'])
        before = copy.deepcopy(restored)
        start = time.monotonic()
        prepared = pipeline.prepare_docking(copy.deepcopy(target), ligands, vina, str(warm), '',
            exhaustiveness=16, n_replicas=3, seed=42)
        with (patch('pipeline.dock_with_replicas', side_effect=AssertionError('Full hit redocked')),
              patch('pipeline.analyze_interactions', side_effect=AssertionError('Full hit reanalyzed'))):
            warm_rows, warm_viz, warm_meta = pipeline.dock_pipeline(target, ligands, vina, str(warm), '',
                prepared=prepared, reuse_entries={entry['key']: restored}, owner_id='local-test-owner')
        warm_seconds = time.monotonic()-start
        self.assertEqual(restored, before)
        self.assertEqual(warm_rows[0]['Calculation origin'], 'reused')
        self.assertEqual(warm_rows[0]['Best affinity (kcal/mol)'], cold_rows[0]['Best affinity (kcal/mol)'])
        self.assertEqual(Path(warm_viz['ethanol']['complex']).read_bytes(), Path(cold_viz['ethanol']['complex']).read_bytes())
        self.assertEqual(warm_rows[0]['Original calculation date'], entry['created_at'])
        import pipeline_core
        partial_dir = root/'partial'; partial_dir.mkdir()
        partial_request = {'target': 'CDK4', 'uploaded_target_name': 'CDK4',
            'uploaded_target_pdb': source, 'docking_mode': 'Standard',
            'ligand_objs': ligands + [{'label': 'benzamidine', 'smiles': 'NC(=N)c1ccccc1'}]}
        decisions, executed = [], []
        real_engine = pipeline.dock_with_replicas
        def choice(offer):
            self.assertEqual(offer['hit_count'], 1)
            self.assertEqual(offer['total_pairs'], 2)
            self.assertTrue((partial_dir/'t00_CDK4'/'c_lig_1.pdbqt').exists())
            self.assertFalse(list(partial_dir.glob('**/c_out_1_r*.pdbqt')))
            decisions.append('reuse')
            return 'reuse'
        def counted_engine(*args, **kwargs):
            executed.append((kwargs['exhaustiveness'], kwargs['n_replicas'], kwargs['base_seed']))
            return real_engine(*args, **kwargs)
        start = time.monotonic()
        with patch('pipeline.dock_with_replicas', side_effect=counted_engine):
            partial_result = pipeline_core.run_job(partial_request, vina, str(partial_dir), '',
                cache_context={'owner_id': 'local-test-owner', 'candidates': [restored]}, reuse_decision=choice)
        partial_seconds = time.monotonic()-start
        self.assertEqual(executed, [(16, 3, 42)])
        self.assertEqual(decisions, ['reuse'])
        self.assertEqual(len(partial_result['rows']), 2)
        ethanol = next(r for r in partial_result['rows'] if r['Ligand'] == 'ethanol')
        benzamidine = next(r for r in partial_result['rows'] if r['Ligand'] == 'benzamidine')
        self.assertEqual(ethanol['Calculation origin'], 'reused')
        self.assertEqual(ethanol['Best affinity (kcal/mol)'], cold_rows[0]['Best affinity (kcal/mol)'])
        self.assertEqual(ethanol['Original calculation date'], entry['created_at'])
        self.assertIsInstance(benzamidine['Best affinity (kcal/mol)'], (int,float), benzamidine)
        self.assertEqual(restored, before)
        self.assertEqual(partial_result['meta']['cache']['new_pairs'], 1)
        docking_jobs._write_json(str(root/'result.json'), {'cold_rows': cold_rows, 'warm_rows': warm_rows,
            'partial_result': partial_result, 'cache_entry': entry, 'cold_seconds': cold_seconds,
            'full_hit_seconds': warm_seconds, 'partial_seconds': partial_seconds,
            'executed_pairs': {'cold': 1, 'partial': 1, 'full_hit': 0},
            'executed_replicas': {'cold': 3, 'partial': 3, 'full_hit': 0}})
        print(f'REAL CACHE PASS: score={cold_rows[0]["Best affinity (kcal/mol)"]}; '
              f'cold={cold_seconds:.2f}s partial={partial_seconds:.2f}s full-hit={warm_seconds:.2f}s; evidence={root}', flush=True)


if __name__ == '__main__':
    unittest.main()
