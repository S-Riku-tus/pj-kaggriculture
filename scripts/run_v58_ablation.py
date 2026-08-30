"""Run paired V58 learned daily-role continuity diagnostics."""

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

from agents.v58 import main as v58  # noqa: E402
from scripts import run_v54_ablation as runner  # noqa: E402
from scripts.analyze_v56_daily_roles import _day_row  # noqa: E402
from scripts.train_v12_relative_policy import _observation  # noqa: E402

runner.v54 = v58
runner.common.v14 = v58.v14


def _role_metrics(replay: dict[str, Any], seat: int, seed: int) -> dict[str, float]:
    rows = [
        row
        for day in v58.ACTIVE_DAYS
        if (
            row := _day_row(
                replay,
                {
                    "submission_seat": str(seat),
                    "episode_id": f"local-{seed}-{seat}",
                    "result": "unknown",
                },
                "v58",
                day,
            )
        )
        is not None
    ]
    reasons: Counter[str] = Counter()
    for day in v58.ACTIVE_DAYS:
        obs = _observation(replay, day * 24, seat)
        if obs is None:
            continue
        safe = v58.base._safe_observation(obs)
        if safe is not None:
            reasons[v58._predict(obs, safe[0], safe[1])["reason"]] += 1
    return {
        "role_active_days": float(reasons["active"]),
        "role_ood_days": float(reasons["ood"]),
        "role_low_target_days": float(reasons["low-continuity-target"]),
        "role_same_transition_rate": mean(
            row["metrics"]["same_role_transition_rate"] for row in rows
        )
        if rows
        else 0.0,
        "role_productive_per_hand": mean(
            row["metrics"]["productive_per_hand"] for row in rows
        )
        if rows
        else 0.0,
        "role_move_per_productive": mean(
            row["metrics"]["move_per_productive"] for row in rows
        )
        if rows
        else 0.0,
        "role_pass_per_hand": mean(row["metrics"]["pass_per_hand"] for row in rows)
        if rows
        else 0.0,
    }


def _run(seed: int, seat: int, opponent: str, path: Path) -> dict[str, Any]:
    game = runner._run(seed, seat, opponent, path)
    replay = json.loads(path.read_text(encoding="utf-8"))
    game["metrics"].update(_role_metrics(replay, seat, seed))
    return game


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("roles", "safe-core"), required=True)
    parser.add_argument(
        "--role-scope",
        choices=("both", "animal", "crop"),
        default="both",
    )
    parser.add_argument("--pairs", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20265801)
    parser.add_argument("--opponent", default="starter")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--active-days",
        default="6,7,8,9,10,11,12",
        help="comma-separated days on which the learned tie-break may run",
    )
    parser.add_argument(
        "--role-score-bonus",
        type=int,
        default=1,
        help="assignment priority points awarded for continuing the same role",
    )
    args = parser.parse_args()
    active_days = tuple(
        sorted({int(value) for value in args.active_days.split(",") if value.strip()})
    )
    if not active_days or any(day < 0 or day > 29 for day in active_days):
        parser.error("--active-days must contain game days in [0, 29]")
    v58.ACTIVE_DAYS = active_days
    if args.role_score_bonus < 0:
        parser.error("--role-score-bonus must be nonnegative")
    v58.ROLE_SCORE_BONUS = args.role_score_bonus
    v58.ENABLE_ROLE_CONTINUITY = args.mode == "roles"
    v58.ROLE_TYPES = {
        "both": {"ANIMAL", "CROP"},
        "animal": {"ANIMAL"},
        "crop": {"CROP"},
    }[args.role_scope]
    created_at = datetime.now().astimezone()
    run_id = created_at.strftime("%Y%m%d_%H%M%S_%z")
    replay_dir = ROOT / "data/replays" / f"{run_id}_v58_{args.mode}_ablation"
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
            "p10": runner.common._percentile([game["ours"] for game in games], 0.10),
            "minimum": min(game["ours"] for game in games),
        },
        "margin": {
            "mean": mean(game["margin"] for game in games),
            "p10": runner.common._percentile([game["margin"] for game in games], 0.10),
        },
        "diagnostics": {
            metric: mean(float(game["metrics"][metric]) for game in games)
            for metric in metric_names
        },
    }
    payload = {
        "created_at": created_at.isoformat(),
        "agent": "agents/v58/main.py",
        "mode": args.mode,
        "opponent": args.opponent,
        "configuration": {
            "pairs": args.pairs,
            "seed": args.seed,
            "episode_steps": 720,
            "active_days": list(active_days),
            "minimum_same_role_target": v58.MIN_SAME_ROLE_TARGET,
            "role_score_bonus": v58.ROLE_SCORE_BONUS,
            "role_scope": args.role_scope,
        },
        "summary": summary,
        "games": games,
    }
    output = args.output or ROOT / "data/runs" / f"v58_ablation_{args.mode}_{args.seed}.json"
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"result: {output}")
    print(f"replays: {replay_dir}")


if __name__ == "__main__":
    main()
