"""Development-only responding-opponent diagnostics. Not a Kaggle submission.
B1 is executed unchanged apart from the specifically declared experiment arm.
The response overlay is an independently written restricted experiment motivated
by arsgorynich's Apache-2.0 Order Book response research; inherited evaluators
retain the original agent's attributions. No private rival input is used.
"""
from pathlib import Path
import sys, json, hashlib, time, itertools, gzip, traceback
W=Path('/mnt/data/r11_work')
P=W/'round10_public_learning_20260924/public_agents'
O=Path('/mnt/data/Kaggriculture_Round11_Research_Revision_20260924/evidence')
sys.path.insert(0,str(W/'round10_public_learning_20260924/engines/kaggriculture-cppsim'))
import kagsim
PATHS={'B1':W/'B1/main.py','v57':P/'ahmed_v57/main.py','order_book':P/'order_book/main.py','metav4':P/'metav4/main.py'}
def load(path):
    raw=path.read_bytes(); ns={'__name__':'__main__','__file__':str(path)}
    exec(compile(raw,str(path),'exec'),ns)
    entry=[v for v in ns.values() if callable(v)][-1]
    return ns,entry,hashlib.sha256(raw).hexdigest()

def response(ns,obs,action,stat):
    # Restricted to all-SELL queues. Fixed spending, buy/sell cycles and deliberate
    # empty slots are excluded, not silently compacted. Production runs only once.
    orders=action.get('market') or []
    if not 2<=len(orders)<=6 or any(not o or o[0]!='SELL' for o in orders):
        return action
    stat['eligible']+=1
    stock={k:max(0,int(v)) for k,v in ns['projected_shed'](action,ns['FarmView'](obs)).items()}
    # One depth of response: model the rival as using our FINAL order list,
    # unlike the inherited pre-reorder proxy. Own stock as rival proxy is uncertain.
    f=ns['_v44y_factor_margin'](orders,dict(obs['market']['inventory']),stock,ns['_v44y_params'](obs))
    baseline=f(orders); best=baseline; chosen=None
    for perm in itertools.permutations(orders):
        cand=list(perm)
        if cand==orders:continue
        value=f(cand);stat['evaluations']+=1
        if value>best+0.5:best,chosen=value,cand
    if chosen is None:return action
    stat['changes']+=1;stat['predicted_gain']+=best-baseline
    return dict(action,market=chosen)

def run(job):
    arm,opponent,seed,seat=job
    start=time.monotonic();ns,agent,ah=load(PATHS['B1']);on,opp,oh=load(PATHS[opponent])
    if arm in ('wool_gate_open','combined'):ns['V9_RACEGATE_BASE']['WOOL']=0
    g=kagsim.Game(seed); records=[]; stat={'eligible':0,'changes':0,'evaluations':0,'predicted_gain':0.0}
    err=None; n=0; times=[0.0,0.0];ordercaps=0;shops=[]
    try:
        while not g.done:
            obs=[g.observe(0),g.observe(1)]
            before=time.monotonic();a=agent(obs[seat],None)
            if arm in ('final_response','combined'):a=response(ns,obs[seat],a,stat)
            times[seat]=max(times[seat],time.monotonic()-before)
            before=time.monotonic();b=opp(obs[1-seat],None);times[1-seat]=max(times[1-seat],time.monotonic()-before)
            actions=[a,b] if seat==0 else [b,a]
            ordercaps+=sum(len(x.get('market') or [])>10 for x in actions)
            records.append({'observations':obs,'actions':actions})
            g.step(*actions);n+=1
        terminal=[g.observe(0),g.observe(1)]
    except Exception as e:
        err=traceback.format_exc();terminal=[g.observe(0),g.observe(1)]
    rewards=[g.reward(0),g.reward(1)];margin=rewards[seat]-rewards[1-seat]
    result={'arm':arm,'opponent':opponent,'seed':seed,'seat':seat,'done':g.done,'decisions':n,
       'self_cash':rewards[seat],'opp_cash':rewards[1-seat],'margin':margin,'points':float(margin>0)+0.5*float(margin==0),
       'error':err,'order_cap_violations':ordercaps,'b1_sha256':ah,'opponent_sha256':oh,'entry':agent.__name__,'opponent_entry':opp.__name__,
       'seconds':round(time.monotonic()-start,3),'max_callback_seconds':times,'response':stat,
       'shops':terminal[0]['town']['unlocked_shops']}
    name=f'{arm}__{opponent}__{seed}__seat{seat}'
    d=O/'development_replays';d.mkdir(exist_ok=True)
    payload=json.dumps({'result':result,'records':records,'terminal':terminal},separators=(',',':')).encode()
    file=d/f'{name}.json.gz'
    with gzip.GzipFile(filename=str(file),mode='wb',mtime=0) as z:z.write(payload)
    result['replay_sha256']=hashlib.sha256(file.read_bytes()).hexdigest()
    result['replay_path']=str(file.relative_to(O));return result

if __name__=='__main__':
    print(json.dumps(run(('B1','B1',402609241,0)),ensure_ascii=False,indent=2))
