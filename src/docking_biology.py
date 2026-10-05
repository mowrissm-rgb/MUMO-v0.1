"""Stored biological context and per-target candidate ADME, isolated on failure."""
import math
from datetime import datetime, timezone
from protein_identity import UNIPROT_ACCESSION


def select_candidates(rows):
    selected, best = {}, {}
    for row in rows:
        target = row.get('Target')
        if isinstance(row.get('Best affinity (kcal/mol)'), bool) or str(
                row.get('Verification status', '')).lower() in ('failed', 'unavailable'):
            continue
        try:
            score = float(row['Best affinity (kcal/mol)'])
        except (KeyError, TypeError, ValueError):
            continue
        if not target or not math.isfinite(score) or row.get('Interaction status') not in ('verified', 'qualified'):
            continue
        if target not in best or score < best[target] - 1e-9:
            selected[target], best[target] = [dict(row)], score
        elif abs(score - best[target]) <= 1e-9:
            selected[target].append(dict(row))
    return selected


def analyze_lead_adme(rows, descriptor=None, model=None):
    from rdkit import Chem
    from agents.admet import druglikeness, admet_ml
    descriptor, model = descriptor or druglikeness, model or admet_ml
    candidates = select_candidates(rows)
    compounds, errors = {}, []
    for target, selected in candidates.items():
        for row in selected:
            molecule = Chem.MolFromSmiles(row.get('SMILES') or '')
            if molecule is None or molecule.GetNumAtoms() == 0:
                errors.append({'target': target, 'ligand': row.get('Ligand'),
                               'error': 'Invalid input chemical structure'})
                continue
            smiles = Chem.MolToSmiles(molecule, isomericSmiles=True)
            if smiles not in compounds:
                entry = {'smiles': smiles, 'targets': [], 'labels': [],
                         'chemical_state': 'Recorded input structure; not a new docking pose'}
                for name, calculate in [('descriptors', descriptor), ('ml', model)]:
                    try:
                        entry[name] = calculate(smiles)
                    except Exception as error:
                        entry[name] = {'status': 'unavailable', '_error': str(error)}
                compounds[smiles] = entry
            entry = compounds[smiles]
            if target not in entry['targets']:
                entry['targets'].append(target)
            if row.get('Ligand') not in entry['labels']:
                entry['labels'].append(row.get('Ligand'))
    return {'candidates': candidates, 'compounds': list(compounds.values()), 'errors': errors,
            'no_candidate': [t for t in dict.fromkeys(r.get('Target') for r in rows) if t not in candidates],
            'selection': 'Lowest finite score per target among interaction-profiled completed pairs; ties retained',
            'created_at': datetime.now(timezone.utc).isoformat()}


def _resolve_species(accession):
    import requests
    response = requests.get(f'https://rest.uniprot.org/uniprotkb/{accession}.json', timeout=15)
    response.raise_for_status()
    data = response.json()
    if data.get('primaryAccession') != accession:
        raise ValueError('UniProt accession identity did not match')
    species = data.get('organism', {}).get('taxonId')
    if type(species) is not int or species <= 0:
        raise ValueError('UniProt species unavailable')
    return species


def collect_string(targets, analyze=None, resolve_species=None):
    from agents.string_analyst import analyze_string
    analyze = analyze or analyze_string
    resolve_species = resolve_species or _resolve_species
    groups, unmapped, identity_errors, species_cache = {}, [], [], {}
    for target, metadata in targets.items():
        accession = str(metadata.get('accession') or '').strip()
        if not UNIPROT_ACCESSION.fullmatch(accession):
            unmapped.append(target)
            continue
        try:
            species = metadata.get('species')
            if type(species) is not int or species <= 0:
                if accession not in species_cache:
                    species_cache[accession] = resolve_species(accession)
                species = species_cache[accession]
            if type(species) is not int or species <= 0:
                raise ValueError('Verified species unavailable')
        except Exception as error:
            unmapped.append(target)
            identity_errors.append({'target': target, 'error': str(error)})
            continue
        group = groups.setdefault(species, {})
        group[target] = accession
    output = []
    for species, mapping in groups.items():
        group = {'species': species, 'mapping': mapping, 'parameters': {'partner_limit': 20},
                 'enrichment_scope': 'Resolved input proteins and up to 12 highest-ranked functional partners',
                 'source': 'https://string-db.org/api',
                 'created_at': datetime.now(timezone.utc).isoformat()}
        try:
            result = analyze(list(dict.fromkeys(mapping.values())), species=species, limit=20)
            for item in result.get('resolved', []):
                if item.get('ncbiTaxonId') is not None and int(item['ncbiTaxonId']) != species:
                    raise ValueError('STRING returned a mapping for a different species')
                if item.get('stringId') and not str(item['stringId']).startswith(f'{species}.'):
                    raise ValueError('STRING identifier belongs to a different species')
            resolved = {str(r.get('queryItem')) for r in result.get('resolved', [])}
            group['unmapped'] = [target for target, accession in mapping.items() if accession not in resolved]
            group.update(status='partial' if group['unmapped'] or not result.get('network_svg') else 'available',
                         result=result)
        except Exception as error:
            group.update(status='unavailable', error=str(error), unmapped=list(mapping))
        output.append(group)
    return {'groups': output, 'unmapped': unmapped, 'identity_errors': identity_errors}


def enrich_result(result, progress=lambda message: None):
    """Attach executed biology; optional failures cannot discard a docking result."""
    if not result.get('ok') or result.get('partial'):
        return result
    output = dict(result)
    meta = dict(result.get('meta') or {})
    targets = dict(meta.get('per_target') or {})
    for target in meta.get('targets') or [meta.get('gene')]:
        if target:
            targets.setdefault(target, meta if len(meta.get('targets') or []) <= 1 else {})
    biology = {'created_at': datetime.now(timezone.utc).isoformat()}
    for name, action, message in [
            ('string', lambda: collect_string(targets), 'Collecting target STRING context…'),
            ('adme', lambda: analyze_lead_adme(result.get('rows') or []),
             'Calculating ADME for each target’s top docking candidate…')]:
        progress(message)
        try:
            biology[name] = action()
        except Exception as error:
            biology[name] = {'status': 'unavailable', 'error': str(error)}
    meta['biology'] = biology
    output['meta'] = meta
    return output
