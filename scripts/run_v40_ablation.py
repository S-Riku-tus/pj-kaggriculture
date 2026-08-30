"""Run paired V40 late-Cow completion diagnostics in the official environment."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kaggle_environments import make  # noqa: E402

from agents.v40 import main as v40  # noqa: E402
from scripts import run_v14_ablation as common  # noqa: E402

common.v14 = v40.v14


def _cow_state(obs: dict[str, Any], seat: int) -> tuple[int, int]:
    farms = obs.get("farms") or []
    player = int(obs.get("player", seat))
    farm = farms[player] if 0 <= player < len(farms) else {}
    placed = sum(
        isinstance(tile, dict) and tile.get("animal") == "COW"
        for row in farm.get("tiles") or []
        for tile in row
    )
    private = obs.get("private") or {}
    pending = int((private.get("shed") or {}).get("COW", 0) or 0) + sum(
        int((inventory or {}).get("COW", 0) or 0)
        for inventory in private.get("inventories") or []
    )
    return placed, pending


def _trace(replay: dict[str, Any], seat: int) -> dict[str, float]:
    metrics = common._trace(replay, seat)
    late_actions: Counter[str] = Counter()
    snapshots: dict[int, tuple[int, int]] = {}
    for states in replay.get("steps") or []:
        state = states[seat]
        obs = state.get("observation") or {}
        day = int(obs.get("day", 0) or 0)
        hour = int(obs.get("hour", 0) or 0)
        if hour == 0 and day in {7, 9}:
            snapshots[day] = _cow_state(obs, seat)
        if day not in v40.COMPLETION_DAYS or hour < v40.COMPLETION_START_HOUR:
            continue
        action = state.get("action") or {}
        actions = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
        for unit_action in actions:
            op = str(unit_action[0]) if unit_action else "PASS"
            item = str(unit_action[1]) if len(unit_action) >= 2 else ""
            if item == "COW" and op in {"PICKUP", "PLACE"}:
                late_actions[op] += 1
    metrics.update(
        {
            "late_cow_pickup": float(late_actions["PICKUP"]),
            "late_cow_place": float(late_actions["PLACE"]),
            "day7_placed_cows": float(snapshots.get(7, (0, 0))[0]),
            "day7_pending_cows": float(snapshots.get(7, (0, 0))[1]),
            "day9_placed_cows": float(snapshots.get(9, (0, 0))[0]),
            "day9_pending_cows": float(snapshots.get(9, (0, 0))[1]),
        }
    )
    return metrics


def _run(seed: int, seat: int, opponent: str, replay_path: Path) -> dict[str, Any]:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=True)
    agents = [v40.agent, opponent] if seat == 0 else [opponent, v40.agent]
    env.run(agents)
    replay = env.toJSON()
    final = env.steps[-1]
    rewards = [float(state.reward or 0) for state in final]
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    replay_path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")
    return {
        "seed": seed,
        "seat": seat,
        "ours": rewards[seat],
        "theirs": rewards[1 - seat],
        "margin": rewards[seat] - rewards[1 - seat],
        "statuses": [state.status for state in final],
        "metrics": _trace(replay, seat),
        "replay": str(replay_path.relative_to(ROOT)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("late-cow", "safe-core"), required=True)
    parser.add_argument("--pairs", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20264001)
    parser.add_argument("--opponent", default="starter")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    v40.ENABLE_LATE_COW_COMPLETION = args.mode == "late-cow"
    created_at = datetime.now().astimezone()
    run_id = created_at.strftime("%Y%m%d_%H%M%S_%z")
    replay_dir = ROOT / "data/replays" / f"{run_id}_v40_{args.mode}_ablation"
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
        "agent": "agents/v40/main.py",
        "mode": args.mode,
        "opponent": args.opponent,
        "configuration": {"pairs": args.pairs, "seed": args.seed, "episode_steps": 720},
        "summary": summary,
        "games": games,
    }
    output = args.output or ROOT / "data/runs" / f"v40_ablation_{args.mode}_{args.seed}.json"
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"result: {output}")
    print(f"replays: {replay_dir}")


if __name__ == "__main__":
    main()
