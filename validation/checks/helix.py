"""Helix check: fidelity of agents.blast_analyst to an independent blastp run.

Protocol: validation/PROTOCOL.md, section "Helix: BLAST sequence search".
The reference uses the same BLAST+ and database, so this tests MUMO's wrapper,
not BLAST's accuracy.
"""
import hashlib
import os
import subprocess
import tempfile
import time
from pathlib import Path

import requests


def fetch_fasta(accession):
    for attempt in range(4):
        try:
            resp = requests.get(f'https://rest.uniprot.org/uniprotkb/{accession}.fasta', timeout=60)
            if resp.status_code not in (429, 500, 502, 503, 504) or attempt == 3:
                resp.raise_for_status()
                return ''.join(resp.text.splitlines()[1:])
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 3:
                raise
        time.sleep(1.0 * (2 ** attempt))


def parse_independent(text):
    """Best (highest bit score) alignment per subject: {accession: (pident, evalue, bitscore)}."""
    best = {}
    for line in text.splitlines():
        parts = line.split('\t')
        if len(parts) < 5:
            continue
        sseqid, pident, _length, evalue, bitscore = parts[:5]
        acc = sseqid.split('|')[1] if sseqid.count('|') >= 2 else sseqid
        row = (float(pident), float(evalue), float(bitscore))
        if acc not in best or row[2] > best[acc][2]:
            best[acc] = row
    return best


def ranked(best):
    return sorted(best.items(), key=lambda kv: (-kv[1][2], kv[1][1]))


def independent_blastp(blastp, db, seq):
    with tempfile.TemporaryDirectory(prefix='helix_ref_') as tmp:
        query = Path(tmp, 'q.fasta')
        query.write_text(f'>q{chr(10)}{seq}{chr(10)}')
        proc = subprocess.run(
            [blastp, '-query', str(query), '-db', db, '-outfmt', '6 sseqid pident length evalue bitscore',
             '-max_target_seqs', '5000', '-evalue', '10', '-num_threads', str(os.cpu_count() or 2)],
            capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            raise RuntimeError('reference blastp failed: ' + (proc.stderr or '')[:200])
        return parse_independent(proc.stdout)


def compare_hits(helix_hits, independent, k, bit_tol, ident_tol, eval_rel):
    """H2 (a)-(c). Returns (ok, details)."""
    order = ranked(independent)
    cutoff = order[k - 1][1][2] if len(order) >= k else None
    required = {a for a, v in independent.items() if cutoff is None or v[2] > cutoff}
    got = {h['accession'] for h in helix_hits}
    missing = sorted(required - got)
    mismatched = []
    for h in helix_hits:
        ref = independent.get(h['accession'])
        if ref is None:
            mismatched.append((h['accession'], 'not in independent results'))
            continue
        pident, evalue, bits = ref
        eval_ok = (h['evalue'] == evalue if evalue == 0 or h['evalue'] == 0
                   else abs(h['evalue'] - evalue) <= eval_rel * evalue)
        if abs(h['bit_score'] - bits) > bit_tol or abs(h['identity'] - pident) > ident_tol or not eval_ok:
            mismatched.append((h['accession'], f"helix {h['bit_score']}/{h['identity']}/{h['evalue']} vs {bits}/{pident}/{evalue}"))
    scores = [h['bit_score'] for h in helix_hits]
    ordered = all(a >= b for a, b in zip(scores, scores[1:]))
    return (not missing and not mismatched and ordered), {
        'missing_from_helix': missing[:8], 'value_mismatches': mismatched[:5], 'order_ok': ordered,
        'n_helix': len(helix_hits), 'n_independent_total': len(independent)}


def run(manifest, ctx):
    from validation.harness import ROOT, sha256_file  # noqa: F401

    blast_bin = str(ROOT / manifest['blast_bin'])
    blastp = str(Path(blast_bin) / 'blastp.exe')
    out = subprocess.run([blastp, '-version'], capture_output=True, text=True, timeout=60).stdout
    if manifest['blast_expected_version'] not in out:
        raise RuntimeError('BLAST+ version differs from the frozen protocol: ' + out[:80])
    os.environ['MUMO_BLAST_DB'] = manifest['blast_db']
    os.environ['PATH'] = blast_bin + os.pathsep + os.environ['PATH']
    from agents import blast_analyst  # imported after the environment is set (module-level DB path)

    k, bit_tol = manifest['max_hits'], manifest['bitscore_tolerance']
    ident_tol, eval_rel = manifest['identity_tolerance'], manifest['evalue_relative_tolerance']
    items, h1, h2, h3, h5 = [], [], [], [], []
    helix_cache, paralog_denominator = {}, 0
    selfhits = {}

    for t in manifest['targets']:
        gene, uni = t['gene'], t['uniprot']
        details = {}
        try:
            started = time.time()
            res = blast_analyst.analyze_blast(gene)
            details['helix_seconds'] = round(time.time() - started, 1)
            helix_cache[gene] = res
            canon = fetch_fasta(uni)
            c1 = res['accession'] == uni and res['seq_len'] == len(canon)
            h1.append(c1)
            independent = independent_blastp(blastp, manifest['blast_db'], canon)
            c2, d2 = compare_hits(res['hits'], independent, k, bit_tol, ident_tol, eval_rel)
            h2.append(c2)
            top = res['hits'][0] if res['hits'] else {}
            selfhits[gene] = {'accession': top.get('accession'), 'identity': top.get('identity'),
                              'evalue': top.get('evalue')}
            found = {h['accession'] for h in res['hits']}
            if t['paralogs']:
                paralog_denominator += 1
                c3 = all(p in found for p in t['paralogs'])
                h3.append(c3)
                details['paralogs_missing'] = [p for p in t['paralogs'] if p not in found]
            details.update(h1_identity=c1, h2_fidelity=c2, h2=d2, accession=res['accession'], seq_len=res['seq_len'],
                           canonical_len=len(canon))
            items.append({'item': gene, 'status': 'PASS' if (c1 and c2) else 'FAIL', 'details': details})
        except Exception as exc:  # errors stay in the denominator
            h1.append(False)
            h2.append(False)
            if t['paralogs']:
                paralog_denominator += 1
                h3.append(False)
            items.append({'item': gene, 'status': 'ERROR', 'details': {'error': f'{type(exc).__name__}: {exc}'}})

    # ── H5 raw sequence path ──
    for gene in manifest['raw_sequence_subset']:
        uni = next(t['uniprot'] for t in manifest['targets'] if t['gene'] == gene)
        try:
            raw = blast_analyst.analyze_blast(fetch_fasta(uni))
            by_gene = [h['accession'] for h in helix_cache[gene]['hits']]
            same = [h['accession'] for h in raw['hits']] == by_gene
            h5.append(same)
            items.append({'item': f'H5:{gene}', 'status': 'PASS' if same else 'FAIL',
                          'details': {'same_accessions_same_order': same, 'raw_accession_field': raw['accession']}})
        except Exception as exc:
            h5.append(False)
            items.append({'item': f'H5:{gene}', 'status': 'ERROR', 'details': {'error': f'{type(exc).__name__}: {exc}'}})

    # ── H4 faults ──
    h4 = []
    for f in manifest['faults']:
        saved = os.environ['PATH']
        if f.get('empty_path'):
            os.environ['PATH'] = ''
        try:
            blast_analyst.analyze_blast(f['query'])
            ok, detail = False, 'no exception raised'
        except ValueError as exc:
            ok, detail = f['expect'] == 'ValueError', f'ValueError: {str(exc)[:100]}'
        except Exception as exc:
            ok, detail = f['expect'] == 'any exception', f'{type(exc).__name__}: {str(exc)[:100]}'
        finally:
            os.environ['PATH'] = saved
        h4.append(ok)
        items.append({'item': f['name'], 'status': 'PASS' if ok else 'FAIL', 'details': {'outcome': detail}})

    n = len(manifest['targets'])
    criteria = [
        {'id': 'H1', 'description': 'accession and sequence length match UniProt (10 of 10)',
         'passed': len(h1) == n and all(h1), 'value': f'{sum(h1)}/{n}'},
        {'id': 'H2', 'description': 'top-25 hits, values and order equal the independent blastp (10 of 10)',
         'passed': len(h2) == n and all(h2), 'value': f'{sum(h2)}/{n}'},
        {'id': 'H3', 'description': f"known paralogues in the top 25 (at least {manifest['paralog_min_items']} of {paralog_denominator})",
         'passed': sum(h3) >= manifest['paralog_min_items'], 'value': f'{sum(h3)}/{paralog_denominator}'},
        {'id': 'H4', 'description': 'bad input raises as specified (4 of 4)',
         'passed': len(h4) == 4 and all(h4), 'value': f'{sum(h4)}/{len(h4)}'},
        {'id': 'H5', 'description': 'raw-sequence path equals gene-name path (3 of 3)',
         'passed': len(h5) == 3 and all(h5), 'value': f'{sum(h5)}/{len(h5)}'},
    ]
    extras = {'blast_version': out.strip().splitlines()[0], 'swissprot_fasta_gz_sha256': manifest['swissprot_fasta_gz_sha256'],
              'swissprot_sequences': manifest['swissprot_sequences'], 'self_hits': selfhits,
              'not_tested': ['other databases', 'NCBI web BLAST', 'alignment and phylogeny views']}
    return items, criteria, extras
