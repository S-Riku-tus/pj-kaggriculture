import sys,zipfile,io,orjson,csv,json,time,pathlib
import argparse
ROOT=pathlib.Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('--battle-zip',required=True,type=pathlib.Path);ap.add_argument('--output',type=pathlib.Path,default=ROOT/'recomputed_parity')
args=ap.parse_args();O=args.output;O.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT/'engine_cppsim'))
import kagsim
z=zipfile.ZipFile(args.battle_zip);rz=zipfile.ZipFile(io.BytesIO(z.read(next(n for n in z.namelist() if n.endswith('_battle_logs.zip')))))
results=[]
for eid in [112748339,112752873,112751861]:
 n=next(n for n in rz.namelist() if f'episode_{eid}.json' in n and '/replays/' in n);d=orjson.loads(rz.read(n));g=kagsim.Game(d['info']['seed']);errors=[];blocks=0
 for t in range(720):
  for seat in (0,1):
   x=g.observe(seat);y={**d['steps'][t][0]['observation'], **d['steps'][t][seat]['observation']}
   for k in ('step','player','day','hour','farms','market','town','private'):
    blocks+=1
    if x[k]!=y[k]:errors.append({'t':t,'seat':seat,'key':k});break
  if errors:break
  if t<719:g.step(d['steps'][t+1][0]['action'],d['steps'][t+1][1]['action'])
 results.append(dict(episode_id=eid,seed=d['info']['seed'],blocks=blocks,errors=errors[:4],rewards=[g.reward(0),g.reward(1)],replay_rewards=d['rewards'],done=g.done))
print(json.dumps(results,indent=2));(O/'cppsim_raw_parity_3.json').write_text(json.dumps(results,indent=2))
