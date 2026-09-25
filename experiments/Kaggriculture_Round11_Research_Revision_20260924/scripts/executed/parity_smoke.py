import sys,zipfile,io,orjson,csv,json,time,pathlib
W=pathlib.Path('/mnt/data/r11_work'); O=pathlib.Path('/mnt/data/Kaggriculture_Round11_Research_Revision_20260924/evidence')
sys.path.insert(0,str(W/'round10_public_learning_20260924/engines/kaggriculture-cppsim'))
import kagsim
z=zipfile.ZipFile('/mnt/data/round10_b1_herd_safe_submission_56509493(1).zip');rz=zipfile.ZipFile(io.BytesIO(z.read(next(n for n in z.namelist() if n.endswith('_battle_logs.zip')))))
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
