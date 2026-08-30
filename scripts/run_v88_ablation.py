"""Run paired V88 task-goal versus exact V14-safe-core diagnostics."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kaggle_environments import make  # noqa: E402

from agents.v88 import main as v88  # noqa: E402
from scripts import run_v14_ablation as common  # noqa: E402

common.v14 = v88.v14


def _run(mode: str, seed: int, seat: int, opponent: str, path: Path) -> dict[str, Any]:
    v88.ENABLE_TASK_GOALS = mode == "task-goal"
    v88.reset_runtime_counts()
    env = make(
        "kaggriculture",
        configuration={"episodeSteps": 720, "seed": seed},
        debug=True,
    )
    env.run([v88.agent, opponent] if seat == 0 else [opponent, v88.agent])
    replay = env.toJSON()
    final = env.steps[-1]
    rewards = [float(state.reward or 0) for state in final]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")
    metrics = common._trace(replay, seat)
    metrics.update({key: float(value) for key, value in v88.RUNTIME_COUNTS.items()})
    return {
        "mode": mode,
        "seed": seed,
        "seat": seat,
        "ours": rewards[seat],
        "theirs": rewards[1 - seat],
        "margin": rewards[seat] - rewards[1 - seat],
        "statuses": [state.status for state in final],
        "metrics": metrics,
        "replay": str(path.relative_to(ROOT)),
    }


def _summary(games: list[dict[str, Any]]) -> dict[str, Any]:
    metric_names = tuple(games[0]["metrics"])
    return {
        "games": len(games),
        "all_done": all(game["statuses"] == ["DONE", "DONE"] for game in games),
        "reward": {
            "mean": mean(game["ours"] for game in games),
            "p10": common._percentile([game["ours"] for game in games], 0.10),
            "minimum": min(game["ours"] for game in games),
        },
        "margin": {
            "mean": mean(game["margin"] for game in games),
            "p10": common._percentile([game["margin"] for game in games], 0.10),
            "minimum": min(game["margin"] for game in games),
        },
        "diagnostics": {metric: mean(float(game["metrics"][metric]) for game in games) for metric in metric_names},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20268801)
    parser.add_argument("--opponent", default="starter")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    created_at = datetime.now().astimezone()
    run_id = created_at.strftime("%Y%m%d_%H%M%S_%z")
    replay_dir = ROOT / "data/replays" / f"{run_id}_v88_ablation"
    games = [
        _run(
            mode,
            args.seed + offset,
            seat,
            args.opponent,
            replay_dir / mode / f"seed_{args.seed + offset}_seat_{seat}.json",
        )
        for mode in ("safe-core", "task-goal")
        for offset in range(args.pairs)
        for seat in (0, 1)
    ]
    by_mode = {mode: [game for game in games if game["mode"] == mode] for mode in ("safe-core", "task-goal")}
    paired = []
    safe_lookup = {(game["seed"], game["seat"]): game for game in by_mode["safe-core"]}
    for game in by_mode["task-goal"]:
        safe = safe_lookup[(game["seed"], game["seat"])]
        paired.append(
            {
                "seed": game["seed"],
                "seat": game["seat"],
                "reward_delta": game["ours"] - safe["ours"],
                "margin_delta": game["margin"] - safe["margin"],
                "move_delta": game["metrics"]["move"] - safe["metrics"]["move"],
                "pass_delta": game["metrics"]["pass"] - safe["metrics"]["pass"],
                "water_delta": game["metrics"]["water"] - safe["metrics"]["water"],
                "feed_delta": game["metrics"]["feed"] - safe["metrics"]["feed"],
                "harvest_delta": game["metrics"]["harvest"] - safe["metrics"]["harvest"],
            }
        )
    summaries = {mode: _summary(local) for mode, local in by_mode.items()}
    summaries["paired_delta"] = {
        key: mean(float(row[key]) for row in paired)
        for key in (
            "reward_delta",
            "margin_delta",
            "move_delta",
            "pass_delta",
            "water_delta",
            "feed_delta",
            "harvest_delta",
        )
    }
    payload = {
        "created_at": created_at.isoformat(),
        "agent": "agents/v88/main.py",
        "opponent": args.opponent,
        "configuration": {
            "pairs": args.pairs,
            "seed": args.seed,
            "episode_steps": 720,
            "minimum_probability": v88.MIN_GOAL_PROBABILITY,
            "task_goal_bonus": v88.TASK_GOAL_BONUS,
        },
        "summary": summaries,
        "paired": paired,
        "games": games,
    }
    output = args.output or ROOT / "data/runs" / f"v88_ablation_{args.seed}.json"
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    print(f"result: {output}")
    print(f"replays: {replay_dir}")


if __name__ == "__main__":
    main()
