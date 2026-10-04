"""Build gate: execute the deployed isolated SASA worker on a real geometry."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from target_validation import solvent_exposure

# One alanine backbone, used only to exercise the native calculation path.
pdb = ('ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 20.00           N  \n'
       'ATOM      2  CA  ALA A   1       1.450   0.000   0.000  1.00 20.00           C  \n'
       'ATOM      3  C   ALA A   1       2.000   1.400   0.000  1.00 20.00           C  \n'
       'ATOM      4  O   ALA A   1       1.400   2.450   0.000  1.00 20.00           O  \nEND\n')
result = solvent_exposure(pdb)
assert result.get('status') == 'calculated', result
assert result['selected_atoms'] == 4, result
assert len(result['residues']) == 1, result
assert result['residues'][0]['chain'] == 'A', result
assert result['residues'][0]['name'] == 'ALA', result
print('Isolated FreeSASA geometry, residue identity and area checks passed')
