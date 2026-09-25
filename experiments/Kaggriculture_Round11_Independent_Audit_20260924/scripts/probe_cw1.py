"""Trace reservations and final actions in the saved CW1 trace. Teacher-forced policy replay only."""
from pathlib import Path
import sys,json,gzip,copy,traceback,argparse
import orjson,pandas as pd

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--workspace',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();r=Path(a.workspace)
 rows=pd.read_csv(r/'track_b/conditional_wool_kagsim/games.csv').to_dict('records')
 row=next(z for z in rows if z['arm']=='cw1_conditional_wool' and json.loads(z['diagnostics_json']).get('changes',0)>0)
 raw=row['replay'];rp=r/raw.split('round11_execution_20260924/',1)[-1];replay=orjson.loads(gzip.decompress(rp.read_bytes()))
 p=r/'arms/cw1_conditional_wool/main.py';ns={'__name__':'__main__','__file__':str(p)};exec(compile(p.read_bytes(),str(p),'exec'),ns);entry=[v for v in ns.values() if callable(v)][-1];host=ns['_RACE_ORIG_RESERVE'];events=[];active=[];seat=int(row['seat'])
 def reserve(obs,act):
  before=copy.deepcopy(act);n=ns['_CW1_REPORT']['changes'];result=host(obs,act)
  if ns['_CW1_REPORT']['changes']>n:
   e=dict(step=obs['step'],price=obs['market']['prices']['WOOL'],before=before['market'],after=copy.deepcopy(result['market']),stack=[dict(function=x.name,line=x.lineno) for x in traceback.extract_stack() if x.filename==str(p)],returns=[])
   events.append(e);active.append(e)
  return result
 ns['_RACE_ORIG_RESERVE']=reserve
 def profiler(frame,event,arg):
  if event=='return' and active and frame.f_code.co_filename==str(p) and isinstance(arg,dict) and 'market' in arg:
   active[-1]['returns'].append(dict(function=frame.f_code.co_name,line=frame.f_code.co_firstlineno,market=copy.deepcopy(arg['market'])))
 mismatch=[]
 for rec in replay['decisions']:
  active.clear();sys.setprofile(profiler)
  try:result=entry(rec['observations'][seat],None)
  finally:sys.setprofile(None)
  if result!=rec['actions'][seat]:mismatch.append(rec['step'])
  if active:
   active[-1]['final']=copy.deepcopy(result['market']);active[-1]['debt_after']=copy.deepcopy(ns['_IMPL'].chassis.players[seat]['sell_state'].get('r36_debts',{}))
 out=dict(opponent=row['opponent_id'],seed=int(row['seed']),seat=seat,agent_entry=entry.__name__,policy_calls=len(replay['decisions']),saved_action_mismatch_steps=mismatch,events=events,telemetry=ns['_CW1_REPORT'])
 Path(a.out).write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
if __name__=='__main__':main()
