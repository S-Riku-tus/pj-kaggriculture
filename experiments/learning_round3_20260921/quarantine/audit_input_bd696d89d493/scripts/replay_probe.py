import os
from pathlib import Path
import gzip,json,sys,importlib.util,copy
P=Path(os.environ['ROUND2_ROOT'])
def load(arm):
 for n in ['common','learning_common']: sys.modules.pop(n,None)
 path=P/'runtime'/arm/'main.py'
 sys.path.insert(0,str(path.parent))
 spec=importlib.util.spec_from_file_location('audit_'+arm,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 return m

def replay(arm,fam,seed,seat):
 return json.load(gzip.open(P/f'external_bank/replays/{arm}/{fam}/seed_{seed}_seat_{seat}.json.gz','rt'))
def obs(r,t,seat):
 o=copy.deepcopy(r['steps'][t][0]['observation']);o['player']=seat;o['private']=copy.deepcopy(r['steps'][t][seat]['observation']['private']);o['step']=t;return o
if __name__=='__main__':
 b2=load('b2');b1=load('b1');a2=load('a2')
 fam,seed,seat='smart_farm',2026092424,0
 c=replay('c0',fam,seed,seat);b=replay('b2',fam,seed,seat); t=264
 o=obs(c,t,seat)
 hist=b2.MarketHistory()
 for ti in range(t+1):hist.update(obs(c,ti,seat),c['steps'][ti][seat]['action'].get('market',[]) if ti else None)
 pred=b2._predict(o,hist);p1=b1._predict(o,hist)
 print('OBS',t,'day/hour',o['day'],o['hour'],'cash',[f['money'] for f in o['farms']],'shed',o['private']['shed'])
 print('MARKET',o['market'])
 for arm,r in [('c0',c),('b2',b)]:
  print(arm,'action',r['steps'][t+1][seat]['action'],'oppaction',r['steps'][t+1][1-seat]['action'])
  print(arm,'nextmoney',[f['money'] for f in r['steps'][t+1][0]['observation']['farms']],'nextshed',r['steps'][t+1][seat]['observation']['private']['shed'])
 for item in b2.PRODUCTS:
  print(item,'B2',[(h,pred[(item,h)]) for h in (1,4,24)],'B1_h1',p1[(item,1)])
 risk={item:sum(pred[item,h][0]*pred[item,h][1]/h for h in (1,4,24)) for item in b2.PRODUCTS}
 acts=b2.sell_blocks(c['steps'][t+1][seat]['action']['market'],risk)
 print('predicted_opponent',[[item,round(pred[item,1][1])] for item in b2.PRODUCTS if pred[item,1][0]>=.25 and pred[item,1][1]>=.5])
 print('SCORES',[(a,b2.score_sell_candidate(o,a,pred)) for a in acts])
 # cash divergence at first B2 change all games
 import pandas as pd
 df=pd.read_csv(P/'external_bank/paired_results.csv'); rows=[]
 for row in df[df.arm=='b2'].to_dict('records'):
  fam,seed,seat=row['opponent_family'],row['requested_seed'],row['seat']; cr=replay('c0',fam,seed,seat);br=replay('b2',fam,seed,seat)
  first=int(row['first_action_difference']);cb=obs(cr,first,seat);bb=obs(br,first,seat)
  for q in [cb,bb]:q.pop('remainingOverageTime',None)
  moneyc=[f['money'] for f in cr['steps'][first+1][0]['observation']['farms']];moneyb=[f['money'] for f in br['steps'][first+1][0]['observation']['farms']]
  udiff=sum(cr['steps'][s][seat]['action'].get('farmer')!=br['steps'][s][seat]['action'].get('farmer') or cr['steps'][s][seat]['action'].get('hands')!=br['steps'][s][seat]['action'].get('hands') for s in range(1,720))
  rows.append({'family':fam,'seed':seed,'seat':seat,'same_initial_obs':cb==bb,'first_step':first,'first_self_delta':moneyb[seat]-moneyc[seat],'first_opp_delta':moneyb[1-seat]-moneyc[1-seat],'first_margin_delta':moneyb[seat]-moneyc[seat]-moneyb[1-seat]+moneyc[1-seat],'terminal_margin_delta':row['paired_margin_delta_vs_c0'],'unit_action_differences':udiff})
 df2=pd.DataFrame(rows);df2.to_csv((Path(os.environ['AUDIT_OUT'])/'b2_first_divergence.csv'),index=False);print('ALL FIRST DIVERGENCE',df2.to_string(index=False));print('MEAN',df2.select_dtypes('number').mean().to_dict())
