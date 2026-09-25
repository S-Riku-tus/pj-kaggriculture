"""Recompute diagnostic tables from raw JSON plus the original B1/M20 CSV.
No policy evaluation, training or submission is performed by this script.
"""
from pathlib import Path
import argparse,json
import numpy as np
import pandas as pd

def exact_bootstrap(seed_point_sums: pd.Series, games: int) -> dict:
    # Points have 0.5 resolution. Convolving the empirical seed distribution
    # retains both seats and all opponents in each sampled world seed.
    x=np.rint(seed_point_sums.to_numpy()*2).astype(int);low=int(x.min())
    p=np.bincount(x-low)/len(x);distribution=np.array([1.0])
    for _ in range(len(x)): distribution=np.convolve(distribution,p)
    values=(np.arange(len(distribution))+len(x)*low)/(2*games)
    cdf=np.cumsum(distribution)
    return {str(q):float(values[np.searchsorted(cdf,q)]) for q in [.05,.1,.9,.95]}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--workspace',required=True);ap.add_argument('--evidence',required=True);a=ap.parse_args();e=Path(a.evidence)
    original=pd.read_csv(Path(a.workspace)/'holdout/m20_kagsim/games.csv')
    base=original[original.arm=='B1'][['opponent_id','seed','seat','self_final_cash','opp_final_cash','margin','result']].rename(columns={'opponent_id':'opponent','self_final_cash':'bself','opp_final_cash':'bopp','margin':'bmargin','result':'bresult'})
    m20=original[original.arm=='m20_multi_hypothesis'][['opponent_id','seed','seat','self_final_cash','opp_final_cash','margin','result']].rename(columns={'opponent_id':'opponent','self_final_cash':'mself','opp_final_cash':'mopp','margin':'mmargin','result':'mresult'})
    rows=json.loads((e/'alt_consensus_full_panel.json').read_text())['rows'];d=pd.DataFrame(rows).merge(base,on=['opponent','seed','seat']).merge(m20,on=['opponent','seed','seat'])
    if len(d)!=192: raise ValueError('Expected 192 complete, uniquely matched diagnostic cells')
    score=lambda s:(s>0).astype(float)+(s==0).astype(float)*.5
    d['points']=score(d.margin);d['delta_points_vs_B1']=d.points-score(d.bmargin);d['delta_points_vs_M20']=d.points-score(d.mmargin)
    d['delta_margin_vs_B1']=d.margin-d.bmargin;d['delta_margin_vs_M20']=d.margin-d.mmargin
    d['delta_self_vs_B1']=d.cash_self-d.bself;d['delta_opp_vs_B1']=d.cash_opponent-d.bopp
    d['result']=np.where(d.margin>0,'W',np.where(d.margin<0,'L','T'))
    d['transition_vs_B1']=d.bresult+'->'+d.result;d['transition_vs_M20']=d.mresult+'->'+d.result
    d.drop(columns=['telemetry','pred_events']).to_csv(e/'alt_consensus_full_panel_results.csv',index=False)
    by=d.groupby('opponent')[['points','delta_points_vs_B1','delta_points_vs_M20','delta_margin_vs_B1','delta_self_vs_B1','delta_opp_vs_B1']].agg(['sum','mean']);by.columns=['_'.join(v) for v in by.columns];by.to_csv(e/'alt_consensus_by_opponent.csv')
    summary={'games':len(d),'WLT':d.result.value_counts().to_dict(),'points':float(d.points.sum()),'point_delta_vs_B1':float(d.delta_points_vs_B1.sum()),'point_delta_vs_M20':float(d.delta_points_vs_M20.sum()),'mean_margin':float(d.margin.mean()),'mean_margin_delta_vs_B1':float(d.delta_margin_vs_B1.mean()),'mean_cash_self_delta_vs_B1':float(d.delta_self_vs_B1.mean()),'mean_cash_opponent_delta_vs_B1':float(d.delta_opp_vs_B1.mean()),'transitions_vs_B1':d.transition_vs_B1.value_counts().to_dict(),'transitions_vs_M20':d.transition_vs_M20.value_counts().to_dict(),'policy_calls':int(d.policy_calls.sum()),'by_opponent':{k:{'points_delta_vs_B1':float(z.delta_points_vs_B1.sum()),'margin_delta_vs_B1':float(z.delta_margin_vs_B1.mean())} for k,z in d.groupby('opponent')},'status':'POST_HOC_DIAGNOSTIC_NOT_PROMOTED','exact_seed_bootstrap_quantiles':exact_bootstrap(d.groupby('seed').delta_points_vs_B1.sum(),len(d))}
    (e/'alt_consensus_summary.json').write_text(json.dumps(summary,indent=2))
    ledger=json.loads((e/'runtime_ledger_audit.json').read_text());pd.DataFrame(ledger['mismatches']).to_csv(e/'runtime_ledger_mismatches.csv',index=False)
    initial=pd.DataFrame(json.loads((e/'reactive_diagnostics.json').read_text())['rows']);initial.drop(columns=['telemetry','pred_events']).to_csv(e/'reactive_diagnostics_results.csv',index=False)
    paired=pd.read_csv(e/'independent_paired_trajectories.csv');h=paired[paired.panel=='holdout/m20_kagsim']
    (e/'bootstrap_exact_check.json').write_text(json.dumps({'method':'Empirical world-seed distribution, exact convolution with0.5 point resolution','quantiles':exact_bootstrap(h.groupby('seed').delta_points.sum(),len(h))},indent=2))
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
