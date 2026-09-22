import os
from replay_probe import *
import numpy as np,pandas as pd,collections
m=load('a2')
rec=[]
for r in (1,2):rec += [json.loads(x) for x in (P/f'datasets/a2/round{r}_candidate_results.jsonl').read_text().splitlines()]
train=[r for r in rec if r['split']=='train'];x=np.array([r['feature'] for r in train]);names=json.loads((P/'models/a2_model.json').read_text())['feature_names']
print('train rows',len(train),'prefixes',len(set(r['prefix_id'] for r in train)),'constant',int((x.std(0)<1e-3).sum()),'dim',x.shape[1]);print('train job types',collections.Counter(r['job_type'] for r in train),'train steps',collections.Counter(r['step'] for r in train))
out=[]
df=pd.read_csv(P/'external_bank/paired_results.csv')
for row in df[df.arm=='a2'].to_dict('records'):
 fam,seed,seat=row['opponent_family'],row['requested_seed'],row['seat'];r=replay('c0',fam,seed,seat);hist=m.MarketHistory();chosen=None
 for t in range(min(719,int(row['first_action_difference'])+1)):
  o=dict(r['steps'][t][0]['observation']);o['player']=seat;o['private']=r['steps'][t][seat]['observation']['private'];o['step']=t
  hist.update(o,r['steps'][t][seat]['action'].get('market') if t else None)
  if t<240:continue
  control=r['steps'][t+1][seat]['action'];cand=m.a2_candidates(o,control,t_min=240)
  if not cand:continue
  ranks=[]
  for ca in cand:
   ft=m.a2_features(o,ca,hist);v,p=m.MODEL.predict(ft);ranks.append((v,-p,ca,ft))
  v,np_,ca,ft=max(ranks,key=lambda a:(a[0],a[1],a[2]['candidate_id']))
  if not (v>m.VALUE_GATE and -np_<m.RISK_GATE):continue
  z=(ft-m.MODEL.mean)/m.MODEL.scale;top=np.argsort(np.abs(z))[-8:][::-1]
  fields=[{'name':names[i],'x':float(ft[i]),'mean':float(m.MODEL.mean[i]),'scale':float(m.MODEL.scale[i]),'z':float(z[i])} for i in top]
  out.append({'family':fam,'seed':seed,'seat':seat,'selected_step':t,'first_difference':row['first_action_difference'],'candidate':ca,'predicted_value':v,'predicted_risk':-np_,'max_abs_z':float(np.abs(z).max()),'n_z_gt_10':int((np.abs(z)>10).sum()),'n_changed_constant_features':int(((np.abs(ft-m.MODEL.mean)>1e-3)&(x.std(0)<1e-3)).sum()),'top_features':fields,'terminal_margin_delta':row['paired_margin_delta_vs_c0']});break
 else:print('NO MATCH',fam,seed,seat)
(Path(os.environ['AUDIT_OUT'])/'a2_first_selections.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
s=pd.DataFrame([{k:v for k,v in o.items() if k not in ['candidate','top_features']}|{'job':o['candidate']['job_type'],'actor':o['candidate']['actor_index']} for o in out]);s.to_csv((Path(os.environ['AUDIT_OUT'])/'a2_first_selections.csv'),index=False)
print(s.to_string(index=False));print('jobs',s.job.value_counts().to_dict());print('TOP EXAMPLE',json.dumps(out[0],indent=2));print('parameter_count',m.MODEL.w1.size+m.MODEL.b1.size+m.MODEL.w2.size+m.MODEL.b2.size)
