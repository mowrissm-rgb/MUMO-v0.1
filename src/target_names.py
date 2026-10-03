"""Conservative target aliases and explicit structure identifiers."""
import re

_ALIASES = {
    'er alpha': 'ESR1', 'eralpha': 'ESR1', 'er a': 'ESR1',
    'estrogen receptor alpha': 'ESR1', 'er beta': 'ESR2',
    'estrogen receptor beta': 'ESR2', 'her2': 'ERBB2', 'her 2': 'ERBB2',
    'pi3k alpha': 'PIK3CA', 'pi3kalpha': 'PIK3CA', 'pde5': 'PDE5A',
    'cox 1': 'PTGS1', 'cox1': 'PTGS1', 'cox 2': 'PTGS2', 'cox2': 'PTGS2',
    'inos': 'NOS2', 'tnf alpha': 'TNF', 'thrombin': 'F2',
    'factor xa': 'F10', 'plasmin': 'PLG', 'tpa': 'PLAT',
    'tissue plasminogen activator': 'PLAT',
}


def canonical_gene(name):
    text = str(name).strip()
    key = text.lower().replace('α', ' alpha').replace('β', ' beta')
    key = re.sub(r'[-_\s]+', ' ', key).strip()
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
