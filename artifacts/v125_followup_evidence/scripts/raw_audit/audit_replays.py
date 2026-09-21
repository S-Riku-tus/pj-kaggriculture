import os,zipfile,gzip,orjson,collections,time,sys
from concurrent.futures import ProcessPoolExecutor,as_completed
from audit_engine import units,market,PRODUCTS,SHOPS
D=os.environ.get('KAGGRI_OUTPUT_DIR',os.path.abspath('analysis_v125'));os.makedirs(D+'/audit',exist_ok=True)

def run(eid):
 dest=D+'/audit/'+str(eid)+'.json.gz'
 if os.path.exists(dest):return eid,'cached'
 with gzip.open(D+'/compact/'+str(eid)+'.json.gz','rb') as f:compact=orjson.loads(f.read())
 with zipfile.ZipFile(os.path.join(os.environ.get('KAGGRI_INPUT_DIR',os.getcwd()),compact['archive'])) as z:r=orjson.loads(z.read(compact['member']))
 ss=r['steps'];cfg=r['configuration'];cap=cfg.get('shedCapacity',100);errors=[];unitsums=[collections.Counter(),collections.Counter()];flows=[collections.Counter(),collections.Counter()];daily=[[collections.Counter() for _ in range(30)] for s in range(2)];alltrades=[];unitfail=[];death_events=[];overflow=[collections.Counter(),collections.Counter()]
 for t in range(1,len(ss)):
  prev=[ss[t-1][s]['observation'] for s in range(2)];farms=[prev[s]['farms'][s] for s in range(2)];prs=[prev[s]['private'] for s in range(2)];actions=[ss[t][s].get('action') or {} for s in range(2)];day=(t-1)//24
  for s in range(2):
   es=units(farms[s],prs[s],actions[s],day,cap)
   for e in es:
    label=e['op']+('_ok' if e['effect'] else '_noop');unitsums[s][label]+=1;daily[s][day][label]+=1
    if not e['effect'] and e['op']!='PASS':
     reason=e.get('reason','precondition');unitsums[s]['noop_reason_'+reason]+=1
     if reason=='atomic_seed_shortage':unitfail.append([t,s,e['op'],reason])
    for k,q in e.get('harvest',{}).items():unitsums[s]['harvest_'+k]+=q;daily[s][day]['harvest_'+k]+=q
    for k,q in e.get('overflow',{}).items():overflow[s][k]+=q;daily[s][day]['overflow_'+k]+=q
    for name in ['planted','placed','fertilized','feed','dug']:
     if name in e:unitsums[s][name+'_'+e[name]]+=1;daily[s][day][name+'_'+e[name]]+=1
  inv=dict(prev[0]['market']['inventory'])
  es=market(farms,prs,actions,inv,cap,cfg.get('maxMarketOrdersPerTurn',10),cfg.get('farmHandCostMult',1))
  agg=collections.Counter()
  for s,slot,op,k,n,amt in es:
   flows[s][op+'_'+k+'_qty']+=n;flows[s][op+'_'+k+'_cash']+=amt;daily[s][day][op+'_'+k+'_qty']+=n;daily[s][day][op+'_'+k+'_cash']+=amt;agg[(s,slot,op,k,'qty')]+=n;agg[(s,slot,op,k,'cash')]+=amt
  # Compact one entry per order instead of per unit.
  keys={k[:4] for k in agg}
  alltrades.extend([[t,*k,agg[k+('qty',)],agg[k+('cash',)]] for k in sorted(keys)])
  if (t-1)%cfg.get('townShopSellInterval',4)==0:
   for shop in prev[0]['town']['unlocked_shops']:
    ps=SHOPS[shop]
    for p in ps:inv[p]-=2 if len(ps)==1 else 1
  if (t-1)%cfg.get('townCenterSellInterval',24)==0:
   for p in PRODUCTS[:-1]:inv[p]-=1
  actual_inv=ss[t][0]['observation']['market']['inventory']
  if inv!=actual_inv:errors.append({'t':t,'kind':'inventory','pred':inv,'actual':actual_inv})
  for s in range(2):
   cur=ss[t][s]['observation'];actual_money=cur['farms'][s]['money']
   if farms[s]['money']!=actual_money:errors.append({'t':t,'seat':s,'kind':'money','pred':farms[s]['money'],'actual':actual_money})
   if t%24==0:
    for y,row in enumerate(farms[s]['tiles']):
     for x,tile in enumerate(row):
      if isinstance(tile,dict) and tile.get('animal') and not tile['fed_today'] and tile.get('consecutive_unfed',0)>=1:
       nxt=cur['farms'][s]['tiles'][y][x];death_events.append([t,s,x,y,tile['animal'],tile.get('yield_units',0),tile.get('placed_day'),nxt])
    for v in prs[s]['inventories']:
     for k,n in list(v.items()):
      q=min(max(0,n),max(0,cap-sum(prs[s]['shed'].values())));prs[s]['shed'][k]=prs[s]['shed'].get(k,0)+q
      if n>q:overflow[s][k]+=n-q;daily[s][day]['overflow_'+k]+=n-q
    # Full shed equality catches mistaken deposit/order execution.
   pred={k:v for k,v in prs[s]['shed'].items() if v};actual={k:v for k,v in cur['private']['shed'].items() if v}
   if pred!=actual:errors.append({'t':t,'seat':s,'kind':'shed','pred':pred,'actual':actual})
  if len(errors)>100:break
 out={'episode_id':eid,'transitions_audited':t,'errors_count':len(errors),'errors':errors[:10],'unit_counts':unitsums,'flows':flows,'daily':daily,'trades':alltrades,'atomic_seed_failures':unitfail,'animal_exits':death_events,'overflow':overflow}
 with gzip.open(dest,'wb',compresslevel=3) as f:f.write(orjson.dumps(out))
 return eid,len(errors)

def main():
 ids=[int(n.split('.')[0]) for n in os.listdir(D+'/compact') if n.endswith('.gz')]
 if len(sys.argv)>1:ids=[int(x) for x in sys.argv[1:]]
 st=time.time();errors=[];done=0
 with ProcessPoolExecutor(max_workers=int(os.environ.get('KAGGRI_WORKERS','4'))) as ex:
  fs={ex.submit(run,e):e for e in ids}
  for f in as_completed(fs):
   try:e,n=f.result()
   except Exception as err:e=fs[f];n=repr(err)
   if n not in (0,'cached'):errors.append((e,n));print('ERROR',e,n,flush=True)
   done+=1
   if done%25==0 or done==len(fs):print('DONE',done,'/',len(fs),'secs',round(time.time()-st,1),'errors',len(errors),flush=True)
 open(D+'/audit_errors_summary.json','wb').write(orjson.dumps(errors))
if __name__=='__main__':main()
