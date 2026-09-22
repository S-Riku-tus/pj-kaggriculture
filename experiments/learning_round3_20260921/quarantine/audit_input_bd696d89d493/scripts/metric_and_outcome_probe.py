import os
from replay_probe import *
import numpy as np, pandas as pd
O=Path(os.environ['AUDIT_OUT'])
met=json.loads((P/'offline_metrics_b2.json').read_text());metrics=[]
for split in ['validation','test']:
 for model,data in [('learned',met[split])]+list(met['baselines'][split].items()):
  if 'by_target' not in data:continue
  for h in [1,4,24]:
   tg=[v for k,v in data['by_target'].items() if k.endswith(':'+str(h))];n=sum(v['rows'] for v in tg)
   metrics.append({'split':split,'model':model,'horizon':h,'cells':n,**{k:sum(v[k]*v['rows'] for v in tg)/n for k in ['brier','quantity_mae']}})
mf=pd.DataFrame(metrics);mf.to_csv(O/'b2_metrics_by_horizon.csv',index=False);print(mf.to_string(index=False))
# Print actual label shapes and training event loss weights.
impact=np.load(P/'datasets/b2/impact_train.npy',mmap_mode='r');mask=np.load(P/'datasets/b2/mask_train.npy',mmap_mode='r')
print('Training targets',impact.shape,mask.shape)
for name in ['MELON:1','FERTILIZER:1']:
 idx=list(met['test']['by_target']).index(name);good=mask[:,idx]>0;pos=int(((impact[:,idx]>0)&good).sum());n=int(good.sum());w=min(20.,(n-pos)/max(pos,1));print(name,'n',n,'positive',pos,'pos_weight',w)
# Exact trace evidence: animal presence and number at day transitions following skipped feed.
trace=[]
for arm in ['c0','a2']:
 r=replay(arm,'mooman_e052a',2026092424,0)
 for t in [242,264,288,312,336]:
  o=obs(r,t,0);farm=o['farms'][0];animals=[{'pos':[x,y],**tile} for y,line in enumerate(farm['tiles']) for x,tile in enumerate(line) if isinstance(tile,dict) and 'animal' in tile]
  trace.append({'arm':arm,'step':t,'animal_count':len(animals),'animals':animals})
  print('animal_count',arm,t,len(animals),[(q['pos'],q['animal'],q.get('consecutive_unfed')) for q in animals])
(O/'a2_animal_outcomes.json').write_text(json.dumps(trace,indent=2))
# Terminal decomposition of A2 first selected job; not a randomized per-job comparison.
f=pd.read_csv(O/'a2_first_selections.csv');group=f.groupby('job').agg(games=('job','size'),sum_terminal_delta=('terminal_margin_delta','sum'),mean_terminal_delta=('terminal_margin_delta','mean'));group.to_csv(O/'a2_delta_by_first_job.csv');print(group.to_string())
