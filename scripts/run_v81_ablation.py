"""Run paired V81 late decay-harvest diagnostics."""

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

from agents.v81 import main as v81  # noqa: E402
from scripts import run_v14_ablation as common  # noqa: E402
from scripts.analyze_v33_asset_labor import _farm  # noqa: E402
from scripts.train_v12_relative_policy import _observation  # noqa: E402

common.v14 = v81.v14


def _decay_metrics(replay: dict[str, Any], seat: int) -> dict[str, float]:
    tiles = 0
    units = 0
    for day in sorted(v81.ACTIVE_DAYS):
        obs = _observation(replay, day * 24, seat)
        if obs is None:
            continue
        farm = _farm(obs, seat)
        for _x, _y, tile in v81.base._iter_tiles(farm):
            if v81.base._tile_kind(tile) != "PLANT":
                continue
            lifespan = v81.base._as_int(
                v81.base._get(tile, "max_lifespan_step", -1), -1
            )
            held = max(0, v81.base._as_int(v81.base._get(tile, "yield_units", 0)))
            if lifespan >= 0 and day * 24 >= lifespan and held > 0:
                tiles += 1
                units += held
    return {
        "late_decaying_tiles": float(tiles),
        "late_decaying_units": float(units),
    }


def _run(seed: int, seat: int, opponent: str, path: Path) -> dict[str, Any]:
    env = make(
        "kaggriculture",
        configuration={"episodeSteps": 720, "seed": seed},
        debug=True,
    )
    env.run([v81.agent, opponent] if seat == 0 else [opponent, v81.agent])
    replay = env.toJSON()
    final = env.steps[-1]
    rewards = [float(state.reward or 0) for state in final]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")
    metrics = common._trace(replay, seat)
    metrics.update(_decay_metrics(replay, seat))
    return {
        "seed": seed,
        "seat": seat,
        "ours": rewards[seat],
        "theirs": rewards[1 - seat],
        "margin": rewards[seat] - rewards[1 - seat],
        "statuses": [state.status for state in final],
        "metrics": metrics,
        "replay": str(path.relative_to(ROOT)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("decay-harvest", "safe-core"), required=True)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20268101)
    parser.add_argument("--opponent", default="starter")
    parser.add_argument(
        "--existing-priority",
        choices=("raise", "keep"),
        default="raise",
        help="whether already-existing decaying HARVEST tasks are reprioritized",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    v81.ENABLE_DECAY_HARVEST = args.mode == "decay-harvest"
    v81.RAISE_EXISTING_DECAY_HARVEST = args.existing_priority == "raise"
    created_at = datetime.now().astimezone()
    run_id = created_at.strftime("%Y%m%d_%H%M%S_%z")
    replay_dir = ROOT / "data/replays" / f"{run_id}_v81_{args.mode}_ablation"
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
        "agent": "agents/v81/main.py",
        "mode": args.mode,
        "opponent": args.opponent,
        "configuration": {
            "pairs": args.pairs,
            "seed": args.seed,
            "episode_steps": 720,
            "active_days": sorted(v81.ACTIVE_DAYS),
            "priority": v81.DECAY_HARVEST_PRIORITY,
            "existing_priority": args.existing_priority,
        },
        "summary": summary,
        "games": games,
    }
    output = args.output or ROOT / "data/runs" / f"v81_ablation_{args.mode}_{args.seed}.json"
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"result: {output}")
    print(f"replays: {replay_dir}")


if __name__ == "__main__":
    main()
