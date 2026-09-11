import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.evaluation import runner

progress = (ROOT / "data/evaluation/research_20260910/runtime_progress.log").open("w", buffering=1)
original_call = runner._call
def timed_call(function, obs, configuration):
    step = int(obs.get("day", 0)) * 24 + int(obs.get("hour", 0))
    started = time.perf_counter()
    if step % 24 == 0:
        progress.write(f"start {step} {function.__module__}\n")
    result = original_call(function, obs, configuration)
    if step % 24 == 0 or time.perf_counter() - started > .5:
        progress.write(f"done {step} {function.__module__} {time.perf_counter() - started:.3f}\n")
    return result
runner._call = timed_call

for name in ("_run_game", "audit_pair", "analyze_safety"):
    original = getattr(runner, name)
    def wrap(*args, _original=original, _name=name, **kwargs):
        print("START", _name, flush=True)
        result = _original(*args, **kwargs)
        print("FINISH", _name, flush=True)
        return result
    setattr(runner, name, wrap)

row = runner.run_pair_task({
    "control_main": str(ROOT / "experiments/research_20260910/runtime/control/main.py"),
    "treatment_main": str(ROOT / "experiments/research_20260910/runtime/v114/main.py"),
    "opponent_main": str(ROOT / "experiments/research_20260910/runtime/mooman_e052a/main.py"),
    "lineage_id": "mooman_e052a", "opponent_name": "mooman_e052a", "opponent_tier": "Gold",
    "meta_weight": .25, "seed": 10091011, "seat": 0, "episode_steps": 720,
    "phase": "runtime_diagnostic_duplicate", "intended_action_step": 153,
    "intervention_kind": "route_choice", "strict_all_step_safety": True,
    "replay_dir": str(ROOT / "data/evaluation/research_20260910/runtime_diagnostic_duplicate"),
})
(ROOT / "data/evaluation/research_20260910/runtime_diagnostic_duplicate.json").write_text(json.dumps(row), encoding="utf-8")
