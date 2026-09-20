import os
import pandas as pd,gzip,orjson,collections
D=os.environ.get('KAGGRI_OUTPUT_DIR',os.path.abspath('analysis_v125'));m=pd.read_csv(D+'/enriched_episode_metrics.csv').fillna(0);m['group']=m.target_submission.map({56357320:'v124',56360233:'v124',56216119:'Top1',56361903:'Top2',56354460:'Top3'});v=m[m.group=='v124'];P=['WHEAT','FERTILIZER','WOOL','MILK','STRAWBERRY','TOMATO','CARROT','EGG','MELON']
print('FLOOR SALES share%, units/game')
for g,df in m[m.flows_reconciled].groupby('group'):
 print(g,{p:(round(df.get('realized_'+p+'_floor_qty',pd.Series([0])).sum()/max(1,df['actual_SELL_'+p+'_qty'].sum())*100,1),round(df['actual_SELL_'+p+'_qty'].mean(),1)) for p in P})
rows=[]
for r in v.to_dict('records'):
 a=orjson.loads(gzip.open(f'{D}/audit/{r["episode_id"]}.json.gz','rb').read());s=r['seat'];f=[collections.Counter(a['flows'][i]) for i in range(2)];z={k:r[k] for k in ['episode_id','target_submission','opponent_submission','opponent_rating','result','margin']}
 for p in P:
  rr=[f[i]['SELL_'+p+'_cash'] for i in range(2)];q=[f[i]['SELL_'+p+'_qty'] for i in range(2)];ps=[rr[i]/q[i] if q[i] else (rr[1-i]/q[1-i] if q[1-i] else 0) for i in range(2)];z['revenue_delta_'+p]=rr[s]-rr[1-s];z['qty_effect_'+p]=(q[s]-q[1-s])*(ps[0]+ps[1])/2;z['price_effect_'+p]=(ps[s]-ps[1-s])*(q[0]+q[1])/2
 for cost in ['HIRE','BUY_LAND','BUY_SEED','BUY_PRODUCT','BUY_ANIMAL']:
  cst=[sum(v for k,v in f[i].items() if k.startswith(cost+'_') and k.endswith('_cash')) for i in range(2)];z['cost_saving_'+cost]=cst[1-s]-cst[s]
 rows.append(z)
x=pd.DataFrame(rows);x.to_csv(D+'/v124_same_game_cash_decomposition.csv',index=False)
for name,df in [('all',x),('all_losses',x[x.result=='loss']),('1600plus',x[x.opponent_rating>=1600]),('1600plus_losses',x[(x.opponent_rating>=1600)&(x.result=='loss')])]:
 print('\nDECOMPOSITION',name,'n',len(df),'meanmargin',df.margin.mean());print(df[[col for col in df if col.startswith(('revenue_delta','cost_saving'))]].mean().round(1).to_string());print('QvP',df[[col for col in df if col.startswith(('qty_effect','price_effect'))]].sum().groupby(lambda n:n.split('_effect')[0]).sum()/len(df))
print('CASE NEARLOSS');print(x[x.episode_id.isin([110837769,110864342,110836675,110857714,110830032])].set_index('episode_id')[[c for c in x if c.startswith(('revenue_delta','cost_saving'))]].T.to_string())
