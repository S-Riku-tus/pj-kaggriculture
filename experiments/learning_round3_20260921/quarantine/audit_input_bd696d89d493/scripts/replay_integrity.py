import os
from replay_probe import *
import pandas as pd
O=Path(os.environ['AUDIT_OUT']);df=pd.read_csv(P/'external_bank/paired_results.csv');checks=[]
family_filter=sys.argv[1] if len(sys.argv)>1 else None
if family_filter: df=df[df['opponent_family']==family_filter]
for (family,seed,seat),group in df.groupby(['opponent_family','requested_seed','seat']):
 cr=replay('c0',family,seed,seat);control=[step[seat].get('action') for step in cr['steps'][1:]]
 for row in group.to_dict('records'):
  r=cr if row['arm']=='c0' else replay(row['arm'],family,seed,seat)
  rewards=[float(s['reward']) for s in r['steps'][-1]];acts=[s[seat].get('action') for s in r['steps'][1:]];diff=[i for i,(a,b) in enumerate(zip(control,acts)) if a!=b]
  checks.append({'arm':row['arm'],'family':family,'seed':int(seed),'seat':int(seat),'states':len(r['steps']),'terminal_rewards_match_csv':rewards[seat]==row['our_cash'] and rewards[1-seat]==row['opponent_cash'],'action_differences_match_csv':len(diff)==row['action_differences_vs_c0'],'first_action_difference_match_csv':((not diff and pd.isna(row['first_action_difference'])) or (bool(diff) and diff[0]==row['first_action_difference'])),'statuses':[s['status'] for s in r['steps'][-1]]})
(O/f"replay_integrity_{family_filter or 'all'}.json").write_text(json.dumps(checks,indent=2))
print('games',len(checks),'states',sorted(set(r['states'] for r in checks)))
for field in ['terminal_rewards_match_csv','action_differences_match_csv','first_action_difference_match_csv']:print(field,sum(r[field] for r in checks),'/',len(checks))
print('statuses',sorted(set(str(r['statuses']) for r in checks)))
