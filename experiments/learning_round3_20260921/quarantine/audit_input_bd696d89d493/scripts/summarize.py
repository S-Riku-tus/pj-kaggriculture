import os
from pathlib import Path
import json,gzip,collections
import numpy as np,pandas as pd
P=Path(os.environ['ROUND2_ROOT'])
O=Path(os.environ['AUDIT_OUT'])
df=pd.read_csv(P/'external_bank/paired_results.csv')
print('SUMMARY')
print(df.groupby('arm').agg(games=('score','size'),wins=('score','sum'),cash=('our_cash','mean'),opp_cash=('opponent_cash','mean'),margin=('margin','mean'),margin_delta=('paired_margin_delta_vs_c0','mean'),actions=('action_differences_vs_c0','sum')).to_string())
print('BY FAMILY')
print(df.groupby(['arm','opponent_family']).agg(wins=('score','sum'),delta=('paired_margin_delta_vs_c0','mean'),n=('score','size')).to_string())
print('B2/B1 GAME DELTAS')
print(df[df.arm.isin(['b2','b1'])][['arm','opponent_family','requested_seed','seat','margin','paired_margin_delta_vs_c0','action_differences_vs_c0','first_action_difference']].to_string(index=False))
print('A2 DATA')
recs=[]
for r in [1,2]:
 recs+= [json.loads(x) for x in (P/f'datasets/a2/round{r}_candidate_results.jsonl').read_text().splitlines()]
rdf=pd.DataFrame(recs).drop(columns=['feature'])
print(rdf.groupby(['round','job_type']).agg(n=('job_type','size'),d=('delta_margin','mean'),mind=('delta_margin','min'),maxd=('delta_margin','max'),start=('step','min'),end=('step','max')).to_string())
print(rdf.groupby(['round','split']).agg(n=('job_type','size'),p=('prefix_id','nunique'),s=('seed','nunique')).to_string())
rdf.to_json(O/'a2_records_without_features.json',orient='records',indent=2)
h=json.loads((P/'b_opportunity_headroom.json').read_text());hd=pd.DataFrame(h['rows']);n=hd.replay.nunique()
print('HEADROOM games',n,'rows',len(hd),'total max',hd.hindsight_gain_vs_c0.sum(),'avg',hd.hindsight_gain_vs_c0.sum()/n)
print(hd.groupby('family')[['hindsight_gain_vs_c0','b1_gain_vs_c0','simple_gain_vs_c0']].sum().to_string())
print('headroom per game',hd.groupby('replay').hindsight_gain_vs_c0.sum().describe().to_dict())
print('largest',hd.nlargest(5,'hindsight_gain_vs_c0')[['family','step','hindsight_gain_vs_c0']].to_dict('records'))
hd.to_csv(O/'headroom_rows.csv',index=False)
# concise offline metric summary
b=json.loads((P/'offline_metrics_b2.json').read_text())
print('B2 metrics keys',list(b['test']))
for key in ['test','baselines']:
 if key=='test':print(json.dumps(b[key],ensure_ascii=False)[:4000])
 else:
  for k,v in b[key]['test'].items():print(k,json.dumps(v,ensure_ascii=False)[:1000])
