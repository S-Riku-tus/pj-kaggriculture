"""Classify late WATER actions by deterministic crop value and deadline.

The raw missed-water count includes intentionally abandoned or exhausted
plants.  This report instead evaluates the public tile at the decision that
issued WATER, using the same mechanics helpers as V14's deterministic
executor.  It separates emergency/output-useful WATER, preventive survival
WATER, and WATER on exhausted ongoing crops.
"""

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

from agents.v14 import main as v14  # noqa: E402
from scripts.analyze_v33_asset_labor import (  # noqa: E402
    _actions,
    _farm,
    _positions,
    _tile,
)
from scripts.analyze_v34_labor_value import SOURCES  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    _manifest,
    _observation,
    _replay_path,
    _split,
)

OUTPUT = ROOT / "data/analysis/v80_late_water_value.json"
DAYS = tuple(range(20, 25))
CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
METRICS = (
    "water_total",
    "water_useful",
    "water_emergency",
    "water_output_window",
    "water_preventive",
    "water_exhausted",
    "useful_share",
    "preventive_share",
    "exhausted_share",
    "start_harvestable_tiles",
    "start_harvestable_units",
    "start_exhausted_tiles",
    "start_decaying_tiles",
)


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = probability * (len(ordered) - 1)
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "median": 0.0, "p10": 0.0, "p90": 0.0}
    return {
        "mean": mean(values),
        "median": median(values),
        "p10": _percentile(values, 0.10),
        "p90": _percentile(values, 0.90),
    }


def _start_state(farm: dict[str, Any], day: int, step: int) -> Counter[str]:
    counts: Counter[str] = Counter()
    for _x, _y, tile in v14.base._iter_tiles(farm):
        if v14.base._tile_kind(tile) != "PLANT":
            continue
        crop = str(v14.base._get(tile, "crop") or "")
        data = v14.base.CROP_DATA.get(crop)
        if data is None:
            continue
        age = day - v14.base._as_int(v14.base._get(tile, "planted_day", day))
        units = max(0, v14.base._as_int(v14.base._get(tile, "yield_units", 0)))
        if data["ongoing"]:
            harvestable = units > 0 and (units >= 2 or day >= 27)
        else:
            harvestable = units > 0 and age >= data["peak"]
        if harvestable:
            counts["start_harvestable_tiles"] += 1
            counts["start_harvestable_units"] += units
        if v14.v4._ongoing_finished(tile, day):
            counts["start_exhausted_tiles"] += 1
        lifespan = v14.base._as_int(v14.base._get(tile, "max_lifespan_step", -1), -1)
        if lifespan >= 0 and step >= lifespan and units > 0:
            counts["start_decaying_tiles"] += 1
    return counts


def _water_kind(tile: Any, day: int) -> str:
    if not isinstance(tile, dict) or tile.get("kind") != "PLANT":
        return "invalid"
    if v14.v4._ongoing_finished(tile, day):
        return "exhausted"
    if v14.base._as_int(v14.base._get(tile, "consecutive_unwatered", 0)) >= 1:
        return "emergency"
    if v14.v4._water_is_useful(tile, day):
        return "output_window"
    return "preventive"


def _day_row(
    replay: dict[str, Any], manifest: dict[str, str], source: str, day: int
) -> dict[str, Any] | None:
    seat = int(manifest["submission_seat"])
    start_obs = _observation(replay, day * 24, seat)
    if start_obs is None:
        return None
    counts = _start_state(_farm(start_obs, seat), day, day * 24)
    crop_kinds: dict[str, Counter[str]] = {crop: Counter() for crop in CROPS}
    for step in range(day * 24, (day + 1) * 24):
        obs = _observation(replay, step, seat)
        if obs is None:
            continue
        farm = _farm(obs, seat)
        positions = _positions(farm)
        actions = _actions(replay, step, seat)
        for unit in range(min(len(positions), len(actions))):
            action = actions[unit]
            if not action or str(action[0]) != "WATER":
                continue
            tile = _tile(farm, positions[unit])
            kind = _water_kind(tile, day)
            crop = str((tile or {}).get("crop") or "UNKNOWN") if isinstance(tile, dict) else "UNKNOWN"
            counts["water_total"] += 1
            counts[f"water_{kind}"] += 1
            if kind in {"emergency", "output_window"}:
                counts["water_useful"] += 1
            if crop in crop_kinds:
                crop_kinds[crop][kind] += 1
                crop_kinds[crop]["total"] += 1
    total = max(1, counts["water_total"])
    metrics = {
        **{metric: float(counts[metric]) for metric in METRICS if not metric.endswith("share")},
        "useful_share": counts["water_useful"] / total,
        "preventive_share": counts["water_preventive"] / total,
        "exhausted_share": counts["water_exhausted"] / total,
    }
    return {
        "source": source,
        "episode_id": str(manifest["episode_id"]),
        "split": _split(str(manifest["episode_id"])),
        "result": str(manifest.get("result") or "unknown"),
        "day": day,
        "metrics": metrics,
        "crop_kinds": {crop: dict(values) for crop, values in crop_kinds.items()},
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"episode_days": 0}
    crop_kinds = ("emergency", "output_window", "preventive", "exhausted", "invalid", "total")
    return {
        "episode_days": len(rows),
        **{
            metric: _stats([float(row["metrics"][metric]) for row in rows])
            for metric in METRICS
        },
        "crop_water_per_episode_day": {
            crop: {
                kind: sum(int(row["crop_kinds"][crop].get(kind, 0)) for row in rows)
                / len(rows)
                for kind in crop_kinds
            }
            for crop in CROPS
        },
    }


def main() -> None:
    rows: list[dict[str, Any]] = []
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

    cohorts: dict[str, list[dict[str, Any]]] = {
        source: [row for row in rows if row["source"] == source]
        for source in SOURCES
    }
    cohorts["top3_all"] = [row for row in rows if str(row["source"]).startswith("rank")]
    cohorts["top3_win"] = [
        row
        for row in rows
        if str(row["source"]).startswith("rank") and row["result"] == "win"
    ]
    payload = {
        "format": "kaggriculture-v80-late-water-value-v1",
        "runtime_policy_enabled": False,
        "scope": {
            "days": list(DAYS),
            "useful_definition": "V14 deterministic executor: emergency survival or output-window WATER",
            "preventive_definition": "survival-prepay WATER outside the current output window",
            "exhausted_definition": "ongoing crop completed final production and has no held yield",
            "causal_warning": "descriptive action classification, not an intervention estimate",
        },
        "data": {
            "episode_days": len(rows),
            "episodes": len({row["episode_id"] for row in rows}),
            "episode_disjoint_split": True,
        },
        "cohorts": {
            name: {
                "all": _summary(cohort),
                "by_day": {
                    str(day): _summary([row for row in cohort if row["day"] == day])
                    for day in DAYS
                },
            }
            for name, cohort in cohorts.items()
        },
        "v11_by_split": {
            split: _summary([row for row in cohorts["v11"] if row["split"] == split])
            for split in ("train", "validation", "test")
        },
        "status": {
            "facts": "public tile and action states from stored replays plus installed mechanics",
            "inferences": "whether V11's local WATER override spends capacity inefficiently",
            "unverified": "causal benefit of suppressing any WATER category",
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = (
        "water_total",
        "useful_share",
        "preventive_share",
        "exhausted_share",
        "start_harvestable_units",
        "start_exhausted_tiles",
        "start_decaying_tiles",
    )
    print(
        json.dumps(
            {
                source: {
                    metric: payload["cohorts"][source]["all"][metric]["mean"]
                    for metric in compact
                }
                for source in ("v11", "rank1", "rank2", "rank3", "top3_win")
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"result: {OUTPUT}")


if __name__ == "__main__":
    main()
