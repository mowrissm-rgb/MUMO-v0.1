import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import docking_engine as de


def _atom(serial, name, alt, res, num, x, occ):
    return (f"ATOM  {serial:5d} {name:<4s}{alt}GLY A{num:4d}    {x:8.3f}{0:8.3f}{0:8.3f}{occ:6.2f}"
            f"{20:6.2f}           {name[0]}\n")


def _pdb():
    lines, n = [], 0
    for num, (occ_a, occ_b) in enumerate([(0.35, 0.65), (0.61, 0.39), (0.50, 0.50)], start=1):
        base = num * 4.0
        for name, dx in (('N', 0.0), ('C', 2.0), ('O', 3.0)):
            n += 1
            lines.append(_atom(n, name, ' ', 'GLY', num, base + dx, 1.0))
        n += 1
        lines.append(_atom(n, 'CA', 'A', 'GLY', num, base + 1.0, occ_a))
        n += 1
        lines.append(_atom(n, 'CA', 'B', 'GLY', num, base + 1.0, occ_b))
    return ''.join(lines) + 'END\n'


class CleanerAlternateConformers(unittest.TestCase):
    def test_best_populated_conformer_is_kept_and_label_is_blanked(self):
        src = Path(tempfile.mkdtemp()) / 'in.pdb'
        out = Path(tempfile.mkdtemp()) / 'out.pdb'
        src.write_text(_pdb())
        de.clean_protein_pdb(str(src), str(out))
        kept = {(l[22:26].strip(), l[54:60].strip()) for l in out.read_text().splitlines() if l[12:16].strip() == 'CA'}
        self.assertEqual(kept, {('1', '0.65'), ('2', '0.61'), ('3', '0.50')})  # B, A, tie goes to A
        self.assertTrue(all(l[16] == ' ' for l in out.read_text().splitlines() if l.startswith('ATOM')))


if __name__ == '__main__':
    unittest.main()
