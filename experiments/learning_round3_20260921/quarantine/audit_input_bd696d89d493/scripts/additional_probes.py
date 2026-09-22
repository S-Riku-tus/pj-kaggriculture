import os
from replay_probe import *
import numpy as np,pandas as pd,collections
O=Path(os.environ['AUDIT_OUT'])
# Frozen-model counterfactual input diagnostics: NOT a policy evaluation or replacement model.
m=load('a2'); model=m.MODEL
rows=[json.loads(l) for r in (1,2) for l in (P/f'datasets/a2/round{r}_candidate_results.jsonl').read_text().splitlines()]
train=np.array([r['feature'] for r in rows if r['split']=='train'],dtype=np.float32)
constant=train.std(0)<1e-3
out=[]
for row in json.loads((O/'a2_first_selections.json').read_text()):
 r=replay('c0',row['family'],row['seed'],row['seat']);hist=m.MarketHistory();t=row['selected_step'];seat=row['seat']
 for i in range(t+1):hist.update(obs(r,i,seat),r['steps'][i][seat]['action'].get('market',[]) if i else None)
 f=m.a2_features(obs(r,t,seat),row['candidate'],hist);z=(f-model.mean)/model.scale
 variants={'original':z,'zero_constant':np.where(constant,0.,z),'clip10':np.clip(z,-10,10),'zero_constant_clip10':np.clip(np.where(constant,0.,z),-10,10)}
 result={k:row[k] for k in ['family','seed','seat','selected_step']};result['job']=row['candidate']['job_type']
 for name,vec in variants.items():
  h=np.maximum(0,vec@model.w1+model.b1);y=h@model.w2+model.b2;v=float(y[0]);risk=float(1/(1+np.exp(-np.clip(y[1],-30,30))))
  result.update({name+'_value':v,name+'_risk':risk,name+'_pass_gate':v>m.VALUE_GATE and risk<m.RISK_GATE})
 out.append(result)
df=pd.DataFrame(out);df.to_csv(O/'a2_normalization_ablation.csv',index=False)
print('A2 FROZEN INPUT ABLATION, number passing value/risk gates', {c:int(df[c].sum()) for c in df if c.endswith('_pass_gate')})
print(df.iloc[[0,6,8]].to_string(index=False))
# Aggregate reported B2 metrics by horizon, with actual mask/actionability counts.
met=json.loads((P/'offline_metrics_b2.json').read_text());print('B2 metric top keys',list(met))
# Use reported metrics, do not pretend absent feature arrays or predictions were recomputed.
for name,val in met.items():
 if isinstance(val,dict) and 'by_target' in val:
  print('METRICS',name)
  for horizon in (1,4,24):
   targets=[v for k,v in val['by_target'].items() if k.endswith(':'+str(horizon))]
   print('h',horizon,'brier',sum(v['brier']*v['rows'] for v in targets)/sum(v['rows'] for v in targets),'qmae',sum(v['quantity_mae']*v['rows'] for v in targets)/sum(v['rows'] for v in targets))
# Selected A2 replay trace, including farmer inventories/tile/shed before and after.
trace={}
for fam,seed,seat,actor,t0 in [('mooman_e052a',2026092424,0,8,240),('mooman_e052a',2026092421,0,10,277)]:
 case=[]
 for arm in ['c0','a2']:
  r=replay(arm,fam,seed,seat)
  for t in range(t0,t0+12):
   o=obs(r,t,seat);farm=o['farms'][seat]
   if actor and len(farm['hands'])<actor: continue
   pos=farm['hands'][actor-1] if actor else farm['farmer'];a=r['steps'][t+1][seat]['action'];inv=o['private']['inventories'][actor] if actor<len(o['private']['inventories']) else None
   case.append({'arm':arm,'step':t,'actor':actor,'position':pos,'inventory':inv,'tile':farm['tiles'][pos[1]][pos[0]],'action':a['hands'][actor-1] if len(a['hands'])>=actor else None,'shed':o['private']['shed'],'shed_total':sum(o['private']['shed'].values()),'money':farm['money']})
 trace[f'{fam}_{seed}_seat{seat}_actor{actor}']=case
 print('\nTRACE',fam,seed)
 for s in case:print(s['arm'],s['step'],s['position'],s['inventory'],'action=',s['action'],'shedtotal=',s['shed_total'])
(O/'a2_execution_traces.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2))
