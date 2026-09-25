import json,gzip,hashlib,collections,os
import orjson
from pathlib import Path
import pandas as pd
R=Path(os.environ.get('ROUND9_ROOT', '/mnt/data/audit_work/round9_teacher_reproduction_and_closed_loop_bc_20260923'))
OUT=Path(os.environ.get('AUDIT_EVIDENCE', str(Path(__file__).resolve().parents[1] / 'evidence')))/os.environ.get('BATCH','all')
OUT.mkdir(parents=True,exist_ok=True)

def local(path):
 s=path.replace('\\','/');return R/s.split(R.name+'/',1)[1]
def read(p):
 with gzip.open(p,'rb') as f:return orjson.loads(f.read())
def clean(x):
 if isinstance(x,dict):return {k:clean(v) for k,v in x.items() if k not in {'duration','remainingOverageTime'}}
 if isinstance(x,list):return [clean(v) for v in x]
 return x
allrows=[];snaps=[];econ=[]
for csv in sorted(R.glob('development*/games.csv')):
 if os.environ.get('PANELS') and csv.parent.name not in os.environ['PANELS'].split(','):continue
 df=pd.read_csv(csv).iloc[int(os.environ.get('START',0)):int(os.environ.get('END',999))]
 for _,row in df.iterrows():
  p=local(row.replay);g=read(p);seat=int(row.seat);steps=g['steps']
  own=steps[-1][seat]['observation']['farms'][seat]['money'];opp=steps[-1][seat]['observation']['farms'][1-seat]['money']
  statuses='/'.join(s['status'] for s in steps[-1])
  h=hashlib.file_digest(open(p,'rb'),'sha256').hexdigest();d=local(row.diagnostics);dh=hashlib.file_digest(open(d,'rb'),'sha256').hexdigest()
  check=h==row.replay_sha256 and dh==row.diagnostics_sha256 and own==row.our_cash and opp==row.opponent_cash and own-opp==row.margin and len(steps)==row.states and statuses==row.statuses and g['info']['seed']==row.seed
  allrows.append(dict(panel=csv.parent.name,anchor=row.anchor,seed=int(row.seed),seat=seat,our_cash=own,opponent_cash=opp,margin=own-opp,score=int(own>opp)+.5*int(own==opp),states=len(steps),statuses=statuses,all_checks=check))
  if csv.parent.name!='development_panel_a2_v2_expanded64':continue
  for t in [0,24,48,96,144,192,240,288,360,480,600,696,719]:
   for s in [seat,1-seat]:
    ob=steps[t][s]['observation'];f=ob['farms'][s];tiles=[c for line in f['tiles'] for c in line if isinstance(c,dict)]
    counts=collections.Counter(c.get('kind') for c in tiles)
    snaps.append(dict(anchor=row.anchor,seed=int(row.seed),seat=seat,record=t,role='A2' if s==seat else 'opponent',money=f['money'],land=len(f['unlocked_quadrants']),crops=sum(c.get('kind')=='PLANT' for c in tiles),animals=sum(bool(c.get('animal')) for c in tiles),empty_pasture=sum(c.get('kind')=='PASTURE' and not c.get('animal') for c in tiles),hands=len(f.get('hands',[])),shed_units=sum(ob['private']['shed'].values()),carried_units=sum(sum(v.values()) for v in ob['private']['inventories'])))
  for s in [seat,1-seat]:
   acts=collections.Counter();market=collections.Counter();by_day=collections.defaultdict(collections.Counter);anti=0;mv=0;stationary=0;productive_days=set();lastmv={}
   for t in range(len(steps)-1):
    ob=steps[t][s]['observation'];nxt=steps[t+1][s]['observation'];a=steps[t+1][s]['action'] or {};far=ob['farms'][s];pos=[far['farmer']]+far['hands'];npos=[nxt['farms'][s]['farmer']]+nxt['farms'][s]['hands'];cmds=[a.get('farmer',['PASS'])]+a.get('hands',[])
    for i,c in enumerate(cmds):
     if not isinstance(c,list) or not c:continue
     op=c[0];acts[op]+=1;by_day[ob['day']][op]+=1
     if op not in {'PASS','NORTH','SOUTH','EAST','WEST'}:productive_days.add(ob['day'])
     if op in {'NORTH','SOUTH','EAST','WEST'}:
      mv+=1
      if i<len(pos) and i<len(npos) and ob['day']==nxt['day']:
       stationary+=pos[i]==npos[i]
       old=lastmv.get(i)
       if old and old[0]==t-1 and old[1]==npos[i] and old[2]==pos[i]:anti+=1
       lastmv[i]=(t,pos[i],npos[i])
     else:lastmv.pop(i,None)
    for c in a.get('market',[]):
     if c:market[':'.join(str(x) for x in c[:2]) if c[0] not in {'HIRE','BUY_LAND'} else c[0]]+=1
   final=steps[-1][s]['observation'];f=final['farms'][s]
   econ.append(dict(anchor=row.anchor,seed=int(row.seed),seat=seat,role='A2' if s==seat else 'opponent',acts=dict(acts),market=dict(market),moves=mv,immediate_backtracks=anti,stationary_moves=stationary,work_commands=sum(v for k,v in acts.items() if k not in {'PASS','NORTH','SOUTH','EAST','WEST'}),terminal_shed=final['private']['shed'],terminal_carried=final['private']['inventories'],days_with_work=len(productive_days),by_day={str(k):dict(v) for k,v in by_day.items()}))
 pd.DataFrame(allrows).to_csv(OUT/'replay_checks.csv',index=False)
 print(csv.parent.name,'checked',len(df),flush=True)
pd.DataFrame(snaps).to_csv(OUT/'state_snapshots.csv',index=False)
(OUT/'behavior_counts.json').write_text(json.dumps(econ,ensure_ascii=False,indent=2))
df=pd.DataFrame(allrows);summary=df.groupby('panel').agg(games=('score','size'),wins=('score','sum'),mean_cash=('our_cash','mean'),mean_opponent=('opponent_cash','mean'),mean_margin=('margin','mean'),all_checks=('all_checks','all')).reset_index().to_dict('records')
(OUT/'panel_summary.json').write_text(json.dumps(summary,indent=2))
if os.environ.get('BATCH')!='small':raise SystemExit(0)
# Compare every action and observation of v2/v3 isolated diagnostic games.
a=pd.read_csv(R/'development_panel_a2_v2/games.csv');b=pd.read_csv(R/'development_panel_a2_v3/games.csv');eq=[]
for _,row in a.iterrows():
 other=b[(b.anchor==row.anchor)&(b.seed==row.seed)&(b.seat==row.seat)].iloc[0];x=read(local(row.replay));y=read(local(other.replay))
 eq.append(dict(anchor=row.anchor,seed=int(row.seed),seat=int(row.seat),semantic_equal=clean(x['steps'])==clean(y['steps']) and x['rewards']==y['rewards'] and x['statuses']==y['statuses']))
(OUT/'v2_v3_independent_equivalence.json').write_text(json.dumps(eq,indent=2))
print(summary)
