"""Read coordinate-file identifiers without guessing a gene or species."""
import re

UNIPROT_ACCESSION = re.compile(r'^(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})$')


def extract_identity(pdb_text, chains=None):
    lines = str(pdb_text or '').splitlines()
    kept = set(chains) if chains is not None else None
    accessions = set()
    for line in lines:
        if line.startswith('DBREF ') and len(line) >= 41:
            if kept is not None and line[12].strip() not in kept:
                continue
            accession = line[33:41].strip()
            if line[26:32].strip() == 'UNP' and UNIPROT_ACCESSION.fullmatch(accession):
                accessions.add(accession)
    title = ' '.join(line[10:].strip() for line in lines if line.startswith('TITLE '))
    if not accessions and 'ALPHAFOLD' in title.upper():
        accessions = {value for value in re.findall(r'\(([A-Z0-9]+)\)', title)
                      if UNIPROT_ACCESSION.fullmatch(value)}
    source = ' '.join(line[10:].strip() for line in lines if line.startswith('SOURCE '))
    taxa = {int(value) for value in re.findall(r'ORGANISM_TAXID:\s*(\d+)', source)
            if int(value) > 0}
    pdb_ids = {line[62:66].strip() for line in lines if line.startswith('HEADER') and len(line) >= 66
               and re.fullmatch(r'[1-9][A-Za-z0-9]{3}', line[62:66].strip())}
    return {'accession': next(iter(accessions)) if len(accessions) == 1 else '',
            'accessions': sorted(accessions), 'species': next(iter(taxa)) if len(taxa) == 1 else None,
            'pdb_id': next(iter(pdb_ids)) if len(pdb_ids) == 1 else '',
            'identity_source': 'Input coordinate file headers; ambiguous identifiers are not assigned'}
