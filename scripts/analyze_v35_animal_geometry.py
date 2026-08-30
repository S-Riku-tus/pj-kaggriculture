"""Separate animal placement geometry from routing overhead.

V34 shows that V11 spends more attributed movement per Cow-day than each top
teacher.  This analysis asks whether public day-start geometry explains that
gap.  Models are trained on top-team episodes only, selected on validation
episodes, and evaluated once on episode-held-out test games.  The V11 residual
is diagnostic: it is not a counterfactual score estimate.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, deque
from pathlib import Path
from statistics import mean, median
from typing import Any

import numpy as np
from kaggle_environments.envs.kaggriculture import kaggriculture as game

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v3.feature_schema import farm_summary  # noqa: E402
from scripts.analyze_v33_asset_labor import _farm  # noqa: E402
from scripts.analyze_v34_labor_value import (  # noqa: E402
    RIDGE_GRID,
    ROW_CACHE_FORMAT,
    SOURCES,
    TOP_SOURCES,
    _metric,
    _observation,
    _phase,
    _ridge_fit,
    _ridge_predict,
    _stats,
)
from scripts.train_v12_relative_policy import _manifest, _replay_path  # noqa: E402

FORMAT = "kaggriculture-v35-animal-geometry-v1"
ANIMALS = ("COW", "SHEEP")
FEATURES = (
    "day_scaled",
    "count_scaled",
    "other_animal_scaled",
    "hands_scaled",
    "utilization",
    "cow_capacity_share",
    "mean_shed_distance_scaled",
    "max_shed_distance_scaled",
    "mean_nearest_same_scaled",
    "components_per_asset",
    "shed_access_fraction",
)


def _positions(farm: dict[str, Any], animal: str) -> list[tuple[int, int]]:
    result = []
    for y, tiles in enumerate(farm.get("tiles") or []):
        for x, tile in enumerate(tiles):
            if isinstance(tile, dict) and str(tile.get("animal") or "") == animal:
                result.append((x, y))
    return result


def _distance(left: tuple[int, int], right: tuple[int, int]) -> int:
    return abs(left[0] - right[0]) + abs(left[1] - right[1])


def _components(positions: list[tuple[int, int]]) -> int:
    remaining = set(positions)
    result = 0
    while remaining:
        result += 1
        queue = deque([remaining.pop()])
        while queue:
            x, y = queue.popleft()
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    queue.append(neighbor)
    return result


def _geometry(farm: dict[str, Any], animal: str) -> dict[str, float]:
    positions = _positions(farm, animal)
    size = len(farm.get("tiles") or [])
    shed = list(game._shed_access_tiles(size)) if size else []
    if not positions:
        return {
            "count": 0.0,
            "mean_shed_distance": 0.0,
            "max_shed_distance": 0.0,
            "mean_nearest_same": 0.0,
            "components": 0.0,
            "shed_access_fraction": 0.0,
        }
    shed_distances = [min(_distance(position, access) for access in shed) for position in positions]
    nearest_same = [
        min(
            (_distance(position, other) for other in positions if other != position),
            default=0,
        )
        for position in positions
    ]
    return {
        "count": float(len(positions)),
        "mean_shed_distance": mean(shed_distances),
        "max_shed_distance": float(max(shed_distances)),
        "mean_nearest_same": mean(nearest_same),
        "components": float(_components(positions)),
        "shed_access_fraction": sum(position in shed for position in positions) / len(positions),
    }


def _feature(row: dict[str, Any]) -> list[float]:
    geometry = row["geometry"]
    values = {
        "day_scaled": float(row["day"]) / 30.0,
        "count_scaled": float(geometry["count"]) / 12.0,
        "other_animal_scaled": float(row["other_animal_count"]) / 12.0,
        "hands_scaled": float(row["hands"]) / 12.0,
        "utilization": float(row["utilization"]),
        "cow_capacity_share": float(row["cow_capacity_share"]),
        "mean_shed_distance_scaled": float(geometry["mean_shed_distance"]) / 10.0,
        "max_shed_distance_scaled": float(geometry["max_shed_distance"]) / 15.0,
        "mean_nearest_same_scaled": float(geometry["mean_nearest_same"]) / 10.0,
        "components_per_asset": float(geometry["components"])
        / max(1.0, float(geometry["count"])),
        "shed_access_fraction": float(geometry["shed_access_fraction"]),
    }
    return [values[name] for name in FEATURES]


def _merge_geometry(cached_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cached = {
        (str(row["source"]), str(row["episode_id"]), int(row["day"])): row
        for row in cached_rows
    }
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for source, directory in SOURCES.items():
        manifests = _manifest(directory)
        for index, manifest in enumerate(manifests, start=1):
            if index == 1 or index % 50 == 0:
                print(f"[{source} {index}/{len(manifests)}]", flush=True)
            episode_id = str(manifest["episode_id"])
            seat = int(manifest["submission_seat"])
            side_key = (source, episode_id, seat)
            if side_key in seen:
                continue
            seen.add(side_key)
            replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
            for day in range(11, 21):
                base = cached.get((source, episode_id, day))
                obs = _observation(replay, day * 24, seat)
                if base is None or obs is None:
                    continue
                farm = _farm(obs, seat)
                summary = farm_summary(farm, day)
                for animal in ANIMALS:
                    geometry = _geometry(farm, animal)
                    count = int(geometry["count"])
                    if count <= 0:
                        continue
                    other = "SHEEP" if animal == "COW" else "COW"
                    movement = float(base["movement"].get(animal, 0) or 0)
                    productive = float(base["productive"].get(animal, 0) or 0)
                    result.append(
                        {
                            "source": source,
                            "episode_id": episode_id,
                            "split": base["split"],
                            "day": day,
                            "animal": animal,
                            "hands": base["hands"],
                            "utilization": summary["utilization"],
                            "cow_capacity_share": base["cow_capacity_share"],
                            "other_animal_count": summary["animals"][other],
                            "geometry": geometry,
                            "movement_per_asset_day": movement / count,
                            "productive_per_asset_day": productive / count,
                            "movement_turns": movement,
                        }
                    )
    return result


def _fit_model(
    train: list[dict[str, Any]],
    validation: list[dict[str, Any]],
    test: list[dict[str, Any]],
    external: list[dict[str, Any]],
) -> dict[str, Any]:
    x_train = np.asarray([_feature(row) for row in train])
    y_train = np.asarray([row["movement_per_asset_day"] for row in train])
    x_validation = np.asarray([_feature(row) for row in validation])
    y_validation = np.asarray([row["movement_per_asset_day"] for row in validation])
    candidates = []
    for alpha in RIDGE_GRID:
        model = _ridge_fit(x_train, y_train, alpha)
        prediction = _ridge_predict(model, x_validation)
        candidates.append((float(np.mean(np.abs(y_validation - prediction))), alpha))
    validation_mae, alpha = min(candidates, key=lambda pair: pair[0])
    fit_rows = train + validation
    model = _ridge_fit(
        np.asarray([_feature(row) for row in fit_rows]),
        np.asarray([row["movement_per_asset_day"] for row in fit_rows]),
        alpha,
    )

    test_actual = np.asarray([row["movement_per_asset_day"] for row in test])
    test_prediction = _ridge_predict(model, np.asarray([_feature(row) for row in test]))
    baseline = np.full_like(test_actual, median(row["movement_per_asset_day"] for row in fit_rows))
    external_actual = np.asarray([row["movement_per_asset_day"] for row in external])
    external_prediction = _ridge_predict(model, np.asarray([_feature(row) for row in external]))
    external_residual = external_actual - external_prediction
    positive_excess_turns = [
        max(0.0, float(residual)) * float(row["geometry"]["count"])
        for row, residual in zip(external, external_residual, strict=True)
    ]
    return {
        "features": list(FEATURES),
        "selected_ridge_alpha": alpha,
        "selection_validation_mae": validation_mae,
        "test": _metric(test_actual, test_prediction),
        "constant_median_test": _metric(test_actual, baseline),
        "v11_external": {
            "actual": _stats(external_actual.tolist()),
            "top_geometry_conditioned_prediction": _stats(external_prediction.tolist()),
            "actual_minus_prediction": _stats(external_residual.tolist()),
            "positive_residual_turns_per_day_upper_bound": _stats(positive_excess_turns),
            "by_phase_actual_minus_prediction": {
                phase: _stats(
                    [
                        float(residual)
                        for row, residual in zip(external, external_residual, strict=True)
                        if _phase(int(row["day"])) == phase
                    ]
                )
                for phase in ("11-13", "14-17", "18-20")
            },
        },
        "top_test_by_source": {
            source: {
                "actual_minus_prediction": _stats(
                    [
                        float(actual - prediction)
                        for row, actual, prediction in zip(
                            test, test_actual, test_prediction, strict=True
                        )
                        if row["source"] == source
                    ]
                )
            }
            for source in sorted(TOP_SOURCES)
        },
    }


def _group_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "rows": len(rows),
        "episodes": len({row["episode_id"] for row in rows}),
        "movement_per_asset_day": _stats(
            [row["movement_per_asset_day"] for row in rows]
        ),
        "productive_per_asset_day": _stats(
            [row["productive_per_asset_day"] for row in rows]
        ),
        "count": _stats([row["geometry"]["count"] for row in rows]),
        "mean_shed_distance": _stats(
            [row["geometry"]["mean_shed_distance"] for row in rows]
        ),
        "max_shed_distance": _stats(
            [row["geometry"]["max_shed_distance"] for row in rows]
        ),
        "mean_nearest_same": _stats(
            [row["geometry"]["mean_nearest_same"] for row in rows]
        ),
        "components_per_asset": _stats(
            [
                row["geometry"]["components"] / row["geometry"]["count"]
                for row in rows
            ]
        ),
        "shed_access_fraction": _stats(
            [row["geometry"]["shed_access_fraction"] for row in rows]
        ),
    }


def _nearest_distances(train: np.ndarray, values: np.ndarray) -> np.ndarray:
    train_norm = np.sum(train * train, axis=1)
    result = []
    for start in range(0, len(values), 256):
        chunk = values[start : start + 256]
        squared = (
            np.sum(chunk * chunk, axis=1)[:, None]
            + train_norm[None, :]
            - 2.0 * chunk @ train.T
        )
        result.extend(np.sqrt(np.maximum(0.0, np.min(squared, axis=1))))
    return np.asarray(result)


def _ood(
    train: list[dict[str, Any]],
    validation: list[dict[str, Any]],
    test: list[dict[str, Any]],
    external: list[dict[str, Any]],
) -> dict[str, Any]:
    raw_train = np.asarray([_feature(row) for row in train])
    center = np.mean(raw_train, axis=0)
    scale = np.std(raw_train, axis=0)
    scale[scale < 1e-9] = 1.0
    normalized_train = (raw_train - center) / scale

    def distance(rows: list[dict[str, Any]]) -> np.ndarray:
        values = (np.asarray([_feature(row) for row in rows]) - center) / scale
        return _nearest_distances(normalized_train, values)

    validation_distance = distance(validation)
    threshold = float(np.quantile(validation_distance, 0.95))

    def report(rows: list[dict[str, Any]]) -> dict[str, Any]:
        values = distance(rows)
        return {
            "rows": len(rows),
            "distance": _stats(values.tolist()),
            "ood_fraction": float(np.mean(values > threshold)),
        }

    return {
        "threshold": threshold,
        "threshold_source": "top-validation p95",
        "top_validation": report(validation),
        "top_test": report(test),
        "v11_external": report(external),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--row-cache",
        type=Path,
        default=Path("data/training/v34_daily_labor_rows.json"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("data/analysis/v35_animal_geometry.json")
    )
    args = parser.parse_args()
    row_cache = args.row_cache if args.row_cache.is_absolute() else ROOT / args.row_cache
    cached = json.loads(row_cache.read_text(encoding="utf-8"))
    if cached.get("format") != ROW_CACHE_FORMAT:
        raise RuntimeError(f"unexpected V34 row cache format: {cached.get('format')}")
    rows = _merge_geometry(list(cached.get("rows") or []))

    analysis: dict[str, Any] = {}
    for animal in ANIMALS:
        animal_rows = [row for row in rows if row["animal"] == animal]
        top = [row for row in animal_rows if row["source"] in TOP_SOURCES]
        train = [row for row in top if row["split"] == "train"]
        validation = [row for row in top if row["split"] == "validation"]
        test = [row for row in top if row["split"] == "test"]
        external = [row for row in animal_rows if row["source"] == "v11"]
        analysis[animal] = {
            "source_summary": {
                source: _group_summary(
                    [row for row in animal_rows if row["source"] == source]
                )
                for source in SOURCES
            },
            "geometry_conditioned_movement_model": _fit_model(
                train, validation, test, external
            ),
            "ood": _ood(train, validation, test, external),
        }

    payload = {
        "format": FORMAT,
        "runtime_policy_enabled": False,
        "objective": "separate public animal placement geometry from realized routing overhead",
        "data": {
            "rows": len(rows),
            "episodes": len({row["episode_id"] for row in rows}),
            "source_rows": dict(Counter(row["source"] for row in rows)),
            "episode_disjoint_split": True,
        },
        "analysis": analysis,
        "interpretation_limits": [
            "movement attribution stops at a non-movement action and looks ahead at most six turns",
            "a positive residual is diagnostic routing overhead, not guaranteed removable movement",
            "geometry is observed at day start while animals may be placed later that day",
            "the model does not value missed service, crop opportunity cost, or final score causally",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
