import os,json,gzip,collections,orjson
from pathlib import Path
R=Path(os.environ.get('ROUND9_ROOT', '/mnt/data/audit_work/round9_teacher_reproduction_and_closed_loop_bc_20260923'));O=Path(os.environ.get('AUDIT_EVIDENCE', str(Path(__file__).resolve().parents[1] / 'evidence')))
st=collections.Counter();reasons=collections.Counter();examples={};opchanges=collections.Counter();topillegal=collections.Counter();eff=collections.Counter()
for p in sorted((R/'development_panel_a2_v2_expanded64/diagnostics').glob('*.gz')):
 j=orjson.loads(gzip.open(p,'rb').read());st['games']+=1
 for k,v in j['base'].items():
  if isinstance(v,int):st['base_'+k]+=v
 for trace in j['trace'].values():
  for t in trace:
   st['steps']+=1;plan=t.get('plan',{});st['plan_disabled']+=bool(plan.get('disabled'));st['plan_active']+=bool(plan.get('active'));st['plan_interventions']+=len(plan.get('interventions',[]));st['final_equal_ledger_turns']+=t['final_action']==t['ledger_action']
   for a in t['decoder']['actors']:
    raw=a['raw_model']['token'];masked=a['mask']['token'];cands=a['mask_candidates'];st['actor_decisions']+=1;st['raw_top1_not_legal']+=raw not in cands;st['raw_mask_token_change']+=raw!=masked
    if raw!=masked:
     opchanges[(raw,masked)]+=1
     st['illegal_to_movement']+=masked in {'NORTH','SOUTH','EAST','WEST'}
     st['work_to_movement']+=masked in {'NORTH','SOUTH','EAST','WEST'} and raw not in {'NORTH','SOUTH','EAST','WEST','PASS'}
    if raw not in cands:topillegal[raw]+=1
   for a in t['final_resolution']['actors']:reasons[a['reason']]+=1
   effect=t.get('effect',{});eff['status_'+effect.get('status','NONE')]+=1
   for a in effect.get('actors',[]):
    cmd=a.get('action',[])
    if cmd and cmd[0] not in ['NORTH','SOUTH','EAST','WEST','PASS']:
     eff['work_rows']+=1;eff['work_success']+=bool(a.get('success'))
   if t['step'] in [480,600,718] and 'seed_2026102301_seat_0' in p.name:examples[str(t['step'])]=t
print(dict(st));print('reasons',dict(reasons));print('effect',dict(eff));print('commonchanges',opchanges.most_common(12));print('topillegal',topillegal.most_common(12))
(O/'diagnostic_recount.json').write_text(json.dumps({'counts':dict(st),'resolver_reasons':dict(reasons),'effect_counts':dict(eff),'top_raw_mask_changes':[[*k,v] for k,v in opchanges.most_common(30)],'top_illegal_raw':dict(topillegal)},indent=2))
(O/'late_state_trace_examples.json').write_text(json.dumps(examples,indent=2))
