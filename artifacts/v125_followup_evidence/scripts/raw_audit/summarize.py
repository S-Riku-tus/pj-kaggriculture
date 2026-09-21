import os,gzip,orjson,collections,hashlib
import pandas as pd,numpy as np
D=os.environ.get('KAGGRI_OUTPUT_DIR',os.path.abspath('analysis_v125')); m=pd.read_csv(D+'/metadata_all.csv');rows=[];days=[]
for row in m.to_dict('records'):
 p=D+'/compact/'+str(row['episode_id'])+'.json.gz'
 if not os.path.exists(p):continue
 try:
  with gzip.open(p,'rb') as f:d=orjson.loads(f.read())
 except:continue
 s=int(row['seat']);o=1-s;n=d['steps'];ks=d['countkeys'];idx={x:i for i,x in enumerate(ks)}
 row['own_reward']=d['rewards'][s];row['opponent_reward']=d['rewards'][o]
 row['margin']=row['own_reward']-row['opponent_reward'];row['result']='win' if row['margin']>0 else ('loss' if row['margin']<0 else 'draw');row['module_version']=d['module_version'];row['steps']=n;row['overage_min']=d['overage_min'][s]
 acts=d['actions'][s]
 for h in [72,144,216,288,360,432,504,576,648,696,719]:
  t=min(h,n-1); row['money_'+str(h)]=d['money'][s][t];row['margin_'+str(h)]=d['money'][s][t]-d['money'][o][t]
  for x in ks[:8]:row[x+'_'+str(h)]=d['counts'][s][t][idx[x]]
  row['land_'+str(h)]=d['land'][s][t]
 for k in ks[:8]:row['max_'+k]=max(c[idx[k]] for c in d['counts'][s])
 for a in ks[:3]:row['lost_'+a]=sum(max(0,a0[idx[a]]-a1[idx[a]]) for a0,a1 in zip(d['counts'][s],d['counts'][s][1:]))
 row['total_lost_animals']=sum(row['lost_'+a] for a in ks[:3]);row['final_shed']=sum(d['private'][s][-1]['shed']);row['final_carry']=sum(d['private'][s][-1]['carry']);row['max_hands']=max(d['hands'][s]);row['hands_days']=sum(max(d['hands'][s][t:min(n,t+24)]) for t in range(0,n,24))
 row['same_opening_120']=d['actions'][s][1:121]==d['actions'][o][1:121]
 row['hash_120']=hashlib.sha256(orjson.dumps(acts[1:121],option=orjson.OPT_SORT_KEYS)).hexdigest()[:16]
 for comp in ['all','units','market']:
  aa=acts[1:145] if comp=='all' else ([{k:a.get(k) for k in ['farmer','hands']} for a in acts[1:145]] if comp=='units' else [a.get('market') for a in acts[1:145]])
  row['opening144_'+comp]=hashlib.sha256(orjson.dumps(aa,option=orjson.OPT_SORT_KEYS)).hexdigest()[:16]
 ops=collections.Counter(); market=collections.Counter()
 for t,a in enumerate(acts[1:],1):
  for ua in [a.get('farmer',[]),*a.get('hands',[])]:
   if isinstance(ua,list) and ua:ops[ua[0]]+=1
  for ma in a.get('market',[]):
   if isinstance(ma,list) and ma:
    market['orders_'+ma[0]]+=1
    if len(ma)>2:
     try:market[ma[0]+'_'+str(ma[1])]+=int(ma[2])
     except:pass
 row.update({'op_'+k:v for k,v in ops.items()});row.update(dict(market))
 for t in range(0,n,24):
  dd={'episode_id':row['episode_id'],'target_submission':row['target_submission'],'seat':s,'result':row['result'],'episode_type':row['episode_type'],'opponent_rating':row['opponent_rating'],'day':t//24,'money':d['money'][s][t],'opponent_money':d['money'][o][t],'margin':d['money'][s][t]-d['money'][o][t],'land':d['land'][s][t],'hands_max':max(d['hands'][s][t:min(n,t+24)])}
  for k in ks[:8]:dd[k]=d['counts'][s][t][idx[k]]
  dd['unfed_end']=d['counts'][s][min(n-1,t+23)][idx['unfed']];dd['uncared_end']=d['counts'][s][min(n-1,t+23)][idx['uncared']];dd['unwatered_end']=d['counts'][s][min(n-1,t+23)][idx['unwatered']]
  days.append(dd)
 rows.append(row)
r=pd.DataFrame(rows);r.to_csv(D+'/episode_metrics.csv',index=False);pd.DataFrame(days).to_csv(D+'/daily_metrics.csv',index=False)
pub=r[r.episode_type=='EPISODE_TYPE_PUBLIC'];print('parsed perspectives',len(r),'public',len(pub))
for sid,g in pub.groupby('target_submission'):
 print('\nGROUP',sid,'N',len(g),'results',g.result.value_counts().to_dict(),'mean bank',g.own_reward.mean(),'margin',g.margin.mean(),'animals lost games',sum(g.total_lost_animals>0))
 print('phases',g[[f'margin_{t}' for t in [144,288,432,576,719]]].mean().round(1).to_dict());print('max species',g[['max_'+k for k in ['COW','SHEEP','GOOSE','WHEAT','CARROT','TOMATO','STRAWBERRY','MELON']]].mean().round(2).to_dict());print('final species',g[[k+'_719' for k in ['COW','SHEEP','GOOSE','WHEAT','CARROT','TOMATO','STRAWBERRY','MELON']]].mean().round(2).to_dict());print('ops',g[[x for x in g if x.startswith('op_')]].mean().round(1).to_dict());print('opening diversity',g.opening144_units.nunique(),g.opening144_market.nunique(),'mean staff-days',g.hands_days.mean());print('final leftovers',g[['final_shed','final_carry']].mean().round(1).to_dict())
 if sid in [56357320,56360233]:
  for lo,hi in [(0,1500),(1500,1600),(1600,1700),(1700,2000)]:
   b=g[(g.opponent_rating>=lo)&(g.opponent_rating<hi)];print(lo,hi,len(b),b.result.value_counts().to_dict(),b.margin.mean())
