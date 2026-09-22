#!/usr/bin/env python3
"""Reproduce this version-specific audit from the original user-provided ZIP.

Python 3.9+; standard library only. No simulator, training, web access, or Kaggle
submission is performed. It imports the input archive's contracts module and
executes selected original functions, so only use the trusted original archive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import tempfile
import zipfile


def safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        if sum(i.file_size for i in z.infolist()) > 256 * 1024 * 1024:
            raise ValueError(f"Archive exceeds the 256 MiB uncompressed limit: {archive}")
        for i in z.infolist():
            name = PurePosixPath(i.filename)
            mode = i.external_attr >> 16
            if name.is_absolute() or '..' in name.parts or '\\' in i.filename:
                raise ValueError(f"Unsafe archive member: {i.filename}")
            if name.parts and ':' in name.parts[0]:
                raise ValueError(f"Unsafe archive drive prefix: {i.filename}")
            if stat.S_ISLNK(mode):
                raise ValueError(f"Symbolic link in archive: {i.filename}")
            target = (destination / Path(*name.parts)).resolve()
            if destination.resolve() not in (target, *target.parents):
                raise ValueError(f"Archive path escapes destination: {i.filename}")
        z.extractall(destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True,
                        help='Original learning_round3_20260921.zip')
    parser.add_argument('--output', type=Path, default=Path('round3_audit_results'))
    parser.add_argument('--overwrite', action='store_true',
                        help='Allow replacement of existing audit output files')
    args = parser.parse_args()
    original, output = args.input.resolve(), args.output.resolve()
    if not original.is_file() or not zipfile.is_zipfile(original):
        parser.error('--input must be an existing ZIP file')
    if output.exists() and any(output.iterdir()) and not args.overwrite:
        parser.error('--output is not empty; choose a new directory or use --overwrite')
    output.mkdir(parents=True, exist_ok=True)
    scripts_dir = Path(__file__).resolve().parent
    script_names = ['audit_replays.py', 'audit_source_and_contracts.py', 'test_report_literals.py']
    for name in script_names:
        if not (scripts_dir / name).is_file():
            raise FileNotFoundError(f'Missing companion script: {name}')
    with tempfile.TemporaryDirectory(prefix='kaggriculture_round3_audit_') as temp:
        work = Path(temp)
        safe_extract(original, work)
        roots = list(work.rglob('FINAL_STATUS.json'))
        roots = [p.parent for p in roots if (p.parent / 'handoff_evidence.zip').is_file()]
        if len(roots) != 1:
            raise ValueError(f'Expected one Round3 root; found {len(roots)}')
        root = roots[0]
        safe_extract(root / 'handoff_evidence.zip', root / 'handoff_extracted')
        env = dict(os.environ, ROUND3_DIR=str(root), AUDIT_OUTPUT_DIR=str(output), PYTHONUTF8='1')
        for name in script_names:
            print(f'Running {name}', flush=True)
            proc = subprocess.run([sys.executable, str(scripts_dir / name)],
                                  env=env, text=True, encoding='utf-8',
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            (output / f'{Path(name).stem}.log').write_text(proc.stdout, encoding='utf-8')
            if proc.returncode:
                raise RuntimeError(f'{name} failed ({proc.returncode}); see its .log file')
    integrity = json.loads((output / 'replay_integrity.json').read_text(encoding='utf-8'))
    source = json.loads((output / 'source_contract_audit.json').read_text(encoding='utf-8'))
    mutations = json.loads((output / 'report_literal_mutation_tests.json').read_text(encoding='utf-8'))
    checks = {
        '16_recorded_replays_verified': len(integrity) == 16 and all(
            x['sha_matches'] and x['terminal_reward_matches_csv'] and
            x['steps'] == 720 and x['statuses'] == ['DONE', 'DONE'] for x in integrity),
        '41_manifest_files_verified': source['handoff_manifest']['checked'] == 41 and
                                     source['handoff_manifest']['all_ok'],
        'immature_harvest_reproduced': source['harvest']['age_days'] == 1 and
                                     not source['harvest']['new_product_created'],
        'duplicate_feed_missed_by_validator': source['feed_once']['same_turn_duplicate_feed_action_actors'] == [4, 5] and
                                             source['feed_once']['joint_validator_reasons'] == [],
        'incorrect_rejoin_proof_reproduced': source['feed_once']['rejoin_status_at_436'][0] == 'PROVEN_REJOIN' and
                                            source['feed_once']['actor5_wheat_at_441'] == 0,
        'positive_synthetic_data_still_reports_false': mutations[0]['reported_economic_benefit']['value'] is False,
        'synthetic_errors_still_report_execution_true': mutations[1]['reported_execution_valid']['value'] is True,
    }
    summary = {
        'input_sha256': hashlib.sha256(original.read_bytes()).hexdigest(),
        'checks': checks, 'all_original_findings_reproduced': all(checks.values()),
        'scope': 'Recorded evidence and extracted functions only; no new engine rollouts, training, or submissions.',
        'synthetic_tests_are_not_game_results': True,
    }
    (output / 'audit_run_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        print(f'Audit failed: {exc}', file=sys.stderr)
        raise SystemExit(2)
