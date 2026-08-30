"""Diagnose whether Day-11/12 PASS comes from assignment or missing tasks.

The V11 deterministic planner is replayed on V11 and Rank-1 observations.
Counts are separated before and after local-water/preposition fallbacks.  For
each raw PASS worker, the report also asks whether any feasible positive-score
task existed, distinguishing task scarcity from Hungarian contention.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v11 import main as v11  # noqa: E402
from scripts.train_v12_relative_policy import _manifest, _observation, _replay_path, _split  # noqa: E402

FORMAT = "kaggriculture-v31-task-supply-gap-v1"
SOURCES = {
    "v11": ROOT / "data/submissions/v11_submission_55787906",
    "rank1": ROOT / "data/submissions/leaderboard_rank1_submission_55614463",
}
DAYS = (11, 12)
MOVEMENT = {"NORTH", "SOUTH", "EAST", "WEST"}


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * quantile
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - position) + ordered[high] * (position - low)


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "median": 0.0, "p10": 0.0, "p90": 0.0}
    return {
        "mean": mean(values),
        "median": median(values),
        "p10": _percentile(values, 0.10),
        "p90": _percentile(values, 0.90),
    }


def _pass_count(actions: list[list[Any]]) -> int:
    return sum((not action) or action[0] == "PASS" for action in actions[1:])


def _actual_counts(action: dict[str, Any]) -> tuple[int, int, int]:
    hands = [list(value or ["PASS"]) for value in (action.get("hands") or [])]
    passes = sum((not value) or value[0] == "PASS" for value in hands)
    productive = sum(
        bool(value) and value[0] != "PASS" and value[0] not in MOVEMENT for value in hands
    )
    return len(hands), passes, productive


def _latent_needs(farm: Any) -> Counter[str]:
    result: Counter[str] = Counter()
    for _x, _y, tile in v11.base._iter_tiles(farm):
        kind = v11.base._tile_kind(tile)
        if kind == "PLANT":
            if not bool(v11.base._get(tile, "watered_today", False)):
                if v11.base._as_int(v11.base._get(tile, "consecutive_unwatered", 0)) >= 1:
                    result["urgent_unwatered"] += 1
                else:
                    result["preventive_unwatered"] += 1
            if v11.base._as_int(v11.base._get(tile, "yield_units", 0)) > 0:
                result["plant_ready"] += 1
        if v11.base._get(tile, "animal") in v11.base.ANIMAL_DATA:
            if not bool(v11.base._get(tile, "fed_today", False)):
                result["unfed"] += 1
            if v11.base._as_int(v11.base._get(tile, "yield_units", 0)) > 0:
                result["animal_ready"] += 1
    return result


def _row(replay: dict[str, Any], seat: int, episode_id: str, source: str, step: int) -> dict[str, Any] | None:
    obs = _observation(replay, step, seat)
    if obs is None:
        return None
    safe = v11.base._safe_observation(obs)
    if safe is None:
        return None
    farm, opponent, private = safe
    summary = v11.base._farm_summary(farm)
    targets = v11._strategy_targets(obs, farm, opponent, private)
    positions = [tuple(v11.base._get(farm, "farmer", [0, 0]))]
    positions.extend(tuple(position) for position in (v11.base._get(farm, "hands", []) or []))
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
    final = v11.v10._preposition_idle_workers(
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
    density: Counter[tuple[int, int]] = Counter(task["pos"] for task in tasks)
    raw_pass_no_feasible = 0
    raw_pass_nonpositive = 0
    raw_pass_positive_contended = 0
    for unit in range(1, len(positions)):
        if raw[unit] != ["PASS"]:
            continue
        costs = [
            v11.v5._assignment_cost(unit, task, positions, inventories, density)
            for task in tasks
        ]
        feasible = [cost for cost in costs if cost < 10**8]
        if not feasible:
            raw_pass_no_feasible += 1
        elif min(feasible) >= 0:
            raw_pass_nonpositive += 1
        else:
            raw_pass_positive_contended += 1
    actual = (replay.get("steps") or [])[step + 1][seat].get("action") or {}
    actual_hands, actual_pass, actual_productive = _actual_counts(actual)
    needs = _latent_needs(farm)
    task_labels = Counter(str(task.get("label", "unknown")) for task in tasks)
    return {
        "source": source,
        "episode_id": episode_id,
        "split": _split(episode_id),
        "day": int(obs.get("day", 0) or 0),
        "hour": int(obs.get("hour", 0) or 0),
        "hands": max(0, len(positions) - 1),
        "actual_hands": actual_hands,
        "actual_pass": actual_pass,
        "actual_productive": actual_productive,
        "task_count": len(tasks),
        "task_labels": dict(task_labels),
        "raw_pass": _pass_count(raw),
        "local_pass": _pass_count(local),
        "final_pass": _pass_count(final),
        "raw_pass_no_feasible": raw_pass_no_feasible,
        "raw_pass_nonpositive": raw_pass_nonpositive,
        "raw_pass_positive_contended": raw_pass_positive_contended,
        "latent_needs": dict(needs),
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    numeric = (
        "hands",
        "actual_pass",
        "actual_productive",
        "task_count",
        "raw_pass",
        "local_pass",
        "final_pass",
        "raw_pass_no_feasible",
        "raw_pass_nonpositive",
        "raw_pass_positive_contended",
    )
    task_labels: Counter[str] = Counter()
    needs: Counter[str] = Counter()
    for row in rows:
        task_labels.update(row["task_labels"])
        needs.update(row["latent_needs"])
    decisions = max(1, len(rows))
    return {
        "decision_states": len(rows),
        **{name: _stats([float(row[name]) for row in rows]) for name in numeric},
        "task_labels_per_state": {
            name: count / decisions for name, count in task_labels.most_common()
        },
        "latent_needs_per_state": {name: count / decisions for name, count in needs.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=Path("data/analysis/v31_task_supply_gap.json")
    )
    parser.add_argument(
        "--days",
        default=",".join(str(day) for day in DAYS),
        help="comma-separated game days to analyze",
    )
    args = parser.parse_args()
    days = tuple(sorted({int(value) for value in args.days.split(",") if value.strip()}))
    if not days or any(day < 0 or day > 29 for day in days):
        parser.error("--days must contain game days in [0, 29]")
    rows: list[dict[str, Any]] = []
    for source, directory in SOURCES.items():
        manifests = _manifest(directory)
        for index, manifest in enumerate(manifests, start=1):
            if index == 1 or index % 25 == 0:
                print(f"[{source} {index}/{len(manifests)}]", flush=True)
            episode_id = str(manifest["episode_id"])
            seat = int(manifest["submission_seat"])
            replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
            for day in days:
                for hour in range(24):
                    value = _row(replay, seat, episode_id, source, day * 24 + hour)
                    if value is not None:
                        rows.append(value)
    payload = {
        "format": FORMAT,
        "objective": "separate task scarcity, assignment contention, and fallback effects",
        "source_day_summary": {
            source: {
                str(day): _summary(
                    [row for row in rows if row["source"] == source and row["day"] == day]
                )
                for day in days
            }
            for source in SOURCES
        },
        "v11_split_summary": {
            split: _summary(
                [row for row in rows if row["source"] == "v11" and row["split"] == split]
            )
            for split in ("train", "validation", "test")
        },
        "interpretation": {
            "fact": "the same V11 planner is replayed on both submitted V11 and Rank-1 states",
            "limit": "V11 planner actions on Rank-1 states are counterfactual diagnostics, not Rank-1 intent",
        },
        "days": list(days),
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["source_day_summary"], ensure_ascii=False, indent=2))
    print(json.dumps(payload["v11_split_summary"], ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
