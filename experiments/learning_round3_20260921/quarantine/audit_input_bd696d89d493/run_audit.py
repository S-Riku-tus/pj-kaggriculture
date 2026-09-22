"""Reproduce the archive audit. Requires Python 3.12+, NumPy, pandas.
Usage: python run_audit.py --input learning_round2_20260921.zip --output audit_out
No network access, Kaggle submission, training, or new full-game rollout is performed.
"""
from __future__ import annotations
import argparse,json,os,pathlib,subprocess,sys,zipfile

def extract_safe(source: pathlib.Path, target: pathlib.Path) -> None:
    target.mkdir(parents=True,exist_ok=True)
    root=target.resolve()
    with zipfile.ZipFile(source) as archive:
        for entry in archive.infolist():
            dest=(root/entry.filename).resolve()
            if not dest.is_relative_to(root):
                raise ValueError(f'Unsafe archive member: {entry.filename}')
        archive.extractall(root)

def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=pathlib.Path,required=True)
    parser.add_argument('--output',type=pathlib.Path,required=True)
    parser.add_argument('--skip-full-integrity',action='store_true',help='Skip the separate 256-replay all-arm integrity pass; other probes still read replays.')
    args=parser.parse_args()
    if sys.version_info<(3,12): raise RuntimeError('Use Python 3.12 or newer.')
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    source=args.input.resolve()
    if source.is_dir(): root=source
    elif source.is_file():
        extract_safe(source,output/'input');root=output/'input'/'learning_round2_20260921'
    else: raise FileNotFoundError(source)
    if not (root/'REPORT_JA.md').is_file(): raise FileNotFoundError(f'Expected report under {root}')
    handoff=output/'handoff';extract_safe(root/'handoff_evidence.zip',handoff)
    results=output/'results';results.mkdir(exist_ok=True)
    env={**os.environ,'ROUND2_ROOT':str(root),'HANDOFF_ROOT':str(handoff),'AUDIT_OUT':str(results),'OPENBLAS_NUM_THREADS':'1'}
    scripts=pathlib.Path(__file__).resolve().parent/'scripts'
    commands=[('summarize.py',[]),('replay_probe.py',[]),('a2_probe.py',[]),('additional_probes.py',[]),('metric_and_outcome_probe.py',[]),('loader_probe.py',[])]
    if not args.skip_full_integrity:
        commands += [('replay_integrity.py',[family]) for family in ['mooman_e052a','qeinstein_moev2','smart_farm','souvik_v4']]
    for script,extra in commands:
        label=pathlib.Path(script).stem+('_'+extra[0] if extra else '')
        print(f'Running {label}',flush=True)
        with (results/(label+'.txt')).open('w',encoding='utf-8') as log:
            subprocess.run([sys.executable,str(scripts/script),*extra],env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    if not args.skip_full_integrity:
        rows=[]
        for path in sorted(results.glob('replay_integrity_*.json')):rows.extend(json.loads(path.read_text()))
        (results/'replay_integrity.json').write_text(json.dumps(rows,indent=2))
    print(f'Results: {results}')

if __name__=='__main__': main()
