from pathlib import Path
from collections import Counter
import gzip,json,csv,hashlib
import os
R=Path(os.environ['ROUND3_DIR'])
O=Path(os.environ['AUDIT_OUTPUT_DIR'])
O.mkdir(parents=True, exist_ok=True)

def read(p):
 with gzip.open(p,'rt') as f:return json.load(f)
def load(arm,fam,seed,seat):
 return read(R/f'p3_paired_development/replays/{arm}/{fam}/seed_{seed}_seat_{seat}.json.gz')
def keyobs(s,seat):
 o=s[seat]['observation'];return {k:o.get(k) for k in ['farms','private','market','town','day','hour']}
def compact(o,seat,actor):
 f=o['farms'][seat];p=[f['farmer'],*f['hands']]
 if actor>=len(p):return {'absent':True}
 x,y=p[actor];return {'position':[x,y],'inventory':o['private']['inventories'][actor], 'tile':f['tiles'][y][x], 'money':f['money'],'shed':{k:v for k,v in o['private']['shed'].items() if v}}
def actions(s,seat):
 a=s[seat].get('action') or {};return [a.get('farmer'),*a.get('hands',[])]
rows=list(csv.DictReader(open(R/'paired_results.csv',encoding='utf-8-sig')))
allsummary=[];traces=[];integrity=[]
for row in rows:
 arm,fam,seed,seat=row['arm'],row['opponent_family'],int(row['requested_seed']),int(row['seat'])
 p=R/f'p3_paired_development/replays/{arm}/{fam}/seed_{seed}_seat_{seat}.json.gz'
 d=load(arm,fam,seed,seat);c=load('c0',fam,seed,seat) if arm!='c0' else d
 side=json.load(open(str(p)+'.sidecar.json'))
 integ={'arm':arm,'family':fam,'seed':seed,'seat':seat,'sha_matches':hashlib.sha256(p.read_bytes()).hexdigest()==side['replay_sha256'], 'steps':len(d['steps']), 'statuses':[s['status'] for s in d['steps'][-1]], 'info':d.get('info'),'config_seed':d['configuration'].get('seed'),'terminal_reward_matches_csv':all(float(d['steps'][-1][s]['reward'])==float(row[k]) for s,k in [(seat,'our_cash'),(1-seat,'opponent_cash')])}
 integrity.append(integ)
 diff=[i-1 for i in range(1,len(d['steps'])) if d['steps'][i][seat].get('action') != c['steps'][i][seat].get('action')]
 oppdiff=[i-1 for i in range(1,len(d['steps'])) if d['steps'][i][1-seat].get('action') != c['steps'][i][1-seat].get('action')]
 # Ignore timer and top-level step fields when checking equal game states.
 statediff=[i for i in range(len(d['steps'])) if keyobs(d['steps'][i],seat)!=keyobs(c['steps'][i],seat)]
 summary={k:row[k] for k in ['arm','opponent_family','requested_seed','seat','paired_margin_delta_vs_c0','action_changes']}
 summary.update({'actual_action_diff_turns':len(diff),'first_action_diff':diff[0] if diff else None,'last_action_diff':diff[-1] if diff else None,'opponent_action_diff_turns':len(oppdiff),'state_diff_turns':len(statediff),'last_state_diff':statediff[-1] if statediff else None,'our_terminal_delta':float(row['our_cash'])-float(next(rr['our_cash'] for rr in rows if rr['arm']=='c0' and rr['opponent_family']==fam and int(rr['requested_seed'])==seed and int(rr['seat'])==seat)), 'diff_steps':diff})
 allsummary.append(summary)
 if not diff:continue
 t=diff[0]
 aa,bb=actions(d['steps'][t+1],seat),actions(c['steps'][t+1],seat)
 actors=[a for a in range(min(len(aa),len(bb))) if aa[a]!=bb[a]]
 for actor in actors:
  states=[]
  end=min(len(d['steps'])-2,max(t+28,((t//24)+2)*24))
  for j in range(max(0,t-2),end+1):
   state={'step':j,'day':d['steps'][j][seat]['observation']['day'],'hour':d['steps'][j][seat]['observation']['hour'],'c0':compact(c['steps'][j][seat]['observation'],seat,actor),'probe':compact(d['steps'][j][seat]['observation'],seat,actor)}
   ca,da=actions(c['steps'][j+1],seat),actions(d['steps'][j+1],seat)
   state.update({'c0_action':ca[actor] if actor<len(ca) else None,'probe_action':da[actor] if actor<len(da) else None})
   states.append(state)
  traces.append({'arm':arm,'family':fam,'seed':seed,'seat':seat,'actor':actor,'first':t,'states':states})
(O/'replay_integrity.json').write_text(json.dumps(integrity,ensure_ascii=False,indent=2))
(O/'replay_diff_summary.json').write_text(json.dumps(allsummary,ensure_ascii=False,indent=2))
with open(O/'replay_diff_summary.csv','w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=[k for k in allsummary[0] if k!='diff_steps']);w.writeheader();w.writerows({k:v for k,v in r.items() if k!='diff_steps'} for r in allsummary)
(O/'first_divergence_traces.json').write_text(json.dumps(traces,ensure_ascii=False,indent=2))
for r in allsummary: print(json.dumps({k:v for k,v in r.items() if k!='diff_steps'}))
print('INTEGRITY',all(i['sha_matches'] and i['terminal_reward_matches_csv'] for i in integrity))
print('INFO',integrity[0]['info'])
for tr in traces:
 if tr['seat']==1:continue
 print('\nTRACE',tr['arm'],tr['family'],'ACTOR',tr['actor'],'FIRST',tr['first'])
 for s in tr['states']:
  if s['step']>tr['first']+24:break
  print(s['step'],'c0',s['c0'].get('position'),s['c0'].get('inventory'),s['c0_action'],'pr',s['probe'].get('position'),s['probe'].get('inventory'),s['probe_action'],'tile',s['probe'].get('tile'))
