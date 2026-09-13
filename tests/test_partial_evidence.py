import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from verification import run_record, evidence_json
from agents import interaction_analyst as ia

class PartialEvidenceTests(unittest.TestCase):
    def test_run_record_does_not_duplicate_raw_artifacts(self):
        rec=run_record('test',{}, {}, {'a':{'status':'verified'}}, {'raw':{'text':'long text','sha256':'abc'}})
        self.assertNotIn('text',rec['artifacts']['raw'])
        self.assertEqual(rec['artifacts']['raw']['sha256'],'abc')

    def test_json_removes_nan_without_converting_to_zero(self):
        self.assertIn(b'null',evidence_json({'missing':float('nan')}))

    @unittest.skipUnless(ia.INTERACTIONS_AVAILABLE, 'ProLIF unavailable')
    def test_bad_contact_keeps_valid_contact_with_rejection_reason(self):
        from rdkit import Chem
        from types import SimpleNamespace
        class Residue:
            chain='A'; name='SER'; number=1
        conf=Chem.Conformer(1); conf.SetAtomPosition(0,(0,0,0))
        metadata={'parent_indices':{'ligand':[0],'protein':[0]},'distance':2.8}
        rejected=[]
        records=ia._collect_interactions({('LIG',Residue()):{'HBDonor':[metadata,{}]}},conf,conf,rejected)
        self.assertEqual(len(records),1)
        self.assertEqual(len(rejected),1)
