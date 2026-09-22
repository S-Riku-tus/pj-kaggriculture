from pathlib import Path
from collections import Counter
from collections.abc import Mapping,Sequence
from typing import Any
from copy import deepcopy
import json,gzip,ast,importlib.util,hashlib
import os
R=Path(os.environ['ROUND3_DIR'])
O=Path(os.environ['AUDIT_OUTPUT_DIR'])
O.mkdir(parents=True, exist_ok=True)
P=R/'handoff_extracted/agents/learning_round3_20260921/a3_probe_agent.py'
C=P.with_name('contracts.py')
spec=importlib.util.spec_from_file_location('audit_contracts',C);cm=importlib.util.module_from_spec(spec);spec.loader.exec_module(cm)
tree=ast.parse(P.read_text(encoding="utf-8"))
needed=['_positions','_move','_distance','_route','_tile','_contract','_unfed','_candidate','_pending_action']
ns={'Mapping':Mapping,'Sequence':Sequence,'Any':Any,'actor_identity':cm.actor_identity,'_jobs':{},'MAX_JOBS':1,'MODE':'harvest_deliver'}
filtered=ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in needed],type_ignores=[])
exec(compile(filtered,str(P),'exec'),ns)
def rp(arm,fam='qeinstein_moev2',seed=2026092421,seat=0):
 return json.load(gzip.open(R/f'p3_paired_development/replays/{arm}/{fam}/seed_{seed}_seat_{seat}.json.gz','rt'))
c0=rp('c0');d=rp('feed_once_replan');har=rp('harvest_deliver')
o=deepcopy(c0['steps'][205][0]['observation']);o.update({'step':205,'player':0})
a=c0['steps'][206][0]['action']
job=ns['_candidate'](o,a)
pending=ns['_pending_action'](o,deepcopy(job))
# Primitive-level direct transition evidence, not a new game simulation.
ho0=har['steps'][205][0]['observation'];ho1=har['steps'][206][0]['observation']
harvest={'candidate_emitted':job is not None,'candidate_id':job['candidate_id'],'day':o['day'],'planted_day':o['farms'][0]['tiles'][1][0]['planted_day'],'age_days':o['day']-o['farms'][0]['tiles'][1][0]['planted_day'],'yield_units':o['farms'][0]['tiles'][1][0]['yield_units'],'contract_continuation':job['continuation'],'contract_reserved_materials':job['reserved_materials'],'runtime_first_action':pending,'inventory_before':ho0['private']['inventories'][4],'inventory_after':ho1['private']['inventories'][4],'tile_unchanged':ho0['farms'][0]['tiles'][1][0]==ho1['farms'][0]['tiles'][1][0],'new_product_created':sum(ho1['private']['inventories'][4].values()) > sum(ho0['private']['inventories'][4].values())}
ns['MODE']='feed_once_replan'
o=deepcopy(d['steps'][434][0]['observation']);o.update({'step':434,'player':0})
feedjob=ns['_candidate'](o,c0['steps'][435][0]['action'])
o435=deepcopy(d['steps'][435][0]['observation']);o435.update({'step':435,'player':0})
o436=deepcopy(d['steps'][436][0]['observation']);o436.update({'step':436,'player':0})
feed={'contract':feedjob,'same_turn_duplicate_feed_action_actors':[i for i,a in enumerate([d['steps'][436][0]['action']['farmer'],*d['steps'][436][0]['action']['hands']]) if a==['FEED'] and [o435['farms'][0]['farmer'],*o435['farms'][0]['hands']][i]==[5,4]],'joint_validator_reasons':cm.validate_joint_action(o435,d['steps'][436][0]['action'],[feedjob]),'rejoin_status_at_436':cm.rejoin_status(o436,feedjob),'actor5_wheat_before_feed':o435['private']['inventories'][5].get('WHEAT',0),'actor5_wheat_after_feed':o436['private']['inventories'][5].get('WHEAT',0),'actor4_wheat_before_feed':o435['private']['inventories'][4].get('WHEAT',0),'actor4_wheat_after_feed':o436['private']['inventories'][4].get('WHEAT',0),'actor5_wheat_at_441':d['steps'][441][0]['observation']['private']['inventories'][5].get('WHEAT',0),'actor5_action_at_441':d['steps'][442][0]['action']['hands'][4],'target_fed_after_441':d['steps'][442][0]['observation']['farms'][0]['tiles'][4][7]['fed_today']}
funcs={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
calls={name:sorted({n.func.id for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}) for name,fn in funcs.items()}
tests=(R/'handoff_extracted/tests/test_learning_round3.py').read_text(encoding="utf-8")
scan=[json.loads(s) for s in (R/'p3_candidate_scan.jsonl').read_text(encoding="utf-8").splitlines()]
manifest=json.load(open(R/'HANDOFF_MANIFEST.json'));checks=[]
for f in manifest['files']:
 p=R/'handoff_extracted'/f['path']
 checks.append({'path':f['path'],'ok':p.exists() and hashlib.sha256(p.read_bytes()).hexdigest()==f['sha256']})
result={'harvest':harvest,'feed_once':feed,'source_call_graph':calls,'production_test_imports_probe_agent':'a3_probe_agent' in tests,'scan':{'count':len(scan),'unique_candidate_id_count':len(set(s['candidate_id'] for s in scan)),'by_job':dict(Counter(s['job_type'] for s in scan)),'harvest_candidate_ids':dict(Counter(s['candidate_id'] for s in scan if s['job_type'].startswith('HARVEST')))},'handoff_manifest':{'checked':len(checks),'all_ok':all(c['ok'] for c in checks),'failures':[c for c in checks if not c['ok']]},'limitations':'AST-extracted functions and attached recorded observations were exercised. No new engine rollout or training was run.'}
(O/'source_contract_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in result.items() if k!='source_call_graph'},ensure_ascii=False,indent=2))
