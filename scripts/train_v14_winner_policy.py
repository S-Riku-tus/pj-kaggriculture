"""Train V14's winner-conditioned 24h/72h strategic goal model.

The source cache contains both seats from 399 deduplicated Top-3 episodes and
keeps every episode in exactly one split.  V14 fits winning sides only and
predicts absolute future portfolio goals.  This is behavior distillation, not
the invalid counterfactual action-value interpretation rejected in V13.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v3.feature_schema import FEATURE_NAMES  # noqa: E402
from scripts.train_v3_strategy import train_forest  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    CACHE_FORMAT,
    PHASES,
    PORTFOLIO,
)

FORMAT = "kaggriculture-v14-winner-goals-v1"
HORIZONS = ("h24", "h72")
TARGET_SCALES = np.asarray([30, 12, 8, 30, 11, 10, 8], dtype=np.float64)
TARGET_IMPORTANCE = np.asarray([1.0, 1.6, 1.8, 1.6, 1.4, 2.2, 2.2])
PROFILE_FEATURE_NAMES = (
    "money_log",
    "land",
    "utilization",
    "hands",
    "own_crop_WHEAT",
    "own_crop_CARROT",
    "own_crop_TOMATO",
    "own_crop_STRAWBERRY",
    "own_crop_MELON",
    "own_animal_COW",
    "own_animal_SHEEP",
    "own_unwatered",
    "own_unfed",
    "demand_WHEAT",
    "demand_CARROT",
    "demand_STRAWBERRY",
    "demand_MILK",
    "demand_WOOL",
    "opp_utilization",
    "opp_crop_WHEAT",
    "opp_crop_STRAWBERRY",
    "opp_animal_COW",
    "opp_animal_SHEEP",
)


def _phase(day: int) -> str:
    for lower, upper in PHASES:
        if lower <= day <= upper:
            return f"{lower}-{upper}"
    return "outside"


def _predict_tree(tree: list[Any], row: np.ndarray) -> list[float]:
    node = tree
    while node[0] == "N":
        node = node[3] if row[int(node[1])] <= float(node[2]) else node[4]
    return [float(value) for value in node[1:]]


def _predict_rows(forest: list[list[Any]], x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    means: list[np.ndarray] = []
    deviations: list[np.ndarray] = []
    for row in x:
        values = np.asarray([_predict_tree(tree, row) for tree in forest], dtype=np.float64)
        means.append(np.mean(values, axis=0))
        deviations.append(np.std(values, axis=0))
    return np.asarray(means), np.asarray(deviations)


def _metrics(actual: np.ndarray, prediction: np.ndarray) -> dict[str, Any]:
    error = np.abs(actual - prediction)
    normalized = (error / TARGET_SCALES) * TARGET_IMPORTANCE
    return {
        "mae": {name: round(float(np.mean(error[:, index])), 4) for index, name in enumerate(PORTFOLIO)},
        "critical_normalized_mae": round(float(np.mean(normalized)), 6),
    }


def _time_baseline(train_day: np.ndarray, train_y: np.ndarray, target_day: np.ndarray) -> np.ndarray:
    overall = np.median(train_y, axis=0)
    by_day = {int(day): np.median(train_y[train_day == day], axis=0) for day in np.unique(train_day)}
    return np.asarray([by_day.get(int(day), overall) for day in target_day])


def _percentile(values: np.ndarray, probability: float) -> float:
    return float(np.quantile(values, probability)) if len(values) else 0.0


def _profiles(rows: list[dict[str, Any]]) -> dict[str, Any]:
    indices = [FEATURE_NAMES.index(name) for name in PROFILE_FEATURE_NAMES]
    groups: dict[str, list[list[float]]] = defaultdict(list)
    for row in rows:
        groups[_phase(int(row["day"]))].append([float(row["features"][index]) for index in indices])
    result: dict[str, Any] = {}
    for phase, values in sorted(groups.items()):
        matrix = np.asarray(values, dtype=np.float64)
        center = np.median(matrix, axis=0)
        mad = np.median(np.abs(matrix - center), axis=0) * 1.4826
        iqr = (np.quantile(matrix, 0.75, axis=0) - np.quantile(matrix, 0.25, axis=0)) / 1.349
        scale = np.maximum(np.maximum(mad, iqr), 0.035)
        z = np.minimum(8.0, np.abs(matrix - center) / scale)
        distance = np.sqrt(np.mean(z * z, axis=1))
        result[phase] = {
            "examples": len(values),
            "feature_indices": indices,
            "center": [round(float(value), 7) for value in center],
            "scale": [round(float(value), 7) for value in scale],
            "distance_p50": round(_percentile(distance, 0.50), 6),
            "distance_p90": round(_percentile(distance, 0.90), 6),
            "distance_p99": round(_percentile(distance, 0.99), 6),
        }
    return result


def _segment_report(
    rows: list[dict[str, Any]],
    split: str,
    horizon: str,
    actual: np.ndarray,
    predictions: dict[str, np.ndarray],
) -> dict[str, Any]:
    split_mask = np.asarray([row["split"] == split for row in rows])
    segments = {
        "all": split_mask,
        "recovery": split_mask & np.asarray([float(row["money_gap_ratio"]) < 0 for row in rows]),
    }
    for source in ("rank1", "rank2", "rank3", "opponent"):
        segments[f"source_{source}"] = split_mask & np.asarray([row["source"] == source for row in rows])
        segments[f"recovery_source_{source}"] = segments["recovery"] & np.asarray(
            [row["source"] == source for row in rows]
        )
    for phase in ("6-9", "10-11", "12-13", "14-17", "18-21", "22-24", "25-27"):
        segments[f"recovery_phase_{phase}"] = segments["recovery"] & np.asarray(
            [_phase(int(row["day"])) == phase for row in rows]
        )
    result: dict[str, Any] = {}
    for name, mask in segments.items():
        if not np.any(mask):
            continue
        result[name] = {
            "rows": int(np.sum(mask)),
            **{policy: _metrics(actual[mask], prediction[mask]) for policy, prediction in predictions.items()},
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=Path, default=Path("data/training/v12_relative_rows.json"))
    parser.add_argument("--trees", type=int, default=36)
    parser.add_argument("--depth", type=int, default=9)
    parser.add_argument("--min-leaf", type=int, default=48)
    parser.add_argument("--seed", type=int, default=20260828)
    parser.add_argument("--output", type=Path, default=Path("agents/v14/winner_goal_model.json"))
    parser.add_argument(
        "--validation-output",
        type=Path,
        default=Path("data/analysis/v14_winner_goal_validation.json"),
    )
    args = parser.parse_args()
    rows_path = args.rows if args.rows.is_absolute() else ROOT / args.rows
    cached = json.loads(rows_path.read_text(encoding="utf-8"))
    if cached.get("format") != CACHE_FORMAT:
        raise ValueError("rebuild the V12 row cache before training V14")
    rows = [row for row in cached["rows"] if row["winner"]]
    x = np.asarray([row["features"] for row in rows], dtype=np.float64)
    day = np.asarray([int(row["day"]) for row in rows], dtype=np.int64)
    split = np.asarray([row["split"] for row in rows])
    training = split == "train"
    validation = split == "validation"
    current = np.asarray(
        [[float(row["current"][item]) for item in PORTFOLIO] for row in rows],
        dtype=np.float64,
    )
    baseline = np.asarray(
        [[float(row["baseline"][item]) for item in PORTFOLIO] for row in rows],
        dtype=np.float64,
    )
    weight = np.asarray(
        [1.15 if float(row["money_gap_ratio"]) < 0 else 1.0 for row in rows],
        dtype=np.float64,
    )
    reports: dict[str, Any] = {}
    uncertainty_p90: dict[str, float] = {}
    for horizon_index, horizon in enumerate(HORIZONS):
        y = np.asarray(
            [[float(row[horizon][item]) for item in PORTFOLIO] for row in rows],
            dtype=np.float64,
        )
        print(f"validation forest: {horizon}", flush=True)
        forest = train_forest(
            x[training],
            y[training],
            weight[training],
            trees=max(18, args.trees // 2),
            depth=args.depth,
            min_leaf=args.min_leaf,
            seed=args.seed + horizon_index * 100,
        )
        prediction, deviation = _predict_rows(forest, x)
        normalized_uncertainty = np.mean(deviation / TARGET_SCALES, axis=1)
        uncertainty_p90[horizon] = float(np.quantile(normalized_uncertainty[validation], 0.90))
        predictions = {
            "model": prediction,
            "crop_model": np.column_stack((prediction[:, :5], baseline[:, 5:])),
            "v11_goal": baseline,
            "unchanged": current,
            "day_median": _time_baseline(day[training], y[training], day),
        }
        reports[horizon] = {
            "validation": _segment_report(rows, "validation", horizon, y, predictions),
            "test": _segment_report(rows, "test", horizon, y, predictions),
            "uncertainty_p90": round(uncertainty_p90[horizon], 6),
        }

    # H24 is deliberately not selected: unchanged state is its best predictor.
    # The only validated use is H72 planning while observably behind.
    recovery = reports["h72"]["validation"]["recovery"]
    enabled = (
        recovery["crop_model"]["critical_normalized_mae"] <= 0.95 * recovery["v11_goal"]["critical_normalized_mae"]
        and recovery["crop_model"]["critical_normalized_mae"] <= 0.98 * recovery["unchanged"]["critical_normalized_mae"]
    )
    selection = {
        "h24": False,
        "h72_recovery": bool(enabled),
        "controls": ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"],
        "recovery_definition": "observable money_gap_ratio < 0",
    }

    final_training = training | validation
    forests: dict[str, list[list[Any]]] = {}
    for horizon_index, horizon in enumerate(HORIZONS):
        y = np.asarray(
            [[float(row[horizon][item]) for item in PORTFOLIO] for row in rows],
            dtype=np.float64,
        )
        print(f"final forest: {horizon}", flush=True)
        forests[horizon] = train_forest(
            x[final_training],
            y[final_training],
            weight[final_training],
            trees=args.trees,
            depth=args.depth,
            min_leaf=args.min_leaf,
            seed=args.seed + 500 + horizon_index * 100,
        )

    episode_split = {
        name: len({row["episode_id"] for row in rows if row["split"] == name})
        for name in ("train", "validation", "test")
    }
    winner_sources = Counter((row["episode_id"], row["source"]) for row in rows)
    source_episode_count = Counter(source for _episode, source in winner_sources)
    payload = {
        "format": FORMAT,
        "created_at": datetime.now().astimezone().isoformat(),
        "enabled": bool(enabled),
        "selection": selection,
        "feature_names": list(FEATURE_NAMES),
        "target_names": list(PORTFOLIO),
        "horizons": {"h24": 24, "h72": 72},
        "target_scales": [float(value) for value in TARGET_SCALES],
        "uncertainty_p90": {name: round(value, 6) for name, value in uncertainty_p90.items()},
        "profiles": _profiles([row for row in rows if row["split"] == "train"]),
        "source": {
            **cached["source"],
            "winner_rows": len(rows),
            "winner_source_episodes": dict(source_episode_count),
        },
        "episode_split": episode_split,
        "hyperparameters": {
            "trees": args.trees,
            "depth": args.depth,
            "min_leaf": args.min_leaf,
            "seed": args.seed,
        },
        "validation_summary": reports,
        "forests": forests,
    }
    validation_payload = {
        "objective": "Winner-conditioned absolute 24h/72h portfolio goals",
        "selection_uses": "validation only; untouched test is reporting only",
        "enabled": bool(enabled),
        "selection": selection,
        "episode_split": episode_split,
        "winner_source_episodes": dict(source_episode_count),
        "reports": reports,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    validation_output = (
        args.validation_output if args.validation_output.is_absolute() else ROOT / args.validation_output
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    validation_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    validation_output.write_text(
        json.dumps(validation_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"enabled": enabled, "episode_split": episode_split, "reports": reports},
            indent=2,
        )
    )
    print(f"model: {output}")
    print(f"validation: {validation_output}")


if __name__ == "__main__":
    main()
