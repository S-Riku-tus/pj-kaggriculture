"""Measure the purchase-to-placement pipeline for Cow and Sheep."""

from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v3.feature_schema import farm_summary  # noqa: E402
from scripts.analyze_v33_asset_labor import _actions, _farm, _positions, _tile  # noqa: E402
from scripts.analyze_v34_labor_value import SOURCES, _market_actions, _stats  # noqa: E402
from scripts.analyze_v37_early_capital import _owned  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    _manifest,
    _observation,
    _replay_path,
    _split,
)

FORMAT = "kaggriculture-v38-animal-placement-latency-v1"
ANIMALS = ("COW", "SHEEP")
SNAPSHOT_DAYS = tuple(range(3, 12))


def _inventory_breakdown(obs: dict[str, Any], seat: int, animal: str) -> dict[str, int]:
    private = obs.get("private") or {}
    shed = int((private.get("shed") or {}).get(animal, 0) or 0)
    carried = sum(
        int((inventory or {}).get(animal, 0) or 0)
        for inventory in private.get("inventories", [])
    )
    placed = int(farm_summary(_farm(obs, seat))["animals"].get(animal, 0))
    return {"placed": placed, "shed": shed, "carried": carried, "pending": shed + carried}


def _successful_places(
    replay: dict[str, Any], step: int, seat: int
) -> list[str]:
    obs = _observation(replay, step, seat)
    next_obs = _observation(replay, step + 1, seat)
    if obs is None or next_obs is None:
        return []
    farm = _farm(obs, seat)
    next_farm = _farm(next_obs, seat)
    positions = _positions(farm)
    result = []
    for unit, action in enumerate(_actions(replay, step, seat)):
        if unit >= len(positions) or len(action) < 2 or str(action[0]) != "PLACE":
            continue
        animal = str(action[1])
        if animal not in ANIMALS:
            continue
        after = _tile(next_farm, positions[unit])
        if isinstance(after, dict) and after.get("animal") == animal:
            result.append(animal)
    return result


def _side(
    replay: dict[str, Any], seat: int, source: str, episode_id: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    queues = {animal: deque() for animal in ANIMALS}
    latency: list[dict[str, Any]] = []
    steps = replay.get("steps") or []
    for step in range(min(21 * 24, len(steps) - 1)):
        obs = _observation(replay, step, seat)
        next_obs = _observation(replay, step + 1, seat)
        if obs is None or next_obs is None:
            continue
        orders = _market_actions(replay, step, seat)
        for animal in ANIMALS:
            if any(
                len(order) >= 2
                and str(order[0]) == "BUY_ANIMAL"
                and str(order[1]) == animal
                for order in orders
            ):
                purchased = max(0, _owned(next_obs, seat, animal) - _owned(obs, seat, animal))
                for _ in range(purchased):
                    queues[animal].append(step)
        for animal in _successful_places(replay, step, seat):
            purchase_step = queues[animal].popleft() if queues[animal] else None
            if purchase_step is None:
                continue
            latency.append(
                {
                    "source": source,
                    "episode_id": episode_id,
                    "split": _split(episode_id),
                    "animal": animal,
                    "purchase_step": purchase_step,
                    "purchase_day": purchase_step // 24,
                    "purchase_hour": purchase_step % 24,
                    "place_step": step,
                    "place_day": step // 24,
                    "latency_turns": step - purchase_step,
                    "same_day": step // 24 == purchase_step // 24,
                }
            )

    snapshots = []
    for day in SNAPSHOT_DAYS:
        obs = _observation(replay, day * 24, seat)
        if obs is None:
            continue
        farm = _farm(obs, seat)
        summary = farm_summary(farm, day)
        snapshots.append(
            {
                "source": source,
                "episode_id": episode_id,
                "split": _split(episode_id),
                "day": day,
                "empty_pastures": int(summary["empty_structures"]),
                "animals": {
                    animal: _inventory_breakdown(obs, seat, animal) for animal in ANIMALS
                },
            }
        )
    return latency, snapshots


def _latency_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["latency_turns"]) for row in rows]
    return {
        "placements": len(rows),
        "episodes": len({row["episode_id"] for row in rows}),
        "latency_turns": _stats(values),
        "fraction_within": {
            str(limit): sum(value <= limit for value in values) / max(1, len(values))
            for limit in (1, 3, 6, 12, 24)
        },
        "purchase_hour": _stats([row["purchase_hour"] for row in rows]),
        "same_day_fraction": sum(bool(row["same_day"]) for row in rows)
        / max(1, len(rows)),
        "by_purchase_hour": {
            name: {
                "placements": len(selected),
                "latency_turns": _stats([row["latency_turns"] for row in selected]),
                "same_day_fraction": sum(bool(row["same_day"]) for row in selected)
                / max(1, len(selected)),
            }
            for name, selected in {
                "early_0-11": [row for row in rows if row["purchase_hour"] <= 11],
                "mid_12-17": [row for row in rows if 12 <= row["purchase_hour"] <= 17],
                "late_18-20": [row for row in rows if 18 <= row["purchase_hour"] <= 20],
                "deadline_21-23": [row for row in rows if 21 <= row["purchase_hour"] <= 23],
            }.items()
        },
        "by_purchase_window": {
            name: {
                "placements": len(selected),
                "latency_turns": _stats([row["latency_turns"] for row in selected]),
            }
            for name, selected in {
                "opening_0-2": [row for row in rows if row["purchase_day"] <= 2],
                "early_3-5": [row for row in rows if 3 <= row["purchase_day"] <= 5],
                "expansion_6-8": [row for row in rows if 6 <= row["purchase_day"] <= 8],
                "branch_9-10": [row for row in rows if 9 <= row["purchase_day"] <= 10],
                "later_11-20": [row for row in rows if 11 <= row["purchase_day"] <= 20],
            }.items()
        },
    }


def _snapshot_summary(rows: list[dict[str, Any]], animal: str) -> dict[str, Any]:
    result = {}
    for day in SNAPSHOT_DAYS:
        selected = [row for row in rows if row["day"] == day]
        result[str(day)] = {
            "rows": len(selected),
            "placed": _stats([row["animals"][animal]["placed"] for row in selected]),
            "pending": _stats([row["animals"][animal]["pending"] for row in selected]),
            "shed": _stats([row["animals"][animal]["shed"] for row in selected]),
            "carried": _stats([row["animals"][animal]["carried"] for row in selected]),
            "empty_pastures": _stats([row["empty_pastures"] for row in selected]),
            "pending_with_empty_pasture_fraction": sum(
                row["animals"][animal]["pending"] > 0 and row["empty_pastures"] > 0
                for row in selected
            )
            / max(1, len(selected)),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v38_animal_placement_latency.json"),
    )
    args = parser.parse_args()
    latency: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for source, directory in SOURCES.items():
        manifests = _manifest(directory)
        for index, manifest in enumerate(manifests, start=1):
            if index == 1 or index % 50 == 0:
                print(f"[{source} {index}/{len(manifests)}]", flush=True)
            episode_id = str(manifest["episode_id"])
            seat = int(manifest["submission_seat"])
            key = (source, episode_id, seat)
            if key in seen:
                continue
            seen.add(key)
            replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
            side_latency, side_snapshots = _side(replay, seat, source, episode_id)
            latency.extend(side_latency)
            snapshots.extend(side_snapshots)

    payload = {
        "format": FORMAT,
        "runtime_policy_enabled": False,
        "objective": "measure successful animal purchase-to-PLACE latency and pending stock",
        "data": {
            "matched_placements": len(latency),
            "snapshots": len(snapshots),
            "episodes": len({row["episode_id"] for row in snapshots}),
            "episode_disjoint_split": True,
        },
        "latency_summary": {
            source: {
                animal: _latency_summary(
                    [
                        row
                        for row in latency
                        if row["source"] == source and row["animal"] == animal
                    ]
                )
                for animal in ANIMALS
            }
            for source in SOURCES
        },
        "snapshot_summary": {
            source: {
                animal: _snapshot_summary(
                    [row for row in snapshots if row["source"] == source], animal
                )
                for animal in ANIMALS
            }
            for source in SOURCES
        },
        "interpretation_limits": [
            "purchase quantity is inferred from total-owned increases on a BUY_ANIMAL turn",
            "FIFO matching cannot identify physical units and may be biased by same-turn escape/rebuy",
            "latency is operational evidence, not causal final-score value",
            "unmatched purchases after Day 20 are outside this report rather than assumed lost",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
