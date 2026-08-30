"""Compare late crop-cohort concentration and expiry waves.

Day-20 public farm states are sufficient to forecast the engine-defined last
production/decay boundary of every then-live plant.  The report tests whether
V11's Day-24 decay backlog is preceded by a more synchronized planting cohort,
without assuming that any single crop mix is universally optimal.
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

from kaggle_environments.envs.kaggriculture import kaggriculture as game  # noqa: E402

from scripts.analyze_v33_asset_labor import _farm  # noqa: E402
from scripts.analyze_v34_labor_value import SOURCES  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    _manifest,
    _observation,
    _replay_path,
    _split,
)

OUTPUT = ROOT / "data/analysis/v82_crop_cohort_waves.json"
SNAPSHOT_DAY = 20
FORECAST_DAYS = tuple(range(20, 28))
CROPS = tuple(game.CROPS)


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


def _expiry_day(crop: str, planted_day: int) -> int:
    spec = game.CROPS[crop]
    if spec["ongoing"]:
        final_production = (
            planted_day
            + int(spec["first_yield_day"])
            + int(spec["interval"]) * (int(spec["max_yield"]) - 1)
        )
        return final_production + 1
    return planted_day + int(spec["max_yield_day"]) + 1


def _concentration(cohorts: Counter[int]) -> tuple[float, float, int]:
    total = sum(cohorts.values())
    if not total:
        return 0.0, 0.0, 0
    largest_share = max(cohorts.values()) / total
    hhi = sum((count / total) ** 2 for count in cohorts.values())
    return largest_share, hhi, len(cohorts)


def _row(manifest: dict[str, str], source: str) -> dict[str, Any] | None:
    replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
    seat = int(manifest["submission_seat"])
    obs = _observation(replay, SNAPSHOT_DAY * 24, seat)
    if obs is None:
        return None
    farm = _farm(obs, seat)
    cohorts: dict[str, Counter[int]] = {crop: Counter() for crop in CROPS}
    expiry: dict[str, Counter[int]] = {crop: Counter() for crop in CROPS}
    for tiles in farm.get("tiles") or []:
        for tile in tiles:
            if not isinstance(tile, dict) or tile.get("kind") != "PLANT":
                continue
            crop = str(tile.get("crop") or "")
            if crop not in cohorts:
                continue
            planted_day = int(tile.get("planted_day", SNAPSHOT_DAY) or SNAPSHOT_DAY)
            cohorts[crop][planted_day] += 1
            expiry[crop][_expiry_day(crop, planted_day)] += 1

    metrics: dict[str, float] = {}
    all_cohorts: Counter[int] = Counter()
    all_expiry: Counter[int] = Counter()
    for crop in CROPS:
        all_cohorts.update(cohorts[crop])
        all_expiry.update(expiry[crop])
        largest, hhi, distinct = _concentration(cohorts[crop])
        metrics[f"{crop.lower()}_count"] = float(sum(cohorts[crop].values()))
        metrics[f"{crop.lower()}_largest_cohort_share"] = largest
        metrics[f"{crop.lower()}_cohort_hhi"] = hhi
        metrics[f"{crop.lower()}_distinct_plant_days"] = float(distinct)
        metrics[f"{crop.lower()}_largest_expiry_wave"] = float(
            max(expiry[crop].values(), default=0)
        )
        for day in FORECAST_DAYS:
            metrics[f"{crop.lower()}_expiry_day_{day}"] = float(expiry[crop][day])
    largest, hhi, distinct = _concentration(all_cohorts)
    metrics.update(
        {
            "crop_count": float(sum(all_cohorts.values())),
            "all_largest_cohort_share": largest,
            "all_cohort_hhi": hhi,
            "all_distinct_plant_days": float(distinct),
            "all_largest_expiry_wave": float(max(all_expiry.values(), default=0)),
            **{
                f"all_expiry_day_{day}": float(all_expiry[day])
                for day in FORECAST_DAYS
            },
        }
    )
    return {
        "source": source,
        "episode_id": str(manifest["episode_id"]),
        "seat": seat,
        "split": _split(str(manifest["episode_id"])),
        "result": str(manifest.get("result") or "unknown"),
        "reward": float(manifest.get("own_reward") or 0),
        "margin": float(manifest.get("own_reward") or 0)
        - float(manifest.get("opponent_reward") or 0),
        "metrics": metrics,
        "cohorts": {
            crop: {str(day): count for day, count in sorted(values.items())}
            for crop, values in cohorts.items()
        },
        "expiry": {
            crop: {str(day): count for day, count in sorted(values.items())}
            for crop, values in expiry.items()
        },
    }


def _pearson(rows: list[dict[str, Any]], metric: str, outcome: str) -> float:
    if len(rows) < 3:
        return 0.0
    xs = [float(row["metrics"][metric]) for row in rows]
    ys = [float(row[outcome]) for row in rows]
    x_mean, y_mean = mean(xs), mean(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True))
    denominator = math.sqrt(sum((x - x_mean) ** 2 for x in xs)) * math.sqrt(
        sum((y - y_mean) ** 2 for y in ys)
    )
    return numerator / denominator if denominator else 0.0


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"sides": 0}
    metrics = tuple(rows[0]["metrics"])
    predictors = (
        "strawberry_largest_cohort_share",
        "strawberry_largest_expiry_wave",
        "strawberry_expiry_day_24",
        "all_largest_expiry_wave",
        "all_expiry_day_24",
    )
    return {
        "sides": len(rows),
        "metrics": {
            metric: _stats([float(row["metrics"][metric]) for row in rows])
            for metric in metrics
        },
        "descriptive_associations": {
            predictor: {
                outcome: _pearson(rows, predictor, outcome)
                for outcome in ("reward", "margin")
            }
            for predictor in predictors
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
            row = _row(manifest, source)
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
        "format": "kaggriculture-v82-crop-cohort-waves-v1",
        "runtime_policy_enabled": False,
        "scope": {
            "snapshot_day": SNAPSHOT_DAY,
            "forecast_days": list(FORECAST_DAYS),
            "expiry_definition": "installed engine max_lifespan_step mechanics",
            "causal_warning": "cohort associations are descriptive and confounded by policy/source",
        },
        "data": {
            "sides": len(rows),
            "episodes": len({row["episode_id"] for row in rows}),
            "episode_disjoint_split": True,
        },
        "cohorts": {name: _summary(cohort) for name, cohort in cohorts.items()},
        "v11_by_split": {
            split: _summary([row for row in cohorts["v11"] if row["split"] == split])
            for split in ("train", "validation", "test")
        },
        "episode_rows": rows,
        "status": {
            "facts": "Day-20 public crop cohorts and engine-derived expiry days",
            "inferences": "synchronized expiry as a source of late labor congestion",
            "unverified": "causal benefit of changing planting cadence",
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = (
        "strawberry_count",
        "strawberry_largest_cohort_share",
        "strawberry_largest_expiry_wave",
        "strawberry_expiry_day_24",
        "all_largest_expiry_wave",
        "all_expiry_day_24",
    )
    print(
        json.dumps(
            {
                source: {
                    metric: payload["cohorts"][source]["metrics"][metric]["mean"]
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
