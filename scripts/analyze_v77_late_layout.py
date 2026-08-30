"""Compare day-20/24 farm geometry in V11 and Top-3 replay logs."""

from __future__ import annotations

import json
import math
import sys
from collections import deque
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_v34_labor_value import SOURCES  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    _manifest,
    _observation,
    _replay_path,
    _split,
)

OUTPUT = ROOT / "data/analysis/v77_late_layout.json"
DAYS = tuple(range(20, 25))
DIRECTIONS = ((1, 0), (-1, 0), (0, 1), (0, -1))


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


def _distance(left: tuple[int, int], right: tuple[int, int]) -> int:
    return abs(left[0] - right[0]) + abs(left[1] - right[1])


def _components(points: set[tuple[int, int]]) -> int:
    unseen = set(points)
    count = 0
    while unseen:
        count += 1
        queue = deque([unseen.pop()])
        while queue:
            x, y = queue.popleft()
            for dx, dy in DIRECTIONS:
                neighbor = (x + dx, y + dy)
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    queue.append(neighbor)
    return count


def _nearest_mean(points: set[tuple[int, int]]) -> float:
    if len(points) <= 1:
        return 0.0
    return mean(
        min(_distance(point, other) for other in points if other != point)
        for point in points
    )


def _pairwise_mean(points: set[tuple[int, int]]) -> float:
    ordered = sorted(points)
    values = [
        _distance(left, right)
        for index, left in enumerate(ordered)
        for right in ordered[index + 1 :]
    ]
    return mean(values) if values else 0.0


def _adjacency(points: set[tuple[int, int]]) -> int:
    return sum(
        int((x + 1, y) in points) + int((x, y + 1) in points)
        for x, y in points
    )


def _cross_edges(
    left: set[tuple[int, int]], right: set[tuple[int, int]]
) -> int:
    return sum(
        (x + dx, y + dy) in right
        for x, y in left
        for dx, dy in DIRECTIONS
    )


def _centroid(points: set[tuple[int, int]]) -> tuple[float, float] | None:
    if not points:
        return None
    return mean(x for x, _y in points), mean(y for _x, y in points)


def _layout(obs: dict[str, Any], seat: int) -> dict[str, float]:
    farm = (obs.get("farms") or [])[seat]
    crops: set[tuple[int, int]] = set()
    animals: set[tuple[int, int]] = set()
    empty_structures: set[tuple[int, int]] = set()
    for y, row in enumerate(farm.get("tiles") or []):
        for x, tile in enumerate(row):
            if not isinstance(tile, dict):
                continue
            if tile.get("kind") == "PLANT":
                crops.add((x, y))
            elif tile.get("animal"):
                animals.add((x, y))
            elif tile.get("kind") in {"COOP", "PASTURE"}:
                empty_structures.add((x, y))
    productive = crops | animals
    planned = productive | empty_structures
    crop_center = _centroid(crops)
    animal_center = _centroid(animals)
    center_gap = (
        abs(crop_center[0] - animal_center[0])
        + abs(crop_center[1] - animal_center[1])
        if crop_center is not None and animal_center is not None
        else 0.0
    )
    shed_adjacent = {(4, 4), (5, 4), (4, 5), (5, 5)}
    return {
        "productive_count": float(len(productive)),
        "crop_count": float(len(crops)),
        "animal_count": float(len(animals)),
        "empty_structure_count": float(len(empty_structures)),
        "productive_components": float(_components(productive)),
        "planned_components": float(_components(planned)),
        "productive_nearest_distance": _nearest_mean(productive),
        "productive_pairwise_distance": _pairwise_mean(productive),
        "productive_adjacency_per_tile": _adjacency(productive)
        / max(1.0, float(len(productive))),
        "crop_adjacency_per_tile": _adjacency(crops) / max(1.0, float(len(crops))),
        "animal_adjacency_per_tile": _adjacency(animals)
        / max(1.0, float(len(animals))),
        "crop_animal_boundary_per_animal": _cross_edges(animals, crops)
        / max(1.0, float(len(animals))),
        "crop_animal_centroid_distance": center_gap,
        "productive_shed_distance": mean(
            min(_distance(point, shed) for shed in shed_adjacent)
            for point in productive
        )
        if productive
        else 0.0,
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
            seat = int(manifest["submission_seat"])
            for day in DAYS:
                obs = _observation(replay, day * 24, seat)
                if obs is None:
                    continue
                rows.append(
                    {
                        "source": source,
                        "episode_id": str(manifest["episode_id"]),
                        "split": _split(str(manifest["episode_id"])),
                        "day": day,
                        "metrics": _layout(obs, seat),
                    }
                )
    sources = tuple(SOURCES)
    payload = {
        "format": "kaggriculture-v77-late-layout-v1",
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
            for source in sources
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
            "layout is observed at day start and is descriptive, not a causal treatment",
            "productive tiles exclude empty structures; planned tiles include them",
            "geometry does not observe private inventory or future placement intent",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    compact_metrics = (
        "productive_count",
        "productive_components",
        "productive_nearest_distance",
        "productive_pairwise_distance",
        "productive_adjacency_per_tile",
        "crop_animal_centroid_distance",
        "productive_shed_distance",
    )
    print(
        json.dumps(
            {
                source: {
                    metric: payload["source"][source]["all"][metric]["mean"]
                    for metric in compact_metrics
                }
                for source in sources
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"result: {OUTPUT}")


if __name__ == "__main__":
    main()
