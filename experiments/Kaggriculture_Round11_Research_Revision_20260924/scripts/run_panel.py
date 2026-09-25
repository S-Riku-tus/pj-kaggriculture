from probe_game import *
from concurrent.futures import ProcessPoolExecutor, as_completed
ARMS=['B1','wool_gate_open','final_response','combined']
SEEDS=[402609241,402609242,402609243,402609244]
OPPONENTS=['B1','v57','order_book','metav4']
if __name__=='__main__':
    protocol={'role':'new small development panel, not promotion/holdout','arms':ARMS,'seeds':SEEDS,'opponents':OPPONENTS,
        'seats':[0,1],'planned_games':128,'independent_seed_blocks':4,
        'simulator':'supplied cppsim; matched three online raw trajectories before evaluation; official Python runtime not available',
        'selection':'all four arms, all planned cells retained, no candidate selection within this panel',
        'primary':'paired change in win+0.5*draw points','secondary':'cash margin, farm/action and town-sequence differences',
        'wool_gate_open':'V9_RACEGATE_BASE[WOOL]=0 only, remaining original gates retained',
        'final_response':'restricted all-SELL 2..6 orders; final-list mirror proxy; independent new diagnostic inspired by Order Book v3, not its exact source',
        'combined':'both interventions, not presumed additive'}
    # Do not reuse traces after a script, source, engine or protocol change.
    root=Path(__file__).resolve().parents[1]
    fingerprint_files=[Path(__file__),root/'scripts/probe_game.py',*PATHS.values(),*sorted((root/'engine_cppsim').rglob('*.hpp')),*sorted((root/'engine_cppsim').rglob('*.cpp'))]
    fingerprint={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in fingerprint_files}
    protocol['implementation_fingerprint']=fingerprint
    dest=O/'development_protocol.json'
    if dest.exists() and json.loads(dest.read_text())!=protocol:
        raise SystemExit('Output contains a different experiment. Choose a new R11_OUTPUT; do not reuse stale results.')
    dest.write_text(json.dumps(protocol,indent=2))
    jobs=list(itertools.product(ARMS,OPPONENTS,SEEDS,[0,1]));results=[]
    with ProcessPoolExecutor(max_workers=6) as ex:
        futures={ex.submit(run,j):j for j in jobs}
        for f in as_completed(futures):
            r=f.result();results.append(r)
            print(len(results),r['arm'],r['opponent'],r['seed'],r['seat'],r['margin'],r['error'],flush=True)
            (O/'development_results_inprogress.json').write_text(json.dumps(results,indent=2))
    results.sort(key=lambda r:(ARMS.index(r['arm']),r['opponent'],r['seed'],r['seat']))
    (O/'development_results.json').write_text(json.dumps(results,indent=2))
