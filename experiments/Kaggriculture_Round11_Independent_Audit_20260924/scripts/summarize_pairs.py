"""Recompute paired trajectory changes and seed-cluster statistics from uploaded replays."""
from pathlib import Path
import argparse,gzip,json,multiprocessing as mp
import orjson,numpy as np,pandas as pd

def read(p):return orjson.loads(gzip.decompress(Path(p).read_bytes()))
def one(job):
 panel,r,arm,opp,seed,seat,expected=job;root=Path(r)/panel/'replays';b=read(root/'B1'/opp/f'seed_{seed}_seat_{seat}.json.gz');c=read(root/arm/opp/f'seed_{seed}_seat_{seat}.json.gz')
 counts=dict(own_action_changed_decisions=0,own_field_changed_decisions=0,own_market_changed_decisions=0,opponent_action_changed_decisions=0,observations_changed_decisions=0)
 first=None;first_fields=None;first_shops=None;divs=[]
 for x,y in zip(b['decisions'],c['decisions']):
  ba,ca=x['actions'][seat],y['actions'][seat];t=x['step']
  if ba!=ca:
   counts['own_action_changed_decisions']+=1
   if first is None:
    first=t;divs.append(dict(step=t,baseline_market=ba['market'],candidate_market=ca['market'],identical_observation=x['observations']==y['observations'],prices=x['observations'][seat]['market']['prices'],shed=x['observations'][seat]['private']['shed']))
  if (ba.get('farmer'),ba.get('hands'))!=(ca.get('farmer'),ca.get('hands')):
   counts['own_field_changed_decisions']+=1
   if first_fields is None:first_fields=t
  if ba.get('market')!=ca.get('market'):counts['own_market_changed_decisions']+=1
  if x['actions'][1-seat]!=y['actions'][1-seat]:counts['opponent_action_changed_decisions']+=1
  if x['observations']!=y['observations']:counts['observations_changed_decisions']+=1
  if first_shops is None and x['observations'][seat]['town']!=y['observations'][seat]['town']:first_shops=t
 bm=b['rewards'][seat]-b['rewards'][1-seat];cm=c['rewards'][seat]-c['rewards'][1-seat]
 res=lambda m:'W' if m>0 else 'L' if m<0 else 'T'
 score=lambda m:1.0 if m>0 else 0 if m<0 else .5
 errors=[k for k in counts if k in expected and counts[k]!=int(expected[k])]
 return dict(panel=panel,arm=arm,opponent=opp,seed=seed,seat=seat,baseline_margin=bm,candidate_margin=cm,transition=res(bm)+'->'+res(cm),delta_points=score(cm)-score(bm),delta_margin=cm-bm,delta_self_cash=c['rewards'][seat]-b['rewards'][seat],delta_opp_cash=c['rewards'][1-seat]-b['rewards'][1-seat],first_action_change=first,first_field_change=first_fields,first_shop_change=first_shops,first_difference=json.dumps(divs,ensure_ascii=False),metric_mismatches=';'.join(errors),full_trajectory_identical=all(v==0 for v in counts.values()) and b['rewards']==c['rewards'],**counts)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--workspace',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();r=Path(a.workspace);out=Path(a.out);jobs=[]
 for panel in ['holdout/m20_kagsim','track_b/conditional_wool_kagsim']:
  f=pd.read_csv(r/panel/'paired_results.csv')
  for row in f.to_dict('records'):
   jobs.append((panel,str(r),row['arm'],row['opponent_id'],int(row['seed']),int(row['seat']),row))
 with mp.Pool(4) as pool:rows=pool.map(one,jobs)
 d=pd.DataFrame(rows);d.to_csv(out/'independent_paired_trajectories.csv',index=False)
 h=d[d.panel=='holdout/m20_kagsim'];seed=h.groupby('seed').delta_points.mean();rng=np.random.default_rng(20260924);boot=seed.to_numpy()[rng.integers(0,len(seed),size=(100000,len(seed)))].mean(axis=1)
 by=h.groupby('opponent')[['delta_points','delta_margin','delta_self_cash','delta_opp_cash']].agg(['sum','mean']);by.to_csv(out/'holdout_by_opponent.csv');h[h.transition=='W->L'].to_csv(out/'holdout_win_to_loss_cases.csv',index=False)
 summary=dict(paired_trajectories=len(d),metric_mismatches=int((d.metric_mismatches!='').sum()),holdout_transitions=h.transition.value_counts().to_dict(),holdout_changes={c:int(h[c].sum()) for c in ['own_action_changed_decisions','own_field_changed_decisions','own_market_changed_decisions','opponent_action_changed_decisions']},holdout_identical=int(h.full_trajectory_identical.sum()),holdout_points_delta=float(h.delta_points.sum()),holdout_mean_margin_delta=float(h.delta_margin.mean()),seed_clusters=len(seed),seed_delta_points=seed.to_dict(),bootstrap_quantiles={str(q):float(np.quantile(boot,q)) for q in [.05,.10,.50,.90,.95]},win_to_loss_unique_worlds=int(h[h.transition=='W->L'].seed.nunique()),win_to_loss_worlds=sorted(h[h.transition=='W->L'].seed.unique().tolist()),cw1_identical=int(d[d.arm=='cw1_conditional_wool'].full_trajectory_identical.sum()),limitations='Bootstrap covers supplied related opponents, not source-family generalization; former holdout is now development evidence.')
 (out/'independent_paired_summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
