"""Run paired V53 persistent FEED-mission diagnostics."""

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

from agents.v53 import main as v53  # noqa: E402
from scripts import run_v14_ablation as common  # noqa: E402
from scripts.analyze_v52_feed_missions import _day_row  # noqa: E402

common.v14 = v53.v14


def _mission_metrics(replay: dict[str, Any], seat: int, seed: int) -> dict[str, float]:
    rows = [
        row
        for day in v53.ACTIVE_DAYS
        if (
            row := _day_row(
                replay,
                {
                    "submission_seat": str(seat),
                    "episode_id": f"local-{seed}-{seat}",
                    "result": "unknown",
                },
                "v53",
                day,
            )
        )
        is not None
    ]
    return {
        "mission_pickup_events": sum(row["metrics"]["pickup_events"] for row in rows),
        "mission_no_feed_events": sum(row["metrics"]["no_feed_events"] for row in rows),
        "mission_passes_before_finish": sum(
            row["metrics"]["passes_before_finish"] for row in rows
        ),
        "mission_mean_first_feed_lag": mean(
            row["metrics"]["first_feed_lag"] for row in rows
        )
        if rows
        else 0.0,
        "mission_mean_route_excess": mean(
            row["metrics"]["first_route_excess"] for row in rows
        )
        if rows
        else 0.0,
    }


def _run(seed: int, seat: int, opponent: str, path: Path) -> dict[str, Any]:
    env = make(
        "kaggriculture",
        configuration={"episodeSteps": 720, "seed": seed},
        debug=True,
    )
    env.run([v53.agent, opponent] if seat == 0 else [opponent, v53.agent])
    replay = env.toJSON()
    final = env.steps[-1]
    rewards = [float(state.reward or 0) for state in final]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")
    metrics = common._trace(replay, seat)
    metrics.update(_mission_metrics(replay, seat, seed))
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
    parser.add_argument("--mode", choices=("missions", "safe-core"), required=True)
    parser.add_argument("--pairs", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20265301)
    parser.add_argument("--opponent", default="starter")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    v53.ENABLE_FEED_MISSIONS = args.mode == "missions"
    created_at = datetime.now().astimezone()
    run_id = created_at.strftime("%Y%m%d_%H%M%S_%z")
    replay_dir = ROOT / "data/replays" / f"{run_id}_v53_{args.mode}_ablation"
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
        "agent": "agents/v53/main.py",
        "mode": args.mode,
        "opponent": args.opponent,
        "configuration": {
            "pairs": args.pairs,
            "seed": args.seed,
            "episode_steps": 720,
            "active_days": list(v53.ACTIVE_DAYS),
        },
        "summary": summary,
        "games": games,
    }
    output = args.output or ROOT / "data/runs" / f"v53_ablation_{args.mode}_{args.seed}.json"
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"result: {output}")
    print(f"replays: {replay_dir}")


if __name__ == "__main__":
    main()
