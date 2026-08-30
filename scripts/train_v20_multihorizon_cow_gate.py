"""Train a seat-aware Cow gate requiring 24h and 72h agreement."""

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

from scripts.build_v18_intraday_herd_rows import FORMAT as ROW_FORMAT  # noqa: E402
from scripts.train_v3_strategy import train_forest  # noqa: E402
from scripts.train_v17_herd_gate import _predict_forest  # noqa: E402
from scripts.train_v18_intraday_herd_gate import (  # noqa: E402
    MIN_PROFILE_CONFIDENCE,
    _profile_confidence,
    _profiles,
)

MODEL_FORMAT = "kaggriculture-v20-multihorizon-cow-gate-v1"
HORIZONS = ("h24", "h72")
ANIMAL = "COW"


def _report(
    mask: np.ndarray,
    current: np.ndarray,
    baseline: np.ndarray,
    actual: dict[str, np.ndarray],
    freeze: np.ndarray,
    profile_eligible: np.ndarray,
) -> dict[str, Any]:
    selected = np.where(freeze, current, baseline)
    result: dict[str, Any] = {
        "rows": int(np.sum(mask)),
        "freeze_rows": int(np.sum(mask & freeze)),
        "freeze_rate": round(float(np.mean(freeze[mask])), 6),
        "profile_eligible_rate": round(float(np.mean(profile_eligible[mask])), 6),
        "horizons": {},
    }
    correct_all = mask & freeze
    for horizon in HORIZONS:
        baseline_error = np.abs(baseline - actual[horizon])
        current_error = np.abs(current - actual[horizon])
        selected_error = np.abs(selected - actual[horizon])
        correct = mask & freeze & (current_error <= baseline_error)
        correct_all &= current_error <= baseline_error
        result["horizons"][horizon] = {
            "freeze_precision": round(float(np.sum(correct) / max(1, np.sum(mask & freeze))), 6),
            "mae": {
                "selected_gate": round(float(np.mean(selected_error[mask])), 6),
                "v11_goal": round(float(np.mean(baseline_error[mask])), 6),
                "unchanged": round(float(np.mean(current_error[mask])), 6),
            },
        }
    result["freeze_precision_both_horizons"] = round(float(np.sum(correct_all) / max(1, np.sum(mask & freeze))), 6)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rows",
        type=Path,
        default=Path("data/training/v18_intraday_herd_rows.json"),
    )
    parser.add_argument("--trees", type=int, default=30)
    parser.add_argument("--depth", type=int, default=7)
    parser.add_argument("--min-leaf", type=int, default=128)
    parser.add_argument("--seed", type=int, default=20260901)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("agents/v20/multihorizon_cow_gate_model.json"),
    )
    parser.add_argument(
        "--validation-output",
        type=Path,
        default=Path("data/analysis/v20_multihorizon_cow_gate_validation.json"),
    )
    args = parser.parse_args()
    rows_path = args.rows if args.rows.is_absolute() else ROOT / args.rows
    cache = json.loads(rows_path.read_text(encoding="utf-8"))
    if cache.get("format") != ROW_FORMAT:
        raise ValueError("rebuild the multi-horizon intraday cache before V20")
    rows = cache["rows"]
    feature_names = [*cache["feature_names"], "seat"]
    x = np.asarray([[*row["features"], float(row["seat"])] for row in rows], dtype=np.float64)
    current = np.asarray([float(row["current_owned"][ANIMAL]) for row in rows])
    baseline = np.asarray([float(row["baseline"][ANIMAL]) for row in rows])
    actual = {horizon: np.asarray([float(row[horizon][ANIMAL]) for row in rows]) for horizon in HORIZONS}
    split = np.asarray([row["split"] for row in rows])
    recovery = np.asarray([float(row["money_gap_ratio"]) < 0 for row in rows])
    seats = np.asarray([int(row["seat"]) for row in rows])
    hours = np.asarray([int(row["hour"]) for row in rows])
    final_margin = np.asarray([float(row["final_margin"]) for row in rows])
    train_mask = split == "train"
    validation_mask = (split == "validation") & recovery
    test_mask = (split == "test") & recovery
    profiles = _profiles(rows, x, train_mask, feature_names)
    profile_confidence = _profile_confidence(rows, x, profiles)
    profile_eligible = profile_confidence >= MIN_PROFILE_CONFIDENCE
    validation_eligible = validation_mask & profile_eligible
    weights = np.asarray(
        [1.2 if float(row["money_gap_ratio"]) < 0 else 1.0 for row in rows],
        dtype=np.float64,
    )

    forests: dict[str, list[list[Any]]] = {}
    predictions: dict[str, np.ndarray] = {}
    deviations: dict[str, np.ndarray] = {}
    uncertainty_limits: dict[str, float] = {}
    advantages: dict[str, np.ndarray] = {}
    for horizon_index, horizon in enumerate(HORIZONS):
        baseline_error = np.abs(baseline - actual[horizon])
        current_error = np.abs(current - actual[horizon])
        advantage = baseline_error - current_error
        advantages[horizon] = advantage
        print(f"training {horizon}", flush=True)
        forest = train_forest(
            x[train_mask],
            advantage[train_mask, None],
            weights[train_mask],
            trees=args.trees,
            depth=args.depth,
            min_leaf=args.min_leaf,
            seed=args.seed + horizon_index * 100,
        )
        prediction, deviation = _predict_forest(forest, x)
        forests[horizon] = forest
        predictions[horizon] = prediction
        deviations[horizon] = deviation
        uncertainty_limits[horizon] = float(np.quantile(deviation[validation_eligible], 0.90))

    candidates = {
        horizon: sorted(
            {
                round(float(value), 6)
                for value in np.quantile(
                    predictions[horizon][validation_eligible],
                    np.linspace(0.0, 1.0, 21),
                )
            }
        )
        for horizon in HORIZONS
    }
    validation_baseline = {
        horizon: float(np.mean(np.abs(baseline - actual[horizon])[validation_mask])) for horizon in HORIZONS
    }
    required_improvement = {horizon: max(0.01, validation_baseline[horizon] * 0.02) for horizon in HORIZONS}
    scored: list[tuple[float, float, float, float, float]] = []
    for threshold24 in candidates["h24"]:
        for threshold72 in candidates["h72"]:
            freeze = (
                (predictions["h24"] > threshold24)
                & (predictions["h72"] > threshold72)
                & (deviations["h24"] <= uncertainty_limits["h24"])
                & (deviations["h72"] <= uncertainty_limits["h72"])
                & profile_eligible
            )
            selected = np.where(freeze, current, baseline)
            loss24 = float(np.mean(np.abs(selected - actual["h24"])[validation_mask]))
            loss72 = float(np.mean(np.abs(selected - actual["h72"])[validation_mask]))
            freeze_rate = float(np.mean(freeze[validation_eligible]))
            scored.append(((loss24 + loss72) / 2.0, loss24, loss72, freeze_rate, threshold24, threshold72))
    eligible_scores = [
        score
        for score in scored
        if 0.05 <= score[3] <= 0.95
        and score[1] <= validation_baseline["h24"] - required_improvement["h24"]
        and score[2] <= validation_baseline["h72"] - required_improvement["h72"]
    ]
    enabled = bool(eligible_scores)
    selected_score = min(
        eligible_scores or scored,
        key=lambda score: (score[0], abs(score[3] - 0.5), score[4], score[5]),
    )
    _, selected_loss24, selected_loss72, selected_rate, threshold24, threshold72 = selected_score
    thresholds = {"h24": threshold24, "h72": threshold72}
    freeze = (
        (predictions["h24"] > threshold24)
        & (predictions["h72"] > threshold72)
        & (deviations["h24"] <= uncertainty_limits["h24"])
        & (deviations["h72"] <= uncertainty_limits["h72"])
        & profile_eligible
    )

    report_masks: list[tuple[str, np.ndarray]] = [
        ("validation_recovery", validation_mask),
        ("test_recovery", test_mask),
        ("test_recovery_seat_0", test_mask & (seats == 0)),
        ("test_recovery_seat_1", test_mask & (seats == 1)),
    ]
    for hour in sorted(set(hours[test_mask])):
        report_masks.append((f"test_recovery_hour_{hour}", test_mask & (hours == hour)))
    bottom_threshold = float(np.quantile(final_margin[test_mask], 0.25))
    report_masks.append(("test_recovery_bottom_margin_quartile", test_mask & (final_margin <= bottom_threshold)))
    reports = {name: _report(mask, current, baseline, actual, freeze, profile_eligible) for name, mask in report_masks}
    model = {
        "format": MODEL_FORMAT,
        "enabled": enabled,
        "selection": "validation requires material MAE gain at both 24h and 72h",
        "feature_names": feature_names,
        "animal": ANIMAL,
        "horizons": list(HORIZONS),
        "day_window": [6, 19],
        "thresholds": thresholds,
        "uncertainty_limits": uncertainty_limits,
        "profile_min_confidence": MIN_PROFILE_CONFIDENCE,
        "profiles": profiles,
        "forests": forests,
        "training": {
            "seed": args.seed,
            "trees_per_horizon": args.trees,
            "depth": args.depth,
            "min_leaf": args.min_leaf,
            "episode_split": cache["split_episodes"],
            "rows": len(rows),
        },
    }
    validation = {
        "objective": "Freeze Cow only when 24h and 72h winner goals agree",
        "enabled": enabled,
        "selection": {
            "thresholds": thresholds,
            "validation_freeze_rate": selected_rate,
            "validation_selected_mae": {
                "h24": selected_loss24,
                "h72": selected_loss72,
            },
            "validation_v11_mae": validation_baseline,
            "required_improvement": required_improvement,
        },
        "bottom_margin_quartile_threshold": bottom_threshold,
        "reports": reports,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    validation_output = (
        args.validation_output if args.validation_output.is_absolute() else ROOT / args.validation_output
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    validation_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(model, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    validation_output.write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    print(f"model: {output}")
    print(f"validation: {validation_output}")


if __name__ == "__main__":
    main()
