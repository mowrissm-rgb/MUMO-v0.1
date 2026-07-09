"""
MUMO Agent — BLAST Sequence Similarity
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

WHAT THIS AGENT DOES (plain English)
------------------------------------
You give it a protein — as a gene NAME (e.g. 'CFTR'), a RAW sequence, or a FASTA.
It finds the most similar known proteins in public databases using BLAST
(Basic Local Alignment Search Tool — the standard way to ask "what known proteins
look like mine, and how closely?").

It returns, for each hit: the accession, the protein/organism, the % identity
(how similar), and the E-value (how likely the match is just chance — smaller is
better). Great for Project 2 (relating a mucolytic enzyme to known enzymes) and
for building the family that later feeds alignment + a phylogenetic tree.

Gene → sequence via UniProt's REST API (a data service, fine for production).
The similarity search runs on a SELF-HOSTED BLAST+ (public-domain NCBI software)
against a local UniProt SwissProt database baked into the image — no dependency on
NCBI's web BLAST service (which isn't licensed for production/commercial use) and
much faster (seconds, not minutes).
"""

import os
import re
import subprocess
import tempfile
import requests

UNIPROT = "https://rest.uniprot.org/uniprotkb/search"
HUMAN = 9606
_AA = set("ACDEFGHIKLMNPQRSTVWYBXZU*")

# Self-hosted BLAST+ database (built into the container at /opt/blastdb/swissprot).
# Overridable for other environments.
_BLAST_DB = os.environ.get("MUMO_BLAST_DB", "/opt/blastdb/swissprot")


def looks_like_sequence(text):
    """True if the input is a raw protein sequence / FASTA rather than a name."""
    t = str(text).strip()
    if t.startswith(">"):
        return True
    t = re.sub(r"\s+", "", t).upper()
    return len(t) >= 25 and sum(c in _AA for c in t) / max(len(t), 1) > 0.9


def clean_sequence(text):
    """Strip FASTA header + whitespace → a bare uppercase sequence."""
    t = str(text).strip()
    if t.startswith(">"):
        t = "".join(ln for ln in t.splitlines() if not ln.startswith(">"))
    return re.sub(r"\s+", "", t).upper()


def fetch_sequence(gene, species=HUMAN):
    """Gene/protein NAME → (accession, name, sequence) from UniProt (reviewed)."""
    def _q(query):
        r = requests.get(UNIPROT, params={
            "query": query, "fields": "accession,protein_name,sequence",
            "format": "json", "size": 1}, timeout=25)
        r.raise_for_status()
        return r.json().get("results", [])

    res = _q(f"gene_exact:{gene} AND organism_id:{species} AND reviewed:true") \
        or _q(f"{gene} AND organism_id:{species} AND reviewed:true")
    if not res:
        raise ValueError(f"Couldn't find a reviewed protein sequence for “{gene}” in UniProt.")
    it = res[0]
    name = (it.get("proteinDescription", {}).get("recommendedName", {})
              .get("fullName", {}).get("value", gene))
    return it["primaryAccession"], name, it["sequence"]["value"]


def _parse_blast_tab(text, max_hits=25):
    """Parse blastp tabular output (outfmt 6 sseqid pident length evalue bitscore
    stitle) from a UniProt SwissProt DB into hit dicts, keeping ONE (best) HSP per
    subject. UniProt headers carry the organism as 'OS=...' and the accession in
    the 'sp|ACC|NAME' id, so no taxonomy DB is needed."""
    out, seen = [], set()
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        sseqid, pident, length, evalue, bitscore, stitle = parts[:6]
        acc = sseqid.split("|")[1] if sseqid.count("|") >= 2 else sseqid
        if acc in seen:                          # first line per subject = best HSP
            continue
        seen.add(acc)
        m = re.search(r"OS=(.+?)(?:\s+(?:OX|GN|PE|SV)=|$)", stitle)
        sciname = m.group(1).strip() if m else ""
        title = re.split(r"\s+OS=", stitle)[0].strip()
        try:
            out.append({
                "accession": acc, "title": title, "sciname": sciname,
                "identity": round(float(pident), 1),
                "evalue": float(evalue), "bit_score": round(float(bitscore), 1),
                "align_len": int(length),
            })
        except ValueError:
            continue
        if len(out) >= max_hits:
            break
    return out


def run_blastp(seq, max_hits=25, timeout=300):
    """Run the self-hosted blastp against the local SwissProt DB → hit dicts."""
    with tempfile.NamedTemporaryFile("w", suffix=".fasta", delete=False) as f:
        f.write(f">query\n{seq}\n")
        qpath = f.name
    try:
        proc = subprocess.run(
            ["blastp", "-query", qpath, "-db", _BLAST_DB,
             "-outfmt", "6 sseqid pident length evalue bitscore stitle",
             "-max_target_seqs", str(max_hits), "-evalue", "10",
             "-num_threads", str(os.cpu_count() or 2)],
            capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            raise RuntimeError(f"blastp failed: {(proc.stderr or '').strip()[:200]}")
        return _parse_blast_tab(proc.stdout, max_hits)
    finally:
        try:
            os.unlink(qpath)
        except Exception:
            pass


def analyze_blast(query, species=HUMAN, program="blastp", database="swissprot", status_cb=None):
    """
    Full BLAST. `query` = a gene/protein NAME (sequence auto-fetched from UniProt)
    OR a raw sequence / FASTA. Returns:
      query_name, accession, seq_len, hits, database, program, rid.
    Fast — the search runs on the self-hosted BLAST+ (seconds, not minutes).
    """
    if looks_like_sequence(query):
        seq, acc, qname = clean_sequence(query), "", "your sequence"
    else:
        acc, qname, seq = fetch_sequence(query, species)
    if len(seq) < 10:
        raise ValueError("The sequence is too short to BLAST (need ≥10 residues).")
    if status_cb:
        status_cb(0)
    hits = run_blastp(seq)
    return {"query_name": qname, "accession": acc, "seq_len": len(seq),
            "hits": hits, "database": database, "program": program, "rid": "local"}


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "DNASE1"
    print(f"BLAST for {q} (this takes a minute)…")
    res = analyze_blast(q, status_cb=lambda w: print(f"  …waited {w}s"))
    print(f"query: {res['query_name']} ({res['accession']}, {res['seq_len']} aa) vs {res['database']}")
    for h in res["hits"][:8]:
        print(f"  {h['accession']:10s} id={h['identity']:5}%  E={h['evalue']:.1e}  {h['title'][:48]}")
