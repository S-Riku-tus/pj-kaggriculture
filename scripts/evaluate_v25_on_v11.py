"""External-distribution evaluation of the V25 public price model on V11."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_v22_opponent_supply_rows import _history_values, _public_values  # noqa: E402
from scripts.train_v12_relative_policy import _manifest, _observation, _replay_path  # noqa: E402
from scripts.train_v22_opponent_supply import _predict_forest  # noqa: E402

MODEL_FORMAT = "kaggriculture-v25-public-price-forecast-v1"
FORMAT = "kaggriculture-v25-v11-external-price-evaluation-v1"
V11 = ROOT / "data/submissions/v11_submission_55787906"
ITEMS = ("WHEAT", "STRAWBERRY", "MILK", "WOOL")
HORIZONS = (24, 72)
BASE_PRICE = {"WHEAT": 25.0, "STRAWBERRY": 120.0, "MILK": 160.0, "WOOL": 200.0}


def _metrics(mask: np.ndarray, target: np.ndarray, predictions: dict[str, np.ndarray]) -> dict[str, Any]:
    result: dict[str, Any] = {"rows": int(np.sum(mask)), "methods": {}}
    for name, prediction in predictions.items():
        errors = np.abs(target[mask] - prediction[mask])
        result["methods"][name] = {
            "normalized_mae": float(np.mean(errors)),
            "p90_row_mae": float(np.quantile(np.mean(errors, axis=1), 0.90)),
            "outputs": [float(value) for value in np.mean(errors, axis=0)],
        }
    current = result["methods"]["current_price"]
    model = result["methods"]["public_residual"]
    result["model_improvement"] = {
        "mae_reduction_fraction": (
            (current["normalized_mae"] - model["normalized_mae"])
            / max(1e-12, current["normalized_mae"])
        ),
        "p90_reduction_fraction": (
            (current["p90_row_mae"] - model["p90_row_mae"])
            / max(1e-12, current["p90_row_mae"])
        ),
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model", type=Path, default=Path("data/models/v25_public_price_model.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("data/analysis/v25_v11_external_price_evaluation.json")
    )
    args = parser.parse_args()
    model_path = args.model if args.model.is_absolute() else ROOT / args.model
    model = json.loads(model_path.read_text(encoding="utf-8"))
    if model.get("format") != MODEL_FORMAT or model.get("target_mode") != "residual":
        raise ValueError("a residual V25 model is required")
    feature_names = list(model["feature_names"])
    output_names = list(model["output_names"])
    rows: list[list[float]] = []
    targets: list[list[float]] = []
    currents: list[list[float]] = []
    days: list[int] = []
    episodes: set[str] = set()
    for manifest in _manifest(V11):
        episode_id = str(manifest["episode_id"])
        episodes.add(episode_id)
        seat = int(manifest["submission_seat"])
        replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
        step_count = len(replay.get("steps") or [])
        for day in range(3, 27):
            for hour in (0, 6, 12, 18):
                step = day * 24 + hour
                observation = _observation(replay, step, seat)
                if observation is None:
                    continue
                values = _public_values(observation, seat)
                values.update(_history_values(replay, step, seat, observation))
                current_prices = (observation.get("market") or {}).get("prices") or {}
                target_row = []
                current_row = []
                for horizon in HORIZONS:
                    future = _observation(replay, min(step + horizon, step_count - 1), seat)
                    if future is None:
                        break
                    future_prices = (future.get("market") or {}).get("prices") or {}
                    for item in ITEMS:
                        base = BASE_PRICE[item]
                        target_row.append(float(future_prices.get(item, base) or 1) / base)
                        current_row.append(float(current_prices.get(item, base) or 1) / base)
                if len(target_row) != len(output_names):
                    continue
                rows.append([float(values[name]) for name in feature_names])
                targets.append(target_row)
                currents.append(current_row)
                days.append(day)
    x = np.asarray(rows, dtype=np.float64)
    target = np.asarray(targets, dtype=np.float64)
    current = np.asarray(currents, dtype=np.float64)
    residual, deviation = _predict_forest(model["public_forest"], x)
    prediction = np.maximum(1.0 / 200.0, current + residual)
    uncertainty = np.mean(deviation, axis=1)
    confidence_limit = float(model["public_uncertainty_p90"])
    confident = uncertainty <= confidence_limit
    day_values = np.asarray(days)
    predictions = {"current_price": current, "public_residual": prediction}
    reports = {
        "all": _metrics(np.ones(len(x), dtype=bool), target, predictions),
        "confident": _metrics(confident, target, predictions),
        "early": _metrics(day_values <= 9, target, predictions),
        "middle": _metrics((day_values >= 10) & (day_values <= 17), target, predictions),
        "late": _metrics(day_values >= 18, target, predictions),
    }
    overall = reports["all"]["model_improvement"]
    external_support = bool(
        overall["mae_reduction_fraction"] >= 0.10
        and overall["p90_reduction_fraction"] >= 0
        and float(np.mean(confident)) >= 0.70
    )
    payload = {
        "format": FORMAT,
        "objective": "external V11 distribution check for the Top-log-trained price model",
        "episodes": len(episodes),
        "rows": len(x),
        "output_names": output_names,
        "confidence_coverage": float(np.mean(confident)),
        "predeclared_support_rule": "MAE improves >=10%, P90 does not worsen, confidence coverage >=70%",
        "external_support": external_support,
        "reports": reports,
        "interpretation": {
            "fact": "V11 episodes do not train the V25 price forest",
            "limit": "V11 submitted-game distribution still differs from a future modified runtime policy",
            "runtime": "disabled regardless of this external predictive result",
        },
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "external_support": external_support,
                "episodes": len(episodes),
                "rows": len(x),
                "confidence_coverage": float(np.mean(confident)),
                "overall": overall,
            },
            indent=2,
        )
    )
    print(f"result: {output}")


if __name__ == "__main__":
    main()
