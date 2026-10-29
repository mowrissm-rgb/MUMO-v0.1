"""Shared run recording for MUMO validation checks.

A check module exposes ``run(manifest, ctx) -> (items, criteria, extras)``:
  items     one dict per validated item: {item, status, details}; status is
            PASS, FAIL, ERROR or INCONCLUSIVE. Only PASS counts as a pass, so
            errors stay in the denominator.
  criteria  one dict per frozen pass criterion: {id, description, passed, value}
  extras    descriptive facts recorded without a pass/fail verdict
"""
import csv
import hashlib
import importlib
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATION = ROOT / 'validation'
STATUSES = ('PASS', 'FAIL', 'ERROR', 'INCONCLUSIVE')


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _git(*args):
    try:
        out = subprocess.run(['git', *args], cwd=ROOT, capture_output=True,
                             text=True, timeout=30)
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def git_info():
    return {'commit': _git('rev-parse', 'HEAD'),
            'branch': _git('branch', '--show-current'),
            'dirty_files': [line for line in (_git('status', '--short') or '').splitlines()
                            if not line[3:].startswith('validation/runs/')],
            'protocol_tag': _git('describe', '--tags', '--abbrev=0', '--match', 'validation-protocol-*')}


def package_versions(names):
    from importlib import metadata
    versions = {}
    for name in names:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def count_statuses(items):
    counts = {status: 0 for status in STATUSES}
    for item in items:
        if item['status'] not in counts:
            raise ValueError(f"Unknown status {item['status']!r} for {item.get('item')}")
        counts[item['status']] += 1
    return counts


def write_items_csv(path, items):
    with open(path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['item', 'status', 'details_json'])
        for item in items:
            writer.writerow([item['item'], item['status'],
                             json.dumps(item.get('details', {}), sort_keys=True, default=str)])


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + '\n',
                          encoding='utf-8')


def run_workflow(workflow, manifest_path=None, out_root=None):
    """Run one check module and write all evidence under validation/runs/."""
    name = workflow.lower()
    manifest_path = Path(manifest_path or VALIDATION / 'manifests' / f'{name}.json')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out_dir = Path(out_root or VALIDATION / 'runs') / name / stamp
    out_dir.mkdir(parents=True, exist_ok=False)

    module = importlib.import_module(f'validation.checks.{name}')
    ctx = {'out_dir': out_dir}
    started = time.time()
    items, criteria, extras = module.run(manifest, ctx)
    wall = round(time.time() - started, 2)

    counts = count_statuses(items)
    summary = {
        'workflow': manifest['workflow'],
        'protocol_version': manifest['protocol_version'],
        'n_items': len(items),
        'counts': counts,
        'criteria': criteria,
        'all_criteria_passed': all(c['passed'] for c in criteria),
        'extras': extras,
    }
    environment = {
        'created_utc': stamp,
        'wall_seconds': wall,
        'python': sys.version,
        'platform': platform.platform(),
        'git': git_info(),
        'manifest': {'path': str(manifest_path.relative_to(ROOT)),
                     'sha256': sha256_file(manifest_path)},
        'protocol': {'path': 'validation/PROTOCOL.md',
                     'sha256': sha256_file(VALIDATION / 'PROTOCOL.md')},
        'packages': package_versions(['rdkit', 'python-docx', 'requests', 'pandas']),
        'seeds': 'none: checks are deterministic given the recorded inputs',
    }
    write_items_csv(out_dir / 'items.csv', items)
    write_json(out_dir / 'summary.json', summary)
    write_json(out_dir / 'environment.json', environment)
    return out_dir, summary
