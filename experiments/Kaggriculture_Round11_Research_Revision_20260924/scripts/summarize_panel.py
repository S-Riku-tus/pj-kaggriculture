from pathlib import Path
import json,csv,gzip,hashlib,collections,orjson
import os
ROOT=Path(__file__).resolve().parents[1]
P=Path(os.environ.get('R11_OUTPUT',str(ROOT/'recomputed_evidence')))
rows=json.load(open(P/'development_results.json'))
def key(r):return (r['opponent'],r['seed'],r['seat'])
base={key(r):r for r in rows if r['arm']=='B1'}
allrows={(r['arm'],key(r)):r for r in rows};paired=[];identities=[]
def read(r):
 f=P/r['replay_path'];assert hashlib.sha256(f.read_bytes()).hexdigest()==r['replay_sha256']
 with gzip.open(f,'rb') as z:return orjson.loads(z.read())

for r in rows:
 if r['arm']=='B1':continue
 k=key(r);b=base[k];d=read(r);br=read(b);seat=r['seat'];actdiff=0;fielddiff=0;allobsame=True;oppfield=0;first=None
 for t,(x,y) in enumerate(zip(d['records'],br['records'])):
  if x['actions'][seat]!=y['actions'][seat]:
   actdiff+=1
   if first is None:first=t
  for side in [seat,1-seat]:
   ua=[x['actions'][side].get('farmer'),x['actions'][side].get('hands')]
   ub=[y['actions'][side].get('farmer'),y['actions'][side].get('hands')]
   if ua!=ub:
    if side==seat:fielddiff+=1
    else:oppfield+=1
  allobsame=allobsame and x['observations']==y['observations']
 same=allobsame and actdiff==0 and d['terminal']==br['terminal'] and all(x['actions']==y['actions'] for x,y in zip(d['records'],br['records']))
 rr={'arm':r['arm'],'opponent':k[0],'seed':k[1],'seat':k[2],'base_points':b['points'],'candidate_points':r['points'],'delta_points':r['points']-b['points'],
     'delta_self_cash':r['self_cash']-b['self_cash'],'delta_opp_cash':r['opp_cash']-b['opp_cash'],'delta_margin':r['margin']-b['margin'],
     'self_action_differences':actdiff,'self_field_differences':fielddiff,'opp_field_differences':oppfield,'first_difference':first,'all_observations_actions_terminal_identical':same,'town_same':r['shops']==b['shops']}
 paired.append(rr)
 # Interventions can leave field commands identical, yet still change economic outcomes.
G=[]
for arm in ['B1','wool_gate_open','final_response','combined']:
 rr=[r for r in rows if r['arm']==arm];pr=[r for r in paired if r['arm']==arm];n=len(rr)
 g={'arm':arm,'games':n,'wins':sum(r['margin']>0 for r in rr),'draws':sum(r['margin']==0 for r in rr),'losses':sum(r['margin']<0 for r in rr),
   'point_rate':sum(r['points'] for r in rr)/n,'mean_margin':sum(r['margin'] for r in rr)/n,'mean_self_cash':sum(r['self_cash'] for r in rr)/n,
   'mean_delta_points':sum(r['delta_points'] for r in pr)/n,'mean_delta_margin':sum(r['delta_margin'] for r in pr)/n,
   'changed_decisions_vs_b1':sum(r['self_action_differences'] for r in pr),'changed_field_decisions_vs_b1':sum(r['self_field_differences'] for r in pr),
   'all_trajectory_identical_games':sum(r['all_observations_actions_terminal_identical'] for r in pr),
   'overlay_evaluations':sum(r['response']['evaluations'] for r in rr),'overlay_changes':sum(r['response']['changes'] for r in rr),
   'overlay_eligible':sum(r['response']['eligible'] for r in rr)}
 G.append(g)

def write(name,rows):
 keys=list(dict.fromkeys(k for r in rows for k in r))
 with (P/name).open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
write('development_panel_summary.csv',G);write('development_paired_comparisons.csv',paired)
write('development_game_results.csv',[{k:v for k,v in r.items() if k not in ['shops','response']}|{f'response_{k}':v for k,v in r['response'].items()} for r in rows])
summary={'games':len(rows),'complete_unique_keys':len(allrows),'full_turn_games':sum(r['done'] and r['decisions']==719 for r in rows),'errors':sum(r['error'] is not None for r in rows),
 'total_decisions':sum(r['decisions'] for r in rows),'order_cap_violations':sum(r['order_cap_violations'] for r in rows),'training_runs':0,'kaggle_submissions':0,
 'scope':'128 unique responding full-game simulations on supplied cppsim; development only, 4 shared seed blocks and 4 related public opponents; no official Python runtime run',
 'results':G}
(P/'development_summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
