"""Summarize saved Round6 audit outputs; no new game or model inference."""
from pathlib import Path
import json, math
import pandas as pd
A=Path(__file__).resolve().parent
G=pd.read_csv(A/'recomputed_games.csv')
M=pd.read_csv(A/'offline_class_metrics_recomputed.csv')
S=pd.read_csv(A/'snapshots.csv')
checks=json.loads((A/'replay_checks.json').read_text())
summary={'scope':'Independent reanalysis of saved evidence, no training/model inference/new games.',
 'input_zip_sha256':'35d34590656e9e1b10e84e3b6a420c80c9a37302b02bcba267cf03e480f72af3',
 'development_integrity':{'n_games':len(checks),**{k:sum(bool(x[k]) for x in checks) for k in ['hash_ok','seed_ok','states_ok','status_ok','cash_ok']}},
 'runtime_replay_checks':json.loads((A/'runtime_replay_checks.json').read_text()),
 'arm_outcomes':[], 'quantity_buckets':[], 'new_bc_structural':{}, 'statistics_planning':{}}
for arm,g in G.groupby('arm'):
 summary['arm_outcomes'].append({'arm':arm,'games':len(g),'wins':int((g.score==1).sum()),'draws':int((g.score==.5).sum()),'losses':int((g.score==0).sum()),'mean_cash':float(g.our_cash.mean()),'mean_margin':float(g.margin.mean())})
for head in ['actor_quantity','market_quantity']:
 m=M[(M['head']==head)&(M['split']=='test')].copy();m['quantity']=pd.to_numeric(m['class'])
 for label,filt in [('all',m.quantity>=0),('1',m.quantity==1),('>=2',m.quantity>=2),('>=10',m.quantity>=10),('>=15',m.quantity>=15)]:
  b=m[filt];n=int(b.support.sum());c=int(b.correct.sum());summary['quantity_buckets'].append({'head':head,'bucket':label,'support':n,'correct':c,'accuracy':c/n if n else None})
g=G[G.arm=='round6_sequence_bc_v1']
summary['new_bc_structural']={'games':len(g),'never_extra_land':int((g.learner_land_final==1).sum()),'first_extra_land_mean_conditional_on_acquisition':float(g.learner_first_extra_land.mean()),'first_extra_land_n_acquirers':int(g.learner_first_extra_land.notna().sum()),'opponent_first_extra_land_mean':float(g.opponent_first_extra_land.mean()),'animal_exits':int(g.learner_animal_exits.sum()),'opponent_animal_exits':int(g.opponent_animal_exits.sum()),'animal_days_mean':float(g.learner_animal_days.mean()),'opponent_animal_days_mean':float(g.opponent_animal_days.mean()),'max_simultaneous_animals_mean':float(g.learner_max_animals.mean()),'opponent_max_simultaneous_animals_mean':float(g.opponent_max_animals.mean()),'snapshot_means':{}}
for t in [96,192,240,288,360,480,600,719]:
 b=S[(S.arm=='round6_sequence_bc_v1')&(S.step==t)];summary['new_bc_structural']['snapshot_means'][t]=b.groupby('side')[['cash','land','animals','crops']].mean().to_dict('index')
ex=json.loads((A/'animal_exits.json').read_text()); ex=[x for x in ex if x['arm']=='round6_sequence_bc_v1' and x['side']=='learner']
summary['new_bc_structural']['all_exits_day_boundary_unfed_pattern']=all(x['step']%24==0 and x['before'].get('consecutive_unfed')==1 and x['before'].get('fed_today')==False and 'animal' not in x['after'] for x in ex)
summary['new_bc_structural']['pre_refresh_age_below_first_yield_threshold']=sum(x['age']<{'COW':8,'SHEEP':6,'GOOSE':4}[x['animal']] for x in ex)
summary['new_bc_structural']['threshold_note']='Age before daily refresh. Includes exits immediately before first scheduled production. Derived using published rule thresholds, not a new counterfactual.'
summary['statistics_planning']={'hoeffding_one_sided_95_penalty_32_blocks':math.sqrt(math.log(20)/(2*32)),'lower_at_60_percent_32_blocks':.6-math.sqrt(math.log(20)/(2*32)),'strict_n_greater_than_for_lower_above_50_at_60':math.log(20)/(2*.1**2),'note':'Conservative planning illustration, not a revised preregistered promotion rule.'}
(A/'independent_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary['quantity_buckets'],indent=2))
print('wrote',A/'independent_summary.json')
