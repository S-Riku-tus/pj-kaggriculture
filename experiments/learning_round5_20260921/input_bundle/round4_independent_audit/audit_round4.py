#!/usr/bin/env python3
"""Read-only audit of saved Round4 replays. No agent execution, training or submission.

Usage:
  python audit_round4.py learning_round4_20260921.zip --out ./audit_output
  python audit_round4.py /path/to/learning_round4_20260921 --out ./audit_output

Only the Python standard library is required. Record k contains the action applied
from observation k-1 and its resulting observation. Boundary inventory attribution
is deliberately left unresolved rather than counted as failed.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import statistics
import tempfile
from typing import Any
import zipfile

FIRST_YIELD = {'WHEAT': 2, 'CARROT': 2, 'TOMATO': 8, 'STRAWBERRY': 10, 'MELON': 10}
ANIMAL_PRODUCTS = {'COW': 'MILK', 'SHEEP': 'WOOL', 'GOOSE': 'EGG'}

def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8-sig'))

def dump(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')

def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        w = csv.DictWriter(stream, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

def key(row: dict[str, Any]) -> tuple[str, str, int, int]:
    return row['arm'], row['family'], int(row['seed']), int(row['seat'])

def audit(root: Path, out: Path, input_sha: str | None) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    results = load_json(root / 'closed_loop/CLOSED_LOOP_RESULTS.json')
    replay_cache: dict[tuple[str, str, int, int], Any] = {}
    summaries, integrity, daily, harvests, lifecycle, opportunities, terminals = [], [], [], [], [], [], []
    opening = []
    for declared in results['rows']:
        k = key(declared)
        arm, family, seed, seat = k
        ids = dict(arm=arm, family=family, seed=seed, seat=seat)
        relative = declared['replay'].replace('\\', '/').split('learning_round4_20260921/', 1)[1]
        path = root / relative
        content = path.read_bytes()
        replay = json.loads(gzip.decompress(content))
        replay_cache[k] = replay
        steps = replay['steps']
        unit_counts, market_counts, market_quantities = Counter(), Counter(), Counter()
        funds, animals_count, crops_count, hands_count = [], [], [], []
        for rec, state in enumerate(steps):
            obs = state[seat]['observation']
            farm = obs['farms'][seat]
            private = obs['private']
            tiles = [t for row in farm['tiles'] for t in row if isinstance(t, dict)]
            animals = [t for t in tiles if 'animal' in t]
            crops = [t for t in tiles if t.get('kind') == 'PLANT']
            funds.append(farm['money'])
            animals_count.append(len(animals))
            crops_count.append(len(crops))
            hands_count.append(len(farm['hands']))
            if rec % 24 == 0 or rec == len(steps) - 1:
                daily.append(dict(**ids, record=rec, day=obs['day'], hour=obs['hour'], money=farm['money'],
                    opponent_money=obs['farms'][1-seat]['money'], animals=len(animals), crops=len(crops),
                    hands=len(farm['hands']), weeds=sum(t.get('kind') == 'WEED' for t in tiles),
                    shed_load=sum(private['shed'].values()),
                    carried_load=sum(sum(i.values()) for i in private['inventories']),
                    quadrants=len(farm['unlocked_quadrants'])))
            if rec == 0:
                continue
            prev = steps[rec-1][seat]['observation']
            pf = prev['farms'][seat]
            action = state[seat].get('action') or {}
            actions = [action.get('farmer', ['PASS'])] + action.get('hands', [])
            positions = [pf['farmer']] + pf['hands']
            old_inventory = prev['private']['inventories']
            for order in action.get('market', []):
                if not order:
                    continue
                market_counts[order[0]] += 1
                quantity = order[2] if len(order) > 2 and isinstance(order[2], (int, float)) else 1
                market_quantities[f'{order[0]}:{order[1] if len(order)>1 else ""}'] += quantity
            for actor, a in enumerate(actions):
                if not a:
                    continue
                unit_counts[a[0]] += 1
                if arm != 'round4_learned' or actor >= len(positions):
                    continue
                x, y = positions[actor]
                tile = pf['tiles'][y][x]
                common = dict(**ids, record=rec, decision_step=rec-1, actor=actor, x=x, y=y,
                              day=prev['day'], hour=prev['hour'])
                if a[0] == 'HARVEST':
                    product = (tile.get('crop') or ANIMAL_PRODUCTS.get(tile.get('animal'))) if isinstance(tile, dict) else None
                    immature = bool(isinstance(tile, dict) and tile.get('kind') == 'PLANT' and
                                    prev['day'] - tile['planted_day'] < FIRST_YIELD[tile['crop']])
                    same_day = prev['day'] == obs['day']
                    increase = None if not same_day or actor >= len(private['inventories']) else (
                        private['inventories'][actor].get(product, 0) - old_inventory[actor].get(product, 0))
                    harvests.append(dict(**common, product=product, immature=immature,
                                         inventory_increase=increase, tile=tile))
                if isinstance(tile, dict) and 'animal' in tile and tile.get('yield_units', 0) > 0:
                    opportunities.append(dict(**common, action=a, tile=tile, inventory_before=old_inventory[actor]))
            if arm == 'round4_learned':
                for y, row in enumerate(pf['tiles']):
                    for x, before in enumerate(row):
                        after = farm['tiles'][y][x]
                        ba = before.get('animal') if isinstance(before, dict) else None
                        aa = after.get('animal') if isinstance(after, dict) else None
                        if ba and ba != aa:
                            lifecycle.append(dict(**ids, record=rec, decision_step=rec-1, x=x, y=y,
                                event='disappeared', before=before, after=after, day_before=prev['day'], day_after=obs['day']))
                        if aa and ba != aa:
                            lifecycle.append(dict(**ids, record=rec, decision_step=rec-1, x=x, y=y,
                                event='placed', before=before, after=after, day_before=prev['day'], day_after=obs['day']))
                if rec <= 72:
                    opening.append(dict(**ids, record=rec, decision_step=rec-1, day=prev['day'], hour=prev['hour'],
                        money_before=pf['money'], money_after=farm['money'], action=action,
                        wheat_before=prev['private']['shed']['WHEAT'], wheat_after=private['shed']['WHEAT'],
                        farmer_before=pf['farmer'], inventory_before=old_inventory))
        final = steps[-1][seat]['observation']
        final_farm = final['farms'][seat]
        integrity.append(dict(**ids, sha256_match=hashlib.sha256(content).hexdigest() == declared['replay_sha256'],
            money_match=final_farm['money'] == declared['self_money'],
            opponent_money_match=final['farms'][1-seat]['money'] == declared['opponent_money'],
            seed_match=replay.get('info', {}).get('seed') == seed,
            stored_states=len(steps), statuses=[s['status'] for s in steps[-1]],
            rewards=[s['reward'] for s in steps[-1]], module_version=replay.get('module_version')))
        summary = dict(**ids, final_money=funds[-1], min_money=min(funds), max_money=max(funds),
            final_animals=animals_count[-1], max_animals=max(animals_count),
            final_crops=crops_count[-1], max_crops=max(crops_count), max_hands=max(hands_count),
            primitive_total=sum(unit_counts.values()), passes=unit_counts['PASS'],
            moves=sum(unit_counts[m] for m in ['NORTH', 'SOUTH', 'EAST', 'WEST']),
            harvests=unit_counts['HARVEST'], feeds=unit_counts['FEED'], cares=unit_counts['CARE'],
            waters=unit_counts['WATER'], plants=unit_counts['PLANT'])
        summaries.append(summary | {'primitive_counts': dict(unit_counts), 'market_counts': dict(market_counts),
                                     'market_requested_quantities': dict(market_quantities)})
        terminals.append(dict(**ids, private=final['private'], farm=final_farm))
    harvest_groups: dict[tuple[Any, ...], list[Any]] = defaultdict(list)
    for h in harvests:
        harvest_groups[(h['family'], h['seed'], h['seat'], h['record'], h['x'], h['y'])].append(h)
    duplicates = []
    for h in harvests:
        g = harvest_groups[(h['family'], h['seed'], h['seat'], h['record'], h['x'], h['y'])]
        earlier = [v['actor'] for v in g if v['actor'] < h['actor']]
        if earlier:
            duplicates.append(h | {'earlier_actors': earlier})
    paired = []
    for k, learned in replay_cache.items():
        arm, family, seed, seat = k
        if arm != 'round4_learned':
            continue
        rule = replay_cache[('round4_rule', family, seed, seat)]
        a, b = learned['steps'], rule['steps']
        af, bf = a[-1][seat]['observation']['farms'], b[-1][seat]['observation']['farms']
        ds, do = af[seat]['money'] - bf[seat]['money'], af[1-seat]['money'] - bf[1-seat]['money']
        scope = next(row['scope'] for row in results['rows'] if key(row) == k)
        town_diff = next((i for i in range(len(a)) if a[i][seat]['observation']['town'] != b[i][seat]['observation']['town']), None)
        action_diff = next((i for i in range(1, len(a)) if a[i][1-seat]['action'] != b[i][1-seat]['action']), None)
        paired.append(dict(scope=scope, family=family, seed=seed, seat=seat, delta_self=ds, delta_opponent=do,
            delta_margin=ds-do, first_town_divergence_record=town_diff,
            first_opponent_action_divergence_record=action_diff,
            learned_town=a[-1][seat]['observation']['town'], rule_town=b[-1][seat]['observation']['town']))
    evidence = load_json(root/'EVIDENCE_HASHES.json')
    verified, missing, mismatch = [], [], []
    for name, expected in evidence['files'].items():
        rel = name.replace('\\', '/')
        prefix = 'experiments/learning_round4_20260921/'
        p = root/(rel[len(prefix):] if rel.startswith(prefix) else rel)
        if not p.is_file():
            missing.append(name)
        elif hashlib.sha256(p.read_bytes()).hexdigest() != expected['sha256'] or p.stat().st_size != expected['bytes']:
            mismatch.append(name)
        else:
            verified.append(name)
    manifest_audit = dict(input_zip_sha256=input_sha, entries=len(evidence['files']), verified=len(verified),
                          missing=missing, mismatched=mismatch)
    training = load_json(root/'TRAINING_RECORD.json')
    metric_checks = {}
    for split in ['validation', 'test']:
        cm = training[split]['confusion']
        total = sum(map(sum, cm))
        accuracy = sum(cm[i][i] for i in range(4))/total
        f1s=[]
        for i in range(4):
            denom = sum(cm[i]) + sum(cm[j][i] for j in range(4))
            f1s.append(2*cm[i][i]/denom if denom else 0.0)
        macro_f1 = statistics.mean(f1s)
        metric_checks[split] = dict(rows=total, accuracy_recomputed=accuracy, macro_f1_recomputed=macro_f1,
            arithmetic_matches=abs(accuracy-training[split]['accuracy'])<1e-12 and abs(macro_f1-training[split]['macro_f1'])<1e-12)
    split = load_json(root/'EPISODE_SPLIT_MANIFEST.json')
    episode_sets={s:{x['episode'] for x in split['selected'] if x['split']==s} for s in ['train','validation','test']}
    split_overlap=sum(len(episode_sets[a]&episode_sets[b]) for a,b in [('train','validation'),('train','test'),('validation','test')])
    learner = [x for x in summaries if x['arm']=='round4_learned']
    rule = [x for x in summaries if x['arm']=='round4_rule']
    vanished=[x for x in lifecycle if x['event']=='disappeared']
    scope_summaries = {}
    for scope in sorted({x['scope'] for x in paired}):
        ps=[x for x in paired if x['scope']==scope]
        scope_summaries[scope]={v:statistics.mean(x[v] for x in ps) for v in ['delta_self','delta_opponent','delta_margin']}
    summary = dict(scope='independent saved-replay audit; no new game, training, model load, or online submission',
        replay_count=len(integrity), input_zip_sha256=input_sha,
        replay_hashes_and_money_verified=all(x['sha256_match'] and x['money_match'] and x['opponent_money_match'] and x['seed_match'] for x in integrity),
        all_720_done=all(x['stored_states']==720 and x['statuses']==['DONE','DONE'] for x in integrity),
        learned_mean_final_money=statistics.mean(x['final_money'] for x in learner),
        rule_mean_final_money=statistics.mean(x['final_money'] for x in rule),
        learned_ever_zero_cash=sum(x['min_money']==0 for x in learner),
        learned_games_with_zero_feed=sum(x['feeds']==0 for x in learner),
        harvest_issued=len(harvests), immature_harvest_issued=sum(x['immature'] for x in harvests),
        harvest_positive_actor_delta=sum((x['inventory_increase'] or 0)>0 for x in harvests),
        harvest_boundary_unattributed=sum(x['inventory_increase'] is None for x in harvests),
        duplicate_harvests=len(duplicates), duplicate_harvest_zero_delta=sum(x['inventory_increase']==0 for x in duplicates),
        all_zero_harvests_are_later_duplicates=sum(x['inventory_increase']==0 for x in harvests)==len(duplicates),
        animal_placements=sum(x['event']=='placed' for x in lifecycle), animal_disappearances=len(vanished),
        disappearance_causes_all_prior_unfed1_false_day_boundary=all(x['before']['consecutive_unfed']==1 and not x['before']['fed_today'] and x['day_after']==x['day_before']+1 for x in vanished),
        animal_harvest_issued=sum(x['product'] in ANIMAL_PRODUCTS.values() for x in harvests),
        standing_on_positive_animal_yield_actions=len(opportunities),
        paired_town_sequences_differ=sum(x['first_town_divergence_record'] is not None for x in paired),
        scope_decomposition=scope_summaries, selected_episode_overlap=split_overlap,
        training_confusion_arithmetic=metric_checks, attachment_hash_coverage=manifest_audit)
    # Minimal snapshots are regression inputs, NOT full engine checkpoints.
    fixtures=[]
    mature_example=next((x for x in opportunities if x['tile']['yield_units']==6), opportunities[0]) if opportunities else None
    selected=[('duplicate_harvest_first',duplicates[0]), ('duplicate_harvest_six_actors',max(harvest_groups.values(),key=len)[-1])]
    if mature_example:
        selected.append(('animal_full_yield_no_harvest',mature_example))
    for case_id, ev in selected:
        kk=key(ev);seat=ev['seat']; rec=ev['record'];steps=replay_cache[kk]['steps']
        fixtures.append(dict(case_id=case_id, replay_record=rec, decision_step=rec-1, diagnostic=ev,
            source_relative_path=f"closed_loop/replays/{ev['arm']}/{ev['family']}/seed_{ev['seed']}_seat_{seat}.json.gz",
            before=steps[rec-1][seat]['observation'], joint_action=steps[rec][seat]['action'], after=steps[rec][seat]['observation'],
            restoration_warning='Observation-only fixture; restore full engine state or replay the full prefix before counterfactual continuation.'))
    kk=('round4_learned','qeinstein_moev2',2026092421,0)
    if kk in replay_cache:
        steps=replay_cache[kk]['steps']
        for case_id,rec in [('opening_sell_feed_reserve',7),('first_two_cows_escape',48)]:
            fixtures.append(dict(case_id=case_id,replay_record=rec,decision_step=rec-1,
                source_relative_path='closed_loop/replays/round4_learned/qeinstein_moev2/seed_2026092421_seat_0.json.gz',
                before=steps[rec-1][0]['observation'],joint_action=steps[rec][0]['action'],after=steps[rec][0]['observation'],
                restoration_warning='Observation-only fixture, not full engine checkpoint.'))
    for name,data in [('audit_summary',summary),('replay_integrity',integrity),('replay_summary',summaries),
        ('harvest_events',harvests),('duplicate_harvests',duplicates),('animal_lifecycle',lifecycle),
        ('animal_harvest_opportunities',opportunities),('terminal_states',terminals),('opening_finance',opening),
        ('paired_decomposition',paired),('attachment_manifest_audit',manifest_audit),('round5_regression_fixtures',fixtures)]:
        dump(out/f'{name}.json',data)
    write_csv(out/'replay_summary.csv',[{k:v for k,v in row.items() if not isinstance(v,dict)} for row in summaries])
    write_csv(out/'daily_state.csv',daily)
    write_csv(out/'paired_decomposition.csv',[{k:v for k,v in row.items() if not k.endswith('_town')} for row in paired])
    return summary

def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input',type=Path)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    if not args.input.exists():
        ap.error(f'Input does not exist: {args.input}')
    if args.input.is_dir():
        root=args.input
        if not (root/'ROUND4_REPORT.md').exists() and (root/'learning_round4_20260921').is_dir():
            root=root/'learning_round4_20260921'
        summary=audit(root,args.out,None)
    else:
        digest=hashlib.sha256(args.input.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory(prefix='round4_audit_') as temp:
            root=Path(temp)
            with zipfile.ZipFile(args.input) as z:
                for info in z.infolist():
                    p=PurePosixPath(info.filename)
                    if p.is_absolute() or '..' in p.parts or '\\' in info.filename:
                        raise ValueError(f'Unsafe archive member: {info.filename}')
                z.extractall(root)
            summary=audit(root/'learning_round4_20260921',args.out,digest)
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
