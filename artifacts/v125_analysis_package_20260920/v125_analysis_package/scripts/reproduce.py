"""Reproduce this five-submission analysis from the original replay ZIPs.

This program does not run or submit a v125 agent and does not access the network.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

STAGES = [
    'analyze_replays.py', 'audit_replays.py', 'summarize.py',
    'enrich_metrics.py', 'cohort_metrics.py', 'paired_decompose.py',
    'build_tables.py', 'extract_cases.py',
]
EXPECTED = {'56357320', '56360233', '56216119', '56361903', '56354460'}

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True,
                        help='Directory containing the five original replay ZIPs.')
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='New or previously used working directory (large caches).')
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    src = args.input_dir.resolve()
    out = args.output_dir.resolve()
    if not src.is_dir():
        parser.error(f'Input directory does not exist: {src}')
    if args.workers < 1:
        parser.error('--workers must be >= 1')
    found = set()
    for path in src.glob('*.zip'):
        match = re.search(r'submission_(\d+)', path.name)
        if match:
            found.add(match.group(1))
    missing = EXPECTED - found
    if missing:
        parser.error('This analysis expects all five named submissions. Missing: '
                     + ', '.join(sorted(missing)))
    out.mkdir(parents=True, exist_ok=True)
    tables = out / 'tables'
    tables.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(KAGGRI_INPUT_DIR=str(src), KAGGRI_OUTPUT_DIR=str(out),
               KAGGRI_TABLES_DIR=str(tables), KAGGRI_WORKERS=str(args.workers),
               PYTHONUNBUFFERED='1')
    here = Path(__file__).resolve().parent
    for stage in STAGES:
        logfile = out / (Path(stage).stem + '.log')
        print(f'Running {stage}; log: {logfile}', flush=True)
        with logfile.open('w', encoding='utf-8') as log:
            result = subprocess.run([sys.executable, str(here / stage)], env=env,
                                    stdout=log, stderr=subprocess.STDOUT,
                                    check=False)
        if result.returncode:
            print(f'Failed: {stage}. Inspect {logfile}.', file=sys.stderr)
            return result.returncode
    print(f'Completed. Tables: {tables}')
    print('Inspect audit_and_provenance.json; nonzero audit discrepancies are not hidden.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
