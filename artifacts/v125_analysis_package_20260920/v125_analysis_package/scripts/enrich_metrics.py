import os,gzip,orjson,collections,hashlib,math
import pandas as pd,numpy as np
from audit_engine import PRODUCTS,price
D=os.environ.get('KAGGRI_OUTPUT_DIR',os.path.abspath('analysis_v125'));m=pd.read_csv(D+'/episode_metrics.csv');m=m[m.episode_type=='EPISODE_TYPE_PUBLIC'];out=[];days=[];exits=[];demands=[]
for j,r in enumerate(m.to_dict('records')):
 eid=r['episode_id'];s=int(r['seat']);sid=r['target_submission']
 d=orjson.loads(gzip.open(f'{D}/compact/{eid}.json.gz','rb').read());a=orjson.loads(gzip.open(f'{D}/audit/{eid}.json.gz','rb').read());c=collections.Counter(a['unit_counts'][s]);fl=collections.Counter(a['flows'][s]);ov=collections.Counter(a['overflow'][s]);err=[e for e in a['errors'] if e.get('seat')==s and e['kind']=='money'];r['own_money_error_count']=len(err);r['inventory_error_count']=sum(e['kind']=='inventory' for e in a['errors']);r['flows_reconciled']=not err
 r['ledger_cash']=3000+sum(v if k.startswith('SELL_') else -v for k,v in fl.items() if k.endswith('_cash'));r['ledger_residual']=r['ledger_cash']-r['own_reward']
 # For capacity-truncation mismatches with correct cash flows, correct item attribution
 # from the observed stock conservation. Total overflow is ordering independent.
 for e in a['errors']:
  if e.get('seat')==s and e['kind']=='shed':
   for k in set(e['pred'])|set(e['actual']):ov[k]+=e['pred'].get(k,0)-e['actual'].get(k,0)
 r.update({'actual_'+k:v for k,v in fl.items()});r.update({'verified_'+k:v for k,v in c.items()});r.update({'overflow_'+k:v for k,v in ov.items()});r['overflow_total']=sum(ov.values());r['overflow_correction_negative']=any(v<0 for v in ov.values())
 r['atomic_seed_cancellations']=c['noop_reason_atomic_seed_shortage'];r['terminal_2days_feed']=sum(x.get('FEED_ok',0) for x in a['daily'][s][28:]);r['terminal_2days_care']=sum(x.get('CARE_ok',0) for x in a['daily'][s][28:]);r['terminal_2days_fert_collect']=sum(x.get('COLLECT_FERTILIZER_ok',0) for x in a['daily'][s][28:]);r['terminal_2days_buy_wheat']=sum(x.get('BUY_PRODUCT_WHEAT_cash',0) for x in a['daily'][s][28:])
 hashes=[]
 for t,act in enumerate(d['actions'][s][1:145],1):
  n=d['hands'][s][t-1];hashes.append([act.get('farmer',['PASS']),act.get('hands',[])[:n]])
 r['effective_opening144_hash']=hashlib.sha256(orjson.dumps(hashes)).hexdigest()[:16]
 for day,dc in enumerate(a['daily'][s]):
  z={'episode_id':eid,'sid':sid,'seat':s,'day':day,'result':r['result'],'flows_reconciled':not err};z.update(dc);days.append(z)
 numreused=0
 for t,seat,x,y,animal,yld,placed,nxt in a['animal_exits']:
  if seat!=s:continue
  z={'episode_id':eid,'sid':sid,'seat':s,'death_t':t,'death_day':t//24,'x':x,'y':y,'animal':animal,'lost_yield':yld,'placed_day':placed,'next_crop':None,'next_crop_t':None}
  for dt in sorted(map(int,d['daily_states'][s])):
   if dt<=t:continue
   tile=d['daily_states'][s][str(dt)]['farm']['tiles'][y][x]
   if isinstance(tile,dict) and tile.get('animal'):break
   if isinstance(tile,dict) and tile.get('crop'):
    z.update(next_crop=tile['crop'],next_crop_t=dt);numreused+=1;break
  exits.append(z)
 r['retired_tiles_crop_reused_daily_observation']=numreused
 # Unit-by-unit pricing of the recorded executed order quantities. This is not
 # a what-if evaluation; it describes realized sales and public demand.
 byt=collections.defaultdict(dict)
 for t,st,slot,op,k,n,cash in a['trades']:
  if op in ('SELL','BUY_PRODUCT'):byt[t][(slot,st)]=(op,k,n,cash)
 sale=collections.Counter();dailyfloor=collections.defaultdict(collections.Counter);demandday={}
 for t in range(1,d['steps']):
  if t not in byt and (t-1)%24!=0:continue
  inv=dict(zip(PRODUCTS,d['market_inventory'][t-1]));sl=byt.get(t,{})
  for slot in range(10):
   z=[sl.get((slot,i)) for i in range(2)]
   for q in range(max([v[2] for v in z if v]+[0])):
    quotes=[]
    for st,v in enumerate(z):
     if v and q<v[2]:
      op,k,n,amt=v;cost=price(k,inv[k]-(op=='BUY_PRODUCT'));quotes.append((st,op,k,cost))
    for st,op,k,cost in quotes:
     if op=='SELL':
      if cost>1:inv[k]+=1
      if st==s:
       sale[k+'_unitcash_sum']+=cost
       if cost==1:sale[k+'_floor_qty']+=1;dailyfloor[(t-1)//24][k+'_floor_qty']+=1
       if cost<=5:sale[k+'_under5_qty']+=1
     else:inv[k]-=1
  if (t-1)%24==0:
   demandday[(t-1)//24]={k:6*(inv[k]-d['market_inventory'][t][i]-1)+1 if k!='FERTILIZER' else 0 for i,k in enumerate(PRODUCTS)}
 r.update({'realized_'+k:v for k,v in sale.items()})
 for day,v in demandday.items():
  z={'episode_id':eid,'sid':sid,'day':day};z.update(v);z.update(dailyfloor.get(day,{}));demands.append(z)
 r['price_unit_cash_check']=sum(sale[k+'_unitcash_sum'] for k in PRODUCTS)-sum(fl['SELL_'+k+'_cash'] for k in PRODUCTS)
 out.append(r)
 if (j+1)%100==0:print('DONE',j+1,'/',len(m),flush=True)
pd.DataFrame(out).to_csv(D+'/enriched_episode_metrics.csv',index=False);pd.DataFrame(days).fillna(0).to_csv(D+'/economic_daily_metrics.csv',index=False);pd.DataFrame(exits).to_csv(D+'/retirement_tile_reuse.csv',index=False);pd.DataFrame(demands).fillna(0).to_csv(D+'/inferred_demand_daily.csv',index=False)
print('COMPLETE',len(out),flush=True)
