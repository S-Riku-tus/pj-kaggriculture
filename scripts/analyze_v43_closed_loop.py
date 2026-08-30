"""Diagnose positive and negative V43 closed-loop branches."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v3.feature_schema import demand_profile, farm_summary  # noqa: E402

FORMAT = "kaggriculture-v43-closed-loop-diagnosis-v1"
SNAPSHOT_DAYS = (5, 6, 9, 11, 14, 20)


def _obs(replay: dict[str, Any], step: int, seat: int) -> dict[str, Any]:
    steps = replay.get("steps") or []
    if not 0 <= step < len(steps):
        return {}
    return steps[step][seat].get("observation") or {}


def _farm(obs: dict[str, Any], seat: int) -> dict[str, Any]:
    farms = obs.get("farms") or []
    player = int(obs.get("player", seat))
    return farms[player] if 0 <= player < len(farms) else {}


def _actions(replay: dict[str, Any], stored_step: int, seat: int) -> list[list[Any]]:
    steps = replay.get("steps") or []
    if not 0 <= stored_step < len(steps):
        return []
    action = steps[stored_step][seat].get("action") or {}
    return [list(action.get("farmer") or ["PASS"]), *(action.get("hands") or [])]


def _snapshot(replay: dict[str, Any], seat: int, day: int) -> dict[str, Any]:
    obs = _obs(replay, day * 24, seat)
    farm = _farm(obs, seat)
    summary = farm_summary(farm, day)
    private = obs.get("private") or {}
    return {
        "money": float(farm.get("money", 0) or 0),
        "cows": int(summary["animals"].get("COW", 0)),
        "sheep": int(summary["animals"].get("SHEEP", 0)),
        "crops": dict(summary["crops"]),
        "productive": int(summary["productive"]),
        "empty_pastures": int(summary["empty_structures"]),
        "pending_cows": int((private.get("shed") or {}).get("COW", 0) or 0)
        + sum(
            int((inventory or {}).get("COW", 0) or 0)
            for inventory in private.get("inventories") or []
        ),
        "unwatered": sum(
            isinstance(tile, dict)
            and tile.get("kind") == "PLANT"
            and int(tile.get("consecutive_unwatered", 0) or 0) >= 1
            for row in farm.get("tiles") or []
            for tile in row
        ),
        "shed_products": sum(
            int(value or 0)
            for item, value in (private.get("shed") or {}).items()
            if item not in {"COW", "SHEEP", "GOOSE"}
        ),
    }


def _first_divergence(
    safe: dict[str, Any], candidate: dict[str, Any], seat: int
) -> dict[str, Any] | None:
    limit = min(len(safe.get("steps") or []), len(candidate.get("steps") or []))
    for stored in range(1, limit):
        left = _actions(safe, stored, seat)
        right = _actions(candidate, stored, seat)
        if left == right:
            continue
        obs = _obs(safe, stored - 1, seat)
        for unit, (before, after) in enumerate(zip(left, right, strict=False)):
            if before != after:
                return {
                    "decision_step": stored - 1,
                    "day": int(obs.get("day", 0) or 0),
                    "hour": int(obs.get("hour", 0) or 0),
                    "unit": unit,
                    "safe": before,
                    "candidate": after,
                }
    return None


def _action_changes(
    safe: dict[str, Any], candidate: dict[str, Any], seat: int
) -> dict[str, int]:
    result: Counter[str] = Counter()
    limit = min(len(safe.get("steps") or []), len(candidate.get("steps") or []))
    for stored in range(1, limit):
        for before, after in zip(
            _actions(safe, stored, seat),
            _actions(candidate, stored, seat),
            strict=False,
        ):
            if before != after:
                result[f"{before[0]}->{after[0]}"] += 1
    return dict(result)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--safe-run",
        type=Path,
        default=Path("data/runs/v43_ablation_safe-core_20264301.json"),
    )
    parser.add_argument(
        "--candidate-run",
        type=Path,
        default=Path("data/runs/v43_ablation_ne-core_20264301.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v43_closed_loop_diagnosis.json"),
    )
    args = parser.parse_args()
    safe_run_path = args.safe_run if args.safe_run.is_absolute() else ROOT / args.safe_run
    candidate_run_path = (
        args.candidate_run if args.candidate_run.is_absolute() else ROOT / args.candidate_run
    )
    safe_run = json.loads(safe_run_path.read_text(encoding="utf-8"))
    candidate_run = json.loads(candidate_run_path.read_text(encoding="utf-8"))
    games = []
    for safe_game, candidate_game in zip(
        safe_run["games"], candidate_run["games"], strict=True
    ):
        if (safe_game["seed"], safe_game["seat"]) != (
            candidate_game["seed"],
            candidate_game["seat"],
        ):
            raise ValueError("run pairing mismatch")
        seat = int(safe_game["seat"])
        safe_replay = json.loads((ROOT / safe_game["replay"]).read_text(encoding="utf-8"))
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
                    "shops": list((day5.get("town") or {}).get("unlocked_shops") or []),
                },
                "first_divergence": _first_divergence(safe_replay, candidate_replay, seat),
                "action_change_counts": _action_changes(safe_replay, candidate_replay, seat),
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
        "comparison": "V43 candidate minus V14 safe core",
        "games": games,
        "interpretation_limits": [
            "ten paired starter games diagnose path dependence but do not estimate leaderboard rating",
            "Day-5 demand, prices, and shops are public context rather than causal moderators",
            "snapshot deltas mix direct geometry effects with all downstream feedback",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
