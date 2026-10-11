"""
MUMO — Pipeline engine (UI-agnostic)
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

The actual docking pipeline, with NO Streamlit code, so any front-end (the chat
app, the old form app, or a future React backend) can call it. Progress is
reported through a `status(message)` callback the caller provides.
"""

import os
import hashlib
import copy
from pathlib import Path
from verification import validate_box, validate_docking_result, capture_artifacts, run_record
from agents.target_analyst import analyze_target
from agents.interaction_analyst import analyze_interactions, prepare_receptor_context
from docking_engine import (clean_protein_pdb, prepare_receptor,
                            prepare_ligand, dock_with_replicas, validate_native_redock,
                            estimate_ki, ligand_efficiency, reliability_assessment)


def resolve_receptor(tgt, data_dir):
    """Get (pdb_path, center, size, pocket) for a target: user PDB or gene→AlphaFold."""
    if tgt.get("pdb_path"):
        return tgt["pdb_path"], tgt["center"], tgt["size"], tgt.get("source", "user PDB")
    info = analyze_target(tgt["gene"], data_dir)
    if info.get('accession'):
        tgt.setdefault('accession', info['accession'])
    for key in ('structure_source', 'pdb_id', 'chains', 'fallback_reason', 'annotation_warning'):
        if info.get(key) is not None:
            tgt[key] = info[key]
    if info.get('structure_source'):
        tgt['source'] = info['structure_source']
    tgt.setdefault('species', 9606)
    return info["pdb_path"], info["center"], info["size"], info["pocket_source"]


def prepared_manifest(target, receptor, ligand, center, size, exhaustiveness,
                      replicas, seed, versions, source_smiles=None):
    """Read chemistry from the actual Meeko output, never infer prepared charge."""
    from rdkit import Chem
    text = Path(ligand).read_text(encoding='utf-8')
    smiles = next((line[len('REMARK SMILES '):].strip() for line in text.splitlines()
                   if line.startswith('REMARK SMILES ')), None)
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    state = {'isomeric_smiles': smiles, 'charge': Chem.GetFormalCharge(mol) if mol else None,
             'ph': 7.4}
    if source_smiles is not None:
        state['source_smiles'] = source_smiles
    return {'schema_version': 1,
            'receptor_sha256': hashlib.sha256(Path(receptor).read_bytes()).hexdigest(),
            'ligand_sha256': hashlib.sha256(Path(ligand).read_bytes()).hexdigest(),
            'target_identity': {k: target.get(k) for k in ('accession', 'species', 'chains')},
            'chemical_state': state, 'grid': {'center': list(center), 'size': list(size)},
            'protocol': {'scoring': 'vina', 'exhaustiveness': exhaustiveness,
                         'seeds': [seed+i for i in range(replicas)]},
            'versions': versions,
            'settings': {'preparation': {'ph': 7.4, 'seed': seed, 'n_confs': 4, 'max_rot': 10,
                                        'receptor': 'clean standard complete amino acids; Meeko templates'},
                         'interactions': {'method': 'configured ProLIF contacts',
                                          'hydrogens': 'RDKit residue templates; unoptimized'},
                         'docking': {'num_modes': 6, 'energy_range': 3.0, 'cpu': 'auto',
                                     'consensus': 'Vinardo score-only'}}}


def runtime_versions(vina, venv_dir):
    """Unknown identities cause cache misses. Fingerprint implementation and binary."""
    import importlib.metadata
    import subprocess
    import shutil
    versions = {}
    for name in ('rdkit', 'meeko', 'prolif'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = 'unknown'
    root = Path(__file__).parent
    for name, files in {'preparation': ['docking_engine.py'],
                        'interactions': ['agents/interaction_analyst.py']}.items():
        versions[name] = hashlib.sha256(b''.join((root/f).read_bytes() for f in files)).hexdigest()
    try:
        binary = Path(vina if Path(vina).is_file() else shutil.which(vina) or vina)
        proc = subprocess.run([str(binary), '--version'], capture_output=True, text=True, timeout=10)
        versions['vina'] = (proc.stdout.strip() + ':' + hashlib.sha256(binary.read_bytes()).hexdigest()
                            if proc.returncode == 0 and proc.stdout.strip() else 'unknown')
    except (OSError, subprocess.SubprocessError):
        versions['vina'] = 'unknown'
    # prepare_receptor uses sys.executable, the same installed Meeko as this process.
    versions['receptor_meeko'] = versions['meeko']
    try:
        versions['openbabel'] = importlib.metadata.version('openbabel-wheel')
    except importlib.metadata.PackageNotFoundError:
        versions['openbabel'] = 'unknown'
    return versions


def prepare_docking(tgt, ligands, vina, data_dir, venv_dir, status=lambda m: None,
                  exhaustiveness=None, n_replicas=None, seed=42, checkpoint=None):
    """
    Prepare the receptor once and dock every ligand.

    Search depth (`exhaustiveness`) and `n_replicas` both default to None,
    meaning "choose by screen size" — see the selection below. Passing a number
    overrides either outright.

    That override used to be a lie: the parameter existed, callers passed it,
    and the body ignored it in favour of a hard-coded value. A caller asking for
    a shallow 4 silently got the deep setting, which made the two impossible to
    compare and hid how slow a deep run really was.

    Returns (rows, viz, meta).
    """
    status(f"Building the {tgt['gene']} structure and finding its pocket…")
    pdb_path, center, size, pocket = resolve_receptor(tgt, data_dir)
    validate_box(center, size)

    cleaned = os.path.join(data_dir, "c_cleaned.pdb")
    receptor = os.path.join(data_dir, "c_receptor.pdbqt")
    clean_protein_pdb(pdb_path, cleaned)

    # Does the search box actually contain the protein we are about to dock
    # into? The box is derived from the RAW structure (usually its co-crystal
    # ligand) while docking runs against the CLEANED one, so the two can drift
    # apart — and when they do, Vina reports 0.000 kcal/mol for every ligand
    # without erroring. That is how 1OYT produced twelve identical scores.
    # One cheap count turns a silent, screen-wide corruption into a clear stop.
    _bx, _by, _bz = center
    _hx, _hy, _hz = (s / 2.0 for s in size)
    _inside = 0
    with open(cleaned) as _f:
        for _ln in _f:
            if _ln.startswith("ATOM"):
                try:
                    _x = float(_ln[30:38]); _y = float(_ln[38:46]); _z = float(_ln[46:54])
                except ValueError:
                    continue
                if (abs(_x - _bx) <= _hx and abs(_y - _by) <= _hy
                        and abs(_z - _bz) <= _hz):
                    _inside += 1
    if _inside < 10:
        raise RuntimeError(
            f"The docking box for {tgt.get('gene', 'this target')} contains only "
            f"{_inside} receptor atoms, so no ligand could bind anywhere inside "
            f"it. The pocket and the prepared protein do not line up — usually "
            f"the chain carrying the binding site was removed during cleaning. "
            f"Docking was stopped rather than returning meaningless scores.")
    status(f"Pocket check: {_inside} receptor atoms inside the search box.")

    # Backbone-geometry (Ramachandran) validation of the receptor we are about
    # to dock into. Computed HERE because this is the only point where the full
    # protein exists on disk — the report later only has pocket-cropped
    # complexes, which can't give whole-structure statistics. It is pure
    # geometry on coordinates already read, so it costs effectively nothing,
    # and it answers the question every affinity in this run depends on: is
    # this structure trustworthy enough to dock into at all?
    rama = None
    with open(cleaned, encoding='utf-8') as source:
        validation_pdb_text = source.read()
    try:
        import ramachandran as _rama
        rama = _rama.compute(validation_pdb_text)
    except Exception as exc:
        rama = {"_error": str(exc), "status": "unavailable"}
    dropped = prepare_receptor(cleaned, receptor, venv_dir) or []
    if dropped:
        # Say it out loud. Meeko has no templates for nucleotides/sugars, so a
        # protein-DNA entry like 1NFK only preps after they are removed — and
        # the user must know the receptor is protein-only before reading any
        # affinity from it.
        status(f"Note: {len(dropped)} residues had no chemical template "
               f"(usually DNA/RNA or sugar chains) and were removed from "
               f"{tgt['gene']} — docking against the protein only.")

    single = len(ligands) == 1
    n_lig = len(ligands)
    # Vina time scales with exhaustiveness x box-volume x ligand-flexibility, so
    # on a 2-vCPU free tier all three matter — but 4 was too shallow to be
    # defensible. Vina's own default is 8 and published work uses 16-32; at 4 the
    # search does not converge, which both adds run-to-run noise and blurs the
    # pocket-specific part of the score (measured across a 108-docking matrix:
    # only 7.7% of score variance came from WHICH TARGET it was).
    #
    # 16 is the publication-grade setting and is what a reported affinity should
    # be computed at. The cost is real and roughly linear — about 4x the runtime
    # of the old setting — so it is capped for very large screens, where the
    # point is to RANK a shortlist rather than to publish each number, and where
    # a 4x wait would otherwise make the run unusable on free CPU. Promote a hit
    # and re-dock it alone to get the deep number.
    if exhaustiveness is not None:
        eff_exh = int(exhaustiveness)          # explicit caller override
    elif n_lig <= 25:
        eff_exh = 16                           # publication-grade
    elif n_lig <= 60:
        eff_exh = 12
    else:
        eff_exh = 8                            # still Vina's own default, never below

    # REPLICATES. Vina's search is stochastic, so ONE run with a fixed seed is a
    # single sample dressed up as an answer: no error bar, and no way to tell a
    # converged result from a coin flip.
    #
    # This is not theoretical. Re-docking erlotinib into 1M17 flips between
    # 1.52 A (correct pose) and 7.92 A (wrong pose) under trivial changes to the
    # search box — non-monotonic, i.e. search noise rather than geometry. With
    # eff_rep = 1 hardcoded, MUMO reported whichever one it happened to land on
    # and looked equally confident either way.
    #
    # Three replicas with DIFFERENT seeds gives the best-of-three (a better
    # estimate, since Vina's score is a minimisation) plus the spread, which
    # dock_with_replicas already turns into mean +/- SD and a confidence flag.
    # That machinery has existed all along and was simply never engaged.
    #
    # Scaled by screen size for the same reason as exhaustiveness: a shortlist
    # being ranked does not need the error bar that a reported number does.
    if n_replicas is not None:
        eff_rep = max(1, int(n_replicas))      # explicit caller override
    elif n_lig <= 10:
        eff_rep = 3                            # reportable: best-of-3 + spread
    elif n_lig <= 30:
        eff_rep = 2                            # enough to expose an unstable pose
    else:
        eff_rep = 1                            # large screen: rank first, re-dock hits
    status(f"Receptor ready ({pocket}). Docking {n_lig} ligand(s) "
           f"— exhaustiveness {eff_exh}, {eff_rep} replica(s)…")

    # Prepare the receptor for interaction profiling ONCE (protonation + ProLIF
    # fingerprint), reused across every ligand — instead of re-protonating the
    # whole protein per ligand, which dominated multi-ligand runtime and, when it
    # failed under batch load, left ligands with no 2D/3D/zip data.
    receptor_ctx = None  # Interactions and native redocking begin only after consent.

    # Gold-standard validation: if the structure has a co-crystal ligand, redock it
    # and report RMSD to the real pose (only experimental complexes — not AlphaFold).
    #
    # This RMSD is the number that substantiates the whole run — it is what a
    # reviewer looks at first and what gets quoted in a methods paper. It was
    # previously run at exhaustiveness 4 with the reasoning that it "only needs
    # to confirm the setup, not to be publication-grade". That was backwards:
    # the one dock in the run that IS publication-grade evidence is this one.
    # Vina's own default of 8 costs roughly 20-30s per target and reproduces
    # crystal poses well (measured: 3PTB 0.40 A, 1STP 0.68 A, 1AZM 1.08 A).
    validation = None

    rows, viz, reliability_by, records = [], {}, {}, {}
    with open(pdb_path, encoding='utf-8') as source:
        original_pdb_text = source.read()
    header_id = next((line[62:66].strip() for line in original_pdb_text.splitlines()
                      if line.startswith('HEADER') and len(line) >= 66), '')
    accessions = sorted({line[33:41].strip() for line in original_pdb_text.splitlines()
                         if line.startswith('DBREF ') and line[26:32].strip() == 'UNP'})
    target_meta = {"gene": tgt["gene"], "center": center, "size": size,
                   "seed": seed, "pocket": pocket,
                   "validation_pdb_text": validation_pdb_text,
                   "pdb_id": tgt.get('pdb_id') or header_id,
                   "accession": tgt.get('accession') or '; '.join(accessions),
                   "dropped_residues": dropped,
                   "exhaustiveness": eff_exh, "replicas": eff_rep,
                   "validation": validation, "reliability_by": reliability_by,
                   "ramachandran": rama, "run_records": records}
    identity = dict(tgt)
    identity['chains'] = sorted({line[21].strip() or '_'
        for line in validation_pdb_text.splitlines() if line.startswith('ATOM')})
    from protein_identity import extract_identity
    extracted = extract_identity(original_pdb_text, chains=identity['chains'])
    for field in ('accession', 'species'):
        if identity.get(field) and extracted.get(field) and identity[field] != extracted[field]:
            raise ValueError(f'Provided target {field} disagrees with source structure metadata')
        # Missing/ambiguous file identity is never made a hit by a display label.
        identity[field] = extracted.get(field)
    target_meta.update({k: identity.get(k) for k in ('accession', 'species', 'chains')})
    target_meta['identity_source'] = extracted.get('identity_source')
    target_meta['pdb_id'] = extracted.get('pdb_id')
    versions = runtime_versions(vina, venv_dir)
    prepared_ligands = []
    for k, lig in enumerate(ligands):
        item = {'ligand': dict(lig), 'index': k}
        try:
            ligf = os.path.join(data_dir, f'c_lig_{k}.pdbqt')
            prepare_ligand(lig['smiles'], ligf, seed=seed)
            item.update(path=ligf, sha256=hashlib.sha256(Path(ligf).read_bytes()).hexdigest())
        except Exception as exc:
            item.update(error=str(exc), manifest=None)
        if not item.get('error'):
            try:
                item['manifest'] = prepared_manifest(identity, receptor, ligf,
                    center, size, eff_exh, eff_rep, seed, versions, source_smiles=lig['smiles'])
            except Exception:
                item['manifest'] = None
                target_meta['cache_notice'] = 'Private cache fingerprint unavailable; calculate fresh.'
        prepared_ligands.append(item)
    return {'tgt': tgt, 'pdb_path': pdb_path, 'cleaned': cleaned, 'receptor': receptor,
            'center': center, 'size': size, 'pocket': pocket, 'data_dir': data_dir,
            'eff_exh': eff_exh, 'eff_rep': eff_rep, 'seed': seed, 'rama': rama,
            'meta': target_meta, 'ligands': prepared_ligands,
            'receptor_sha256': hashlib.sha256(Path(receptor).read_bytes()).hexdigest()}


def dock_pipeline(tgt, ligands, vina, data_dir, venv_dir, status=lambda m: None,
                  exhaustiveness=None, n_replicas=None, seed=42, checkpoint=None,
                  prepared=None, reuse_entries=None, owner_id=None, source_run_id=None):
    from docking_memory import pair_key, eligible_entry
    from datetime import datetime, timezone
    import uuid
    plan = prepared or prepare_docking(tgt, ligands, vina, data_dir, venv_dir,
        status, exhaustiveness, n_replicas, seed)
    pdb_path, cleaned, receptor = (plan[k] for k in ('pdb_path', 'cleaned', 'receptor'))
    center, size, pocket = (plan[k] for k in ('center', 'size', 'pocket'))
    eff_exh, eff_rep, seed, rama = (plan[k] for k in ('eff_exh', 'eff_rep', 'seed', 'rama'))
    target_meta = plan['meta']
    rows, viz = [], {}
    reliability_by, records = target_meta['reliability_by'], target_meta['run_records']
    validation = target_meta.get('validation')
    receptor_ctx = None
    source_run_id, created_at = source_run_id or str(uuid.uuid4()), datetime.now(timezone.utc).isoformat()
    target_meta['cache_entries'] = []
    cache_bytes = 0
    for k, lig in enumerate(ligands):
        label = lig["label"]
        status(f"Docking {label} ({k+1}/{len(ligands)})…")
        try:
            ligf = os.path.join(data_dir, f"c_lig_{k}.pdbqt")
            cmplx = os.path.join(data_dir, f"c_complex_{k}.pdb")
            item = plan['ligands'][k]
            if item.get('error'):
                raise ValueError(item['error'])
            manifest = item['manifest']
            key = pair_key(manifest)
            receptor_hash = (manifest or {}).get('receptor_sha256') or plan.get('receptor_sha256')
            ligand_hash = (manifest or {}).get('ligand_sha256') or item.get('sha256')
            if (hashlib.sha256(Path(receptor).read_bytes()).hexdigest() != receptor_hash
                    or hashlib.sha256(Path(ligf).read_bytes()).hexdigest() != ligand_hash):
                raise ValueError('Prepared inputs changed after preflight')
            cached = (reuse_entries or {}).get(key)
            if cached and eligible_entry(cached, owner_id, key):
                from viz import rehydrate_viz
                row = copy.deepcopy(cached['row'])
                row.update(Ligand=label, **{'Calculation origin': 'reused',
                    'Original run ID': cached['source_run_id'], 'Original calculation date': cached['created_at'],
                    'Pair key': key})
                rows.append(row)
                viz.update(rehydrate_viz({label: copy.deepcopy(cached.get('viz') or {})}, data_dir))
                prior = cached.get('target_meta') or {}
                reliability_by[label] = copy.deepcopy(prior.get('reliability_by', {}).get(cached['row'].get('Ligand'), {}))
                records[label] = copy.deepcopy(cached.get('viz', {}).get('verification', {}))
                target_meta.setdefault('reused_provenance', {})[label] = {
                    'source_run_id': cached['source_run_id'], 'created_at': cached['created_at'],
                    'validation': copy.deepcopy(prior.get('validation'))}
                if checkpoint:
                    checkpoint(rows, viz, target_meta)
                continue
            if receptor_ctx is None:
                receptor_ctx = prepare_receptor_context(cleaned)
            if validation is None and 'co-crystal' in pocket.lower():
                validation = validate_native_redock(pdb_path, receptor, vina, center, size,
                    data_dir, exhaustiveness=max(8, min(eff_exh, 16)), seed=seed)
                target_meta['validation'] = validation
            res = dock_with_replicas(
                vina, receptor, ligf,
                os.path.join(data_dir, f"c_out_{k}"), os.path.join(data_dir, f"c_cfg_{k}"),
                center, size, exhaustiveness=eff_exh, n_replicas=eff_rep, base_seed=seed)
            best, modes, outp = res["best_score"], res["modes"], res["out_pdbqt"]
            validate_docking_result(res)
            ia = analyze_interactions(cleaned, outp, cmplx, ligand_smiles=lig["smiles"],
                                      receptor_ctx=receptor_ctx)
            artifacts = capture_artifacts(ia.get("artifacts", {}))
            artifacts.update(capture_artifacts({
                "docking_receptor": receptor, "docking_ligand": ligf,
                "selected_docking_output": outp, "source_receptor": pdb_path}))
            # Every replica's raw log, configuration and pose stays with the run.
            for evidence_path in Path(data_dir).glob(f"c_*_{k}_r*.*"):
                artifacts.update(capture_artifacts({evidence_path.name: str(evidence_path)}))
            record = run_record('docking', {'target': tgt['gene'], 'ligand': label,
                'smiles': lig['smiles']}, {'center_angstrom': center, 'size_angstrom': size,
                'exhaustiveness': eff_exh, 'replicas': res['n'],
                'seeds': [seed + i for i in range(res['n'])]}, {
                'docking': {'status': 'verified', 'result': res},
                'interactions': ia,
                'ramachandran': {'status': (rama or {}).get('_verification', {}).get('status', 'unavailable'), 'result': rama},
                'native_redocking': {'status': 'qualified' if validation else 'unavailable',
                                    'result': validation}}, artifacts)
            records[label] = record

            # ── validation / statistics layer (#5): interpretable + aggregate metrics ──
            n_heavy = None
            try:
                from rdkit import Chem
                _m = Chem.MolFromSmiles(lig["smiles"])
                n_heavy = _m.GetNumHeavyAtoms() if _m else None
            except Exception:
                pass
            le = ligand_efficiency(best, n_heavy)
            rel = reliability_assessment(res, validation)
            reliability_by[label] = rel

            rows.append({
                "Ligand": label,
                "Best affinity (kcal/mol)": best,
                "Est. Ki": estimate_ki(best),
                "Ligand efficiency": le if le is not None else "—",
                "Vinardo (kcal/mol)": res.get("vinardo") if res.get("vinardo") is not None else "—",
                "Consensus": res.get("consensus", "—"),
                "Pose consistency": (f"{res.get('n_clustered', '?')}/{res.get('n_poses', '?')} poses"
                                     if res.get("n_poses") else "—"),
                "Mean ± SD (kcal/mol)": (f"{res['mean']} ± {res['sd']}" if eff_rep > 1 else "—"),
                "Confidence": res["confidence"],
                "Reliability": rel["reliability"],
                "Total interactions": ia["total_interactions"], "H-bonds": ia["n_hbonds"],
                "Hydrophobic": ia["n_hydrophobic"], "Pi-stack": ia["n_pistacking"],
                "Salt bridges": ia["n_saltbridges"], "Halogen": ia["n_halogen"],
                "H-bond residues": "; ".join(ia["hbond_residues"]) or "-",
                "All interacting residues": "; ".join(ia["interacting_residues"]) or "-",
                "SMILES": lig["smiles"],
                "Interaction status": ia.get("status", "unavailable"),
                "Interaction note": ia.get("note", ""),
                "Verification status": record['status'], "Run ID": record['run_id'],
                "Calculation origin": "new", "Original run ID": source_run_id,
                "Original calculation date": created_at, "Pair key": key,
            })
            viz[label] = {"complex": cmplx,
                          "ia": ia, "artifact_texts": artifacts, "verification": record}
            if key and owner_id:
                try:
                    from viz import serialize_viz
                    from docking_engine import parse_docking_results
                    replicas = []
                    for i in range(eff_rep):
                        pose_path = os.path.join(data_dir, f'c_out_{k}_r{i}.pdbqt')
                        log_path = os.path.join(data_dir, f'c_out_{k}_r{i}_vina.log')
                        replicas.append({'seed': seed+i, 'score': parse_docking_results(log_path)[0],
                            'pose': capture_artifacts({'pose': pose_path})['pose'],
                            'log': Path(log_path).read_text(),
                            'config': Path(data_dir, f'c_cfg_{k}_r{i}.txt').read_text()})
                        for field in ('log', 'config'):
                            replicas[-1][field+'_sha256'] = hashlib.sha256(replicas[-1][field].encode()).hexdigest()
                    entry = {'owner_id': owner_id, 'key': key, 'manifest': manifest,
                        'source_run_id': source_run_id, 'created_at': created_at,
                        'row': copy.deepcopy(rows[-1]), 'interactions': ia, 'replicas': replicas,
                        'artifacts': {'selected_pose': capture_artifacts({'pose': outp})['pose']},
                        'viz': serialize_viz({label: viz[label]})[label],
                        'target_meta': {name: copy.deepcopy(target_meta.get(name)) for name in
                            ('validation', 'ramachandran', 'dropped_residues')}}
                    entry['target_meta']['reliability_by'] = {label: copy.deepcopy(rel)}
                    if eligible_entry(entry, owner_id, key):
                        import json
                        from docking_cache_store import MAX_RAW_BYTES
                        entry_bytes = len(json.dumps(entry, allow_nan=False).encode())
                        if (entry_bytes <= MAX_RAW_BYTES and cache_bytes + entry_bytes <= 64*1024*1024
                                and len(target_meta['cache_entries']) < 64):
                            target_meta['cache_entries'].append(entry)
                            cache_bytes += entry_bytes
                        else:
                            target_meta['cache_notice'] = 'Private cache evidence limit reached; finished docking remains available.'
                except Exception:
                    target_meta['cache_notice'] = 'Cache evidence incomplete; finished docking remains available.'
        except Exception as le:
            # MUMO attempts every ligand rather than pre-filtering, so a
            # molecule Vina genuinely cannot handle lands HERE. Name the real
            # reason where we can — an unsupported element is the common one —
            # so a FAILED row is informative instead of an opaque parse error.
            reason = str(le)[:60]
            try:
                import ligand_check as _lc
                bad = _lc.unsupported_elements(lig.get("smiles"))
                if bad:
                    names = ", ".join(_lc.UNSUPPORTED_ELEMENTS[b] for b in bad)
                    reason = f"contains {names} — AutoDock Vina has no parameters for it"
            except Exception:
                pass
            rows.append({"Ligand": label, "Best affinity (kcal/mol)": "FAILED",
                         "Total interactions": None, "SMILES": lig["smiles"],
                         "Failure reason": str(le), "Interaction status": "unavailable",
                         "Interaction note": reason})
        if checkpoint:
            checkpoint(rows, viz, target_meta)
        status(f"Completed {label} ({k+1}/{len(ligands)}) against {tgt['gene']}.")
    return rows, viz, target_meta
