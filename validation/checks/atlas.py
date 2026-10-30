"""Atlas check: Ramachandran vs wwPDB validation, pocket detection vs bound ligands, target identity.

Protocol: validation/PROTOCOL.md, section "Atlas: Ramachandran validation,
pocket detection and target identity".
"""
import gzip
import json
import math
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

RCSB = 'https://files.rcsb.org'
CLASS_MAP = {'Favored': 'favoured', 'Allowed': 'allowed', 'OUTLIER': 'outlier'}
AA3 = {'ALA': 'A', 'ARG': 'R', 'ASN': 'N', 'ASP': 'D', 'CYS': 'C', 'GLN': 'Q', 'GLU': 'E', 'GLY': 'G',
       'HIS': 'H', 'ILE': 'I', 'LEU': 'L', 'LYS': 'K', 'MET': 'M', 'PHE': 'F', 'PRO': 'P', 'SER': 'S',
       'THR': 'T', 'TRP': 'W', 'TYR': 'Y', 'VAL': 'V'}


class Client:
    def __init__(self):
        self.requests = 0

    def fetch(self, url, params=None):
        for attempt in range(4):
            self.requests += 1
            try:
                resp = requests.get(url, params=params, timeout=120)
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 3:
                    raise
            else:
                if resp.status_code not in (429, 500, 502, 503, 504) or attempt == 3:
                    resp.raise_for_status()
                    return resp
            time.sleep(1.0 * (2 ** attempt))

    def pdb_text(self, pdb):
        return self.fetch(f'{RCSB}/download/{pdb}.pdb').text

    def validation_xml(self, pdb):
        p = pdb.lower()
        url = f'{RCSB}/pub/pdb/validation_reports/{p[1:3]}/{p}/{p}_validation.xml.gz'
        return gzip.decompress(self.fetch(url).content).decode('utf-8')


def angle_diff(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)


def report_residues(xml_text):
    """key (chain, resnum, icode, resname) -> (phi, psi, class) for model 1, rama present."""
    out = {}
    for el in ET.fromstring(xml_text).iter('ModelledSubgroup'):
        a = el.attrib
        if a.get('model') != '1' or a.get('rama') not in CLASS_MAP:
            continue
        if a.get('altcode', ' ').strip() not in ('', 'A') or not a.get('phi') or not a.get('psi'):
            continue
        key = (a['chain'], int(a['resnum']), a.get('icode', ' ').strip(), a['resname'])
        out.setdefault(key, (float(a['phi']), float(a['psi']), CLASS_MAP[a['rama']]))
    return out


def compare_rama(mumo, report, tol):
    """Return per-entry stats and the residue-level pairs."""
    points = {}
    for p in mumo['points']:
        points.setdefault((p['chain'], int(p['resseq']), str(p['icode']).strip(), p['resname']), p)
    matched = [(k, points[k], report[k]) for k in report if k in points]
    angle_ok, class_ok, confusion, worst = 0, 0, {}, []
    for key, p, (phi, psi, cls) in matched:
        d = max(angle_diff(p['phi_unrounded'], phi), angle_diff(p['psi_unrounded'], psi))
        angle_ok += d <= tol
        class_ok += p['region'] == cls
        confusion[f"{cls}->{p['region']}"] = confusion.get(f"{cls}->{p['region']}", 0) + 1
        worst.append((round(d, 3), f'{key[3]}{key[1]}({key[0]})'))
    worst.sort(reverse=True)
    return {'matched': len(matched), 'angle_ok': angle_ok, 'class_ok': class_ok, 'confusion': confusion,
            'in_report_not_scored': len(set(report) - set(points)),
            'scored_not_in_report': len(set(points) - set(report)),
            'worst_angle_diffs': worst[:3]}


# ── Part P ──────────────────────────────────────────────────────────────────
def parse_complex(text, ligand):
    """Protein ATOM coordinates (first model) and the first ligand residue's heavy-atom centroid."""
    protein, lig_atoms, lig_key = [], [], None
    for line in text.splitlines():
        if line.startswith('ENDMDL'):
            break
        if line.startswith('ATOM'):
            protein.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
        elif line.startswith('HETATM') and line[17:20].strip() == ligand:
            key = (line[21], line[22:26].strip(), line[26].strip())
            lig_key = lig_key or key
            element = (line[76:78].strip() or line[12:16].strip()[:1]).upper()
            if key == lig_key and element != 'H':
                lig_atoms.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
    if not lig_atoms:
        raise ValueError(f'ligand {ligand} not found')
    n = len(lig_atoms)
    return protein, tuple(sum(a[i] for a in lig_atoms) / n for i in range(3)), n


def dist(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


# ── Part I ──────────────────────────────────────────────────────────────────
def pdb_sequence_and_checks(text):
    seq, seen, finite, bfac_ok = [], None, True, True
    for line in text.splitlines():
        if not line.startswith('ATOM'):
            continue
        xyz = [float(line[a:b]) for a, b in ((30, 38), (38, 46), (46, 54))]
        finite &= all(math.isfinite(v) for v in xyz)
        b = float(line[60:66])
        bfac_ok &= 0.0 <= b <= 100.0
        key = (line[21], line[22:26], line[26])
        if key != seen:
            seen = key
            seq.append(AA3.get(line[17:20].strip(), 'X'))
    return ''.join(seq), finite, bfac_ok


def minimal_pdb(n_residues):
    lines, serial = [], 1
    for r in range(1, n_residues + 1):
        for name, x in (('N', 0.0), ('CA', 1.4), ('C', 2.4)):
            lines.append(f'ATOM  {serial:5d} {name:<4s} ALA A{r:4d}    {x + 3.8 * r:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00 20.00           {name[0]:>2s}')
            serial += 1
    return '\n'.join(lines) + '\n'


def run(manifest, ctx):
    import ramachandran
    from agents import target_analyst

    client = Client()
    items = []
    # ── Part R ──
    tol = manifest['angle_tolerance_deg']
    tot = {'matched': 0, 'angle_ok': 0, 'class_ok': 0}
    confusion, per_entry = {}, {}
    for pdb in manifest['rama_entries']:
        try:
            mumo = ramachandran.compute(client.pdb_text(pdb))
            if '_error' in mumo:
                raise RuntimeError(mumo['_error'])
            stats = compare_rama(mumo, report_residues(client.validation_xml(pdb)), tol)
            for k in tot:
                tot[k] += stats[k]
            for k, v in stats['confusion'].items():
                confusion[k] = confusion.get(k, 0) + v
            a_frac = stats['angle_ok'] / stats['matched'] if stats['matched'] else 0
            c_frac = stats['class_ok'] / stats['matched'] if stats['matched'] else 0
            per_entry[pdb] = {'matched': stats['matched'], 'angle_fraction': round(a_frac, 4),
                              'class_agreement': round(c_frac, 4)}
            ok = (stats['matched'] > 0 and a_frac >= manifest['angle_min_fraction']
                  and c_frac >= manifest['class_min_agreement'])
            items.append({'item': f'R:{pdb}', 'status': 'PASS' if ok else 'FAIL', 'details': stats | per_entry[pdb]})
        except Exception as exc:  # errors stay in the denominator
            items.append({'item': f'R:{pdb}', 'status': 'ERROR', 'details': {'error': f'{type(exc).__name__}: {exc}'}})
    r_err = sum(1 for i in items if i['item'].startswith('R:') and i['status'] == 'ERROR')

    # ── Part P ──
    thresh = manifest['dcc_threshold_angstrom']
    p_ok, base_ok, p_rows = 0, 0, []
    for cx in manifest['pocket_complexes']:
        name = f"P:{cx['pdb']}/{cx['ligand']}"
        try:
            protein, lig, n_lig = parse_complex(client.pdb_text(cx['pdb']), cx['ligand'])
            started = time.time()
            pocket = target_analyst.detect_pocket(protein)
            seconds = round(time.time() - started, 2)
            centroid = tuple(sum(a[i] for a in protein) / len(protein) for i in range(3))
            base_d = dist(centroid, lig)
            base_ok += base_d <= thresh
            if pocket is None:
                items.append({'item': name, 'status': 'FAIL', 'details': {
                    'outcome': 'no pocket returned', 'baseline_dcc': round(base_d, 2)}})
                p_rows.append((name, None, base_d))
                continue
            center, size = pocket
            d = dist(center, lig)
            inside = all(abs(c - l) <= size[0] / 2 for c, l in zip(center, lig))
            p_ok += d <= thresh
            p_rows.append((name, d, base_d))
            items.append({'item': name, 'status': 'PASS' if d <= thresh else 'FAIL', 'details': {
                'dcc': round(d, 2), 'baseline_dcc': round(base_d, 2), 'box_size': size[0],
                'ligand_centroid_inside_box': inside, 'ligand_heavy_atoms': n_lig, 'seconds': seconds}})
        except Exception as exc:
            p_rows.append((name, None, None))
            items.append({'item': name, 'status': 'ERROR', 'details': {'error': f'{type(exc).__name__}: {exc}'}})

    # ── Part I ──
    i1, i2 = [], []
    cache = tempfile.mkdtemp(prefix='atlas_validation_')
    for g in manifest['identity_genes']:
        gene, uni = g['gene'], g['uniprot']
        details = {}
        try:
            acc = target_analyst.gene_to_uniprot(gene)
            details['accession'] = acc
            i1.append(acc == uni)
        except Exception as exc:
            i1.append(False)
            details['i1_error'] = f'{type(exc).__name__}: {exc}'
        try:
            path = target_analyst.download_alphafold(uni, cache)
            seq, finite, bfac = pdb_sequence_and_checks(Path(path).read_text())
            meta = json.loads(Path(path).with_suffix('.source.json').read_text())
            fasta = client.fetch(f'https://rest.uniprot.org/uniprotkb/{uni}.fasta').text
            canon = ''.join(fasta.splitlines()[1:])
            start, end = meta.get('uniprot_start') or 1, meta.get('uniprot_end') or len(canon)
            same = seq == canon[start - 1:end]
            i2.append(same and finite and bfac)
            details.update(sequence_equal=same, finite=finite, plddt_in_range=bfac, model_length=len(seq),
                           uniprot_length=len(canon), model_range=[start, end])
        except Exception as exc:
            i2.append(False)
            details['i2_error'] = f'{type(exc).__name__}: {exc}'
        ok = i1[-1] and i2[-1]
        items.append({'item': f'I:{gene}', 'status': 'PASS' if ok else ('ERROR' if ('i1_error' in details or 'i2_error' in details) else 'FAIL'),
                      'details': details})

    # ── I3 faults ──
    i3 = []
    def fault(name, fn):
        try:
            passed, detail = fn()
        except Exception as exc:
            passed, detail = False, f'raised {type(exc).__name__}: {exc}'
        i3.append(passed)
        items.append({'item': name, 'status': 'PASS' if passed else 'FAIL', 'details': {'outcome': detail}})

    def unknown_gene():
        try:
            target_analyst.gene_to_uniprot('zzqxnotagene')
        except ValueError as exc:
            return True, f'ValueError: {exc}'
        return False, 'no ValueError'

    def rama_error(text):
        def check():
            out = ramachandran.compute(text)
            return (isinstance(out, dict) and '_error' in out), 'error record' if '_error' in out else 'no error record'
        return check

    fault('fault:unknown_gene', unknown_gene)
    fault('fault:rama_empty', rama_error(''))
    fault('fault:rama_non_pdb', rama_error('this is not a structure file\n'))
    fault('fault:rama_two_residues', rama_error(minimal_pdb(2)))

    n_r = tot['matched']
    a_frac = tot['angle_ok'] / n_r if n_r else 0.0
    c_frac = tot['class_ok'] / n_r if n_r else 0.0
    n_p = len(manifest['pocket_complexes'])
    p_rate = p_ok / n_p
    n_g = len(manifest['identity_genes'])
    criteria = [
        {'id': 'R1', 'description': f"phi/psi within {tol} deg of wwPDB for >= {manifest['angle_min_fraction']} of matched residues",
         'passed': n_r > 0 and r_err == 0 and a_frac >= manifest['angle_min_fraction'],
         'value': f"{tot['angle_ok']}/{n_r} = {a_frac:.4f} over {len(manifest['rama_entries']) - r_err} entries ({r_err} errors)"},
        {'id': 'R2', 'description': f"three-class agreement with wwPDB >= {manifest['class_min_agreement']}",
         'passed': n_r > 0 and r_err == 0 and c_frac >= manifest['class_min_agreement'],
         'value': f"{tot['class_ok']}/{n_r} = {c_frac:.4f}"},
        {'id': 'P1', 'description': f"DCC <= {thresh} A for >= {manifest['pocket_min_success_rate']} of complexes and more than the centroid baseline",
         'passed': p_rate >= manifest['pocket_min_success_rate'] and p_ok > base_ok,
         'value': f'{p_ok}/{n_p} detector vs {base_ok}/{n_p} centroid baseline'},
        {'id': 'I1', 'description': 'gene_to_uniprot equals manifest accession (10 of 10)',
         'passed': len(i1) == n_g and all(i1), 'value': f'{sum(i1)}/{n_g}'},
        {'id': 'I2', 'description': 'AlphaFold model sequence equals UniProt canonical, coordinates valid (10 of 10)',
         'passed': len(i2) == n_g and all(i2), 'value': f'{sum(i2)}/{n_g}'},
        {'id': 'I3', 'description': 'bad input fails safely (4 of 4)',
         'passed': len(i3) == 4 and all(i3), 'value': f'{sum(i3)}/{len(i3)}'},
    ]
    tp = confusion.get('outlier->outlier', 0)
    fn = sum(v for k, v in confusion.items() if k.startswith('outlier->') and k != 'outlier->outlier')
    fp = sum(v for k, v in confusion.items() if k.endswith('->outlier') and not k.startswith('outlier->'))
    extras = {
        'http_requests': client.requests, 'rama_pooled': {'matched': n_r, 'angle_fraction': a_frac, 'class_agreement': c_frac},
        'confusion_wwpdb_to_mumo': confusion,
        'outlier_recall_vs_wwpdb': tp / (tp + fn) if tp + fn else None,
        'outlier_precision_vs_wwpdb': tp / (tp + fp) if tp + fp else None,
        'per_entry': per_entry,
        'pocket': [{'item': n, 'dcc': d, 'baseline_dcc': b} for n, d, b in p_rows],
        'p2rank_run': False, 'java_available': False,
    }
    return items, criteria, extras
