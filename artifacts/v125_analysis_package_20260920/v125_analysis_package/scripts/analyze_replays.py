"""Stream uploaded ZIPs. Replay action at t maps observation t-1 to t."""
import os,re,zipfile,orjson,collections,hashlib,io,gzip,time
import pandas as pd
from concurrent.futures import ProcessPoolExecutor,as_completed
ROOT=os.environ.get('KAGGRI_INPUT_DIR',os.getcwd()); OUT=os.environ.get('KAGGRI_OUTPUT_DIR',os.path.join(ROOT,'analysis_v125')); os.makedirs(OUT+'/compact',exist_ok=True)
FILES=[]
for _name in sorted(os.listdir(ROOT)):
 if _name.endswith('.zip') and re.search(r'submission_\d+',_name):
  with zipfile.ZipFile(os.path.join(ROOT,_name)) as _z:
   if any('/replay' in _p and _p.endswith('.json') for _p in _z.namelist()): FILES.append(_name)
if not FILES: raise FileNotFoundError('No submission ZIP containing replay JSON found in input directory')
PRODUCTS=['WHEAT','CARROT','TOMATO','STRAWBERRY','MELON','EGG','MILK','WOOL','FERTILIZER']; ANIMALS=['COW','SHEEP','GOOSE']; CROPS=PRODUCTS[:5]
COUNTKEYS=['COW','SHEEP','GOOSE','WHEAT','CARROT','TOMATO','STRAWBERRY','MELON','WEED','empty','LOCKED','empty_PASTURE','empty_COOP','unwatered','unfed','uncared','yield_WHEAT','yield_CARROT','yield_TOMATO','yield_STRAWBERRY','yield_MELON','yield_EGG','yield_MILK','yield_WOOL','fert_available']
I={s:i for i,s in enumerate(COUNTKEYS)}

def parse(job):
 eid,zfile,member=job; path=OUT+'/compact/'+str(eid)+'.json.gz'
 if os.path.exists(path):return eid,'cached'
 with zipfile.ZipFile(ROOT+'/'+zfile) as z:r=orjson.loads(z.read(member))
 steps=r['steps']; l=len(steps)
 d={'episode_id':eid,'archive':zfile,'member':member,'configuration':r.get('configuration'), 'module_version':r.get('module_version'),'info':r.get('info'),'rewards':r.get('rewards'),'statuses':r.get('statuses'),'countkeys':COUNTKEYS,'products':PRODUCTS,'steps':l,'money':[],'counts':[],'hands':[],'land':[],'private':[],'actions':[],'daily_states':[],'overage_min':[],'obs_logs_nonempty':[],'prices':[],'market_inventory':[]}
 for t,s in enumerate(steps):
  o=s[0]['observation'];d['prices'].append([o['market']['prices'].get(p,0) for p in PRODUCTS]);d['market_inventory'].append([o['market']['inventory'].get(p,0) for p in PRODUCTS])
 for p in range(2):
  money=[];counts=[];hands=[];land=[];priv=[];acts=[];daily={}; over=60; logs=0
  for t,s in enumerate(steps):
   o=s[p]['observation']; f=o['farms'][p];money.append(f['money']); hands.append(len(f['hands']));land.append(len(f['unlocked_quadrants']));c=[0]*len(COUNTKEYS)
   for row in f['tiles']:
    for tile in row:
     if tile is None:c[I['empty']]+=1
     elif isinstance(tile,str):
      if tile in I:c[I[tile]]+=1
     else:
      kind=tile.get('kind','')
      if kind=='PLANT':
       crop=tile['crop'];c[I[crop]]+=1;c[I['yield_'+crop]]+=tile.get('yield_units',0);c[I['unwatered']]+=int(not tile.get('watered_today',False))
      elif kind in ('PASTURE','COOP'):
       a=tile.get('animal')
       if a:
        c[I[a]]+=1;product={'COW':'MILK','SHEEP':'WOOL','GOOSE':'EGG'}[a];c[I['yield_'+product]]+=tile.get('yield_units',0);c[I['unfed']]+=int(not tile.get('fed_today',False));c[I['uncared']]+=int(not tile.get('cared_today',False));c[I['fert_available']]+=int(tile.get('fertilizer_available',False))
       else:c[I['empty_'+kind]]+=1
      elif kind=='WEED':c[I['WEED']]+=1
   counts.append(c)
   pr=o.get('private',{});shed=pr.get('shed',{});invs=pr.get('inventories',[])
   priv.append({'shed':[shed.get(k,0) for k in PRODUCTS+ANIMALS], 'carry':[sum(inv.get(k,0) for inv in invs) for k in PRODUCTS], 'seed':[pr.get('seeds',{}).get(k,0) for k in CROPS]})
   acts.append(s[p].get('action') or {});over=min(over,o.get('remainingOverageTime',60));logs+=int(bool(o.get('logs')))
   if t%24==0 or t==l-1:daily[str(t)]={'farm':f,'private':pr}
  d['money'].append(money);d['counts'].append(counts);d['hands'].append(hands);d['land'].append(land);d['private'].append(priv);d['actions'].append(acts);d['daily_states'].append(daily);d['overage_min'].append(over);d['obs_logs_nonempty'].append(logs)
 with gzip.open(path,'wb',compresslevel=3) as out:out.write(orjson.dumps(d))
 return eid,'ok'

def main():
 allmeta=[];jobs={}
 for fn in FILES:
  z=zipfile.ZipFile(ROOT+'/'+fn);ns=z.namelist();sid=int(re.search(r'submission_(\d+)',fn).group(1))
  df=pd.read_csv(io.BytesIO(z.read(next(n for n in ns if n.endswith('episodes.csv')))))
  mf=pd.read_csv(io.BytesIO(z.read(next(n for n in ns if n.endswith('manifest.csv')))))
  df['target_submission']=sid;df['archive']=fn
  cols=[x for x in ['episode_id','submission_seat','opponent_submission_id','team_name','opponent_team_name','result','own_reward','opponent_reward','step_count'] if x in mf]
  df=df.merge(mf[cols],on='episode_id',how='left',suffixes=('','_manifest'))
  df['seat']=(df['agent_1_submission_id']==sid).astype(int)
  df['opponent_submission']=df.apply(lambda x:x['agent_'+str(1-x['seat'])+'_submission_id'],axis=1)
  df['opponent_rating']=df.apply(lambda x:x['agent_'+str(1-x['seat'])+'_initial_score'],axis=1)
  df['initial_rating']=df.apply(lambda x:x['agent_'+str(x['seat'])+'_initial_score'],axis=1)
  df['updated_rating']=df.apply(lambda x:x['agent_'+str(x['seat'])+'_updated_score'],axis=1)
  allmeta.append(df)
  for n in ns:
   if '/replay' in n and n.endswith('.json'):
    eid=int(re.search(r'episode_(\d+)\.json$',n).group(1));jobs.setdefault(eid,(eid,fn,n))
 meta=pd.concat(allmeta,ignore_index=True).drop_duplicates(['target_submission','episode_id'],keep='last');meta.to_csv(OUT+'/metadata_all.csv',index=False)
 print('METADATA',len(meta),'UNIQUE JOBS',len(jobs),flush=True)
 start=time.time();done=0;errors=[]
 with ProcessPoolExecutor(max_workers=int(os.environ.get('KAGGRI_WORKERS','4'))) as ex:
  futs={ex.submit(parse,j):j[0] for j in jobs.values()}
  for fut in as_completed(futs):
   eid=futs[fut]
   try:fut.result()
   except Exception as e:errors.append((eid,str(e)));print('ERROR',eid,repr(e),flush=True)
   done+=1
   if done%25==0 or done==len(futs):print('DONE',done,'/',len(futs),'elapsed',round(time.time()-start,1),'errors',len(errors),flush=True)
 open(OUT+'/parse_errors.json','wb').write(orjson.dumps(errors))
if __name__=='__main__':main()
