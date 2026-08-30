"""Locate the first V21/V14 divergence and summarize downstream state drift."""

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

from agents.v14 import main as v14  # noqa: E402

MOVEMENT = {"NORTH", "SOUTH", "EAST", "WEST"}


def _farm(obs: dict[str, Any], seat: int) -> dict[str, Any]:
    farms = obs.get("farms") or []
    player = int(obs.get("player", seat))
    return farms[player] if 0 <= player < len(farms) else {}


def _state(obs: dict[str, Any], seat: int) -> dict[str, Any]:
    farm = _farm(obs, seat)
    private = obs.get("private") or {}
    crops: Counter[str] = Counter()
    animals: Counter[str] = Counter()
    risk = 0
    for _x, _y, tile in v14.base._iter_tiles(farm):
        crop = v14.base._get(tile, "crop")
        animal = v14.base._get(tile, "animal")
        if crop:
            crops[str(crop)] += 1
            risk += v14.base._as_int(v14.base._get(tile, "consecutive_unwatered", 0)) >= 1
        if animal:
            animals[str(animal)] += 1
    return {
        "money": v14.base._as_int(v14.base._get(farm, "money", 0)),
        "hands": len(v14.base._get(farm, "hands", []) or []),
        "crops": dict(crops),
        "animals": dict(animals),
        "water_risk": risk,
        "shed": dict(private.get("shed") or {}),
        "seeds": dict(private.get("seeds") or {}),
    }


def _delta(left: Any, right: Any) -> Any:
    if isinstance(left, dict) and isinstance(right, dict):
        return {
            key: value
            for key in sorted(set(left) | set(right))
            if (value := _delta(left.get(key, 0), right.get(key, 0))) not in (0, {}, None)
        }
    if isinstance(left, int | float) and isinstance(right, int | float):
        return right - left
    return None if left == right else {"safe": left, "candidate": right}


def _units(action: dict[str, Any]) -> list[list[Any]]:
    return [list(action.get("farmer") or ["PASS"]), *[list(x or ["PASS"]) for x in action.get("hands") or []]]


def _compare_game(safe_game: dict[str, Any], candidate_game: dict[str, Any]) -> dict[str, Any]:
    seat = int(safe_game["seat"])
    safe = json.loads((ROOT / safe_game["replay"]).read_text(encoding="utf-8"))
    candidate = json.loads((ROOT / candidate_game["replay"]).read_text(encoding="utf-8"))
    changes: Counter[str] = Counter()
    divergences = []
    steps = min(len(safe.get("steps") or []), len(candidate.get("steps") or []))
    for recorded_step in range(1, steps):
        safe_units = _units(safe["steps"][recorded_step][seat].get("action") or {})
        candidate_units = _units(candidate["steps"][recorded_step][seat].get("action") or {})
        previous_obs = safe["steps"][recorded_step - 1][seat].get("observation") or {}
        for unit in range(max(len(safe_units), len(candidate_units))):
            left = safe_units[unit] if unit < len(safe_units) else ["MISSING"]
            right = candidate_units[unit] if unit < len(candidate_units) else ["MISSING"]
            if left == right:
                continue
            left_op = str(left[0]) if left else "PASS"
            right_op = str(right[0]) if right else "PASS"
            changes[f"{left_op}->{right_op}"] += 1
            if len(divergences) < 40:
                divergences.append(
                    {
                        "decision_step": recorded_step - 1,
                        "day": int(previous_obs.get("day", 0) or 0),
                        "hour": int(previous_obs.get("hour", 0) or 0),
                        "unit": unit,
                        "safe": left,
                        "candidate": right,
                    }
                )
    daily = []
    for day in range(30):
        step = day * 24
        if step >= steps:
            break
        safe_obs = safe["steps"][step][seat].get("observation") or {}
        candidate_obs = candidate["steps"][step][seat].get("observation") or {}
        state_delta = _delta(_state(safe_obs, seat), _state(candidate_obs, seat))
        if state_delta:
            daily.append({"day": day, "delta_candidate_minus_safe": state_delta})
    return {
        "seed": int(safe_game["seed"]),
        "seat": seat,
        "reward": {
            "safe": float(safe_game["ours"]),
            "candidate": float(candidate_game["ours"]),
            "delta": float(candidate_game["ours"]) - float(safe_game["ours"]),
        },
        "first_divergence": divergences[0] if divergences else None,
        "action_change_counts": dict(changes),
        "sample_divergences": divergences,
        "daily_state_deltas": daily,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--safe", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("data/analysis/v21_closed_loop_diagnosis.json")
    )
    args = parser.parse_args()
    safe = json.loads((args.safe if args.safe.is_absolute() else ROOT / args.safe).read_text(encoding="utf-8"))
    candidate = json.loads(
        (args.candidate if args.candidate.is_absolute() else ROOT / args.candidate).read_text(encoding="utf-8")
    )
    games = [
        _compare_game(left, right)
        for left, right in zip(safe["games"], candidate["games"], strict=True)
        if float(left["ours"]) != float(right["ours"])
    ]
    payload = {
        "format": "kaggriculture-v21-closed-loop-diagnosis-v1",
        "comparison": "candidate minus safe core",
        "games": games,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
