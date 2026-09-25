import os
os.environ['OPENBLAS_NUM_THREADS']='1'
import json,hashlib,zipfile,io
from pathlib import Path
import numpy as np,pandas as pd
R=Path(os.environ.get('ROUND9_ROOT', '/mnt/data/audit_work/round9_teacher_reproduction_and_closed_loop_bc_20260923'));O=Path(os.environ.get('AUDIT_EVIDENCE', str(Path(__file__).resolve().parents[1] / 'evidence')))
z=zipfile.ZipFile(os.environ.get('ROUND9_ZIP', '/mnt/data/round9_teacher_reproduction_and_closed_loop_bc_20260923.zip'))
def arr(name):
 return np.load(io.BytesIO(z.read(R.name+'/a2_prefix_bc/dataset_v1/'+name)),allow_pickle=False)
def predict(x,m):
 y=(x-m['mean'])/m['scale']
 for i in range(1,4):
  y=y@m['w'+str(i)]+m['b'+str(i)]
  if i<3:y=np.maximum(y,0)
 return y
results={};rows=[]
for head in ['actor_token','market_token']:
 typ=head.split('_')[0];p=R/'a2_prefix_bc/models_v1/seed_20260924'/f'{head}.npz'
 m=np.load(p,allow_pickle=False);meta=json.loads(p.with_suffix('.json').read_text());x=arr(typ+'_x_test.npy');y=arr(typ+'_y_test.npy');logits=predict(x,m);pred=logits.argmax(1)
 labels=[str(s) for s in m['classes']];cm=np.zeros((len(labels),len(labels)),dtype=int);np.add.at(cm,(y,pred),1)
 ini=np.load(p.with_name(head+'_initial.npz'),allow_pickle=False);pi=predict(x,ini).argmax(1)
 groups={'all':list(range(len(labels)))}
 if typ=='actor':groups.update(movement=[1,2,3,4],movement_pass=[0,1,2,3,4],work=list(range(5,len(labels))))
 else:groups.update(eos_hire=[0,1],non_eos_hire=list(range(2,len(labels))),sell=[i for i,l in enumerate(labels) if l.startswith('SELL:')],investment=[2,3,4,5,6,7,8,9,10,11,12])
 stats={}
 for key,idx in groups.items():
  mask=np.isin(y,idx);stats[key]={'correct':int(np.sum(pred[mask]==y[mask])),'rows':int(mask.sum()),'accuracy':float(np.mean(pred[mask]==y[mask]))}
 for i,l in enumerate(labels):
  n=int(cm[i].sum());rows.append(dict(head=head,label=l,correct=int(cm[i,i]),support=n,recall=float(cm[i,i]/n) if n else None,predicted_eos=int(cm[i,0]) if typ=='market' else None))
 results[head]={'rows':len(y),'initial_accuracy':float(np.mean(pi==y)),'accuracy':float(np.mean(pred==y)),'stored_confusion_exact':cm.tolist()==meta['test']['confusion'],'checkpoint_hash_ok':hashlib.file_digest(open(p,'rb'),'sha256').hexdigest()==meta['sha256'],'groups':stats,'normalization_mean_zero':bool(np.all(m['mean']==0)),'normalization_scale_one':bool(np.all(m['scale']==1))}
 print(head,results[head],flush=True)
 if typ=='actor':
  # Descriptive inverse-sampling estimate, not an unsampled metric.
  w=np.where(np.isin(y,[0,1,2,3,4]),8.,1.)
  results[head]['sampling_reweighted_accuracy_estimate']=float(np.sum(w*(y==pred))/w.sum())
 if typ=='market':
  idx=groups['non_eos_hire'];results[head]['non_eos_hire_predicted_eos']={'count':int(cm[idx,0].sum()),'denominator':int(cm[idx].sum())}
 del x,logits,m,ini
pd.DataFrame(rows).to_csv(O/'independent_model_class_metrics.csv',index=False)
(O/'independent_model_inference.json').write_text(json.dumps(results,indent=2))
# Model identities across both training seeds, all four heads.
identities=[]
for p in (R/'a2_prefix_bc/models_v1').glob('seed_*/*.json'):
 if p.stem=='training_summary':continue
 m=json.loads(p.read_text());fp=p.with_suffix('.npz');ip=p.with_name(p.stem+'_initial.npz')
 identities.append(dict(seed=p.parent.name,head=p.stem,final_hash=hashlib.file_digest(open(fp,'rb'),'sha256').hexdigest(),initial_hash=hashlib.file_digest(open(ip,'rb'),'sha256').hexdigest(),declared_hash_matches=hashlib.file_digest(open(fp,'rb'),'sha256').hexdigest()==m['sha256'] and hashlib.file_digest(open(ip,'rb'),'sha256').hexdigest()==m['initial_sha256'],optimizer_steps_total=m['optimizer_steps_total'],optimizer_steps_at_checkpoint=m['optimizer_steps_at_checkpoint']))
(O/'checkpoint_identities.json').write_text(json.dumps(identities,indent=2))
provenance={}
for kind in ['actor','market']:
 d=pd.read_csv(R/'a2_prefix_bc/dataset_v1'/f'{kind}_row_provenance.csv.gz')
 print(kind,'provenance columns',list(d));print(d.head(1).to_dict('records'))
 provenance[kind]={'columns':list(d),'rows':len(d)}
 if 'partition' in d:
  provenance[kind]['partition_counts']=d['partition'].value_counts().to_dict()
  ep='episode_id' if 'episode_id' in d else 'episode'
  if ep in d:provenance[kind]['episode_counts']=d.groupby('partition')[ep].nunique().to_dict()
(O/'provenance_counts.json').write_text(json.dumps(provenance,indent=2))
