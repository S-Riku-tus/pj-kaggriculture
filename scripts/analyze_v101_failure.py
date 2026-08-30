"""Trace the first divergence and failure cascade in V101 calibration."""

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

from agents.v101 import main as v101  # noqa: E402

ANIMALS = ("COW", "SHEEP", "GOOSE")
CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
FAILURE_STATUSES = {"ERROR", "INVALID", "TIMEOUT"}


def _runtime_failures(replay: dict[str, Any], seat: int) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    previous: str | None = None
    for index, states in enumerate(replay.get("steps") or []):
        status = str(states[seat].get("status") or "")
        if status in FAILURE_STATUSES and status != previous:
            obs = states[seat].get("observation") or {}
            failures.append(
                {
                    "state_index": index,
                    "status": status,
                    "day": int(obs.get("day", 0) or 0),
                    "hour": int(obs.get("hour", 0) or 0),
                }
            )
        previous = status
    return failures


def _snapshot(obs: dict[str, Any], seat: int) -> dict[str, Any]:
    farm = obs["farms"][seat]
    crops: Counter[str] = Counter()
    animals: Counter[str] = Counter()
    unfed: Counter[str] = Counter()
    unwatered = 0
    for row in farm.get("tiles") or []:
        for tile in row:
            if not isinstance(tile, dict):
                continue
            if tile.get("kind") == "PLANT":
                crops[str(tile.get("crop"))] += 1
                unwatered += int(tile.get("consecutive_unwatered", 0) or 0) > 0
            animal = str(tile.get("animal") or "")
            if animal:
                animals[animal] += 1
                unfed[animal] += int(tile.get("consecutive_unfed", 0) or 0) > 0
    return {
        "money": float(farm.get("money", 0) or 0),
        "crops": {crop: crops[crop] for crop in CROPS},
        "animals": {animal: animals[animal] for animal in ANIMALS},
        "unfed": {animal: unfed[animal] for animal in ANIMALS},
        "unwatered": unwatered,
        "productive": sum(crops.values()) + sum(animals.values()),
    }


def _action_ops(replay: dict[str, Any], seat: int, start_day: int, end_day: int) -> Counter[str]:
    result: Counter[str] = Counter()
    previous_obs: dict[str, Any] | None = None
    for states in replay.get("steps") or []:
        state = states[seat]
        obs = state.get("observation") or {}
        if previous_obs is None:
            previous_obs = obs
            continue
        day = int(previous_obs.get("day", 0) or 0)
        if start_day <= day <= end_day:
            action = state.get("action") or {}
            for unit_action in [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]:
                operation = str(unit_action[0]) if unit_action else "PASS"
                result[operation] += 1
                if operation == "PLANT" and len(unit_action) > 1:
                    result[f"PLANT_{unit_action[1]}"] += 1
            for order in action.get("market") or []:
                if not order:
                    continue
                quantity = int(order[2]) if len(order) > 2 else 1
                result[str(order[0])] += quantity
                if len(order) > 1:
                    result[f"{order[0]}_{order[1]}"] += quantity
        previous_obs = obs
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--safe",
        type=Path,
        default=Path("data/replays/v101_calibration_20261101/safe_seed_20261102_seat_0.json"),
    )
    parser.add_argument(
        "--candidate",
        type=Path,
        default=Path("data/replays/v101_calibration_20261101/candidate_seed_20261102_seat_0.json"),
    )
    parser.add_argument("--seat", type=int, default=0)
    parser.add_argument(
        "--output", type=Path, default=Path("data/analysis/v101_failure_seed_20261102_seat_0.json")
    )
    args = parser.parse_args()
    safe_path = args.safe if args.safe.is_absolute() else ROOT / args.safe
    candidate_path = args.candidate if args.candidate.is_absolute() else ROOT / args.candidate
    safe = json.loads(safe_path.read_text(encoding="utf-8"))
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    safe_failures = _runtime_failures(safe, args.seat)
    candidate_failures = _runtime_failures(candidate, args.seat)
    if safe_failures or candidate_failures:
        result = {
            "format": "kaggriculture-v101-failure-trace-v2",
            "valid": False,
            "safe_replay": str(safe_path.relative_to(ROOT)),
            "candidate_replay": str(candidate_path.relative_to(ROOT)),
            "seat": args.seat,
            "runtime_failures": {
                "safe": safe_failures,
                "candidate": candidate_failures,
            },
            "interpretation": {
                "fact": "a runtime failure precedes the reported late-game collapse",
                "conclusion": "the old causal trace is invalid and must not be used as policy evidence",
                "replacement": "use data/runs/v101_calibration_corrected.json for clean paired results",
            },
        }
        output = args.output if args.output.is_absolute() else ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"result: {output}")
        return
    safe_steps = safe.get("steps") or []
    candidate_steps = candidate.get("steps") or []
    if len(safe_steps) != len(candidate_steps):
        raise ValueError("replays have different step counts")

    first_divergence = None
    for index, (safe_states, candidate_states) in enumerate(zip(safe_steps, candidate_steps, strict=True)):
        safe_action = safe_states[args.seat].get("action")
        candidate_action = candidate_states[args.seat].get("action")
        if safe_action == candidate_action:
            continue
        decision_index = max(0, index - 1)
        decision_obs = candidate_steps[decision_index][args.seat].get("observation") or {}
        v101.ENABLE_EARLY_OPTIONALITY = True
        diagnostics = v101.policy_diagnostics(decision_obs).get("v101_early_optionality") or {}
        v101.ENABLE_EARLY_OPTIONALITY = False
        first_divergence = {
            "state_index": index,
            "decision_index": decision_index,
            "day": int(decision_obs.get("day", 0) or 0),
            "hour": int(decision_obs.get("hour", 0) or 0),
            "safe_action": safe_action,
            "candidate_action": candidate_action,
            "decision": diagnostics,
        }
        break

    timeline = []
    seen_days: set[int] = set()
    for index, (safe_states, candidate_states) in enumerate(zip(safe_steps, candidate_steps, strict=True)):
        safe_obs = safe_states[args.seat].get("observation") or {}
        candidate_obs = candidate_states[args.seat].get("observation") or {}
        day = int(candidate_obs.get("day", 0) or 0)
        if day in seen_days or not 7 <= day <= 24:
            continue
        seen_days.add(day)
        safe_snapshot = _snapshot(safe_obs, args.seat)
        candidate_snapshot = _snapshot(candidate_obs, args.seat)
        timeline.append(
            {
                "day": day,
                "state_index": index,
                "safe": safe_snapshot,
                "candidate": candidate_snapshot,
                "delta": {
                    "money": candidate_snapshot["money"] - safe_snapshot["money"],
                    "productive": candidate_snapshot["productive"] - safe_snapshot["productive"],
                    "strawberry": (
                        candidate_snapshot["crops"]["STRAWBERRY"]
                        - safe_snapshot["crops"]["STRAWBERRY"]
                    ),
                    "wheat": candidate_snapshot["crops"]["WHEAT"] - safe_snapshot["crops"]["WHEAT"],
                    "cow": candidate_snapshot["animals"]["COW"] - safe_snapshot["animals"]["COW"],
                    "sheep": candidate_snapshot["animals"]["SHEEP"] - safe_snapshot["animals"]["SHEEP"],
                },
            }
        )

    safe_ops = _action_ops(safe, args.seat, 7, 18)
    candidate_ops = _action_ops(candidate, args.seat, 7, 18)
    operation_delta = {
        operation: candidate_ops[operation] - safe_ops[operation]
        for operation in sorted(set(safe_ops) | set(candidate_ops))
        if candidate_ops[operation] != safe_ops[operation]
    }
    result = {
        "format": "kaggriculture-v101-failure-trace-v1",
        "safe_replay": str(safe_path.relative_to(ROOT)),
        "candidate_replay": str(candidate_path.relative_to(ROOT)),
        "seat": args.seat,
        "first_divergence": first_divergence,
        "timeline": timeline,
        "day7_18_operation_delta": operation_delta,
        "interpretation": {
            "fact": "the first action divergence precedes all state divergence",
            "limit": "the trace identifies a mechanism but is not a counterfactual value estimate",
        },
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
