"""Synthetic mutation tests of report generation; these are NOT game results."""
from pathlib import Path
from statistics import mean
import ast,json,csv,tempfile,shutil
import os
R=Path(os.environ['ROUND3_DIR'])
O=Path(os.environ['AUDIT_OUTPUT_DIR'])
O.mkdir(parents=True, exist_ok=True)
src=R/'handoff_extracted/scripts/learning_round3.py'
tree=ast.parse(src.read_text(encoding="utf-8"))
fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='command_finalize')
# Exercise only the real reporting part, stopping before packaging/housekeeping.
fn.body=[n for n in fn.body if n.lineno <= 1172]
module=ast.Module(body=[fn],type_ignores=[])
names=['paired_results.csv','p3_paired_development/paired_summary.json','p3_candidate_scan_summary.json','p2_decomposition_summary.json','NORMALIZATION_AND_SUPPORT_AUDIT.json','LOADER_VALIDATION.json','P3_PROBE_LOADER_VALIDATION.json','EXECUTOR_CONTRACT_TESTS.json','audit_input_validation.json','MODEL_USAGE.json']
results=[]
for mode in ['positive_economic_evidence','invalid_terminal_status']:
 with tempfile.TemporaryDirectory() as td:
  p=Path(td)
  for name in names:
   (p/name).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(R/name,p/name)
  rows=list(csv.DictReader(open(p/'paired_results.csv',encoding='utf-8-sig')))
  for row in rows:
   if row['arm']=='c0':continue
   if mode=='positive_economic_evidence':
    row['paired_margin_delta_vs_c0']='500.0'
    base=next(r for r in rows if r['arm']=='c0' and r['opponent_family']==row['opponent_family'] and r['requested_seed']==row['requested_seed'] and r['seat']==row['seat'])
    base_margin=float(base['our_cash'])-float(base['opponent_cash'])
    row['our_cash']=str(float(row['opponent_cash'])+base_margin+500.0)
    row['margin']=str(base_margin+500.0)
    row['score']=str(1.0 if base_margin+500.0>0 else 0.5 if base_margin+500.0==0 else 0.0)
   else:
    row['statuses']='ERROR/ERROR';row['jobs_aborted']='1'
  with open(p/'paired_results.csv','w',newline='') as f:
   w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
  ps=json.load(open(p/'p3_paired_development/paired_summary.json'))
  if mode=='positive_economic_evidence':
   for arm,s in ps['summary'].items():
    if arm!='c0':s.update({'mean_paired_margin_delta':500.0,'positive_games':4,'negative_games':0})
   ps['positive_candidate_arms']=['feed_once_replan','feed_refill','harvest_deliver']
  (p/'p3_paired_development/paired_summary.json').write_text(json.dumps(ps))
  def write_json(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
  ns={'EXPERIMENT':p,'csv':csv,'json':json,'mean':mean,'utc_now':lambda:'SYNTHETIC_MUTATION_TEST','write_json':write_json}
  exec(compile(module,str(src),'exec'),ns);ns['command_finalize']()
  status=json.load(open(p/'FINAL_STATUS.json'));scope=json.load(open(p/'P3_SCOPE_RESULTS.json'))
  results.append({'test':mode,'synthetic_only':True,'mutated_input':'+500 all non-C0 paired margins and positive summary' if mode=='positive_economic_evidence' else 'all non-C0 terminal statuses ERROR/ERROR and aborted count 1','reported_economic_benefit':status['required_gates']['ECONOMICALLY_BENEFICIAL'],'reported_execution_valid':status['required_gates']['EXECUTION_VALID'],'reported_verdict':status['verdict'],'reported_fixed_expansion_sentence':scope['candidate_expansion_executed']['result']})
(O/'report_literal_mutation_tests.json').write_text(json.dumps(results,indent=2,ensure_ascii=False))
print(json.dumps(results,indent=2,ensure_ascii=False))
