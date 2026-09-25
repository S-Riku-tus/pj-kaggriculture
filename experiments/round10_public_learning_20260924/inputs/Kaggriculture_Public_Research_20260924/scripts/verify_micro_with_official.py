#!/usr/bin/env python3
"""Compare market_microcheck against installed official engine (NOT run here).
Requires kaggle_environments in the chosen environment. Checks exact source blob
identity; rejects drift by default instead of claiming compatibility silently.
This exercises market settlement only, not a full season or an adaptive policy.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from market_microcheck import run_market, trip

EXPECTED_BLOB = '3c202c7ee921da239356789e266b694635103fc4'


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument('--allow-different-source', action='store_true')
    args=ap.parse_args()
    try:
        official=importlib.import_module('kaggle_environments.envs.kaggriculture.kaggriculture')
    except ImportError as exc:
        raise SystemExit('NOT RUN: install/use the audited official environment first.') from exc
    source=Path(official.__file__).read_bytes()
    observed=git_blob_sha(source)
    if observed != EXPECTED_BLOB and not args.allow_different_source:
        raise SystemExit(f'ENGINE DRIFT: expected blob {EXPECTED_BLOB}, got {observed}. Review before proceeding.')
    cases=[('isolated70',[trip(70),[]],(3000,3000),(0,0)),
           ('mirror70',[trip(70),trip(70)],(3000,3000),(0,0)),
           ('small10_vs70',[trip(10),trip(70)],(3000,3000),(0,0)),
           ('large70_vs10',[trip(70),trip(10)],(3000,3000),(0,0)),
           ('squeeze90',[trip(90)+[['BUY_PRODUCT','WHEAT',5]],
                         [['SELL','WHEAT',13],['BUY_PRODUCT','WHEAT',5]]],(3000,3000),(0,0)),
           ('sell_hire',[[['SELL','WHEAT',1],['HIRE']],[]],(0,0),(1,0)),
           ('hire_sell',[[['HIRE'],['SELL','WHEAT',1]],[]],(0,0),(1,0)),
           ('seed159',[[['BUY_SEED','MELON',2]],[]],(159,0),(0,0)),
           ('seed160',[[['BUY_SEED','MELON',2]],[]],(160,0),(0,0))]
    results=[]
    for name, queues, cash, wheat in cases:
        farms=[official._new_farm(10,c) for c in cash]
        private=[official._new_private(),official._new_private()]
        for p in (0,1): private[p]['shed']['WHEAT']=wheat[p]
        market=official._new_market()
        states=[SimpleNamespace(observation=SimpleNamespace(farms=farms,market=market,private=private[p]),
                                action={'market':queues[p]}) for p in (0,1)]
        env=SimpleNamespace(configuration={'boardSize':10,'maxMarketOrdersPerTurn':10,
                                           'farmHandCostMult':1,'shedCapacity':100})
        official._process_market(states,env)
        ref=run_market(queues,cash,wheat)
        actual={'cash':[f['money'] for f in farms],
                'wheat':[d['shed']['WHEAT'] for d in private],
                'hires':[f['hires_today'] for f in farms],
                'seeds':[{k:v for k,v in d['seeds'].items() if v} for d in private],
                'market_inventory':market['inventory']['WHEAT']}
        expected={k:ref[k] for k in actual}
        if actual != expected:
            raise AssertionError(f'{name}: official={actual}, independent={expected}')
        results.append({'name':name,'passed':True})
    out={'official_blob':observed,'same_expected_source':observed==EXPECTED_BLOB,
         'scope':'Market-only settlement, not full-agent validation','cases':results}
    path=Path(__file__).resolve().parents[1]/'evidence'/'official_comparison_results.json'
    path.write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps(out,indent=2))

if __name__=='__main__': main()
