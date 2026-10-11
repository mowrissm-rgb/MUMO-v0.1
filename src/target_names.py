"""Conservative target aliases and explicit structure identifiers."""
import re
from copy import deepcopy

_ALIASES = {
    'er alpha': 'ESR1', 'eralpha': 'ESR1', 'er a': 'ESR1',
    'estrogen receptor alpha': 'ESR1', 'er beta': 'ESR2',
    'estrogen receptor beta': 'ESR2', 'her2': 'ERBB2', 'her 2': 'ERBB2',
    'pi3k alpha': 'PIK3CA', 'pi3kalpha': 'PIK3CA', 'pde5': 'PDE5A',
    'cox 1': 'PTGS1', 'cox1': 'PTGS1', 'cox 2': 'PTGS2', 'cox2': 'PTGS2',
    'inos': 'NOS2', 'tnf alpha': 'TNF', 'thrombin': 'F2',
    'factor xa': 'F10', 'plasmin': 'PLG', 'tpa': 'PLAT',
    'tissue plasminogen activator': 'PLAT',
    'il 6': 'IL6', 'il6': 'IL6', 'interleukin 6': 'IL6',
    'nf kappa b p65': 'RELA', 'nf kb p65': 'RELA', 'nfkb p65': 'RELA',
    'nf kappa b p50': 'NFKB1', 'nf kb p50': 'NFKB1', 'nfkb p50': 'NFKB1',
    'p65': 'RELA', 'p50': 'NFKB1', 'p52': 'NFKB2', 'relb': 'RELB', 'c rel': 'REL',
    'nf kappa b p52': 'NFKB2', 'nf kb p52': 'NFKB2', 'nfkb p52': 'NFKB2',
    'nf kappa b relb': 'RELB', 'nf kb relb': 'RELB', 'nfkb relb': 'RELB',
    'nf kappa b c rel': 'REL', 'nf kb c rel': 'REL', 'nfkb c rel': 'REL',
}

_NF_MEMBERS = {'RELA', 'NFKB1', 'NFKB2', 'RELB', 'REL'}
_NF_PATTERN = re.compile(r'\bNF[\s-]*(?:κ|kappa|k)[\s-]*B\b', re.I)


def _nf_family(name):
    try:
        canonical_gene(name)
    except ValueError:
        return True
    return False


def nfkb_clarification(actions, convo):
    """Pause structure-dependent work before resolving ligands or launching jobs."""
    if not set(actions or []).intersection({'dock', 'ramachandran'}):
        return None
    if not any(_nf_family(t) for t in split_targets(convo.get('target'))):
        return None
    prompt = (
        'NF-κB is a family, not one protein. Which member or exact PDB structure should I dock?\n\n'
        '- **RELA (p65):** commonly activates inflammatory and immune-response genes.\n'
        '- **NFKB1 (p50; made from p105):** partners with p65; p50 dimers can regulate or repress transcription.\n'
        '- **NFKB2 (p52; made from p100):** often partners with RelB in the alternative NF-κB pathway.\n'
        '- **RELB (RelB):** involved in alternative-pathway immune regulation.\n'
        '- **REL (c-Rel):** involved in lymphocyte activation and immune regulation.\n\n'
        'Reply with p65, p50, p52, RelB, c-Rel, or a PDB ID. Choose the member relevant to your study; '
        'there is no universal best docking target. For mature p50/p52 or a particular complex, '
        'an exact PDB ID avoids using the full p105/p100 precursor. I will keep your other targets and ligands. '
        'Reply cancel to discard this pending request.'
    )
    return {'actions': list(actions), 'convo': deepcopy(convo), 'prompt': prompt}


def resume_nfkb_choice(pending, reply):
    text = str(reply).strip().strip('.!')
    if re.fullmatch(r'[1-9][A-Za-z0-9]{3}', text):
        choice = text.upper()
    else:
        try:
            choice = canonical_gene(text).upper()
        except ValueError:
            return None
        if choice not in _NF_MEMBERS:
            return None
    convo = deepcopy(pending['convo'])
    convo['target'] = [choice if _nf_family(t) else t for t in split_targets(convo.get('target'))]
    return {'actions': list(pending['actions']), 'convo': convo}


def preserve_nfkb_request(targets, message):
    """Do not let model slot extraction erase an explicit NF-κB structure choice."""
    match = _NF_PATTERN.search(str(message))
    if not match:
        return targets
    tail = str(message)[match.end():]
    pdb = re.match(r'\s*\(\s*([1-9][A-Za-z0-9]{3})\s*\)', tail)
    subunit = re.match(r'\s*(p65|p50|p52|RelB|c-Rel|RELA|NFKB1|NFKB2|REL)\b', tail, re.I)
    choice = pdb.group(1).upper() if pdb else canonical_gene(subunit.group(1)).upper() if subunit else 'NF-κB'
    values = split_targets(targets)
    has_family = any(_nf_family(v) for v in values)
    replaced = False
    for i, value in enumerate(values):
        gene = None if _nf_family(value) else canonical_gene(value).upper()
        explicitly_named = bool(gene and re.search(r'\b' + re.escape(gene) + r'\b', str(message), re.I))
        if _nf_family(value) or (not has_family and gene in _NF_MEMBERS and not explicitly_named):
            values[i] = choice
            replaced = True
    if not replaced and choice not in values:
        values.append(choice)
    return list(dict.fromkeys(values))


def canonical_gene(name):
    text = str(name).strip()
    key = text.lower().replace('α', ' alpha').replace('β', ' beta').replace('κ', ' kappa ')
    key = re.sub(r'[-_\s–—−]+', ' ', key).strip()
    if key in {'nfkb', 'nf kb', 'nf kappa b', 'nuclear factor kappa b'}:
        raise ValueError('NF-κB names a protein family. Specify RELA (p65), NFKB1 (p50/p105), '
                         'another subunit, or the exact PDB ID used in your previous run.')
    return _ALIASES.get(key, text)


def split_targets(value):
    """Split a batch without asking the language model to invent structures.

    Explicit PDB identifiers take precedence within each comma/list item.
    Unknown target names are retained for the resolver to explain.
    """
    values = value if isinstance(value, (list, tuple)) else [value]
    result = []
    for item in values:
        for part in re.split(r'[,;\n]+|\s+\+\s+|\s+and\s+', str(item or ''), flags=re.I):
            part = re.sub(r'^\s*\d+[.)]\s*', '', part).strip()
            if not part:
                continue
            pdbs = re.findall(r'(?<![A-Za-z0-9])[1-9][A-Za-z0-9]{3}(?![A-Za-z0-9])', part)
            result.extend([p.upper() for p in pdbs] if pdbs else [part])
    return list(dict.fromkeys(result))
