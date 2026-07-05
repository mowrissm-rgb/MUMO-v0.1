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

Free — UniProt (gene → sequence) + NCBI BLAST web API. No key, pure requests.
NOTE: BLAST is inherently slow — a search is a JOB that takes ~1–3 minutes.
"""

import re
import time
import requests

UNIPROT = "https://rest.uniprot.org/uniprotkb/search"
NCBI_BLAST = "https://blast.ncbi.nlm.nih.gov/Blast.cgi"
HUMAN = 9606
_AA = set("ACDEFGHIKLMNPQRSTVWYBXZU*")


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


def submit_blast(seq, program="blastp", database="swissprot"):
    """Submit a BLAST job → returns the NCBI request id (RID)."""
    r = requests.post(NCBI_BLAST, data={
        "CMD": "Put", "PROGRAM": program, "DATABASE": database, "QUERY": seq}, timeout=30)
    r.raise_for_status()
    m = re.search(r"RID = (\S+)", r.text)
    if not m:
        raise RuntimeError("NCBI BLAST didn't return a job id — try again shortly.")
    return m.group(1)


def poll_blast(rid, max_wait=240, interval=20, status_cb=None):
    """Poll a BLAST job until READY. Raises on failure/timeout."""
    waited = 0
    while waited < max_wait:
        txt = requests.get(NCBI_BLAST, params={
            "CMD": "Get", "RID": rid, "FORMAT_OBJECT": "SearchInfo"}, timeout=30).text
        if "Status=READY" in txt:
            return True
        if "Status=UNKNOWN" in txt or "Status=FAILED" in txt:
            raise RuntimeError("The BLAST job failed or expired — please try again.")
        if status_cb:
            status_cb(waited)
        time.sleep(interval)
        waited += interval
    raise TimeoutError("BLAST is taking longer than usual — try again in a moment.")


def get_results(rid, max_hits=25):
    """Fetch + parse BLAST hits → list of {accession, title, sciname, identity, evalue, ...}."""
    d = requests.get(NCBI_BLAST, params={
        "CMD": "Get", "RID": rid, "FORMAT_TYPE": "JSON2_S"}, timeout=60).json()
    hits = d["BlastOutput2"][0]["report"]["results"]["search"].get("hits", [])
    out = []
    for h in hits[:max_hits]:
        desc = h["description"][0]
        hsp = h["hsps"][0]
        out.append({
            "accession": desc.get("accession", ""),
            "title": desc.get("title", ""),
            "sciname": desc.get("sciname", ""),
            "identity": round(100 * hsp["identity"] / hsp["align_len"], 1),
            "evalue": hsp["evalue"],
            "bit_score": round(hsp.get("bit_score", 0), 1),
            "align_len": hsp["align_len"],
        })
    return out


def analyze_blast(query, species=HUMAN, program="blastp", database="swissprot", status_cb=None):
    """
    Full BLAST. `query` = a gene/protein NAME (sequence auto-fetched from UniProt)
    OR a raw sequence / FASTA. Returns:
      query_name, accession, seq_len, hits, database, program, rid.
    Slow (~1–3 min) because BLAST is a remote job.
    """
    if looks_like_sequence(query):
        seq, acc, qname = clean_sequence(query), "", "your sequence"
    else:
        acc, qname, seq = fetch_sequence(query, species)
    if len(seq) < 10:
        raise ValueError("The sequence is too short to BLAST (need ≥10 residues).")
    rid = submit_blast(seq, program, database)
    poll_blast(rid, status_cb=status_cb)
    return {"query_name": qname, "accession": acc, "seq_len": len(seq),
            "hits": get_results(rid), "database": database, "program": program, "rid": rid}


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "DNASE1"
    print(f"BLAST for {q} (this takes a minute)…")
    res = analyze_blast(q, status_cb=lambda w: print(f"  …waited {w}s"))
    print(f"query: {res['query_name']} ({res['accession']}, {res['seq_len']} aa) vs {res['database']}")
    for h in res["hits"][:8]:
        print(f"  {h['accession']:10s} id={h['identity']:5}%  E={h['evalue']:.1e}  {h['title'][:48]}")
