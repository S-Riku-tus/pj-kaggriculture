"""Compare the runtime predictor's stored own-sales ledger with simulator fills.
Four known diagnostic cases, no candidate modification, no selection experiment.
"""
from pathlib import Path
import argparse,sys,json,copy
from reactive_diagnostics import load

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--workspace',required=True);ap.add_argument('--revision',required=True);ap.add_argument('--b1',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();sys.path.insert(0,str(Path(a.revision)/'engine_cppsim'));import kagsim_ledger as kagsim
 rows=[];total=0;own_bad=0;infer_bad=0;guard_skip=0;skip_sales=0;summaries=[]
 for seed in [612609254,612609264]:
  for arm in ['B1','m20_multi_hypothesis']:
   p=Path(a.b1) if arm=='B1' else Path(a.workspace)/'arms/m20_multi_hypothesis/main.py';fn,ns,_=load(p,'none');ofn,ons,_=load(Path(a.revision)/'inputs/agents/v57.py','none');g=kagsim.Game(seed);lc={'own_bad':0,'rival_inference_bad':0,'eligible':0,'low_price_skip':0,'low_price_skipped_true_sale':0}
   while not g.done:
    obs=[g.observe(z) for z in [0,1]];t=obs[0]['step'];acts=[fn(obs[0]),ofn(obs[1])];prev=copy.deepcopy(ns['_V9_RACE'].get(0,{}).get('prev'));before=[g.telemetry(z)['sold_by_product'] for z in [0,1]];g.step(*acts);after=[g.telemetry(z)['sold_by_product'] for z in [0,1]];nxt=g.observe(0)
    if not prev:continue
    draw=ns['_v9_town_draw'](prev['shops'],prev['step'])
    for item in ns['_V92_P_ITEMS']:
     own=after[0].get(item,0)-before[0].get(item,0);other=after[1].get(item,0)-before[1].get(item,0);recorded=prev['own'].get(item,0);lc['own_bad']+=own!=recorded
     if prev['prices'].get(item,0)<=3:
      lc['low_price_skip']+=1;lc['low_price_skipped_true_sale']+=other>0;continue
     est=nxt['market']['inventory'][item]-prev['inventory'][item]+draw.get(item,0)-recorded;lc['eligible']+=1
     if est!=other:
      lc['rival_inference_bad']+=1;rows.append({'seed':seed,'arm':arm,'step':t,'item':item,'price':prev['prices'][item],'runtime_own':recorded,'true_own_fill':own,'true_opponent_fill':other,'inferred_opponent_fill':est,'inferred_positive_event':est>=2,'true_positive_event':other>=2,'final_market':acts[0]['market'],'opponent_market':acts[1]['market']})
   summaries.append({'seed':seed,'arm':arm,**lc,'rewards':[g.reward(z) for z in [0,1]]})
 out={'scope':'4 new reactive cppsim ledger diagnostic games, no modification, on exposed seeds','summaries':summaries,'mismatches':rows}
 Path(a.out).write_text(json.dumps(out,indent=2));print(json.dumps(summaries,indent=2));print('mismatches',len(rows))
if __name__=='__main__':main()
