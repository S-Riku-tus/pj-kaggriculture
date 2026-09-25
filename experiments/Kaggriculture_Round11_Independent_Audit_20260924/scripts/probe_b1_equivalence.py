"""Show the baseline producer of the sale also proposed by CW1 at step668."""
from pathlib import Path
import argparse,sys,gzip,copy,json
import orjson
ap=argparse.ArgumentParser();ap.add_argument('--workspace',required=True);ap.add_argument('--b1',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();p=Path(a.b1);r=Path(a.workspace);data=orjson.loads(gzip.decompress((r/'track_b/conditional_wool_kagsim/replays/B1/B1/seed_532609243_seat_0.json.gz').read_bytes()));ns={'__name__':'__main__','__file__':str(p)};exec(compile(p.read_bytes(),str(p),'exec'),ns);entry=[v for v in ns.values() if callable(v)][-1];returns=[];mismatches=[]
def profile(frame,event,arg):
 if event=='return' and frame.f_code.co_filename==str(p) and isinstance(arg,dict) and 'market' in arg:returns.append({'function':frame.f_code.co_name,'line':frame.f_code.co_firstlineno,'market':copy.deepcopy(arg['market'])})
for rec in data['decisions'][:669]:
 if rec['step']==668:sys.setprofile(profile)
 try:action=entry(rec['observations'][0])
 finally:sys.setprofile(None)
 if action!=rec['actions'][0]:mismatches.append(rec['step'])
compressed=[]
for row in returns:
 if not compressed or row['market']!=compressed[-1]['market']:compressed.append(row)
out={'seed':532609243,'opponent':'B1','seat':0,'step':668,'policy_calls':669,'saved_action_mismatch_steps':mismatches,'action_changes_in_return_chain':compressed,'final':action['market'],'debt_after':ns['_IMPL'].chassis.players[0]['sell_state'].get('r36_debts',{})};Path(a.out).write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
