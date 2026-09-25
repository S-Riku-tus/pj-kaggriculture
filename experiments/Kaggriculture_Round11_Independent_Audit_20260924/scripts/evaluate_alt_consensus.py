"""Broaden one predeclared diagnostic ablation across all exposed Round11 cells.
This is development re-use of a formerly held-out panel, NOT fresh validation.
"""
from pathlib import Path
import argparse,json,multiprocessing as mp
from reactive_diagnostics import run

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--workspace',required=True);ap.add_argument('--revision',required=True);ap.add_argument('--b1',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();o=Path(a.out);(o/'reactive_consensus_traces').mkdir(exist_ok=True)
 jobs=[(a.workspace,a.revision,a.b1,a.out,seed,opp,seat,'alt_two_votes','reactive_consensus_traces') for seed in range(612609241,612609265) for opp in ['B1','v57','order_book','metav4'] for seat in [0,1]]
 rows=[]
 with mp.Pool(4) as pool:
  for x in pool.imap_unordered(run,jobs):
   rows.append(x)
   if len(rows)%16==0: print(json.dumps({'done':len(rows),'total':len(jobs)}),flush=True)
 (o/'alt_consensus_full_panel.json').write_text(json.dumps({'scope':'192 new reactive cppsim runs of one diagnostic arm, all on exposed Round11 seed/opponent/seat cells. No fresh holdout, no training, no submission.','rows':rows},indent=2))
if __name__=='__main__':main()
