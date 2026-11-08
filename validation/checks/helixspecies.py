"""Helix species filter and hit count: fidelity to an independent blastp restricted to one organism.

Protocol: validation/PROTOCOL.md, "Version 1.6". The reference uses the same BLAST+ and database
and filters on the organism name in the UniProt header itself, so this tests MUMO's wrapper.
"""
import os
import re
import subprocess
import tempfile
from pathlib import Path

from validation.checks.helix import fetch_fasta


def independent_with_organism(blastp, db, seq):
    """Best alignment per subject: {accession: (pident, evalue, bitscore, organism)}."""
    with tempfile.TemporaryDirectory(prefix='helixsp_ref_') as tmp:
        query = Path(tmp, 'q.fasta')
        query.write_text(f'>q{chr(10)}{seq}{chr(10)}')
        proc = subprocess.run(
            [blastp, '-query', str(query), '-db', db,
             '-outfmt', '6 sseqid pident length evalue bitscore stitle',
             '-max_target_seqs', '5000', '-evalue', '10', '-num_threads', str(os.cpu_count() or 2)],
            capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            raise RuntimeError('reference blastp failed: ' + (proc.stderr or '')[:200])
    best = {}
    for line in proc.stdout.splitlines():
        parts = line.split('\t')
        if len(parts) < 6:
            continue
        sseqid, pident, _length, evalue, bitscore, stitle = parts[:6]
        acc = sseqid.split('|')[1] if sseqid.count('|') >= 2 else sseqid
        m = re.search(r'OS=(.+?)(?:\s+(?:OX|GN|PE|SV)=|$)', stitle)
        row = (float(pident), float(evalue), float(bitscore), m.group(1).strip() if m else '')
        if acc not in best or row[2] > best[acc][2]:
            best[acc] = row
    return best


def expected_top(independent, organism, k):
    pool = {a: v for a, v in independent.items() if organism is None or organism.lower() in v[3].lower()}
    order = sorted(pool.items(), key=lambda kv: (-kv[1][2], kv[1][1]))
    return pool, order, (order[k - 1][1][2] if len(order) >= k else None)


def compare(helix_hits, independent, organism, k, bit_tol, ident_tol, eval_rel):
    pool, _order, cutoff = expected_top(independent, organism, k)
    required = {a for a, v in pool.items() if cutoff is None or v[2] > cutoff}
    got = [h['accession'] for h in helix_hits]
    missing = sorted(required - set(got))
    bad = []
    for h in helix_hits:
        ref = pool.get(h['accession'])
        if ref is None:
            bad.append((h['accession'], 'not an expected hit (absent, or wrong organism)'))
            continue
        pident, evalue, bits, _org = ref
        eval_ok = (h['evalue'] == evalue if evalue == 0 or h['evalue'] == 0
                   else abs(h['evalue'] - evalue) <= eval_rel * evalue)
        if abs(h['bit_score'] - bits) > bit_tol or abs(h['identity'] - pident) > ident_tol or not eval_ok:
            bad.append((h['accession'], f"helix {h['bit_score']}/{h['identity']}/{h['evalue']} vs {bits}/{pident}/{evalue}"))
    scores = [h['bit_score'] for h in helix_hits]
    ordered = all(a >= b for a, b in zip(scores, scores[1:]))
    count_ok = len(helix_hits) == min(k, len(pool))
    return (not missing and not bad and ordered and count_ok), {
        'missing': missing[:8], 'mismatched': bad[:5], 'ordered': ordered, 'count_ok': count_ok,
        'n_helix': len(helix_hits), 'n_expected_pool': len(pool)}


def run(manifest, ctx):
    from validation.harness import ROOT

    blast_bin = str(ROOT / manifest['blast_bin'])
    blastp = str(Path(blast_bin) / 'blastp.exe')
    out = subprocess.run([blastp, '-version'], capture_output=True, text=True, timeout=60).stdout
    if manifest['blast_expected_version'] not in out:
        raise RuntimeError('BLAST+ version differs from the frozen protocol: ' + out[:80])
    os.environ['MUMO_BLAST_DB'] = manifest['blast_db']
    os.environ['PATH'] = blast_bin + os.pathsep + os.environ['PATH']
    from agents import blast_analyst

    k, org = manifest['max_hits'], manifest['organism']
    tol = (manifest['bitscore_tolerance'], manifest['identity_tolerance'], manifest['evalue_relative_tolerance'])
    items, f1, f2, f3, f4, f5 = [], [], [], [], [], []
    for t in manifest['targets']:
        gene, uni = t['gene'], t['uniprot']
        d = {}
        try:
            seq = fetch_fasta(uni)
            independent = independent_with_organism(blastp, manifest['blast_db'], seq)
            filt = blast_analyst.analyze_blast(seq, hit_organism=org)['hits']
            plain = blast_analyst.analyze_blast(seq)['hits']
            wide = blast_analyst.analyze_blast(seq, max_hits=2 * k, hit_organism=org)['hits']
            ok1, d1 = compare(filt, independent, org, k, *tol)
            ok2, d2 = compare(plain, independent, None, k, *tol)
            found_f = {h['accession'] for h in filt}
            found_p = {h['accession'] for h in plain}
            para_f = [p for p in t['paralogs'] if p in found_f]
            para_p = [p for p in t['paralogs'] if p in found_p]
            ok3 = len(para_f) == len(t['paralogs'])
            ok4 = len(para_f) >= len(para_p)
            ok5 = ([h['accession'] for h in wide[:k]] == [h['accession'] for h in filt]
                   and len(wide) == min(2 * k, d1['n_expected_pool']))
            f1.append(ok1); f2.append(ok2); f3.append(ok3); f4.append(ok4); f5.append(ok5)
            d.update(f1=ok1, f1_detail=d1, f2=ok2, f2_detail=d2, paralogs_with_filter=para_f,
                     paralogs_without_filter=para_p, paralogs_missing_with_filter=[p for p in t['paralogs'] if p not in found_f],
                     f5=ok5, n_wide=len(wide))
            items.append({'item': gene, 'status': 'PASS' if (ok1 and ok2 and ok5) else 'FAIL', 'details': d})
        except Exception as exc:  # errors stay in every denominator
            f1.append(False); f2.append(False); f3.append(False); f4.append(False); f5.append(False)
            items.append({'item': gene, 'status': 'ERROR', 'details': {'error': f'{type(exc).__name__}: {exc}'}})

    n = len(manifest['targets'])
    gained = sum(1 for i in items if i['status'] != 'ERROR'
                 and len(i['details']['paralogs_with_filter']) > len(i['details']['paralogs_without_filter']))
    criteria = [
        {'id': 'HF1', 'description': f'filtered top-{k} equals the independent blastp restricted to {org} (all targets)',
         'passed': len(f1) == n and all(f1), 'value': f'{sum(f1)}/{n}'},
        {'id': 'HF2', 'description': 'unfiltered default output still equals the independent blastp (all targets)',
         'passed': len(f2) == n and all(f2), 'value': f'{sum(f2)}/{n}'},
        {'id': 'HF3', 'description': f"all listed human paralogues in the filtered top {k} (at least {manifest['paralog_min_items']} of {n} targets)",
         'passed': sum(f3) >= manifest['paralog_min_items'], 'value': f'{sum(f3)}/{n}'},
        {'id': 'HF4', 'description': 'the filter never recovers fewer paralogues than no filter, and recovers more for at least one target',
         'passed': len(f4) == n and all(f4) and gained >= 1, 'value': f'never fewer {sum(f4)}/{n}; more for {gained} targets'},
        {'id': 'HF5', 'description': f'max_hits={2 * k} returns twice as many hits and its first {k} equal the {k}-hit list (all targets)',
         'passed': len(f5) == n and all(f5), 'value': f'{sum(f5)}/{n}'},
    ]
    extras = {'blast_version': out.strip().splitlines()[0], 'swissprot_fasta_gz_sha256': manifest['swissprot_fasta_gz_sha256'],
              'not_tested': ['species filters other than a scientific-name match', 'the chat front door (not wired to these options)',
                             'databases other than Swiss-Prot']}
    return items, criteria, extras
