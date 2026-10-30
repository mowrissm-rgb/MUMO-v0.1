import importlib.util
import math
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    'md_analyst', Path(__file__).parents[1] / 'src/agents/md_analyst.py')
md = importlib.util.module_from_spec(spec)
spec.loader.exec_module(md)


def atom(serial, name, resseq, xyz, element):
    return (f"ATOM  {serial:5d} {name:<4s} ALA A{resseq:4d}    "
            f"{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}  1.00  0.00          {element:>2s}")


def residue(first_serial, resseq, origin):
    ox, oy, oz = origin
    return [atom(first_serial, ' N', resseq, (ox, oy, oz), 'N'),
            atom(first_serial + 1, ' CA', resseq, (ox + 1.46, oy, oz), 'C'),
            atom(first_serial + 2, ' C', resseq, (ox + 2.0, oy + 1.4, oz), 'C'),
            atom(first_serial + 3, ' O', resseq, (ox + 1.3, oy + 2.4, oz), 'O')]


def read_atoms(path):
    rows = {}
    for line in Path(path).read_text().splitlines():
        if line.startswith('ATOM'):
            key = (int(line[22:26]), line[12:16].strip())
            rows[key] = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
    return rows


def angle(a, b, c):
    u = [a[i] - b[i] for i in range(3)]
    v = [c[i] - b[i] for i in range(3)]
    dot = sum(u[i] * v[i] for i in range(3))
    return math.degrees(math.acos(dot / (math.hypot(*u) * math.hypot(*v))))


class TerminalOxygenTests(unittest.TestCase):
    def _structure(self):
        r1 = residue(1, 1, (0.0, 0.0, 0.0))
        # residue 2 is peptide-bonded to residue 1 (its N is 1.3 A from C of residue 1)
        r2 = [atom(5, ' N', 2, (3.3, 1.5, 0.0), 'N'), atom(6, ' CA', 2, (4.0, 2.8, 0.0), 'C'),
              atom(7, ' C', 2, (5.5, 2.7, 0.0), 'C'), atom(8, ' O', 2, (6.1, 1.7, 0.0), 'O')]
        r3 = residue(9, 3, (20.0, 0.0, 0.0))      # far away: a chain break before residue 3
        return r1 + r2 + r3

    def test_oxt_added_at_chain_end_and_before_a_gap_only(self):
        with tempfile.TemporaryDirectory() as directory:
            src, out = Path(directory) / 'in.pdb', Path(directory) / 'out.pdb'
            src.write_text('\n'.join(self._structure()) + '\nEND\n')
            added = md._add_missing_oxt(str(src), str(out))
            atoms = read_atoms(out)
            self.assertEqual(added, 2)
            self.assertNotIn((1, 'OXT'), atoms)          # bonded to the next residue
            for resseq in (2, 3):                        # before the gap, and the chain end
                c, o, ca, oxt = (atoms[(resseq, n)] for n in ('C', 'O', 'CA', 'OXT'))
                self.assertAlmostEqual(math.dist(c, oxt), 1.25, places=2)
                # equal to within PDB coordinate rounding (three decimals)
                self.assertAlmostEqual(angle(oxt, c, ca), angle(oxt, c, o), delta=0.05)

    def test_capped_residue_is_not_bonded_across_the_gap_by_openmm(self):
        # Found by the Anchor validation: OpenMM joins consecutive residues of a chain even
        # across a gap, so the capped residue still had an extra external bond.
        try:
            from openmm import app
        except ImportError:
            self.skipTest('openmm not installed')
        with tempfile.TemporaryDirectory() as directory:
            src, out = Path(directory) / 'in.pdb', Path(directory) / 'out.pdb'
            src.write_text('\n'.join(self._structure()) + '\nEND\n')
            md._add_missing_oxt(str(src), str(out))
            residues = list(app.PDBFile(str(out)).topology.residues())
            self.assertEqual(len(residues), 3)
            across_gap = [(a, b) for a, b in app.PDBFile(str(out)).topology.bonds()
                          if {a.residue.index, b.residue.index} == {1, 2}]
            self.assertEqual(across_gap, [])
            joined = [(a, b) for a, b in app.PDBFile(str(out)).topology.bonds()
                      if {a.residue.index, b.residue.index} == {0, 1}]
            self.assertEqual(len(joined), 1)         # the real peptide bond is kept

    def test_running_it_again_adds_nothing_and_serials_are_unique(self):
        with tempfile.TemporaryDirectory() as directory:
            src, once, twice = (Path(directory) / n for n in ('in.pdb', 'once.pdb', 'twice.pdb'))
            src.write_text('\n'.join(self._structure()) + '\nEND\n')
            md._add_missing_oxt(str(src), str(once))
            self.assertEqual(md._add_missing_oxt(str(once), str(twice)), 0)
            serials = [int(l[6:11]) for l in once.read_text().splitlines() if l.startswith('ATOM')]
            self.assertEqual(serials, list(range(1, len(serials) + 1)))


if __name__ == '__main__':
    unittest.main()
