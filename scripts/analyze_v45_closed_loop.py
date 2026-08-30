"""Diagnose matched V45 staged-expansion closed-loop branches."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v3.feature_schema import demand_profile  # noqa: E402
from scripts.analyze_v43_closed_loop import (  # noqa: E402
    _action_changes,
    _first_divergence,
    _obs,
    _snapshot,
)

FORMAT = "kaggriculture-v45-closed-loop-diagnosis-v1"
SNAPSHOT_DAYS = (5, 6, 7, 8, 9, 11, 14, 20)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--safe-run",
        type=Path,
        default=Path("data/runs/v45_ablation_safe-core_20264501.json"),
    )
    parser.add_argument(
        "--candidate-run",
        type=Path,
        default=Path("data/runs/v45_ablation_staged_20264501.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v45_closed_loop_diagnosis.json"),
    )
    args = parser.parse_args()
    safe_path = args.safe_run if args.safe_run.is_absolute() else ROOT / args.safe_run
    candidate_path = (
        args.candidate_run
        if args.candidate_run.is_absolute()
        else ROOT / args.candidate_run
    )
    safe_run = json.loads(safe_path.read_text(encoding="utf-8"))
    candidate_run = json.loads(candidate_path.read_text(encoding="utf-8"))
    games = []
    for safe_game, candidate_game in zip(
        safe_run["games"], candidate_run["games"], strict=True
    ):
        identity = (safe_game["seed"], safe_game["seat"])
        if identity != (candidate_game["seed"], candidate_game["seat"]):
            raise ValueError("run pairing mismatch")
        seat = int(safe_game["seat"])
        safe_replay = json.loads(
            (ROOT / safe_game["replay"]).read_text(encoding="utf-8")
        )
        candidate_replay = json.loads(
            (ROOT / candidate_game["replay"]).read_text(encoding="utf-8")
        )
        day5 = _obs(safe_replay, 5 * 24, seat)
        games.append(
            {
                "seed": safe_game["seed"],
                "seat": seat,
                "reward": {
                    "safe": safe_game["ours"],
                    "candidate": candidate_game["ours"],
                    "delta": candidate_game["ours"] - safe_game["ours"],
                },
                "day5_public": {
                    "demand": demand_profile(day5),
                    "prices": dict((day5.get("market") or {}).get("prices") or {}),
                    "shops": list(
                        (day5.get("town") or {}).get("unlocked_shops") or []
                    ),
                },
                "first_divergence": _first_divergence(
                    safe_replay, candidate_replay, seat
                ),
                "action_change_counts": _action_changes(
                    safe_replay, candidate_replay, seat
                ),
                "snapshots": {
                    str(day): {
                        "safe": _snapshot(safe_replay, seat, day),
                        "candidate": _snapshot(candidate_replay, seat, day),
                    }
                    for day in SNAPSHOT_DAYS
                },
            }
        )
    payload = {
        "format": FORMAT,
        "runtime_policy_enabled": False,
        "comparison": "V45 staged expansion minus V14 safe core",
        "games": games,
        "interpretation_limits": [
            "ten paired starter games diagnose path dependence but do not estimate leaderboard rating",
            "shop-conditioned deltas are hypothesis generation, not a validated runtime gate",
            "snapshot deltas include all downstream closed-loop feedback",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"games": len(games)}, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
