"""Official-Python versus C++ parity on Round12-divergent full episodes."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ROUND12 = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "experiments/round10_public_learning_20260924/engines/kaggriculture-cppsim"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from run_round12_panel import jsonable, load_last, run_game


def official_run(arm_path, opponent_path, seed, seat):
    from kaggle_environments import make

    arm, _ = load_last(arm_path)
    opponent, _ = load_last(opponent_path)
    agents = [arm, opponent] if seat == 0 else [opponent, arm]
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
        env.run(agents)
    return env


def compare(case):
    arm_path = ROUND12 / case["arm"]
    opponent_path = ROOT / case["opponent"]
    env = official_run(arm_path, opponent_path, case["seed"], case["seat"])
    cpp, _ = run_game(arm_path, opponent_path, case["seed"], case["seat"], collect_route_metrics=False)
    errors = []
    n = len(cpp["decisions"])
    if n != 719 or len(env.steps) != 720:
        errors.append({"kind": "length", "cpp_decisions": n, "official_states": len(env.steps)})
    for step in range(min(n, len(env.steps) - 1)):
        for seat in (0, 1):
            # Kaggle's stored state omits shared keys (notably step) from the
            # second seat.  Reconstruct the actual full observation exactly as
            # the saved-replay auditor does: shared seat-0 block, then private
            # seat-specific fields.
            official_obs = {
                **jsonable(env.steps[step][0].observation),
                **jsonable(env.steps[step][seat].observation),
            }
            cpp_obs = cpp["decisions"][step]["observations"][seat]
            if official_obs != cpp_obs:
                errors.append({"kind": "observation", "step": step, "seat": seat})
                break
            official_action = jsonable(env.steps[step + 1][seat].action or {})
            cpp_action = cpp["decisions"][step]["actions"][seat]
            if official_action != cpp_action:
                errors.append({"kind": "action", "step": step, "seat": seat, "official": official_action, "cpp": cpp_action})
                break
        if errors:
            break
    official_rewards = [float(env.steps[-1][seat].reward) for seat in (0, 1)]
    official_statuses = [str(env.steps[-1][seat].status) for seat in (0, 1)]
    if official_rewards != cpp["terminal"]["rewards"]:
        errors.append({"kind": "rewards", "official": official_rewards, "cpp": cpp["terminal"]["rewards"]})
    return {
        **case,
        "agent_sha256": hashlib.sha256(arm_path.read_bytes()).hexdigest(),
        "official_states": len(env.steps),
        "cpp_decisions": n,
        "official_statuses": official_statuses,
        "cpp_statuses": cpp["terminal"]["statuses"],
        "official_rewards": official_rewards,
        "cpp_rewards": cpp["terminal"]["rewards"],
        "errors": errors,
    }


def main():
    cases = [
        {
            "name": "P0M1_market_diverges_from_B1",
            "arm": "agents/P0M1_market/main.py",
            "opponent": "experiments/Kaggriculture_Round11_Research_Revision_20260924/inputs/agents/v57.py",
            "seed": 612609254,
            "seat": 0,
        },
        {
            "name": "P1_independent_route",
            "arm": "agents/P1M1_strawberry_route/main.py",
            "opponent": "experiments/Kaggriculture_Round11_Research_Revision_20260924/inputs/agents/B1.py",
            "seed": 712609243,
            "seat": 1,
        },
    ]
    result = {
        "scope": "new full official-Python and reactive C++ executions; includes actual Round12 divergences",
        "cases": [compare(case) for case in cases],
    }
    result["passed"] = all(not case["errors"] for case in result["cases"])
    target = ROUND12 / "metrics/official_cpp_parity.json"
    target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
