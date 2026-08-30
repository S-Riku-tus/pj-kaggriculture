"""Paired adaptive closed-loop diagnostics for V106 versus V14 or active V18."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kaggle_environments import make  # noqa: E402

from agents.v14 import main as opponent_v14  # noqa: E402
from agents.v18 import main as opponent_v18  # noqa: E402
from agents.v100 import main as opponent_v100  # noqa: E402
from agents.v106 import main as v106  # noqa: E402
from scripts.run_v102_diagnostic import (  # noqa: E402
    _mode_summary,
    _runtime_failures,
    _trace,
)
from scripts.run_v105_replay_forks import _action_difference  # noqa: E402


def _reset(module: Any) -> None:
    mission = getattr(module, "v9", None)
    if mission is None and hasattr(module, "v92"):
        mission = module.v92.v9
    if mission is None:
        raise AttributeError(f"opponent has no mission state: {module!r}")
    mission._MISSION_LAST_STEP = -1
    mission._MISSION_PREVIOUS_ACTIONS = []
    reset_counts = getattr(module, "reset_runtime_counts", None)
    if callable(reset_counts):
        reset_counts()


def _run(
    seed: int,
    seat: int,
    enabled: bool,
    opponent_name: str,
    replay_path: Path,
) -> dict[str, Any]:
    opponents = {"v14": opponent_v14, "v18": opponent_v18, "v100": opponent_v100}
    opponent = opponents[opponent_name]
    v106.reset_runtime_state()
    _reset(v106)
    _reset(opponent)
    v106.ENABLE_SPEC_ACCURATE_DAILY_RECOVERY = enabled
    if opponent_name == "v18":
        opponent_v18.ENABLE_INTRADAY_HERD_GATE = True
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=True)
    policies = [v106.agent, opponent.agent] if seat == 0 else [opponent.agent, v106.agent]
    env.run(policies)
    replay = env.toJSON()
    rewards = [float(value or 0) for value in replay.get("rewards") or (0, 0)]
    trace = _trace(replay, seat)
    trace["active_steps"] = int(v106.v105._DAILY_ACTIVE_STEPS) if enabled else 0
    trace["changed_steps"] = int(v106.v105._DAILY_ACTIVE_STEPS) if enabled else 0
    trace["daily_activations"] = int(v106.v105._DAILY_ACTIVATIONS) if enabled else 0
    trace["emergency_fallbacks"] = int(v106.v105._DAILY_EMERGENCY_FALLBACKS) if enabled else 0
    if not enabled:
        trace["mean_normalized_change"] = 0.0
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    replay_path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")
    return {
        "seed": seed,
        "resolved_seed": int(replay["info"]["seed"]),
        "seat": seat,
        "mode": "candidate" if enabled else "safe-core",
        "opponent": opponent_name,
        "ours": rewards[seat],
        "theirs": rewards[1 - seat],
        "margin": rewards[seat] - rewards[1 - seat],
        "statuses": [str(state["status"]) for state in replay["steps"][-1]],
        "runtime_failures": _runtime_failures(replay),
        "trace": trace,
        "replay": str(replay_path.relative_to(ROOT)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--opponent", choices=("v14", "v18", "v100"), required=True)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--label", default="holdout")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    replay_dir = ROOT / "data/replays" / f"v106_{args.label}_{args.opponent}_{args.seed}"
    games = [
        _run(
            args.seed + offset,
            seat,
            enabled,
            args.opponent,
            replay_dir
            / f"{'candidate' if enabled else 'safe'}_seed_{args.seed + offset}_seat_{seat}.json",
        )
        for offset in range(args.pairs)
        for seat in (0, 1)
        for enabled in (False, True)
    ]
    summary = {
        mode: _mode_summary([game for game in games if game["mode"] == mode])
        for mode in ("safe-core", "candidate")
    }
    paired = []
    for seed in range(args.seed, args.seed + args.pairs):
        for seat in (0, 1):
            safe = next(
                game
                for game in games
                if game["seed"] == seed and game["seat"] == seat and game["mode"] == "safe-core"
            )
            candidate = next(
                game
                for game in games
                if game["seed"] == seed and game["seat"] == seat and game["mode"] == "candidate"
            )
            safe_replay = json.loads((ROOT / safe["replay"]).read_text(encoding="utf-8"))
            candidate_replay = json.loads((ROOT / candidate["replay"]).read_text(encoding="utf-8"))
            paired.append(
                {
                    "seed": seed,
                    "seat": seat,
                    "reward_delta_context": candidate["ours"] - safe["ours"],
                    "margin_delta_context": candidate["margin"] - safe["margin"],
                    "day15_productive_delta": (
                        candidate["trace"]["checkpoints"]["15"]["productive"]
                        - safe["trace"]["checkpoints"]["15"]["productive"]
                    ),
                    "day20_productive_delta": (
                        candidate["trace"]["checkpoints"]["20"]["productive"]
                        - safe["trace"]["checkpoints"]["20"]["productive"]
                    ),
                    "daily_activations": candidate["trace"]["daily_activations"],
                    "active_steps": candidate["trace"]["active_steps"],
                    "emergency_fallbacks": candidate["trace"]["emergency_fallbacks"],
                    "action_differences": _action_difference(
                        safe_replay, candidate_replay, candidate["seat"]
                    ),
                    "candidate_runtime_failures": candidate["runtime_failures"],
                }
            )
    result = {
        "created_at": datetime.now().astimezone().isoformat(),
        "format": "kaggriculture-v106-adaptive-diagnostic-v1",
        "agent": "agents/v106/main.py",
        "safe_core": "V106 daily recovery disabled (V11 targets/executor)",
        "opponent": {
            "v14": "independent agents/v14/main.py",
            "v18": "independent agents/v18/main.py with submitted gate enabled",
            "v100": "independent rejected agents/v100/main.py as state-coverage diagnostic",
        }[args.opponent],
        "purpose": "adaptive trajectory/safety diagnostic; opponent win rate is not a selection KPI",
        "configuration": {
            "pairs": args.pairs,
            "seed": args.seed,
            "label": args.label,
            "opponent": args.opponent,
        },
        "summary": summary,
        "paired_diagnostics": paired,
        "games": games,
    }
    output = args.output or ROOT / "data/runs" / f"v106_{args.label}_{args.opponent}_{args.seed}.json"
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": summary, "paired": paired}, ensure_ascii=False, indent=2))
    print(f"result: {output}")
    print(f"replays: {replay_dir}")


if __name__ == "__main__":
    main()
