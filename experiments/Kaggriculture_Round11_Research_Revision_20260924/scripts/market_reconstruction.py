
"""Independent one-transition reconstruction for the supplied Kaggriculture logs.

Uses deterministic unit semantics extracted from the supplied submission and a
separately written market executor checked against the official source viewed
2026-09-24. Not a full interactive game engine. Future RNG/shop behavior is NOT
modeled. Replays supply each transition's starting state.
"""
import math
from collections import Counter

def shape(f,x,T):
    x=max(0,x)
    if f=="linear": return x
    if f=="sq": return x*x
    if f=="sqrt": return math.sqrt(x)
    if f=="log": return math.log1p(x)
    if f=="log10": return math.log10(1+x)
    if f=="hinge":
        u=x/T
        return u+8*max(0,u-1)**2
    return x

def price(item, inv, params):
    p=params[item];side="below" if inv<p["I0"] else "above"
    f=p[side+"_func"]
    delta=p[side+"_target"]*p["base"]*shape(f,abs(inv-p["I0"]),p["T"])/shape(f,p["T"],p["T"])
    return max(1,int(round(p["base"]+(delta if side=="below" else -delta))))

def fib(n):
    a,b=1,1
    for _ in range(n):a,b=b,a+b
    return a

def market_execute(farms,privates,inventory,orders,params,cfg):
    """Mutate post-unit states; aggregate actual fills/costs per player/slot."""
    events=[]
    queues=[list(q)[:max(1,cfg.get("maxMarketOrdersPerTurn",10))] for q in orders]
    cap=cfg.get("shedCapacity",100)
    crops={"WHEAT":10,"CARROT":20,"TOMATO":50,"STRAWBERRY":100,"MELON":80}
    animals={"COW":400,"SHEEP":500,"GOOSE":300}
    for slot in range(max(map(len,queues))):
        pending=[None,None]
        for p,q in enumerate(queues):
            if slot>=len(q) or not isinstance(q[slot],list) or not q[slot]:continue
            o=q[slot];op=o[0];f=farms[p];pr=privates[p]
            if op=="HIRE":
                cost=fib(f["hires_today"])*cfg.get("farmHandCostMult",1);ok=f["money"]>=cost
                if ok:
                    f["money"]-=cost;f["hires_today"]+=1
                    bs=cfg.get("boardSize",10);half=bs//2
                    locs=[(half-1,half-1),(half,half-1),(half-1,half),(half,half)]
                    occ=Counter(tuple(x) for x in [f["farmer"]]+f["hands"])
                    pos=min(locs,key=lambda x:(occ[x],locs.index(x)))
                    f["hands"].append(list(pos));pr["inventories"].append({})
                events.append(dict(seat=p,slot=slot,op=op,item="",requested=1,units=int(ok),cash=-cost if ok else 0))
            elif op=="BUY_LAND":
                extra=len(f["unlocked_quadrants"])-1;cost=[1000,2000,4000][extra] if extra<3 else 0
                ok=extra<3 and f["money"]>=cost
                if ok:
                    f["money"]-=cost;quad=["NE","SW","SE"][extra];f["unlocked_quadrants"].append(quad)
                    half=len(f["tiles"])//2
                    for y,row in enumerate(f["tiles"]):
                        for x,v in enumerate(row):
                            qq=("N" if y<half else "S")+("W" if x<half else "E")
                            if qq==quad and v=="LOCKED":row[x]=None
                events.append(dict(seat=p,slot=slot,op=op,item="",requested=1,units=int(ok),cash=-cost if ok else 0))
            elif len(o)>=3 and op in ("SELL","BUY_PRODUCT","BUY_SEED","BUY_ANIMAL"):
                try:n=int(o[2])
                except (ValueError,TypeError):continue
                if n<=0:continue
                event=dict(seat=p,slot=slot,op=op,item=o[1],requested=n,units=0,cash=0)
                events.append(event);pending[p]=[op,o[1],n,event]
        for _ in range(99999):
            quotes=[None,None]
            for p,r in enumerate(pending):
                if r is None or r[2]<=0:continue
                op,it,n,ev=r
                if op=="SELL" and it in params:v=price(it,inventory[it],params)
                elif op=="BUY_PRODUCT" and it in ("WHEAT","FERTILIZER"):v=price(it,inventory[it]-1,params)
                elif op=="BUY_SEED" and it in crops:v=crops[it]
                elif op=="BUY_ANIMAL" and it in animals:v=animals[it]
                else:pending[p]=None;continue
                quotes[p]=v
            if all(v is None for v in quotes):break
            any_commit=False
            for p,v in enumerate(quotes):
                if v is None:continue
                op,it,n,ev=pending[p];f=farms[p];pr=privates[p]
                if op=="SELL":
                    ok=pr["shed"].get(it,0)>0
                    if ok:
                        pr["shed"][it]-=1;f["money"]+=v
                        if v>1:inventory[it]+=1
                elif op in ("BUY_PRODUCT","BUY_ANIMAL"):
                    ok=f["money"]>=v and sum(pr["shed"].values())<cap
                    if ok:
                        f["money"]-=v;pr["shed"][it]=pr["shed"].get(it,0)+1
                        if op=="BUY_PRODUCT":inventory[it]-=1
                else:
                    ok=f["money"]>=v
                    if ok:f["money"]-=v;pr["seeds"][it]=pr["seeds"].get(it,0)+1
                if ok:
                    pending[p][2]-=1;ev["units"]+=1;ev["cash"]+=v if op=="SELL" else -v;any_commit=True
                else:pending[p]=None
            if not any_commit:break
        else:raise RuntimeError("Market loop guard")
    return events
