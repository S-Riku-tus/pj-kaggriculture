"""Measure how newly unlocked central land is allocated after expansion."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_v33_asset_labor import _farm, _tile  # noqa: E402
from scripts.analyze_v34_labor_value import SOURCES, _stats  # noqa: E402
from scripts.analyze_v36_pasture_expansion import (  # noqa: E402
    _kind,
    _shed_distance,
    _unlocked_positions,
)
from scripts.train_v12_relative_policy import (  # noqa: E402
    _manifest,
    _observation,
    _replay_path,
    _split,
)

FORMAT = "kaggriculture-v42-new-land-allocation-v1"
REFERENCE_DAY = 6
SNAPSHOT_DAYS = (6, 7, 8, 9, 11)
PREFIXES = (4, 8, 12, 20)


def _normalized_kind(tile: Any) -> str:
    kind = _kind(tile)
    return "CROP" if kind.startswith("CROP_") else kind


def _side(
    replay: dict[str, Any], seat: int, source: str, episode_id: str
) -> dict[str, Any] | None:
    day3 = _observation(replay, 3 * 24, seat)
    reference = _observation(replay, REFERENCE_DAY * 24, seat)
    snapshots = {day: _observation(replay, day * 24, seat) for day in SNAPSHOT_DAYS}
    if day3 is None or reference is None or any(obs is None for obs in snapshots.values()):
        return None
    farm3 = _farm(day3, seat)
    reference_farm = _farm(reference, seat)
    size = len(reference_farm.get("tiles") or [])
    previous = set(_unlocked_positions(farm3))
    newly_unlocked = [
        position
        for position in _unlocked_positions(reference_farm)
        if position not in previous
    ]
    newly_unlocked.sort(
        key=lambda position: (
            _shed_distance(position, size),
            position[1],
            position[0],
        )
    )
    daily = {}
    for day, obs in snapshots.items():
        farm = _farm(obs, seat)
        daily[str(day)] = {
            str(prefix): {
                kind: sum(
                    _normalized_kind(_tile(farm, position)) == kind
                    for position in newly_unlocked[:prefix]
                )
                for kind in (
                    "COW",
                    "SHEEP",
                    "EMPTY_PASTURE",
                    "CROP",
                    "EMPTY",
                    "WEED",
                    "LOCKED",
                )
            }
            for prefix in PREFIXES
        }
    return {
        "source": source,
        "episode_id": episode_id,
        "split": _split(episode_id),
        "new_positions": len(newly_unlocked),
        "distance": [_shed_distance(position, size) for position in newly_unlocked],
        "daily": daily,
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        str(day): {
            str(prefix): _prefix_summary(rows, day, prefix)
            for prefix in PREFIXES
        }
        for day in SNAPSHOT_DAYS
    }


def _prefix_summary(
    rows: list[dict[str, Any]], day: int, prefix: int
) -> dict[str, Any]:
    selected = [row for row in rows if row["new_positions"] >= prefix]
    return {
        "rows": len(selected),
        **{
            kind: _stats(
                [row["daily"][str(day)][str(prefix)][kind] for row in selected]
            )
            for kind in (
                "COW",
                "SHEEP",
                "EMPTY_PASTURE",
                "CROP",
                "EMPTY",
                "WEED",
                "LOCKED",
            )
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v42_new_land_allocation.json"),
    )
    args = parser.parse_args()
    rows = []
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
            row = _side(replay, seat, source, episode_id)
            if row is not None:
                rows.append(row)
    payload = {
        "format": FORMAT,
        "runtime_policy_enabled": False,
        "objective": "compare allocation of land locked on Day 3 and unlocked by Day 6",
        "data": {
            "rows": len(rows),
            "episodes": len({row["episode_id"] for row in rows}),
            "new_positions": {
                source: _stats(
                    [row["new_positions"] for row in rows if row["source"] == source]
                )
                for source in SOURCES
            },
            "episode_disjoint_split": True,
        },
        "daily_summary": {
            source: _summary([row for row in rows if row["source"] == source])
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
        "interpretation_limits": [
            "new land is defined by Day-3 locked versus Day-6 unlocked coordinates",
            "prefixes are sorted by shed distance and deterministic coordinates within ties",
            "rank-specific allocation branches are retained",
            "compact animal allocation has crop opportunity cost and is not causal score proof",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
