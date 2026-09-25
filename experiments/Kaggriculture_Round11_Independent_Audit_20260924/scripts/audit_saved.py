"""Fixed-action replay audit, not new responding-policy evaluation. Requires orjson/kagsim."""
from pathlib import Path
import argparse,csv,json,gzip,hashlib,sys,multiprocessing as mp,time
import orjson
ENGINE=None

def init(engine_dir):
 global ENGINE
 sys.path.insert(0,engine_dir)
 import kagsim
 ENGINE=kagsim

def audit(job):
 csvpath,row,root=job
 rawpath=row['replay'];p=Path(root)/rawpath.split('round11_execution_20260924/',1)[-1] if 'round11_execution_20260924/' in rawpath else Path(csvpath).parent/rawpath
 data=p.read_bytes();d=orjson.loads(gzip.decompress(data));seat=int(row['seat']);seed=int(row['seed']);errors=[]
 def check(test,msg):
  if not test and len(errors)<12:errors.append(msg)
 check(hashlib.sha256(data).hexdigest()==row['replay_sha256'],'hash')
 check(float(row['self_final_cash'])-float(row['opp_final_cash'])==float(row['margin']),'csv_margin')
 check(row['result']==('W' if float(row['margin'])>0 else 'L' if float(row['margin'])<0 else 'T'),'csv_result')
 check(not row['error'],'csv_error')
 g=ENGINE.Game(seed);obs_count=0;ordercaps=0;official='steps' in d
 if official:
  states=d['steps'];check(d.get('info',{}).get('seed')==seed,'seed');check(len(states)==720,'state_count');check(d.get('statuses')==['DONE','DONE'],'statuses')
  for t,state in enumerate(states):
   for pl in [0,1]:
    expected=g.observe(pl);got=dict(state[0]['observation']);got.update(state[pl]['observation']);got['step']=t
    for k in expected:
     if k!='remainingOverageTime':check(got.get(k)==expected[k],f'obs:{t}:{pl}:{k}')
    obs_count+=1
   if t<len(states)-1:
    acts=[states[t+1][pl]['action'] for pl in [0,1]];ordercaps+=sum(len(a.get('market') or [])>10 for a in acts);g.step(*acts)
 else:
  check(d['seed']==seed,'seed');check(len(d['decisions'])==719,'decision_count')
  full=(row['arm']=='m20_multi_hypothesis' and seed==612609264)
  for t,rec in enumerate(d['decisions']):
   check(rec['step']==t,'step')
   for pl in [0,1]:
    check(rec['observations'][pl]['step']==t,'observation_step')
    if full:
     check(rec['observations'][pl]==g.observe(pl),f'obs:{t}:{pl}');obs_count+=1
   acts=rec['actions'];ordercaps+=sum(len(a.get('market') or [])>10 for a in acts)
   if full:g.step(*acts)
  if not full:
   streams=[ENGINE.Stream([r['actions'][pl] for r in d['decisions']]) for pl in [0,1]]
   rewards=list(ENGINE.run_episode(*streams,seed))
 if official or full:
  rewards=[g.reward(0),g.reward(1)];check(g.done,'done');check(g.step_count==719,'step_count')
 check(rewards==d['rewards'],'raw_rewards');check(rewards[seat]==float(row['self_final_cash']),'self_cash');check(rewards[1-seat]==float(row['opp_final_cash']),'opp_cash');check(ordercaps==0,'ordercaps')
 return dict(panel=str(Path(csvpath).relative_to(root).parent),arm=row['arm'],opponent=row['opponent_id'],seed=seed,seat=seat,observations_checked=obs_count,official=official,stored_states=720 if official else 719,reconstructed_terminal=True,replay_sha256=hashlib.sha256(data).hexdigest(),errors=';'.join(errors))

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--workspace',required=True);ap.add_argument('--engine-dir',required=True);ap.add_argument('--out',required=True);ap.add_argument('--workers',type=int,default=4);a=ap.parse_args();root=Path(a.workspace);out=Path(a.out);out.mkdir(parents=True,exist_ok=True);jobs=[]
 for c in sorted(root.rglob('games.csv')):
  for row in csv.DictReader(c.open(encoding='utf-8-sig')):jobs.append((str(c),row,str(root)))
 start=time.time();results=[];incremental=(out/'audit_progress.jsonl').open('w')
 with mp.Pool(a.workers,initializer=init,initargs=(a.engine_dir,)) as pool:
  for i,res in enumerate(pool.imap_unordered(audit,jobs,chunksize=2),1):
   results.append(res);incremental.write(json.dumps(res)+"\n");incremental.flush()
   if i%100==0:print('verified',i,'/',len(jobs),'errors',sum(bool(x['errors']) for x in results),flush=True)
 results.sort(key=lambda x:(x['panel'],x['arm'],x['opponent'],x['seed'],x['seat']))
 with (out/'independent_replay_audit.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(results[0]));w.writeheader();w.writerows(results)
 summary=dict(saved_games=len(results),official_saved_games=sum(x['official'] for x in results),cpp_saved_games=sum(not x['official'] for x in results),observations_checked=sum(x['observations_checked'] for x in results),error_games=sum(bool(x['errors']) for x in results),errors=[x for x in results if x['errors']],seconds=time.time()-start,scope='saved action replay only; zero new agent inference in this script')
 (out/'independent_replay_audit.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
