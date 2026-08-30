"""Run paired V47 anti-reversal diagnostics in the official environment."""

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

from agents.v47 import main as v47  # noqa: E402
from scripts import analyze_v46_mission_continuity as mission  # noqa: E402
from scripts import run_v14_ablation as common  # noqa: E402

common.v14 = v47.v14


def _trace(replay: dict[str, Any], seat: int, seed: int) -> dict[str, float]:
    metrics = common._trace(replay, seat)
    rows = mission._side(
        replay,
        {
            "submission_seat": str(seat),
            "episode_id": f"local-{seed}-{seat}",
            "result": "unknown",
        },
        "v47",
    )
    for row in rows:
        rates = mission._rates(row)
        phase = row["phase"]
        for name in (
            "blocked_rate",
            "immediate_reverse_rate",
            "completion_3_rate",
            "completion_6_rate",
            "progress_rate",
            "regress_rate",
            "route_reverse_rate",
            "mean_route_excess",
        ):
            metrics[f"{phase}_{name}"] = rates[name]
    return metrics


def _run(seed: int, seat: int, opponent: str, path: Path) -> dict[str, Any]:
    env = make(
        "kaggriculture",
        configuration={"episodeSteps": 720, "seed": seed},
        debug=True,
    )
    env.run([v47.agent, opponent] if seat == 0 else [opponent, v47.agent])
    replay = env.toJSON()
    final = env.steps[-1]
    rewards = [float(state.reward or 0) for state in final]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")
    return {
        "seed": seed,
        "seat": seat,
        "ours": rewards[seat],
        "theirs": rewards[1 - seat],
        "margin": rewards[seat] - rewards[1 - seat],
        "statuses": [state.status for state in final],
        "metrics": _trace(replay, seat, seed),
        "replay": str(path.relative_to(ROOT)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("anti-reversal", "safe-core"), required=True)
    parser.add_argument("--pairs", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20264701)
    parser.add_argument("--opponent", default="starter")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--active-start", type=int, default=5)
    parser.add_argument("--active-end", type=int, default=15)
    parser.add_argument("--bonus", type=int, default=900)
    parser.add_argument(
        "--task-actions",
        default="ALL",
        help="comma-separated prior mission actions eligible for continuity, or ALL",
    )
    args = parser.parse_args()
    v47.ENABLE_ANTI_REVERSAL = args.mode == "anti-reversal"
    if not 0 <= args.active_start < args.active_end <= 30:
        parser.error("active window must satisfy 0 <= start < end <= 30")
    v47.ACTIVE_DAYS = range(args.active_start, args.active_end)
    v47.CONTINUITY_BONUS = args.bonus
    task_actions = {
        value.strip().upper()
        for value in args.task_actions.split(",")
        if value.strip()
    }
    v47.CONTINUITY_TASK_ACTIONS = (
        None if not task_actions or task_actions == {"ALL"} else frozenset(task_actions)
    )
    mission.PHASES = {
        f"active_{args.active_start}_{args.active_end - 1}": tuple(v47.ACTIVE_DAYS)
    }
    created_at = datetime.now().astimezone()
    run_id = created_at.strftime("%Y%m%d_%H%M%S_%z")
    replay_dir = ROOT / "data/replays" / f"{run_id}_v47_{args.mode}_ablation"
    games = [
        _run(
            args.seed + offset,
            seat,
            args.opponent,
            replay_dir / f"seed_{args.seed + offset}_seat_{seat}.json",
        )
        for offset in range(args.pairs)
        for seat in (0, 1)
    ]
    metric_names = tuple(games[0]["metrics"])
    summary = {
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
        },
        "diagnostics": {
            metric: mean(float(game["metrics"][metric]) for game in games)
            for metric in metric_names
        },
    }
    payload = {
        "created_at": created_at.isoformat(),
        "agent": "agents/v47/main.py",
        "mode": args.mode,
        "opponent": args.opponent,
        "configuration": {
            "pairs": args.pairs,
            "seed": args.seed,
            "episode_steps": 720,
            "phases": {name: list(days) for name, days in mission.PHASES.items()},
            "active_days": list(v47.ACTIVE_DAYS),
            "continuity_bonus": v47.CONTINUITY_BONUS,
            "continuity_task_actions": (
                sorted(v47.CONTINUITY_TASK_ACTIONS)
                if v47.CONTINUITY_TASK_ACTIONS is not None
                else ["ALL"]
            ),
        },
        "summary": summary,
        "games": games,
    }
    output = args.output or ROOT / "data/runs" / f"v47_ablation_{args.mode}_{args.seed}.json"
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"result: {output}")
    print(f"replays: {replay_dir}")


if __name__ == "__main__":
    main()
