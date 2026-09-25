"""Post-hoc reactive diagnostics on already exposed seeds; NOT a fresh holdout.
Runs both actual agents once per observation. Frozen source behavior is checked
against the supplied action traces for B1 and M20. Diagnostic patches are inline.
"""
from pathlib import Path
import argparse,hashlib,json,gzip,time,sys,multiprocessing as mp,copy
import orjson

def load(path,variant):
    text=path.read_text(encoding='utf-8-sig')
    if variant in ('no_alt_wool','alt_two_votes'):
        old='''        if votes < 1:
            continue
        alternate = not ('''
        condition='''        alternate_only = not (best[0].get((step + 1, i), 0) + best[0].get((step + 2, i), 0) >= _V92_P_K)
'''
        if variant=='no_alt_wool':condition+='        if votes < 1 or (alternate_only and item == "WOOL"):\n'
        else:condition+='        if votes < 1 or (alternate_only and votes < 2):\n'
        new=condition+'''            continue
        alternate = not ('''
        assert text.count(old)==1
        text=text.replace(old,new)
    ns={'__name__':'__main__','__file__':str(path)}
    exec(compile(text,str(path),'exec'),ns)
    fn=[v for v in ns.values() if callable(v)][-1]
    return fn,ns,hashlib.sha256(text.encode()).hexdigest()

def run(job):
    r,rev,b1,out,seed,opp,seat,arm,*extras=job;start=time.monotonic();trace_dir=extras[0] if extras else "reactive_initial_traces"
    sys.path.insert(0,str(Path(rev)/'engine_cppsim'));import kagsim
    path=Path(b1) if arm=='B1' else Path(r)/'arms/m20_multi_hypothesis/main.py'
    fn,ns,source=load(path,arm)
    ofn,ons,osource=load(Path(rev)/'inputs/agents'/f'{opp}.py','none')
    original=ns['_v92_predict'];events=[]
    def predictor(obs,action,st):
        before=copy.deepcopy(action);result=original(obs,action,st)
        if before!=result:
            best=st.get('best',[]);t=int(obs['step']);items=ns['_V92_P_ITEMS'];K=ns['_V92_P_K']
            changes=[]
            for order in result.get('market',[]):
                if order not in before.get('market',[]) and len(order)>2 and order[0]=='SELL' and order[1] in items:
                    i=items.index(order[1]);future=[ev.get((t+1,i),0)+ev.get((t+2,i),0) for ev in best]
                    changes.append(dict(item=order[1],qty=order[2],future_qty_by_model=future,alternate_only=bool(future and future[0]<K),price=obs['market']['prices'][order[1]]))
            events.append(dict(step=t,changes=changes,before_market=before['market'],after_market=result['market']))
        return result
    ns['_v92_predict']=predictor
    ref=None
    if arm in ['B1','m20_multi_hypothesis']:
        p=Path(r)/'holdout/m20_kagsim/replays'/arm/opp/f'seed_{seed}_seat_{seat}.json.gz';ref=orjson.loads(gzip.decompress(p.read_bytes()))
    game=kagsim.Game(seed);rows=[];mismatch=0;obs_mismatch=0;calls=0
    while not game.done:
        obs=[game.observe(0),game.observe(1)]
        acts=[None,None];acts[seat]=fn(obs[seat]);acts[1-seat]=ofn(obs[1-seat]);calls+=2
        t=int(obs[seat]['step'])
        if ref is not None:
            if acts!=ref['decisions'][t]['actions']:mismatch+=1
            # remainingOverageTime is runtime-specific, all gameplay fields match.
            exp=ref['decisions'][t]['observations']
            if any({k:v for k,v in obs[z].items() if k!='remainingOverageTime'}!={k:v for k,v in exp[z].items() if k!='remainingOverageTime'} for z in [0,1]):obs_mismatch+=1
        rows.append(dict(step=t,actions=acts,cash=[obs[z]['farms'][z]['money'] for z in [0,1]],prices=obs[0]['market']['prices'],shed=[obs[z]['private']['shed'] for z in [0,1]],inventory=obs[0]['market']['inventory']))
        game.step(acts[0],acts[1])
    reward=[game.reward(z) for z in [0,1]]
    row=dict(seed=seed,opponent=opp,seat=seat,arm=arm,source_text_sha256=source,opponent_source_text_sha256=osource,cash_self=reward[seat],cash_opponent=reward[1-seat],margin=reward[seat]-reward[1-seat],steps=game.step_count,policy_calls=calls,saved_action_mismatch=mismatch if ref else None,saved_observation_mismatch=obs_mismatch if ref else None,telemetry=[game.telemetry(z) for z in [0,1]],pred_events=events,seconds=time.monotonic()-start)
    p=Path(out)/trace_dir;p.mkdir(exist_ok=True)
    fp=p/f'{seed}_{opp}_seat{seat}_{arm}.json.gz';fp.write_bytes(gzip.compress(orjson.dumps(dict(summary=row,decisions=rows,rewards=reward)),mtime=0));row['trace']=str(fp.relative_to(Path(out)));row['trace_sha256']=hashlib.sha256(fp.read_bytes()).hexdigest()
    return row

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--workspace',required=True);ap.add_argument('--revision',required=True);ap.add_argument('--b1',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    cases=[(612609254,'v57',0),(612609264,'v57',0),(612609241,'order_book',0),(612609243,'B1',0)]
    arms=['B1','m20_multi_hypothesis','no_alt_wool','alt_two_votes']
    jobs=[(a.workspace,a.revision,a.b1,a.out,seed,opp,seat,arm) for seed,opp,seat in cases for arm in arms]
    rows=[]
    with mp.Pool(4) as pool:
        for x in pool.imap_unordered(run,jobs):
            rows.append(x);print(json.dumps({k:x[k] for k in ['seed','opponent','arm','margin','saved_action_mismatch','saved_observation_mismatch','seconds']}),flush=True)
    (Path(a.out)/'reactive_diagnostics.json').write_text(json.dumps(dict(scope='16 new reactive cppsim executions on 4 exposed post-hoc cases, not official runtime or new holdout',rows=rows),indent=2))
if __name__=='__main__':main()
