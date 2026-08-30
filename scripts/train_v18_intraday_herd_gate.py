"""Train the intraday V18 herd gate with episode-held-out evaluation."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_v18_intraday_herd_rows import (  # noqa: E402
    ANIMALS,
)
from scripts.build_v18_intraday_herd_rows import (  # noqa: E402
    FORMAT as ROW_FORMAT,
)
from scripts.train_v3_strategy import train_forest  # noqa: E402
from scripts.train_v14_winner_policy import PROFILE_FEATURE_NAMES  # noqa: E402
from scripts.train_v17_herd_gate import _loss, _predict_forest, _report  # noqa: E402

MODEL_FORMAT = "kaggriculture-v18-intraday-herd-gate-v1"
MIN_PROFILE_CONFIDENCE = 0.35


def _phase(day: int) -> str:
    for lower, upper in ((6, 9), (10, 11), (12, 13), (14, 17), (18, 19)):
        if lower <= day <= upper:
            return f"{lower}-{upper}"
    return "outside"


def _profiles(
    rows: list[dict[str, Any]],
    x: np.ndarray,
    train_mask: np.ndarray,
    feature_names: list[str],
) -> dict[str, Any]:
    profile_names = (*PROFILE_FEATURE_NAMES, "hour")
    indices = [feature_names.index(name) for name in profile_names]
    groups: dict[str, list[np.ndarray]] = defaultdict(list)
    for row, features, selected in zip(rows, x, train_mask, strict=True):
        if selected:
            groups[_phase(int(row["day"]))].append(features[indices])
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
            "distance_p50": round(float(np.quantile(distance, 0.50)), 6),
            "distance_p90": round(float(np.quantile(distance, 0.90)), 6),
            "distance_p99": round(float(np.quantile(distance, 0.99)), 6),
        }
    return result


def _profile_confidence(rows: list[dict[str, Any]], x: np.ndarray, profiles: dict[str, Any]) -> np.ndarray:
    values: list[float] = []
    for row, features in zip(rows, x, strict=True):
        profile = profiles.get(_phase(int(row["day"])))
        if profile is None:
            values.append(0.0)
            continue
        indices = [int(value) for value in profile["feature_indices"]]
        center = np.asarray(profile["center"], dtype=np.float64)
        scale = np.asarray(profile["scale"], dtype=np.float64)
        z = np.minimum(8.0, np.abs(features[indices] - center) / scale)
        distance = math.sqrt(float(np.mean(z * z)))
        p50 = float(profile["distance_p50"])
        p90 = max(p50 + 1e-6, float(profile["distance_p90"]))
        p99 = max(p90 + 1e-6, float(profile["distance_p99"]))
        if distance <= p50:
            confidence = 1.0
        elif distance <= p90:
            confidence = 1.0 - 0.35 * (distance - p50) / (p90 - p50)
        elif distance <= p99:
            confidence = 0.65 - 0.50 * (distance - p90) / (p99 - p90)
        else:
            confidence = max(0.0, 0.15 * math.exp(-(distance - p99)))
        values.append(confidence)
    return np.asarray(values, dtype=np.float64)


def _add_prediction_diagnostics(
    report: dict[str, Any],
    mask: np.ndarray,
    prediction: np.ndarray,
    advantage: np.ndarray,
    deviation: np.ndarray,
) -> None:
    report["advantage_prediction_mae"] = round(float(np.mean(np.abs(prediction[mask] - advantage[mask]))), 6)
    report["uncertainty_p90_observed"] = round(float(np.quantile(deviation[mask], 0.90)), 6)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rows",
        type=Path,
        default=Path("data/training/v18_intraday_herd_rows.json"),
    )
    parser.add_argument("--trees", type=int, default=36)
    parser.add_argument("--depth", type=int, default=7)
    parser.add_argument("--min-leaf", type=int, default=128)
    parser.add_argument("--seed", type=int, default=20260830)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("agents/v18/intraday_herd_gate_model.json"),
    )
    parser.add_argument(
        "--validation-output",
        type=Path,
        default=Path("data/analysis/v18_intraday_herd_gate_validation.json"),
    )
    args = parser.parse_args()
    rows_path = args.rows if args.rows.is_absolute() else ROOT / args.rows
    cache = json.loads(rows_path.read_text(encoding="utf-8"))
    if cache.get("format") != ROW_FORMAT:
        raise ValueError("rebuild the V18 intraday row cache before training")
    rows = cache["rows"]
    feature_names = list(cache["feature_names"])
    x = np.asarray([row["features"] for row in rows], dtype=np.float64)
    current = np.asarray(
        [[float(row["current_owned"][animal]) for animal in ANIMALS] for row in rows],
        dtype=np.float64,
    )
    baseline = np.asarray(
        [[float(row["baseline"][animal]) for animal in ANIMALS] for row in rows],
        dtype=np.float64,
    )
    actual = np.asarray(
        [[float(row["h72"][animal]) for animal in ANIMALS] for row in rows],
        dtype=np.float64,
    )
    split = np.asarray([row["split"] for row in rows])
    recovery = np.asarray([float(row["money_gap_ratio"]) < 0 for row in rows])
    hours = np.asarray([int(row["hour"]) for row in rows])
    final_margin = np.asarray([float(row["final_margin"]) for row in rows])
    train_mask = split == "train"
    profiles = _profiles(rows, x, train_mask, feature_names)
    manifold_confidence = _profile_confidence(rows, x, profiles)
    manifold_eligible = manifold_confidence >= MIN_PROFILE_CONFIDENCE
    validation_mask = (split == "validation") & recovery
    test_mask = (split == "test") & recovery
    validation_eligible = validation_mask & manifold_eligible
    baseline_loss = _loss(baseline, actual)
    freeze_loss = _loss(current, actual)
    advantage = baseline_loss - freeze_loss
    weights = np.asarray(
        [1.2 if float(row["money_gap_ratio"]) < 0 else 1.0 for row in rows],
        dtype=np.float64,
    )

    forest = train_forest(
        x[train_mask],
        advantage[train_mask, None],
        weights[train_mask],
        trees=args.trees,
        depth=args.depth,
        min_leaf=args.min_leaf,
        seed=args.seed,
    )
    prediction, deviation = _predict_forest(forest, x)
    uncertainty_limit = float(np.quantile(deviation[validation_eligible], 0.90))
    candidates = sorted(
        {round(float(value), 6) for value in np.quantile(prediction[validation_eligible], np.linspace(0.0, 1.0, 101))}
    )
    scored: list[tuple[float, float, float]] = []
    for threshold in candidates:
        freeze = (prediction > threshold) & (deviation <= uncertainty_limit) & manifold_eligible
        selected = np.where(freeze[:, None], current, baseline)
        loss = float(np.mean(_loss(selected, actual)[validation_mask]))
        freeze_rate = float(np.mean(freeze[validation_eligible]))
        scored.append((loss, freeze_rate, threshold))
    validation_baseline = float(np.mean(baseline_loss[validation_mask]))
    eligible = [score for score in scored if 0.05 <= score[1] <= 0.95 and score[0] < validation_baseline]
    enabled = bool(eligible)
    selected_loss, selected_rate, threshold = min(
        eligible or scored,
        key=lambda score: (score[0], abs(score[1] - 0.5), score[2]),
    )

    report_masks: list[tuple[str, np.ndarray]] = [
        ("validation_recovery", validation_mask),
        ("test_recovery", test_mask),
    ]
    for hour in sorted(set(hours[test_mask])):
        report_masks.append((f"test_recovery_hour_{hour}", test_mask & (hours == hour)))
    bottom_threshold = float(np.quantile(final_margin[test_mask], 0.25))
    report_masks.append(("test_recovery_bottom_margin_quartile", test_mask & (final_margin <= bottom_threshold)))
    reports: dict[str, Any] = {}
    for name, mask in report_masks:
        report = _report(
            mask,
            current,
            baseline,
            actual,
            prediction,
            deviation,
            threshold,
            uncertainty_limit,
            manifold_eligible,
        )
        _add_prediction_diagnostics(report, mask, prediction, advantage, deviation)
        reports[name] = report

    model = {
        "format": MODEL_FORMAT,
        "enabled": enabled,
        "selection": "validation recovery rows only; test reporting only",
        "feature_names": feature_names,
        "animals": list(ANIMALS),
        "freeze_goal": "placed herd plus shed and worker inventories",
        "day_window": [6, 19],
        "sample_hours": list(cache["sampling"]["hours"]),
        "threshold": threshold,
        "validation_selected_loss": selected_loss,
        "validation_freeze_rate": selected_rate,
        "manifold_min_confidence": MIN_PROFILE_CONFIDENCE,
        "profiles": profiles,
        "uncertainty_limit": uncertainty_limit,
        "forest": forest,
        "training": {
            "seed": args.seed,
            "trees": args.trees,
            "depth": args.depth,
            "min_leaf": args.min_leaf,
            "episode_split": cache["split_episodes"],
            "rows": len(rows),
        },
    }
    validation = {
        "objective": "Choose V11 herd goal or owned herd at intraday states",
        "enabled": enabled,
        "threshold_selected_on": "validation_recovery with runtime fallbacks",
        "threshold": threshold,
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
