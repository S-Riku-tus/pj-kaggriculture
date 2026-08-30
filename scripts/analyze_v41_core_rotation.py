"""Track how opening core crop cells are reused during animal expansion."""

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

from scripts.analyze_v33_asset_labor import _farm, _tile  # noqa: E402
from scripts.analyze_v34_labor_value import SOURCES, _stats  # noqa: E402
from scripts.analyze_v36_pasture_expansion import _kind, _ring  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    _manifest,
    _observation,
    _replay_path,
    _split,
)

FORMAT = "kaggriculture-v41-core-rotation-v1"
DAYS = (3, 4, 5, 6, 7, 8, 9)
CORE_SIZE = 12


def _crop(tile: Any) -> str:
    if isinstance(tile, dict) and tile.get("kind") == "PLANT":
        return f"CROP_{tile.get('crop', 'UNKNOWN')}"
    return _kind(tile)


def _side(
    replay: dict[str, Any], seat: int, source: str, episode_id: str
) -> dict[str, Any] | None:
    observations = {day: _observation(replay, day * 24, seat) for day in DAYS}
    if any(obs is None for obs in observations.values()):
        return None
    farms = {day: _farm(observations[day], seat) for day in DAYS}
    core = _ring(farms[3], CORE_SIZE)
    states: dict[int, dict[tuple[int, int], dict[str, Any]]] = {}
    for day in DAYS:
        states[day] = {}
        for position in core:
            tile = _tile(farms[day], position)
            states[day][position] = {
                "kind": _crop(tile),
                "planted_day": (
                    int(tile.get("planted_day", -1) or -1)
                    if isinstance(tile, dict) and tile.get("kind") == "PLANT"
                    else -1
                ),
            }
    opening_crops = [
        position for position in core if states[3][position]["kind"].startswith("CROP_")
    ]
    daily = {}
    for day in DAYS:
        counts = Counter(value["kind"] for value in states[day].values())
        refilled = sum(
            states[day][position]["kind"].startswith("CROP_")
            and states[day][position]["planted_day"] > states[3][position]["planted_day"]
            for position in opening_crops
        )
        converted = Counter(states[day][position]["kind"] for position in opening_crops)
        daily[str(day)] = {
            "counts": dict(counts),
            "opening_crop_refilled": refilled,
            "opening_crop_transition": dict(converted),
        }
    return {
        "source": source,
        "episode_id": episode_id,
        "split": _split(episode_id),
        "daily": daily,
        "opening": {
            "positions": [list(position) for position in opening_crops],
            "crop_counts": dict(
                Counter(states[3][position]["kind"] for position in opening_crops)
            ),
        },
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for day in DAYS:
        selected = [row["daily"][str(day)] for row in rows]
        kinds = sorted(
            {
                kind
                for row in selected
                for kind in row["counts"]
            }
        )
        transitions = sorted(
            {
                kind
                for row in selected
                for kind in row["opening_crop_transition"]
            }
        )
        result[str(day)] = {
            "rows": len(selected),
            "core_counts": {
                kind: _stats([row["counts"].get(kind, 0) for row in selected])
                for kind in kinds
            },
            "opening_crop_refilled": _stats(
                [row["opening_crop_refilled"] for row in selected]
            ),
            "opening_crop_transition": {
                kind: _stats(
                    [row["opening_crop_transition"].get(kind, 0) for row in selected]
                )
                for kind in transitions
            },
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=Path("data/analysis/v41_core_rotation.json")
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
        "objective": "measure opening core crop reuse versus conversion to compact animal capacity",
        "data": {
            "rows": len(rows),
            "episodes": len({row["episode_id"] for row in rows}),
            "core_size": CORE_SIZE,
            "episode_disjoint_split": True,
        },
        "opening_crop_counts": {
            source: {
                crop: _stats(
                    [
                        row["opening"]["crop_counts"].get(crop, 0)
                        for row in rows
                        if row["source"] == source
                    ]
                )
                for crop in sorted(
                    {
                        crop
                        for row in rows
                        if row["source"] == source
                        for crop in row["opening"]["crop_counts"]
                    }
                )
            }
            for source in SOURCES
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
            "the core is the nearest 12 unlocked Day-3 cells under deterministic tie-breaking",
            "refill means a later planted_day on an opening crop coordinate, not causal waste",
            "empty core cells can preserve future geometry but also carry crop opportunity cost",
            "rank-specific branches are retained rather than averaged into one teacher",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
