"""Independent saved-replay audit. No training, model inference, or new games.
Usage: python audit_round6.py [extracted_root] [output_dir]
"""
import pathlib,json,gzip,hashlib,collections,sys
import pandas as pd
import numpy as np
R=pathlib.Path(sys.argv[1]) if len(sys.argv)>1 else pathlib.Path('/mnt/data/round6_audit_input/learning_round6_20260922')
O=pathlib.Path(sys.argv[2]) if len(sys.argv)>2 else pathlib.Path('/mnt/data/round6_independent_audit')
O.mkdir(exist_ok=True,parents=True)
def jwrite(name,o): (O/name).write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8')
def obs_at(steps,t,p):
 b=steps[t][0]['observation'].copy();b.update(steps[t][p]['observation']);return b
costs={'WHEAT':10,'CARROT':20,'TOMATO':50,'STRAWBERRY':100,'MELON':80}
def snapshot(obs,p):
 f=obs['farms'][p];pr=obs['private'];tiles=[x for row in f['tiles'] for x in row if isinstance(x,dict)]
 a=collections.Counter(x['animal'] for x in tiles if 'animal' in x);c=collections.Counter(x['crop'] for x in tiles if x.get('kind')=='PLANT')
 return {'cash':f['money'],'land':len(f['unlocked_quadrants']),'hands':len(f['hands']),'animals':sum(a.values()),'crops':sum(c.values()),'weeds':sum(x.get('kind')=='WEED' for x in tiles),'seed_book_cost':sum(costs[k]*v for k,v in pr['seeds'].items()),'seed_units':sum(pr['seeds'].values()),'animal_counts':dict(a),'crop_counts':dict(c),'seeds':pr['seeds']}
rows=[];snaprows=[];actions=[];exits=[];checks=[];signatures={}
df=pd.read_csv(R/'development_evaluation/games.csv')
if len(sys.argv)>3:
 start,end=map(int,sys.argv[3:5]);df=df.iloc[start:end]
for k,rec in enumerate(df.to_dict('records')):
 p=R/'development_evaluation/replays'/rec['arm']/rec['anchor']/f"seed_{rec['seed']}_seat_{rec['seat']}.json.gz"
 b=p.read_bytes();o=json.loads(gzip.decompress(b));steps=o['steps'];seat=rec['seat'];key={k:rec[k] for k in ['arm','anchor','seed','seat']}
 final=obs_at(steps,len(steps)-1,seat);cash=final['farms'][seat]['money'];opp=final['farms'][1-seat]['money']
 checks.append({**key,'hash_ok':hashlib.sha256(b).hexdigest()==rec['replay_sha256'],'seed_ok':o['info'].get('seed')==rec['seed'],'states_ok':len(steps)==720,'status_ok':all(x['status']=='DONE' for x in steps[-1]),'cash_ok':cash==rec['our_cash'] and opp==rec['opponent_cash'] and cash-opp==rec['margin']})
 row={**key,'our_cash':cash,'opponent_cash':opp,'margin':cash-opp,'score':1 if cash>opp else 0.5 if cash==opp else 0}
 hashes=[]
 for side in [seat,1-seat]:
  who='learner' if side==seat else 'opponent';counts=collections.Counter();maxani=0;maxcrop=0;maxhands=0;anidays=0;cropdays=0;move_unchanged=0;amove=0;landbuys=0;firstland=None;lost=0
  for t in range(len(steps)):
   ob=obs_at(steps,t,side);f=ob['farms'][side];s=snapshot(ob,side);maxani=max(maxani,s['animals']);maxcrop=max(maxcrop,s['crops']);maxhands=max(maxhands,s['hands'])
   anidays+=s['animals']/24;cropdays+=s['crops']/24
   if s['land']>1 and firstland is None:firstland=t
   if t%24==0 or t in [96,120,192,240,288,360,480,600,719]:
    sr={**key,'side':who,'step':t,**s};snaprows.append(sr)
   if t==0:continue
   prev=obs_at(steps,t-1,side);pf=prev['farms'][side];act=steps[t][side].get('action') or {};aa=[act.get('farmer',['PASS'])]+act.get('hands',[])
   for cmd in act.get('market',[]):
    if not cmd:
     counts['market:EMPTY']+=1;continue
    token=cmd[0]+(':'+str(cmd[1]) if len(cmd)>1 else '')
    counts['market:'+token]+=1
    if len(cmd)>2:counts['market_requested_units:'+token]+=cmd[2]
    if cmd[0]=='BUY_LAND':landbuys+=1
   for i,cmd in enumerate(aa):
    if i>len(pf['hands']):counts['nonexistent_actor_command']+=1;continue
    op=cmd[0] if cmd else 'EMPTY';counts['actor:'+op]+=1
    if op in ['NORTH','SOUTH','EAST','WEST']:
     amove+=1
     if prev['day']==ob['day']:
      before=pf['farmer'] if i==0 else pf['hands'][i-1]
      after=f['farmer'] if i==0 else f['hands'][i-1]
      if before==after:move_unchanged+=1
   for y,r in enumerate(pf['tiles']):
    for x,bt in enumerate(r):
     at=f['tiles'][y][x]
     if isinstance(bt,dict) and 'animal' in bt and (not isinstance(at,dict) or at.get('animal')!=bt['animal']):
      lost+=1;exits.append({**key,'side':who,'step':t,'day_before':prev['day'],'x':x,'y':y,'animal':bt['animal'],'placed_day':bt['placed_day'],'age':prev['day']-bt['placed_day'],'before':bt,'after':at})
  fs=snapshot(final if side==seat else obs_at(steps,len(steps)-1,side),side)
  row.update({f'{who}_{k}':v for k,v in {'land_final':fs['land'],'first_extra_land':firstland,'max_animals':maxani,'max_crops':maxcrop,'max_hands':maxhands,'animal_days':anidays,'crop_days':cropdays,'animal_exits':lost,'seed_units_final':fs['seed_units'],'seed_book_cost_final':fs['seed_book_cost'],'move_nochange_observed':move_unchanged,'move_commands':amove,'buy_land_commands':landbuys}.items()})
  for token,n in counts.items():actions.append({**key,'side':who,'metric':token,'count':n})
 hashes=[hashlib.sha256(json.dumps([s[z].get('action') for s in steps],sort_keys=True,separators=(',',':')).encode()).hexdigest() for z in [seat,1-seat]]
 signatures[(rec['arm'],rec['anchor'],rec['seed'],seat)]=hashes
 rows.append(row)
 if (k+1)%24==0:print('Audited',k+1,flush=True)
a=pd.DataFrame(rows);a.to_csv(O/'recomputed_games.csv',index=False)
pd.DataFrame(actions).to_csv(O/'action_counts.csv',index=False)
pd.DataFrame([{k:v for k,v in x.items() if not isinstance(v,dict)} for x in snaprows]).to_csv(O/'snapshots.csv',index=False)
jwrite('snapshots_full.json',snaprows);jwrite('animal_exits.json',exits);jwrite('replay_checks.json',checks)
jwrite('hash_checks_summary.json',{'n_games':len(checks),**{k:sum(x[k] for x in checks) for k in checks[0] if k.endswith('_ok')}})
group=a.groupby(['arm','anchor']).mean(numeric_only=True);group.to_csv(O/'group_means.csv')
summary=a.groupby('arm').mean(numeric_only=True);summary.to_csv(O/'arm_means.csv');print(summary[['our_cash','margin','learner_land_final','learner_animal_exits']].to_string())
match=[]
for (arm,anchor,seed,seat),h in signatures.items():
 if anchor=='v122':
  other=signatures.get((arm,'v123',seed,seat))
  if other is None:continue
  match.append({'arm':arm,'seed':seed,'seat':seat,'learner_action_equal':h[0]==other[0],'opponent_action_equal':h[1]==other[1]})
jwrite('v122_v123_action_identity.json',match)
# Local model-member hashes, numerical dimensions and training metrics (not inference).
manifest=json.loads((R/'candidate_v1_archive_manifest.json').read_text());members=[]
for e in manifest['members']:
 p=R/'models/sequence_bc_v1'/e['name'];members.append({'name':e['name'],'available':p.exists(),'hash_ok':hashlib.sha256(p.read_bytes()).hexdigest()==e['sha256'] if p.exists() else None})
jwrite('candidate_member_checks.json',members)
metric=json.loads((R/'candidate_v1_offline_metrics.json').read_text());tables=[];modelrows=[]
for name,model in metric['models'].items():
 z=np.load(R/'models/sequence_bc_v1'/f'{name}.npz',allow_pickle=False);classes=z['classes'].tolist()
 modelrows.append({'name':name,'shapes':{k:list(z[k].shape) for k in z.files},'learned_parameters':sum(z[k].size for k in ['w1','b1','w2','b2']),'test_accuracy':model['test']['accuracy'],'steps':model['optimizer_steps']})
 for split in ['validation','test']:
  met=model[split];conf=np.array(met['confusion']);
  for i,cl in enumerate(classes):
   support=int(conf[i].sum());correct=int(conf[i,i]);pred=int(conf[:,i].sum())
   tables.append({'head':name,'split':split,'class':cl,'support':support,'correct':correct,'predicted':pred,'recall':correct/support if support else None,'precision':correct/pred if pred else None})
pd.DataFrame(tables).to_csv(O/'offline_class_metrics_recomputed.csv',index=False);jwrite('model_shapes.json',modelrows)
print('DONE all_checks',all(all(v for k,v in d.items() if k.endswith('_ok')) for d in checks))
