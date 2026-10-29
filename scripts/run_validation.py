"""Run one MUMO validation check: python scripts/run_validation.py quill|scout"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))

try:  # use the OS certificate store (needed behind TLS-scanning antivirus); verification stays on
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from validation.harness import run_workflow  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workflow', choices=['quill', 'scout'])
    parser.add_argument('--manifest', help='override the default manifest path')
    args = parser.parse_args(argv)
    out_dir, summary = run_workflow(args.workflow, args.manifest)
    print(f"{summary['workflow']}: {summary['counts']}")
    for criterion in summary['criteria']:
        print(f"  [{'PASS' if criterion['passed'] else 'FAIL'}] {criterion['id']}: {criterion['value']}")
    print(f'evidence: {out_dir}')
    return 0 if summary['all_criteria_passed'] else 2


if __name__ == '__main__':
    sys.exit(main())
