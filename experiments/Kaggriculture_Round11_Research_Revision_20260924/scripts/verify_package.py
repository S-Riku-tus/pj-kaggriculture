#!/usr/bin/env python3
"""Verify package hashes and the stored 128-game development evidence.
Standard library only; no network, training, games or Kaggle submission.
"""
from pathlib import Path
import csv,gzip,hashlib,json,sys,math
ROOT=Path(__file__).resolve().parents[1]
def require(x,msg):
    if not x:raise AssertionError(msg)
def main():
    manifest=json.loads((ROOT/'MANIFEST.json').read_text(encoding='utf-8'))
    for r in manifest['files']:
        p=ROOT/r['path'];require(p.is_file(),'Missing '+r['path'])
        require(hashlib.sha256(p.read_bytes()).hexdigest()==r['sha256'],'Hash mismatch '+r['path'])
    data=json.loads((ROOT/'evidence/development_results.json').read_text())
    keys={(r['arm'],r['opponent'],r['seed'],r['seat']) for r in data}
    require(len(data)==len(keys)==128,'Expected exactly 128 distinct panel cells')
    require(all(r['done'] and r['decisions']==719 and r['error'] is None for r in data),'Incomplete/error game')
    require(all(r['order_cap_violations']==0 for r in data),'Order cap violation')
    expected={'B1':(20,4,8),'wool_gate_open':(18,14,0),'final_response':(20,4,8),'combined':(18,14,0)}
    for arm,wlt in expected.items():
        rr=[r for r in data if r['arm']==arm]
        got=(sum(r['margin']>0 for r in rr),sum(r['margin']<0 for r in rr),sum(r['margin']==0 for r in rr))
        require(got==wlt,(arm,got,wlt))
    for r in data:
        p=ROOT/'evidence'/r['replay_path']
        require(hashlib.sha256(p.read_bytes()).hexdigest()==r['replay_sha256'],'Replay hash '+str(p))
    ledger=json.loads((ROOT/'evidence/online_extended_summary.json').read_text())
    require(ledger['checks']==71*719*7,'Wrong ledger coverage')
    require(ledger['certified_exact']+ledger['not_exact']==ledger['checks'],'Ledger coverage mismatch')
    require(ledger['bound_failures']==ledger['exact_failures']==0,'Ledger validation failures')
    require(ledger['terminal_shed_saleable_total']==ledger['terminal_cargo_saleable_total']==0,'Wrong terminal totals')
    scope=json.loads((ROOT/'evidence/EXECUTION_SCOPE.json').read_text())
    require(scope['new_training_runs']==scope['new_kaggle_submissions']==0,'Wrong scope')
    print(json.dumps({'status':'PASS','files_verified':len(manifest['files']),'unique_complete_games':128,'ledger_checks':ledger['checks'],'training_runs':0,'submissions':0},indent=2))
if __name__=='__main__':
    try:main()
    except Exception as e:
        print('FAILED:',str(e),file=sys.stderr);raise
