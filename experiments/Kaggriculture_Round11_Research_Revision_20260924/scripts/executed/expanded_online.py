"""New descriptive audit, not counterfactual effects or deployed inference.
Reads raw observations; executed quantities are inherited independently audited
Round10 receipts. Rival private data are NOT used by the market-ledger formula.
"""
import sys,pathlib,zipfile,io,orjson,csv,json,ast,collections,hashlib
W=pathlib.Path('/mnt/data/r11_work');P=W/'Round10_Independent_Audit_20260924';O=pathlib.Path('/mnt/data/Kaggriculture_Round11_Research_Revision_20260924/evidence')
sys.path.insert(0,str(P));from market_reconstruction import price
source=(W/'B1/main.py').read_bytes();a=ast.parse(source)
params=next(ast.literal_eval(n.value) for n in a.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_R37_MARKET_PARAMS' for t in n.targets))
SHOPS={'BAKERY':['EGG','WHEAT'],'PIZZA_SHOP':['MILK','TOMATO','WHEAT'],'BRUNCH_SPOT':['EGG','WHEAT','STRAWBERRY'],'YARN_STORE':['WOOL'],'ICE_CREAM_SHOP':['STRAWBERRY','MILK','WHEAT'],'PET_CAFE':['CARROT'],'SMOOTHIE_SHOP':['STRAWBERRY','MILK'],'FARMERS_MARKET':['WHEAT','CARROT','TOMATO','STRAWBERRY']}
ITEMS=['CARROT','TOMATO','STRAWBERRY','MELON','EGG','MILK','WOOL'];PRODS=list(params)
import gzip
fills=collections.Counter()
with gzip.open(P/'online_actual_order_fills.csv.gz','rt') as f:
 for r in csv.DictReader(f):
  if r['op']=='SELL':fills[(int(r['episode_id']),int(r['step']),r['role'],r['item'])]+=int(r['units'])
with zipfile.ZipFile('/mnt/data/round10_b1_herd_safe_submission_56509493(1).zip') as z:
 manifest={int(r['episode_id']):r for r in csv.DictReader(io.StringIO(z.read(next(n for n in z.namelist() if n.endswith('manifest.csv'))).decode('utf-8-sig')))}
 ep={int(r['episode_id']):r for r in csv.DictReader(io.StringIO(z.read(next(n for n in z.namelist() if n.endswith('episodes.csv'))).decode('utf-8-sig')))}
 rz=zipfile.ZipFile(io.BytesIO(z.read(next(n for n in z.namelist() if n.endswith('_battle_logs.zip')))))
raws={int(n.split('episode_')[-1].split('.')[0]):n for n in rz.namelist() if '/replays/' in n and n.endswith('.json')}
summary=collections.Counter();byitem=collections.defaultdict(collections.Counter);floorcases=[];terminal=[];firsts=[];case=[]
for eid in sorted(raws):
 if ep[eid]['episode_type']!='EPISODE_TYPE_PUBLIC':continue
 d=orjson.loads(rz.read(raws[eid]));s=int(manifest[eid]['submission_seat']);r=d['steps'];summary['public_games']+=1
 pp={k:dict(v) for k,v in params.items()}
 for k,v in r[0][0]['observation']['market'].get('params',{}).items():pp[k].update(v)
 priv=r[-1][s]['observation']['private'];cargo=collections.Counter()
 for inv in priv['inventories']:cargo.update(inv)
 row={'episode_id':eid,'seat':s,'final_cash':d['rewards'][s], 'quadrants':len(r[-1][0]['observation']['farms'][s]['unlocked_quadrants'])}
 for prefix,inv in [('shed',priv['shed']),('cargo',cargo),('seeds',priv['seeds'])]:
  for k,v in inv.items():row[prefix+'_'+k]=v
 row['unspent_seed_face_cost']=sum(priv['seeds'].get(k,0)*v for k,v in {'WHEAT':10,'CARROT':20,'TOMATO':50,'STRAWBERRY':100,'MELON':80}.items())
 terminal.append(row);seen=set()
 for t in range(1,720):
  before=r[t-1][0]['observation'];after=r[t][0]['observation'];decision=t-1
  if decision>=672:
   for o in (r[t][s].get('action') or {}).get('market',[]):
    if o and o[0]=='BUY_SEED':summary['late_seed_orders']+=1
  for seat,role in ((s,'self'),(1-s,'opp')):
   for yy,line in enumerate(after['farms'][seat]['tiles']):
    for xx,tile in enumerate(line):
     if not isinstance(tile,dict) or tile.get('kind')!='PLANT':continue
     key=(role,tile['crop'])
     if key not in seen:
      seen.add(key);firsts.append({'episode_id':eid,'role':role,'crop':tile['crop'],'first_record_step':t,'planted_day':tile['planted_day']})
  C=collections.Counter()
  if decision%max(1,d['configuration'].get('townShopSellInterval',4))==0:
   for shop in before['town']['unlocked_shops']:
    for k in SHOPS[shop]:C[k]+=2 if len(SHOPS[shop])==1 else 1
  if decision%max(1,d['configuration'].get('townCenterSellInterval',24))==0:
   for k in PRODS:
    if k!='FERTILIZER':C[k]+=1
  for k in ITEMS:
   I=before['market']['inventory'][k];J=after['market']['inventory'][k];D=J-I+C[k]
   S=fills[(eid,t,'self',k)];R=fills[(eid,t,'opp',k)];M=J+C[k]
   exact=price(k,M,pp)>1;lb=max(0,D-S);U=sum(price(k,I+j,pp)>1 for j in range(S));tight=max(0,D-U)
   c=byitem[k];c['checks']+=1;c['certified_exact']+=exact;c['rival_sale_events']+=R>0
   c['hidden_rival_events_D_zero']+=int(R>0 and D==0);c['rival_event_exact']+=int(R>0 and exact)
   c['not_exact']+=not exact;c['display_recovered_but_censored']+=int(not exact and after['market']['prices'][k]>1)
   c['tight_bound_improved']+=tight>lb
   if not (0<=lb<=tight<=R):raise AssertionError((eid,t,k,'bound',D,S,R,lb,tight))
   if exact and D-S!=R:raise AssertionError((eid,t,k,'exact mismatch',D,S,R))
   if not exact and (S>0 or R>0):
    floorcases.append({'episode_id':eid,'record_step':t,'item':k,'own_executed':S,'rival_executed':R,'inventory_increments':D,'rival_lower_bound':lb,'tight_lower_bound':tight,'next_quote':after['market']['prices'][k],'pre_town_quote':price(k,M,pp)})
  if eid==112752873 and t in [48,72,144,192,240,288,360,432,480,528,576,624,672,696,719]:
   cr={'record_step':t,'day':t//24,'self_cash':after['farms'][s]['money'],'opp_cash':after['farms'][1-s]['money'],'shops':after['town']['unlocked_shops']}
   for seat,role in ((s,'self'),(1-s,'opp')):
    counts=collections.Counter(tile.get('crop',tile.get('animal','OTHER')) for line in after['farms'][seat]['tiles'] for tile in line if isinstance(tile,dict))
    cr.update({role+'_'+k:v for k,v in counts.items()});cr[role+'_land']=len(after['farms'][seat]['unlocked_quadrants'])
   case.append(cr)
 print('raw',summary['public_games'],eid,flush=True)
for c in byitem.values():summary.update(c)
summary['bound_failures']=0;summary['exact_failures']=0
summary['terminal_seed_face_cost_total']=sum(r['unspent_seed_face_cost'] for r in terminal)
summary['terminal_seed_face_cost_mean']=summary['terminal_seed_face_cost_total']/len(terminal)
summary['terminal_shed_saleable_total']=sum(r.get('shed_'+k,0) for r in terminal for k in PRODS)
summary['terminal_cargo_saleable_total']=sum(r.get('cargo_'+k,0) for r in terminal for k in PRODS)
summary['four_quadrant_games']=sum(r['quadrants']==4 for r in terminal)
summary['seed_leftover_games']=sum(r['unspent_seed_face_cost']>0 for r in terminal)
def write(name,rows):
 keys=list(dict.fromkeys(k for r in rows for k in r))
 with (O/name).open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
write('online_terminal_raw_audit.csv',terminal);write('online_first_crop_plant.csv',firsts);write('online_floor_cases.csv',floorcases);write('case_112752873_growth_and_cash.csv',case)
write('online_floor_ledger_by_item.csv',[dict(item=k,**v) for k,v in byitem.items()])
(O/'online_extended_summary.json').write_text(json.dumps(dict(summary),indent=2))
print(json.dumps(dict(summary),indent=2))
