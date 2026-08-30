"""Reconstruct pasture construction and animal-placement expansion paths."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_v33_asset_labor import _actions, _farm, _positions, _tile  # noqa: E402
from scripts.analyze_v34_labor_value import SOURCES, TOP_SOURCES, _stats  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    _manifest,
    _observation,
    _replay_path,
    _split,
)

FORMAT = "kaggriculture-v36-pasture-expansion-v1"
SNAPSHOT_DAYS = (3, 6, 9, 11, 14, 17, 20)
RING_SIZES = (12, 16, 20)


def _distance(left: tuple[int, int], right: tuple[int, int]) -> int:
    return abs(left[0] - right[0]) + abs(left[1] - right[1])


def _shed_tiles(size: int) -> list[tuple[int, int]]:
    half = size // 2
    return [(half - 1, half - 1), (half, half - 1), (half - 1, half), (half, half)]


def _shed_distance(position: tuple[int, int], size: int) -> int:
    return min(_distance(position, shed) for shed in _shed_tiles(size))


def _unlocked_positions(farm: dict[str, Any]) -> list[tuple[int, int]]:
    result = []
    for y, row in enumerate(farm.get("tiles") or []):
        for x, tile in enumerate(row):
            if tile != "LOCKED":
                result.append((x, y))
    return result


def _ring(farm: dict[str, Any], count: int) -> list[tuple[int, int]]:
    size = len(farm.get("tiles") or [])
    return sorted(
        _unlocked_positions(farm),
        key=lambda position: (
            _shed_distance(position, size),
            position[1],
            position[0],
        ),
    )[:count]


def _kind(tile: Any) -> str:
    if tile is None:
        return "EMPTY"
    if tile == "LOCKED":
        return "LOCKED"
    if not isinstance(tile, dict):
        return "OTHER"
    if tile.get("animal") in {"COW", "SHEEP"}:
        return str(tile["animal"])
    if tile.get("kind") == "PASTURE":
        return "EMPTY_PASTURE"
    if tile.get("kind") == "PLANT":
        return f"CROP_{tile.get('crop', 'UNKNOWN')}"
    return str(tile.get("kind") or "OTHER")


def _snapshot(
    replay: dict[str, Any], seat: int, source: str, episode_id: str, day: int
) -> dict[str, Any] | None:
    obs = _observation(replay, day * 24, seat)
    if obs is None:
        return None
    farm = _farm(obs, seat)
    size = len(farm.get("tiles") or [])
    positions: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for y, row in enumerate(farm.get("tiles") or []):
        for x, tile in enumerate(row):
            kind = _kind(tile)
            if kind in {"COW", "SHEEP", "EMPTY_PASTURE"}:
                positions[kind].append((x, y))
    rings = {}
    for count in RING_SIZES:
        occupancy = Counter(_kind(_tile(farm, position)) for position in _ring(farm, count))
        rings[str(count)] = dict(occupancy)
    return {
        "source": source,
        "episode_id": episode_id,
        "split": _split(episode_id),
        "day": day,
        "positions": {key: [list(position) for position in value] for key, value in positions.items()},
        "mean_distance": {
            animal: mean([_shed_distance(position, size) for position in positions[animal]])
            if positions[animal]
            else 0.0
            for animal in ("COW", "SHEEP")
        },
        "max_distance": {
            animal: max(
                [_shed_distance(position, size) for position in positions[animal]],
                default=0,
            )
            for animal in ("COW", "SHEEP")
        },
        "rings": rings,
    }


def _events(
    replay: dict[str, Any], seat: int, source: str, episode_id: str
) -> list[dict[str, Any]]:
    result = []
    steps = replay.get("steps") or []
    for step in range(min(21 * 24, len(steps) - 1)):
        obs = _observation(replay, step, seat)
        next_obs = _observation(replay, step + 1, seat)
        if obs is None or next_obs is None:
            continue
        farm = _farm(obs, seat)
        next_farm = _farm(next_obs, seat)
        size = len(farm.get("tiles") or [])
        positions = _positions(farm)
        actions = _actions(replay, step, seat)
        for unit, action in enumerate(actions):
            if unit >= len(positions) or not action:
                continue
            op = str(action[0])
            if op not in {"BUILD_PASTURE", "PLACE"}:
                continue
            animal = str(action[1]) if op == "PLACE" and len(action) >= 2 else None
            if op == "PLACE" and animal not in {"COW", "SHEEP"}:
                continue
            position = positions[unit]
            before = _tile(farm, position)
            after = _tile(next_farm, position)
            success = (
                op == "BUILD_PASTURE"
                and isinstance(after, dict)
                and after.get("kind") == "PASTURE"
            ) or (
                op == "PLACE"
                and isinstance(after, dict)
                and after.get("animal") == animal
            )
            if not success:
                continue
            if op == "BUILD_PASTURE":
                feasible = [
                    candidate
                    for candidate in _unlocked_positions(farm)
                    if _tile(farm, candidate) is None
                ]
            else:
                feasible = [
                    candidate
                    for candidate in _unlocked_positions(farm)
                    if isinstance(_tile(farm, candidate), dict)
                    and _tile(farm, candidate).get("kind") == "PASTURE"
                    and _tile(farm, candidate).get("animal") is None
                ]
            chosen_distance = _shed_distance(position, size)
            result.append(
                {
                    "source": source,
                    "episode_id": episode_id,
                    "split": _split(episode_id),
                    "step": step,
                    "day": int(obs.get("day", 0) or 0),
                    "hour": int(obs.get("hour", 0) or 0),
                    "event": "build" if op == "BUILD_PASTURE" else "place",
                    "animal": animal,
                    "position": list(position),
                    "shed_distance": chosen_distance,
                    "nearer_feasible_count": sum(
                        _shed_distance(candidate, size) < chosen_distance
                        for candidate in feasible
                    ),
                    "same_distance_feasible_count": sum(
                        _shed_distance(candidate, size) == chosen_distance
                        for candidate in feasible
                    ),
                    "tile_before": _kind(before),
                }
            )
    return result


def _event_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    late = [row for row in rows if int(row["day"]) >= 1]
    return {
        "events": len(rows),
        "episodes": len({row["episode_id"] for row in rows}),
        "day": _stats([row["day"] for row in rows]),
        "shed_distance": _stats([row["shed_distance"] for row in rows]),
        "nearer_feasible_count": _stats([row["nearer_feasible_count"] for row in rows]),
        "distance_histogram": dict(Counter(str(row["shed_distance"]) for row in rows)),
        "after_opening": {
            "events": len(late),
            "day": _stats([row["day"] for row in late]),
            "shed_distance": _stats([row["shed_distance"] for row in late]),
            "nearer_feasible_count": _stats([row["nearer_feasible_count"] for row in late]),
            "distance_histogram": dict(Counter(str(row["shed_distance"]) for row in late)),
        },
    }


def _snapshot_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for day in SNAPSHOT_DAYS:
        selected = [row for row in rows if row["day"] == day]
        day_result: dict[str, Any] = {
            "rows": len(selected),
            "cow_mean_distance": _stats([row["mean_distance"]["COW"] for row in selected]),
            "cow_max_distance": _stats([row["max_distance"]["COW"] for row in selected]),
        }
        for count in RING_SIZES:
            crops = []
            pastures = []
            animals = []
            for row in selected:
                ring = row["rings"][str(count)]
                crops.append(sum(value for key, value in ring.items() if key.startswith("CROP_")))
                pastures.append(int(ring.get("EMPTY_PASTURE", 0)))
                animals.append(int(ring.get("COW", 0)) + int(ring.get("SHEEP", 0)))
            day_result[f"nearest_{count}"] = {
                "crop_occupancy": _stats(crops),
                "empty_pastures": _stats(pastures),
                "animals": _stats(animals),
            }
        result[str(day)] = day_result
    return result


def _coordinate_heatmap(rows: list[dict[str, Any]], animal: str) -> dict[str, float]:
    counts: Counter[str] = Counter()
    for row in rows:
        for x, y in row["positions"].get(animal, []):
            counts[f"{x},{y}"] += 1
    games = max(1, len(rows))
    return {position: count / games for position, count in counts.most_common()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=Path("data/analysis/v36_pasture_expansion.json")
    )
    args = parser.parse_args()
    events: list[dict[str, Any]] = []
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
            events.extend(_events(replay, seat, source, episode_id))
            for day in SNAPSHOT_DAYS:
                row = _snapshot(replay, seat, source, episode_id, day)
                if row is not None:
                    snapshots.append(row)

    payload = {
        "format": FORMAT,
        "runtime_policy_enabled": False,
        "objective": "reconstruct successful pasture builds and Cow/Sheep placements",
        "data": {
            "events": len(events),
            "snapshots": len(snapshots),
            "episodes": len({row["episode_id"] for row in snapshots}),
            "episode_disjoint_split": True,
        },
        "event_summary": {
            source: {
                event: _event_summary(
                    [
                        row
                        for row in events
                        if row["source"] == source and row["event"] == event
                    ]
                )
                for event in ("build", "place")
            }
            for source in SOURCES
        },
        "placement_by_animal": {
            source: {
                animal: _event_summary(
                    [
                        row
                        for row in events
                        if row["source"] == source
                        and row["event"] == "place"
                        and row["animal"] == animal
                    ]
                )
                for animal in ("COW", "SHEEP")
            }
            for source in SOURCES
        },
        "snapshot_summary": {
            source: _snapshot_summary([row for row in snapshots if row["source"] == source])
            for source in SOURCES
        },
        "cow_coordinate_heatmap_day11": {
            source: _coordinate_heatmap(
                [
                    row
                    for row in snapshots
                    if row["source"] == source and row["day"] == 11
                ],
                "COW",
            )
            for source in SOURCES
        },
        "common_strategy_check": {
            "top_sources": sorted(TOP_SOURCES),
            "note": (
                "Rank-specific summaries are retained because a shared mean could hide "
                "the distant-but-route-efficient Rank-3 strategy."
            ),
        },
        "interpretation_limits": [
            "events count successful state transitions, not merely requested actions",
            "nearer-feasible means empty for build or empty-pasture for place at that exact turn",
            "a crop in a future-near ring is not proven waste because crop opportunity value is omitted",
            "layout similarity does not prove final-score improvement",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
