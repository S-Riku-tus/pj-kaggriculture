"""Reproduce selected descriptive checks and bounded market experiments.
Python 3.9+ standard library only. This is NOT an agent or a closed-loop evaluator.
Run: python scripts/verify_fixtures.py
"""
from pathlib import Path
import copy
import json
from audit_engine import units, market

ROOT = Path(__file__).resolve().parents[1]
def load(name):
    with (ROOT / 'fixtures' / name).open(encoding='utf-8') as stream:
        return json.load(stream)

def verify():
    results=[]
    for fixture in load('market_one_step.json'):
        obs, actions = fixture['observations_before'], fixture['actions']
        seat, t = fixture['target_seat'], fixture['record_index']
        margins=[]
        for swap in (False, True):
            farms=[copy.deepcopy(obs[p]['farms'][p]) for p in range(2)]
            privates=[copy.deepcopy(obs[p]['private']) for p in range(2)]
            candidate=copy.deepcopy(actions)
            if swap:
                assert candidate[seat]['market'][0][0]=='SELL'
                assert candidate[seat]['market'][1][0]=='SELL'
                candidate[seat]['market'][0],candidate[seat]['market'][1]=candidate[seat]['market'][1],candidate[seat]['market'][0]
            for p in range(2):
                units(farms[p],privates[p],candidate[p],(t-1)//24)
            market(farms,privates,candidate,dict(obs[0]['market']['inventory']))
            cash=[f['money'] for f in farms]
            if not swap:
                assert cash == fixture['cash_after'], (fixture['episode_id'],t,cash)
            margins.append(cash[seat]-cash[1-seat])
        delta=margins[1]-margins[0]
        assert delta==fixture['expected_immediate_margin_delta']
        results.append({'episode_id':fixture['episode_id'],'record_index':t,'baseline_money_verified':True,'immediate_margin_delta':delta})
    failures=load('failed_transfers.json')
    for case in failures:
        op=case['action'][0]
        if op in ('PICKUP','PLACE'):
            assert tuple(case['position']) not in ((4,4),(5,4),(4,5),(5,5))
            assert case['inventory_before']==case['inventory_after']
        elif op=='FEED':
            assert case['inventory_before'].get('WHEAT',0)==0
    exits=load('animal_exits.json')
    for case in exits:
        for tile in case['tiles']:
            assert tile['before'].get('animal')
            assert not (isinstance(tile['after'],dict) and tile['after'].get('animal'))
    layout=load('identical_layouts.json')
    for case in layout:
        assert len(case['snapshots'])==31
        assert all(s['tiles_0']==s['tiles_1'] for s in case['snapshots'])
    return {'status':'PASS','market_one_step':results,'failed_transfer_records_verified':len(failures),
      'four_animal_exit_cases_verified':len(exits),'identical_layout_cases_verified':len(layout),
      'scope':'Recorded-state checks and three single-transition market swaps. No repaired agent, future rollout, or win uplift is tested.'}
if __name__=='__main__':
    print(json.dumps(verify(),ensure_ascii=False,indent=2))
