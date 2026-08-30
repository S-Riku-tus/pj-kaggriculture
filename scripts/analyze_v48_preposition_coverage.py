"""Diagnose why V11's idle-worker preposition layer leaves PASS actions."""

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

from agents.v11 import main as v11  # noqa: E402
from scripts.analyze_v34_labor_value import _stats  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    _manifest,
    _observation,
    _replay_path,
    _split,
)

FORMAT = "kaggriculture-v48-preposition-coverage-v1"
SOURCE = ROOT / "data/submissions/v11_submission_55787906"
DAYS = tuple(range(6, 13))


def _passes(actions: list[list[Any]]) -> int:
    return sum(action == ["PASS"] for action in actions[1:])


def _actual_pass(replay: dict[str, Any], step: int, seat: int) -> int:
    stored = (replay.get("steps") or [])[step + 1][seat].get("action") or {}
    return sum((value or ["PASS"])[0] == "PASS" for value in stored.get("hands") or [])


def _row(
    replay: dict[str, Any], seat: int, episode_id: str, step: int
) -> dict[str, Any] | None:
    obs = _observation(replay, step, seat)
    if obs is None:
        return None
    safe_obs = v11.base._safe_observation(obs)
    if safe_obs is None:
        return None
    farm, opponent, private = safe_obs
    summary = v11.base._farm_summary(farm)
    targets = v11._strategy_targets(obs, farm, opponent, private)
    positions = [tuple(v11.base._get(farm, "farmer", [0, 0]))]
    positions.extend(
        tuple(position) for position in (v11.base._get(farm, "hands", []) or [])
    )
    raw_inventories = list(v11.base._get(private, "inventories", []) or [])
    inventories = [
        raw_inventories[index] if index < len(raw_inventories) else {}
        for index in range(len(positions))
    ]
    tasks, _reserved = v11._field_tasks(
        obs,
        farm,
        private,
        positions,
        inventories,
        summary,
        targets[0],
        targets[1],
        targets[5],
        opponent,
    )
    raw = v11.v9._mission_assign(positions, inventories, tasks, step)
    prediction = v11.v8._expert_prediction(obs, farm, opponent, private)
    local = v11.v10._prefer_local_water(
        obs,
        farm,
        opponent,
        private,
        positions,
        inventories,
        raw,
        prediction,
    )
    guarded = v11.v10._preposition_idle_workers(
        obs,
        farm,
        opponent,
        private,
        positions,
        inventories,
        tasks,
        local,
        prediction,
    )
    ungated = v11.v10._preposition_idle_workers(
        obs,
        farm,
        opponent,
        private,
        positions,
        inventories,
        tasks,
        local,
        (None, None, 1.0),
    )
    candidates = {
        task.get("pos")
        for task in tasks
        if isinstance(task.get("pos"), tuple)
        and task.get("action")
        and task["action"][0] != "PASS"
    }
    safe_pass_units = [
        unit for unit in range(1, len(guarded)) if guarded[unit] == ["PASS"]
    ]
    loaded_pass = sum(
        v11.base._inventory_total(inventories[unit]) > 0 for unit in safe_pass_units
    )
    density: Counter[tuple[int, int]] = Counter(task["pos"] for task in tasks)
    loaded_details: Counter[str] = Counter()
    shed_tiles = set(v11.base._shed_tiles(len(v11.base._get(farm, "tiles", []) or [])))
    for unit in safe_pass_units:
        inventory = inventories[unit]
        if v11.base._inventory_total(inventory) <= 0:
            continue
        for item in (
            "WHEAT",
            "CARROT",
            "TOMATO",
            "STRAWBERRY",
            "MELON",
            "MILK",
            "WOOL",
            "FERTILIZER",
            "COW",
            "SHEEP",
        ):
            if v11.base._inventory_count(inventory, item) > 0:
                loaded_details[f"item_{item.lower()}"] += 1
        costs = [
            v11.v5._assignment_cost(unit, task, positions, inventories, density)
            for task in tasks
        ]
        feasible = [cost for cost in costs if cost < 10**8]
        loaded_details["positive_feasible"] += bool(feasible and min(feasible) < 0)
        loaded_details["no_feasible"] += not feasible
        loaded_details["at_shed"] += positions[unit] in shed_tiles
        if feasible and min(feasible) < 0:
            best_index = min(
                (index for index, cost in enumerate(costs) if cost < 10**8),
                key=lambda index: costs[index],
            )
            best = tasks[best_index]
            loaded_details[f"best_op_{best['action'][0].lower()}"] += 1
            loaded_details[f"best_label_{str(best.get('label', 'unknown'))}"] += 1
    transitions: Counter[str] = Counter()
    for before, after in zip(guarded[1:], ungated[1:], strict=True):
        if before != after:
            transitions[f"{before[0]}->{after[0]}"] += 1
    return {
        "episode_id": episode_id,
        "split": _split(episode_id),
        "day": int(obs.get("day", 0) or 0),
        "hour": int(obs.get("hour", 0) or 0),
        "hands": max(0, len(positions) - 1),
        "actual_pass": _actual_pass(replay, step, seat),
        "raw_pass": _passes(raw),
        "local_pass": _passes(local),
        "guarded_pass": _passes(guarded),
        "ungated_pass": _passes(ungated),
        "safe_to_ungated_changes": sum(transitions.values()),
        "loaded_safe_pass": loaded_pass,
        "empty_safe_pass": len(safe_pass_units) - loaded_pass,
        "candidate_positions": len(candidates),
        "prediction_available": prediction is not None,
        "prediction_confidence": float(prediction[2]) if prediction is not None else -1.0,
        "prediction_low": prediction is None or float(prediction[2]) < 0.35,
        "transitions": dict(transitions),
        "loaded_details": dict(loaded_details),
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = (
        "hands",
        "actual_pass",
        "raw_pass",
        "local_pass",
        "guarded_pass",
        "ungated_pass",
        "safe_to_ungated_changes",
        "loaded_safe_pass",
        "empty_safe_pass",
        "candidate_positions",
        "prediction_confidence",
    )
    transitions = sum((Counter(row["transitions"]) for row in rows), Counter())
    loaded_details = sum((Counter(row["loaded_details"]) for row in rows), Counter())
    return {
        "states": len(rows),
        **{
            metric: _stats([float(row[metric]) for row in rows])
            for metric in metrics
        },
        "prediction_available_rate": sum(row["prediction_available"] for row in rows)
        / max(1, len(rows)),
        "prediction_low_rate": sum(row["prediction_low"] for row in rows)
        / max(1, len(rows)),
        "safe_to_ungated_transitions_per_state": {
            name: count / max(1, len(rows)) for name, count in transitions.items()
        },
        "loaded_pass_details_per_state": {
            name: count / max(1, len(rows)) for name, count in loaded_details.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v48_preposition_coverage.json"),
    )
    args = parser.parse_args()
    rows = []
    seen: set[tuple[str, int]] = set()
    manifests = _manifest(SOURCE)
    for index, manifest in enumerate(manifests, start=1):
        print(f"[v11 {index}/{len(manifests)}]", flush=True)
        episode_id = str(manifest["episode_id"])
        seat = int(manifest["submission_seat"])
        if (episode_id, seat) in seen:
            continue
        seen.add((episode_id, seat))
        replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
        for day in DAYS:
            for hour in range(24):
                row = _row(replay, seat, episode_id, day * 24 + hour)
                if row is not None:
                    rows.append(row)
    payload = {
        "format": FORMAT,
        "runtime_policy_enabled": False,
        "objective": "measure whether the expert-confidence gate leaves observable idle-worker routes unused",
        "data": {
            "states": len(rows),
            "episodes": len({row["episode_id"] for row in rows}),
            "episode_disjoint_split": True,
        },
        "daily": {
            str(day): _summary([row for row in rows if row["day"] == day])
            for day in DAYS
        },
        "by_split": {
            split: _summary([row for row in rows if row["split"] == split])
            for split in ("train", "validation", "test")
        },
        "interpretation_limits": [
            "ungated actions are fixed-state counterfactuals and do not include downstream feedback",
            "preposition only changes empty-inventory PASS workers and never replaces an assigned operation",
            "removing a learned confidence gate can improve coverage while reducing OOD safety",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["data"], ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
