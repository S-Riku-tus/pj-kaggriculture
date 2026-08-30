"""Compare late action density and asset mix in V11 and Top-3 logs."""

from __future__ import annotations

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

from scripts.analyze_v33_asset_labor import _actions, _farm, _positions  # noqa: E402
from scripts.analyze_v34_labor_value import SOURCES  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    _manifest,
    _observation,
    _replay_path,
    _split,
)

OUTPUT = ROOT / "data/analysis/v78_late_action_density.json"
DAYS = tuple(range(20, 25))
CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
ANIMALS = ("GOOSE", "COW", "SHEEP")
MOVES = {"NORTH", "SOUTH", "EAST", "WEST"}
OPS = (
    "FEED",
    "CARE",
    "COLLECT_FERTILIZER",
    "ANIMAL_HARVEST",
    "PLACE",
    "WATER",
    "FERTILIZE",
    "PLANT",
    "CROP_HARVEST",
    "PICKUP",
    "DROP",
    "MOVE",
    "PASS",
    "OTHER",
)


def _stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {"mean": 0.0, "median": 0.0, "p10": 0.0, "p90": 0.0}

    def percentile(probability: float) -> float:
        position = probability * (len(ordered) - 1)
        lower, upper = math.floor(position), math.ceil(position)
        if lower == upper:
            return ordered[lower]
        fraction = position - lower
        return ordered[lower] * (1 - fraction) + ordered[upper] * fraction

    return {
        "mean": mean(ordered),
        "median": median(ordered),
        "p10": percentile(0.10),
        "p90": percentile(0.90),
    }


def _tile(farm: dict[str, Any], position: tuple[int, int]) -> Any:
    x, y = position
    tiles = farm.get("tiles") or []
    if 0 <= y < len(tiles) and 0 <= x < len(tiles[y]):
        return tiles[y][x]
    return None


def _asset_counts(farm: dict[str, Any]) -> tuple[Counter[str], Counter[str]]:
    crops: Counter[str] = Counter()
    animals: Counter[str] = Counter()
    for row in farm.get("tiles") or []:
        for tile in row:
            if not isinstance(tile, dict):
                continue
            crop = str(tile.get("crop") or "")
            animal = str(tile.get("animal") or "")
            if tile.get("kind") == "PLANT" and crop in CROPS:
                crops[crop] += 1
            if animal in ANIMALS:
                animals[animal] += 1
    return crops, animals


def _classified_op(op: str, tile: Any) -> str:
    if op in MOVES:
        return "MOVE"
    if op == "PASS":
        return "PASS"
    if op != "HARVEST":
        return op if op in OPS else "OTHER"
    if isinstance(tile, dict) and tile.get("animal"):
        return "ANIMAL_HARVEST"
    if isinstance(tile, dict) and tile.get("kind") == "PLANT":
        return "CROP_HARVEST"
    return "OTHER"


def _day_row(
    replay: dict[str, Any], manifest: dict[str, str], source: str, day: int
) -> dict[str, Any] | None:
    seat = int(manifest["submission_seat"])
    start = _observation(replay, day * 24, seat)
    if start is None:
        return None
    farm_start = _farm(start, seat)
    crop_counts, animal_counts = _asset_counts(farm_start)
    counts: Counter[str] = Counter()
    hands_peak = 0
    for step in range(day * 24, (day + 1) * 24):
        obs = _observation(replay, step, seat)
        if obs is None:
            continue
        farm = _farm(obs, seat)
        positions = _positions(farm)
        actions = _actions(replay, step, seat)
        hands_peak = max(hands_peak, max(0, len(positions) - 1))
        for unit in range(1, min(len(positions), len(actions))):
            action = actions[unit]
            op = str(action[0]) if action else "PASS"
            counts[_classified_op(op, _tile(farm, positions[unit]))] += 1
    crops = float(sum(crop_counts.values()))
    animals = float(sum(animal_counts.values()))
    productive = crops + animals
    crop_ops = sum(
        counts[op] for op in ("WATER", "FERTILIZE", "PLANT", "CROP_HARVEST")
    )
    animal_ops = sum(
        counts[op]
        for op in (
            "FEED",
            "CARE",
            "COLLECT_FERTILIZER",
            "ANIMAL_HARVEST",
            "PLACE",
        )
    )
    productive_ops = crop_ops + animal_ops
    denominator = max(1, hands_peak)
    metrics = {
        **{f"crop_{crop.lower()}": float(crop_counts[crop]) for crop in CROPS},
        **{f"animal_{animal.lower()}": float(animal_counts[animal]) for animal in ANIMALS},
        **{f"op_{op.lower()}": float(counts[op]) for op in OPS},
        "crop_count": crops,
        "animal_count": animals,
        "productive_count": productive,
        "crop_ops": float(crop_ops),
        "animal_ops": float(animal_ops),
        "productive_ops": float(productive_ops),
        "crop_ops_per_asset": crop_ops / max(1.0, crops),
        "animal_ops_per_asset": animal_ops / max(1.0, animals),
        "productive_ops_per_asset": productive_ops / max(1.0, productive),
        "productive_ops_per_hand": productive_ops / denominator,
        "logistics_ops_per_hand": (counts["PICKUP"] + counts["DROP"]) / denominator,
        "move_per_hand": counts["MOVE"] / denominator,
        "pass_per_hand": counts["PASS"] / denominator,
    }
    return {
        "source": source,
        "episode_id": str(manifest["episode_id"]),
        "split": _split(str(manifest["episode_id"])),
        "day": day,
        "metrics": metrics,
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"episode_days": 0}
    metrics = tuple(rows[0]["metrics"])
    return {
        "episode_days": len(rows),
        **{
            metric: _stats([float(row["metrics"][metric]) for row in rows])
            for metric in metrics
        },
    }


def main() -> None:
    rows = []
    seen: set[tuple[str, str, int]] = set()
    for source, directory in SOURCES.items():
        manifests = _manifest(directory)
        for index, manifest in enumerate(manifests, start=1):
            if index == 1 or index % 50 == 0:
                print(f"[{source} {index}/{len(manifests)}]", flush=True)
            key = (source, str(manifest["episode_id"]), int(manifest["submission_seat"]))
            if key in seen:
                continue
            seen.add(key)
            replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
            for day in DAYS:
                row = _day_row(replay, manifest, source, day)
                if row is not None:
                    rows.append(row)
    payload = {
        "format": "kaggriculture-v78-late-action-density-v1",
        "runtime_policy_enabled": False,
        "days": list(DAYS),
        "data": {
            "episode_days": len(rows),
            "episodes": len({row["episode_id"] for row in rows}),
            "episode_disjoint_split": True,
        },
        "source": {
            source: {
                "all": _summary([row for row in rows if row["source"] == source]),
                "by_day": {
                    str(day): _summary(
                        [
                            row
                            for row in rows
                            if row["source"] == source and row["day"] == day
                        ]
                    )
                    for day in DAYS
                },
            }
            for source in SOURCES
        },
        "v11_by_split": {
            split: _summary(
                [
                    row
                    for row in rows
                    if row["source"] == "v11" and row["split"] == split
                ]
            )
            for split in ("train", "validation", "test")
        },
        "limits": [
            "asset counts are day-start snapshots while actions cover the following 24 turns",
            "HARVEST is classified from the public tile under the worker before action",
            "action density is descriptive and does not prove which asset mix is causal",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    compact_metrics = (
        "crop_count",
        "animal_count",
        "productive_ops_per_asset",
        "crop_ops_per_asset",
        "animal_ops_per_asset",
        "productive_ops_per_hand",
        "logistics_ops_per_hand",
        "move_per_hand",
        "pass_per_hand",
    )
    print(
        json.dumps(
            {
                source: {
                    metric: payload["source"][source]["all"][metric]["mean"]
                    for metric in compact_metrics
                }
                for source in SOURCES
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"result: {OUTPUT}")


if __name__ == "__main__":
    main()
