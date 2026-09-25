"""Merge saved-game audit batches; no training or environment execution."""
from __future__ import annotations
import json
import os
from pathlib import Path
import pandas as pd

O = Path(os.environ.get('AUDIT_EVIDENCE', str(Path(__file__).resolve().parents[1] / 'evidence')))
batches = ['all'] if (O / 'all/replay_checks.csv').is_file() else ['small', 'old64', 'final64']
frames = [pd.read_csv(O / name / 'replay_checks.csv') for name in batches]
df = pd.concat(frames, ignore_index=True)
if df.duplicated(['panel', 'anchor', 'seed', 'seat']).any():
    raise ValueError('Overlapping audit rows: do not silently count duplicates.')
if not df.all_checks.all():
    raise ValueError('One or more saved-game integrity checks failed.')
df.to_csv(O / 'replay_checks.csv', index=False)
summary = df.groupby('panel').agg(
    games=('score', 'size'), wins=('score', lambda x: int((x == 1).sum())),
    draws=('score', lambda x: int((x == .5).sum())), losses=('score', lambda x: int((x == 0).sum())),
    mean_cash=('our_cash', 'mean'), mean_opponent=('opponent_cash', 'mean'),
    mean_margin=('margin', 'mean'), all_checks=('all_checks', 'all')
).reset_index()
summary.to_csv(O / 'panel_summary.csv', index=False)
(O / 'panel_summary.json').write_text(summary.to_json(orient='records', indent=2), encoding='utf-8')
source = O / ('all' if 'all' in batches else 'final64')
snaps = pd.read_csv(source / 'state_snapshots.csv')
snaps.to_csv(O / 'state_snapshots.csv', index=False)
means = snaps.groupby(['record', 'role'])[['money','land','crops','animals','empty_pasture','hands','shed_units','carried_units']].mean().reset_index()
means.to_csv(O / 'mean_state_snapshots.csv', index=False)
print(summary.to_string(index=False))
print('All saved games checked:', len(df))
print('Final64 at day20 with no crops or animals:', len(snaps[(snaps.record == 480) & (snaps.role == 'A2') & (snaps.crops == 0) & (snaps.animals == 0)]))
