"""Test deployable public-state 24/72-turn price forecasts.

The V22 supply model is frozen.  Price forests train on the original V22
validation episodes.  The original untouched test episodes are deterministically
split into price-validation and price-test, so the support decision and final
confirmation use disjoint games.  Models remain analytical and runtime-disabled.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_v18_intraday_herd_rows import _episode_sources  # noqa: E402
from scripts.build_v22_opponent_supply_rows import FORMAT as ROW_FORMAT  # noqa: E402
from scripts.train_v3_strategy import train_forest  # noqa: E402
from scripts.train_v12_relative_policy import _observation  # noqa: E402
from scripts.train_v22_opponent_supply import _predict_forest, _raw_predictions  # noqa: E402

FORMAT = "kaggriculture-v25-public-price-forecast-v1"
MODEL_FORMAT = "kaggriculture-v22-opponent-supply-model-v1"
BASE_PRICE = {"WHEAT": 25.0, "STRAWBERRY": 120.0, "MILK": 160.0, "WOOL": 200.0}


def _price_partition(episode_id: str) -> str:
    digest = hashlib.sha256(f"v25-price:{episode_id}".encode()).digest()
    return "price_validation" if digest[0] < 128 else "price_test"


def _metrics(mask: np.ndarray, target: np.ndarray, prediction: np.ndarray) -> dict[str, Any]:
    errors = np.abs(target[mask] - prediction[mask])
    by_output = np.mean(errors, axis=0)
    return {
        "rows": int(np.sum(mask)),
        "normalized_mae": float(np.mean(errors)),
        "outputs": [float(value) for value in by_output],
        "p90_row_mae": float(np.quantile(np.mean(errors, axis=1), 0.90)),
    }


def _improvement(base: dict[str, Any], augmented: dict[str, Any]) -> dict[str, float]:
    return {
        "mae_reduction_fraction": (
            (base["normalized_mae"] - augmented["normalized_mae"])
            / max(1e-12, base["normalized_mae"])
        ),
        "p90_reduction_fraction": (
            (base["p90_row_mae"] - augmented["p90_row_mae"])
            / max(1e-12, base["p90_row_mae"])
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rows", type=Path, default=Path("data/training/v22_opponent_supply_rows.json")
    )
    parser.add_argument(
        "--supply-model", type=Path, default=Path("data/models/v22_opponent_supply_model.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("data/analysis/v25_public_price_forecast.json")
    )
    parser.add_argument(
        "--model-output", type=Path, default=Path("data/models/v25_public_price_model.json")
    )
    parser.add_argument("--trees", type=int, default=16)
    parser.add_argument("--seed", type=int, default=20261025)
    parser.add_argument("--target-mode", choices=("absolute", "residual"), default="residual")
    args = parser.parse_args()
    rows_path = args.rows if args.rows.is_absolute() else ROOT / args.rows
    model_path = args.supply_model if args.supply_model.is_absolute() else ROOT / args.supply_model
    cache = json.loads(rows_path.read_text(encoding="utf-8"))
    supply_model = json.loads(model_path.read_text(encoding="utf-8"))
    if cache.get("format") != ROW_FORMAT or supply_model.get("format") != MODEL_FORMAT:
        raise ValueError("V22 row/model format mismatch")

    rows = cache["rows"]
    items = list(cache["items"])
    horizons = [int(value) for value in cache["horizons"]]
    output_names = [f"h{horizon}_{item}" for horizon in horizons for item in items]
    x_public = np.asarray([row["features"] for row in rows], dtype=np.float64)
    supply_raw, supply_deviation = _predict_forest(supply_model["forest"], x_public)
    supply_event, supply_quantity = _raw_predictions(supply_raw, len(output_names))
    supply_features = np.concatenate(
        (
            supply_event,
            np.log1p(supply_quantity) / 5.0,
            np.mean(supply_deviation, axis=1, keepdims=True),
        ),
        axis=1,
    )
    x_augmented = np.concatenate((x_public, supply_features), axis=1)
    target = np.zeros((len(rows), len(output_names)), dtype=np.float64)
    current = np.zeros_like(target)
    row_indices: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        row_indices[str(row["episode_id"])].append(index)
    episode_paths, _sources = _episode_sources()
    for episode_index, episode_id in enumerate(sorted(row_indices), start=1):
        if episode_index == 1 or episode_index % 25 == 0:
            print(f"[{episode_index}/{len(row_indices)}] episode {episode_id}", flush=True)
        replay = json.loads(episode_paths[episode_id].read_text(encoding="utf-8"))
        step_count = len(replay.get("steps") or [])
        for row_index in row_indices[episode_id]:
            row = rows[row_index]
            start = int(row["day"]) * 24 + int(row["hour"])
            seat = int(row["own_seat"])
            observation = _observation(replay, start, seat)
            if observation is None:
                continue
            current_prices = (observation.get("market") or {}).get("prices") or {}
            for horizon_index, horizon in enumerate(horizons):
                stop = min(start + horizon, step_count - 1)
                future = _observation(replay, stop, seat)
                if future is None:
                    continue
                future_prices = (future.get("market") or {}).get("prices") or {}
                for item_index, item in enumerate(items):
                    output = horizon_index * len(items) + item_index
                    base = BASE_PRICE[item]
                    current[row_index, output] = float(current_prices.get(item, base) or 1) / base
                    target[row_index, output] = float(future_prices.get(item, base) or 1) / base

    split = np.asarray([row["split"] for row in rows])
    episode_id = np.asarray([str(row["episode_id"]) for row in rows])
    calibration_train = split == "validation"
    price_partition = np.asarray(
        [_price_partition(value) if split[index] == "test" else "unused" for index, value in enumerate(episode_id)]
    )
    price_validation = price_partition == "price_validation"
    price_test = price_partition == "price_test"
    weights = np.ones(len(rows), dtype=np.float64)
    predictions: dict[str, np.ndarray] = {"current_price": current}
    forests: dict[str, list[Any]] = {}
    uncertainties: dict[str, np.ndarray] = {}
    training_target = target - current if args.target_mode == "residual" else target
    for name, matrix in (("public", x_public), ("public_plus_supply", x_augmented)):
        print(f"training {name} with {matrix.shape[1]} features", flush=True)
        forest = train_forest(
            matrix[calibration_train],
            training_target[calibration_train],
            weights[calibration_train],
            trees=args.trees,
            depth=6,
            min_leaf=64,
            seed=args.seed,
        )
        forests[name] = forest
        prediction, deviation = _predict_forest(forest, matrix)
        uncertainties[name] = np.mean(deviation, axis=1)
        if args.target_mode == "residual":
            prediction = current + prediction
        predictions[name] = np.maximum(1.0 / 200.0, prediction)

    reports: dict[str, Any] = {}
    for name, mask in (("price_validation", price_validation), ("price_test", price_test)):
        reports[name] = {
            method: _metrics(mask, target, prediction)
            for method, prediction in predictions.items()
        }
        reports[name]["supply_feature_improvement"] = _improvement(
            reports[name]["public"], reports[name]["public_plus_supply"]
        )
    validation_gain = reports["price_validation"]["supply_feature_improvement"]
    test_gain = reports["price_test"]["supply_feature_improvement"]
    validation_support = bool(
        validation_gain["mae_reduction_fraction"] >= 0.01
        and validation_gain["p90_reduction_fraction"] >= 0
    )
    test_confirmation = bool(
        validation_support
        and test_gain["mae_reduction_fraction"] > 0
        and test_gain["p90_reduction_fraction"] >= -0.01
    )
    validation_episodes = sorted(set(episode_id[price_validation]))
    test_episodes = sorted(set(episode_id[price_test]))
    payload = {
        "format": FORMAT,
        "objective": "Does frozen opponent-supply prediction improve a public-state future-price model?",
        "target_mode": args.target_mode,
        "output_names": output_names,
        "training_rows": int(np.sum(calibration_train)),
        "price_validation_episodes": len(validation_episodes),
        "price_test_episodes": len(test_episodes),
        "price_episode_disjoint": not bool(set(validation_episodes) & set(test_episodes)),
        "predeclared_support_rule": (
            "price-validation MAE improves >=1% and P90 does not worsen; "
            "price-test confirms positive MAE and P90 degradation <1%"
        ),
        "validation_support": validation_support,
        "untouched_price_test_confirmation": test_confirmation,
        "reports": reports,
        "interpretation": {
            "fact": "all runtime inputs are public; original test games never train either price forest",
            "limit": "teacher/opponent policy distribution differs from a future V14 deployment",
            "runtime": "disabled pending policy-value and OOD validation",
        },
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    model_output = args.model_output if args.model_output.is_absolute() else ROOT / args.model_output
    model_output.parent.mkdir(parents=True, exist_ok=True)
    model_output.write_text(
        json.dumps(
            {
                "format": FORMAT,
                "analytical_only": True,
                "runtime_enabled": False,
                "target_mode": args.target_mode,
                "feature_names": list(cache["feature_names"]),
                "output_names": output_names,
                "public_forest": forests["public"],
                "public_uncertainty_p90": float(
                    np.quantile(uncertainties["public"][calibration_train], 0.90)
                ),
                "training_split": "original V22 validation episodes only",
                "validation_support": validation_support,
                "untouched_price_test_confirmation": test_confirmation,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "validation_support": validation_support,
                "untouched_price_test_confirmation": test_confirmation,
                "price_validation": validation_gain,
                "price_test": test_gain,
            },
            indent=2,
        )
    )
    print(f"result: {output}")
    print(f"model: {model_output}")


if __name__ == "__main__":
    main()
