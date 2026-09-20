import os
import gzip,orjson,collections
import pandas as pd
D=os.environ.get('KAGGRI_OUTPUT_DIR',os.path.abspath('analysis_v125'));m=pd.read_csv(D+'/episode_metrics.csv');m=m[m.episode_type=='EPISODE_TYPE_PUBLIC'];rows=[]
for ii,r in enumerate(m.to_dict('records')):
 d=orjson.loads(gzip.open(f'{D}/compact/{r["episode_id"]}.json.gz','rb').read());s=r['seat'];last={};seen=set()
 for t in sorted(map(int,d['daily_states'][s])):
  farm=d['daily_states'][s][str(t)]['farm']
  for y,row in enumerate(farm['tiles']):
   for x,z in enumerate(row):
    if not isinstance(z,dict):continue
    if z.get('animal'):
     last[(x,y)]=('ANIMAL_'+z['animal'],z['placed_day']);continue
    if not z.get('crop'):continue
    crop=z['crop'];day=z['planted_day'];key=(x,y,crop,day)
    if key not in seen:
     fore=last.get((x,y),('EMPTY_OR_UNOBSERVED',None));rows.append({'episode_id':r['episode_id'],'sid':r['target_submission'],'seat':s,'x':x,'y':y,'crop':crop,'planted_day':day,'first_seen_t':t,'preceding_crop':fore[0],'preceding_planted_day':fore[1]});seen.add(key)
    last[(x,y)]=(crop,day)
 if (ii+1)%200==0:print('DONE',ii+1,flush=True)
f=pd.DataFrame(rows);f.to_csv(D+'/observed_crop_cohorts.csv',index=False);print('COMPLETE',len(f),flush=True)
