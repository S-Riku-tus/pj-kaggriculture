import os
"""Isolated loader-semantic smoke tests on actual supplied archives.
This reproduces compile/exec(empty dict)/last-callable selection from official
get_last_callable; it does not claim to run the pinned Kaggle full environment.
"""
from pathlib import Path
import hashlib,json,subprocess,sys,tarfile
ROOT=Path(os.environ['HANDOFF_ROOT'])/'artifacts'/'submissions'
OUT=Path(os.environ['AUDIT_OUT'])
WORK=Path(os.environ['AUDIT_OUT'])/'archive_loader_tmp'; WORK.mkdir(exist_ok=True)
CODE=r'''
import sys,pathlib,traceback,json,builtins
p=pathlib.Path(sys.argv[1]);mode=sys.argv[2];sys.path.append(str(p))
env={} if mode=='empty_globals' else {'__file__':str(p/'main.py'),'__name__':'loader_test'}
if mode=='no_numpy':
 original=builtins.__import__
 def blocked(name,*args,**kwargs):
  if name=='numpy' or name.startswith('numpy.'):raise ModuleNotFoundError('numpy deliberately unavailable in this diagnostic')
  return original(name,*args,**kwargs)
 builtins.__import__=blocked
try:
 exec(compile((p/'main.py').read_text(),str(p/'main.py'),'exec'),env)
 funcs=[v for v in env.values() if callable(v)]
 print(json.dumps({'mode':mode,'success':True,'last_callable':getattr(funcs[-1],'__name__',str(funcs[-1]))}))
except Exception as e:
 print(json.dumps({'mode':mode,'success':False,'error_type':type(e).__name__,'error':str(e),'last_traceback_line':traceback.format_exc().strip().splitlines()[-1]}))
'''
rows=[]
for archive in sorted(ROOT.glob('learning_round2_20260921_*.tar.gz')):
 target=WORK/archive.stem.replace('.tar','');target.mkdir(exist_ok=True)
 with tarfile.open(archive) as tf:tf.extractall(target,filter='data')
 result={'archive':archive.name,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'tests':[]}
 for mode in ['empty_globals','injected_globals','no_numpy']:
  cp=subprocess.run([sys.executable,'-c',CODE,str(target),mode],cwd=target,capture_output=True,text=True,timeout=15)
  result['tests'].append(json.loads(cp.stdout.splitlines()[-1]) if cp.stdout else {'exit_code':cp.returncode,'stderr':cp.stderr})
 rows.append(result)
(OUT/'loader_probe.json').write_text(json.dumps(rows,indent=2))
print(json.dumps(rows,indent=2))
