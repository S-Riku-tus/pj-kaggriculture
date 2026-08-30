"""Measure demand-conditioned late portfolios in the top-three teachers.

Every row is one public episode.  Aggregates retain the deterministic episode
split used by the V9 training pipeline so changes can be checked on unused
validation/test matches rather than on pooled observations.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.train_v9_decision_policy import _split  # noqa: E402

TEACHERS = ("rank1", "rank2", "rank3")
CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
ANIMALS = ("COW", "SHEEP", "GOOSE")


def _percentile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _distribution(values: list[float]) -> dict[str, float]:
    return {
        "minimum": round(min(values, default=0.0), 4),
        "p10": round(_percentile(values, 0.10), 4),
        "p25": round(_percentile(values, 0.25), 4),
        "median": round(_percentile(values, 0.50), 4),
        "mean": round(mean(values), 4) if values else 0.0,
        "p75": round(_percentile(values, 0.75), 4),
        "p90": round(_percentile(values, 0.90), 4),
        "maximum": round(max(values, default=0.0), 4),
    }


def _truth(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def _snapshot(raw: dict[str, Any], demands: dict[str, int]) -> dict[str, Any]:
    crops = raw.get("crops") or {}
    animals = raw.get("animals") or {}
    return {
        **{crop: int(crops.get(crop, 0) or 0) for crop in CROPS},
        **{animal: int(animals.get(animal, 0) or 0) for animal in ANIMALS},
        "productive": int(raw.get("productive_tiles", 0) or 0),
        "money": float(raw.get("money", 0) or 0),
        **demands,
    }


def _episode(row: dict[str, str]) -> dict[str, Any] | None:
    if _truth(row.get("is_self_play", "")):
        return None
    snapshots = json.loads(row["day_snapshots"])
    if "20" not in snapshots or "24" not in snapshots:
        return None
    demands = {
        f"demand_{item}": int(float(row.get(f"demand_{item}", 0) or 0))
        for item in ("wheat", "carrot", "tomato", "strawberry", "milk", "wool")
    }
    return {
        "episode_id": str(row["episode_id"]),
        "split": _split(str(row["episode_id"])),
        "reward": float(row.get("own_reward", 0) or 0),
        "margin": float(row.get("margin", 0) or 0),
        "day20": _snapshot(snapshots["20"], demands),
        "day24": _snapshot(snapshots["24"], demands),
        "day27": _snapshot(snapshots["27"], demands) if "27" in snapshots else None,
    }


def _conditional(rows: list[dict[str, Any]], demand_name: str) -> dict[str, Any]:
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[int(row["day24"][demand_name])].append(row)
    metrics = (*CROPS, "COW", "SHEEP", "productive", "money", "reward", "margin")
    result: dict[str, Any] = {}
    for demand, bucket in sorted(groups.items()):
        result[str(demand)] = {
            "episodes": len(bucket),
            **{
                metric: _distribution(
                    [
                        float(row[metric])
                        if metric in {"reward", "margin"}
                        else float(row["day24"][metric])
                        for row in bucket
                    ]
                )
                for metric in metrics
            },
        }
    return result


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "episodes": len(rows),
        "day24": {
            metric: _distribution([float(row["day24"][metric]) for row in rows])
            for metric in (*CROPS, "COW", "SHEEP", "productive", "money")
        },
        "by_carrot_demand": _conditional(rows, "demand_carrot"),
        "by_tomato_demand": _conditional(rows, "demand_tomato"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--episodes",
        type=Path,
        default=Path("data/analysis/v8_top3_full_episodes.csv"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v11_teacher_rotation.json"),
    )
    args = parser.parse_args()
    episodes_path = args.episodes if args.episodes.is_absolute() else ROOT / args.episodes
    with episodes_path.open(encoding="utf-8", newline="") as handle:
        raw_rows = list(csv.DictReader(handle))
    episodes: dict[str, list[dict[str, Any]]] = {}
    for label in TEACHERS:
        episodes[label] = [
            episode
            for row in raw_rows
            if row.get("label") == label
            for episode in [_episode(row)]
            if episode is not None
        ]
    combined = [episode for values in episodes.values() for episode in values]
    result = {
        "objective": "Demand-conditioned Day-24 portfolios; all aggregates are episode based",
        "experts": {
            label: {
                split: _aggregate([row for row in values if split == "all" or row["split"] == split])
                for split in ("all", "train", "validation", "test")
            }
            for label, values in episodes.items()
        },
        "combined": {
            split: _aggregate([row for row in combined if split == "all" or row["split"] == split])
            for split in ("all", "train", "validation", "test")
        },
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
