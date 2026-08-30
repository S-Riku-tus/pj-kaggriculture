"""Run paired V49 loaded-worker preposition diagnostics."""

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

from agents.v49 import main as v49  # noqa: E402
from scripts import run_v14_ablation as common  # noqa: E402
from scripts.analyze_v33_asset_labor import _actions  # noqa: E402
from scripts.analyze_v46_mission_continuity import PHASES, _rates, _side  # noqa: E402

common.v14 = v49.v14


def _loaded_pipeline(replay: dict[str, Any], seat: int) -> dict[str, float]:
    counts: Counter[str] = Counter()
    steps = replay.get("steps") or []
    for step in range(min(len(steps) - 1, 13 * 24)):
        state = steps[step][seat]
        obs = state.get("observation") or {}
        day = int(obs.get("day", -1) or -1)
        if day not in range(6, 13):
            continue
        private = obs.get("private") or {}
        inventories = list(private.get("inventories") or [])
        actions = _actions(replay, step, seat)
        for unit in range(1, min(len(actions), len(inventories))):
            inventory = inventories[unit]
            loaded = v49.base._inventory_total(inventory) > 0
            if not loaded:
                continue
            counts["loaded_turns"] += 1
            op = str(actions[unit][0]) if actions[unit] else "PASS"
            counts[f"loaded_{op.lower()}"] += 1
            if op == "PASS":
                counts["loaded_pass"] += 1
            elif op in {"NORTH", "SOUTH", "EAST", "WEST"}:
                counts["loaded_move"] += 1
            else:
                counts["loaded_productive"] += 1
    turns = max(1, counts["loaded_turns"])
    return {
        "loaded_turns": float(counts["loaded_turns"]),
        "loaded_pass": float(counts["loaded_pass"]),
        "loaded_move": float(counts["loaded_move"]),
        "loaded_productive": float(counts["loaded_productive"]),
        "loaded_pass_rate": counts["loaded_pass"] / turns,
        "loaded_move_rate": counts["loaded_move"] / turns,
        "loaded_productive_rate": counts["loaded_productive"] / turns,
    }


def _trace(replay: dict[str, Any], seat: int, seed: int) -> dict[str, float]:
    metrics = common._trace(replay, seat)
    metrics.update(_loaded_pipeline(replay, seat))
    rows = _side(
        replay,
        {
            "submission_seat": str(seat),
            "episode_id": f"local-{seed}-{seat}",
            "result": "unknown",
        },
        "v49",
    )
    for row in rows:
        rates = _rates(row)
        phase = row["phase"]
        for name in (
            "immediate_reverse_rate",
            "completion_3_rate",
            "completion_6_rate",
            "regress_rate",
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
    env.run([v49.agent, opponent] if seat == 0 else [opponent, v49.agent])
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
    parser.add_argument("--mode", choices=("loaded", "safe-core"), required=True)
    parser.add_argument("--pairs", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20264901)
    parser.add_argument("--opponent", default="starter")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    v49.ENABLE_LOADED_PREPOSITION = args.mode == "loaded"
    created_at = datetime.now().astimezone()
    run_id = created_at.strftime("%Y%m%d_%H%M%S_%z")
    replay_dir = ROOT / "data/replays" / f"{run_id}_v49_{args.mode}_ablation"
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
        "agent": "agents/v49/main.py",
        "mode": args.mode,
        "opponent": args.opponent,
        "configuration": {
            "pairs": args.pairs,
            "seed": args.seed,
            "episode_steps": 720,
            "active_days": list(v49.ACTIVE_DAYS),
            "minimum_confidence": v49.MIN_CONFIDENCE,
            "phases": {name: list(days) for name, days in PHASES.items()},
        },
        "summary": summary,
        "games": games,
    }
    output = args.output or ROOT / "data/runs" / f"v49_ablation_{args.mode}_{args.seed}.json"
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"result: {output}")
    print(f"replays: {replay_dir}")


if __name__ == "__main__":
    main()
