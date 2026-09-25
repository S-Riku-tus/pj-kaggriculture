#!/usr/bin/env python3
"""Restricted market micro-check, NOT a full Kaggriculture simulator.

Independently written from the public official engine at commit
302d8e20c83822b8d4572975cdea1180b792b748, kaggriculture.py:
MARKET_PARAMS, market_price, _process_market, _commit_unit, _hire_cost.
Only WHEAT BUY_PRODUCT/SELL, HIRE and BUY_SEED are implemented.
No farm actions, day transitions, town consumption, private opponent policy,
planting, random draws, or future income are simulated. Publication comparisons
are illustrative market-only counterfactuals, not agent-performance replication.
"""
from __future__ import annotations
import copy
import json
import math
from pathlib import Path
from typing import Any

OFFICIAL_COMMIT = "302d8e20c83822b8d4572975cdea1180b792b748"


def wheat_price(inv: int) -> int:
    if inv < 10000:
        p = 25 + (0.8 * 25 / math.sqrt(400)) * math.sqrt(10000-inv)
    else:
        p = 25 - (0.2 * 25 / math.log(401)) * math.log(1+inv-10000)
    return max(1, int(round(p)))


def hire_cost(n_already: int) -> int:
    a, b = 1, 1
    for _ in range(n_already):
        a, b = b, a+b
    return a


def run_market(queues: list[list[list[Any]]], initial_cash=(3000, 3000),
               initial_wheat=(0, 0), initial_inventory=10000) -> dict[str, Any]:
    if len(queues) != 2:
        raise ValueError('Exactly two players are required')
    cash, wheat = list(initial_cash), list(initial_wheat)
    hires = [0, 0]
    seed = [{}, {}]
    market = initial_inventory
    parsed = copy.deepcopy([q[:10] for q in queues])
    transactions: list[dict[str, Any]] = []
    for slot in range(max(map(len, parsed), default=0)):
        remaining: list[list[Any] | None] = []
        for player in range(2):
            order = parsed[player][slot] if slot < len(parsed[player]) else []
            if not order:
                remaining.append(None)
                continue
            op = order[0]
            if op == 'HIRE':
                cost = hire_cost(hires[player])
                filled = cash[player] >= cost
                if filled:
                    cash[player] -= cost
                    hires[player] += 1
                transactions.append(dict(player=player, slot=slot, op=op,
                                         cost=cost, filled=filled))
                remaining.append(None)
            elif op in ('BUY_PRODUCT', 'SELL', 'BUY_SEED'):
                if len(order) != 3 or int(order[2]) <= 0:
                    raise ValueError(f'Malformed test order: {order!r}')
                if op != 'BUY_SEED' and order[1] != 'WHEAT':
                    raise ValueError('Only wheat market trades are supported')
                if op == 'BUY_SEED' and order[1] not in ('WHEAT','CARROT','MELON'):
                    raise ValueError('Unsupported seed')
                remaining.append([op, order[1], int(order[2])])
            else:
                raise ValueError(f'Unsupported order: {order!r}')
        unit_round = 0
        while any(o is not None and o[2] > 0 for o in remaining):
            unit_round += 1
            if unit_round > 1000:
                raise RuntimeError('Unexpected long test order')
            quoted = []
            for o in remaining:
                if o is None or o[2] <= 0:
                    quoted.append(None)
                elif o[0] == 'SELL':
                    quoted.append(wheat_price(market))
                elif o[0] == 'BUY_PRODUCT':
                    quoted.append(wheat_price(market-1))
                else:
                    quoted.append({'WHEAT':10,'CARROT':20,'MELON':80}[o[1]])
            any_commit = False
            for player, price in enumerate(quoted):
                if price is None:
                    continue
                o = remaining[player]
                assert o is not None
                op, item, _ = o
                ok = False
                if op == 'SELL' and wheat[player] > 0:
                    wheat[player] -= 1
                    cash[player] += price
                    if price > 1:
                        market += 1
                    ok = True
                elif op == 'BUY_PRODUCT' and cash[player] >= price and wheat[player] < 100:
                    cash[player] -= price
                    wheat[player] += 1
                    market -= 1
                    ok = True
                elif op == 'BUY_SEED' and cash[player] >= price:
                    cash[player] -= price
                    seed[player][item] = seed[player].get(item,0)+1
                    ok = True
                transactions.append(dict(player=player, slot=slot, unit_round=unit_round,
                                         op=op, price=price, filled=ok))
                if ok:
                    o[2] -= 1
                    any_commit = True
                else:
                    remaining[player] = None
            if not any_commit:
                break
    return dict(cash=cash, wheat=wheat, hires=hires, seeds=seed, market_inventory=market,
                cash_delta=[cash[i]-initial_cash[i] for i in (0,1)],
                cash_margin=cash[0]-cash[1], transactions=transactions)


def trip(n: int) -> list[list[Any]]:
    return [['BUY_PRODUCT','WHEAT',n],['SELL','WHEAT',n]]


def main() -> None:
    cases = {
        'isolated_70': ([trip(70), []], (3000,3000), (0,0)),
        'mirror_70': ([trip(70), trip(70)], (3000,3000), (0,0)),
        'small_10_vs_70': ([trip(10), trip(70)], (3000,3000), (0,0)),
        'large_70_vs_10': ([trip(70), trip(10)], (3000,3000), (0,0)),
        'buy90_sell90_buy5_vs_delayed_buy5':
            ([trip(90)+[['BUY_PRODUCT','WHEAT',5]],
              [['SELL','WHEAT',13],['BUY_PRODUCT','WHEAT',5]]], (3000,3000), (0,0)),
        'cash_zero_sell_then_hire':
            ([[['SELL','WHEAT',1],['HIRE']],[]], (0,0), (1,0)),
        'cash_zero_hire_then_sell':
            ([[['HIRE'],['SELL','WHEAT',1]],[]], (0,0), (1,0)),
        'cash_159_buy_two_melon':
            ([[['BUY_SEED','MELON',2]],[]],(159,0),(0,0)),
        'cash_160_buy_two_melon':
            ([[['BUY_SEED','MELON',2]],[]],(160,0),(0,0)),
    }
    result={name:run_market(q,c,w) for name,(q,c,w) in cases.items()}
    assert result['isolated_70']['cash_delta'] == [0,0]
    assert result['mirror_70']['cash_margin'] == 0
    assert result['small_10_vs_70']['cash_margin'] == -result['large_70_vs_10']['cash_margin']
    assert result['cash_zero_sell_then_hire']['hires'][0] == 1
    assert result['cash_zero_hire_then_sell']['hires'][0] == 0
    assert result['cash_159_buy_two_melon']['seeds'][0]['MELON'] == 1
    assert result['cash_160_buy_two_melon']['seeds'][0]['MELON'] == 2
    output = {'scope':'Restricted independently implemented market model, not full engine verification',
              'official_commit':OFFICIAL_COMMIT, 'cases':result,
              'all_win_one_sided_95_lower':{str(n):0.05**(1/n) for n in (20,40,59,100)}}
    dest=Path(__file__).resolve().parents[1]/'evidence'/'market_microcheck_results.json'
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    for name, row in result.items():
        print(name, {k:row[k] for k in ('cash_delta','cash_margin','hires','seeds')})
    print('Written:', dest)

if __name__ == '__main__':
    main()
