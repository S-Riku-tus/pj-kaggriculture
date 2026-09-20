import os
import gzip,orjson,zipfile,json
import pandas as pd
D=os.environ.get('KAGGRI_OUTPUT_DIR',os.path.abspath('analysis_v125'));O=os.environ.get('KAGGRI_TABLES_DIR',os.path.join(D,'tables'));os.makedirs(O,exist_ok=True);m=pd.read_csv(D+'/enriched_episode_metrics.csv').fillna(0);v=m[m.target_submission.isin([56357320,56360233])];b=v[v.max_TOMATO>0].copy();b['distance']=(b.actual_SELL_TOMATO_cash-b.actual_SELL_TOMATO_cash.median()).abs();z=b.sort_values('distance').iloc[0];print('TOMATO REPRESENTATIVE',z[['episode_id','target_submission','opponent_submission','own_reward','margin','actual_SELL_TOMATO_cash','actual_SELL_TOMATO_qty','actual_HIRE__cash']].to_dict())
ids=[110837769,111075166,int(z.episode_id)];output=[]
for eid in ids:
 meta=m[m.episode_id==eid].iloc[0];s=int(meta.seat);d=orjson.loads(gzip.open(f'{D}/compact/{eid}.json.gz','rb').read());a=orjson.loads(gzip.open(f'{D}/audit/{eid}.json.gz','rb').read());raw=orjson.loads(zipfile.ZipFile(os.path.join(os.environ.get('KAGGRI_INPUT_DIR',os.getcwd()),d['archive'])).read(d['member']));o={'episode_id':eid,'target_submission':int(meta.target_submission),'seat':s,'opponent_submission':int(meta.opponent_submission),'own_reward':meta.own_reward,'opponent_reward':meta.opponent_reward,'margin':meta.margin,'money_by_day':{str(t//24):d['money'][s][t] for t in range(0,720,24)},'actual_cash_flows':a['flows'][s],'own_animal_exits':[x for x in a['animal_exits'] if x[1]==s]}
 if eid==110837769:
  o['care_order_example']={'previous_replay_step':191,'next_replay_step':192,'tile':[4,3],'before':raw['steps'][191][s]['observation']['farms'][s]['tiles'][3][4],'after':raw['steps'][192][s]['observation']['farms'][s]['tiles'][3][4]}
 if eid==111075166:
  rows=[]
  for t in range(385,482):
   p=raw['steps'][t-1][s]['observation']['farms'][s];act=raw['steps'][t][s]['action'];u=[act.get('farmer',['PASS']),*act.get('hands',[])];pos=[p['farmer'],*p['hands']]
   for i,(coords,cmd) in enumerate(zip(pos,u)):
    if coords==[8,3] and cmd[0] not in ['NORTH','SOUTH','EAST','WEST','PASS']:
     rows.append({'t':t,'action_day':(t-1)//24,'worker':i,'action':cmd,'tile_before':p['tiles'][3][8],'tile_after':raw['steps'][t][s]['observation']['farms'][s]['tiles'][3][8]})
  o['tile_8_3_action_trace']=rows;o['prices_at_retirement_t456']=dict(zip(d['products'],d['prices'][456]));print('RETIREMENT EXAMPLE',[(r['t'],r['action']) for r in rows],o['prices_at_retirement_t456'])
 if eid==int(z.episode_id):
  o['tomato_branch']={'planted_day':18,'tiles':[{'x':x,'y':y,'plant':p} for y,row in enumerate(raw['steps'][456][s]['observation']['farms'][s]['tiles']) for x,p in enumerate(row) if isinstance(p,dict) and p.get('crop')=='TOMATO'],'trades':[tr for tr in a['trades'] if tr[1]==s and (tr[4]=='TOMATO' or tr[3]=='BUY_LAND')]}
 output.append(o)
open(O+'/forensic_cases.json','w').write(json.dumps(output,ensure_ascii=False,indent=2));print('SAVED',ids)
