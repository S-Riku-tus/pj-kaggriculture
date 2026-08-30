"""Test whether public history predicts opponent 24/72-turn sell supply.

Model selection and event thresholds use validation episodes only.  The test
split is reported once without fitting on it.  This model is analytical: it is
not wired into an agent until closed-loop value and OOD fallback are shown.
"""

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

from scripts.build_v22_opponent_supply_rows import FORMAT as ROW_FORMAT  # noqa: E402
from scripts.train_v3_strategy import train_forest  # noqa: E402

MODEL_FORMAT = "kaggriculture-v22-opponent-supply-model-v1"


def _predict_tree(tree: list[Any], row: np.ndarray) -> np.ndarray:
    node = tree
    while node[0] == "N":
        node = node[3] if row[int(node[1])] <= float(node[2]) else node[4]
    return np.asarray(node[1:], dtype=np.float64)


def _predict_forest(forest: list[list[Any]], x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    outputs = len(_predict_tree(forest[0], x[0]))
    means = np.zeros((len(x), outputs), dtype=np.float64)
    deviations = np.zeros_like(means)
    for row_index, row in enumerate(x):
        values = np.asarray([_predict_tree(tree, row) for tree in forest])
        means[row_index] = np.mean(values, axis=0)
        deviations[row_index] = np.std(values, axis=0)
    return means, deviations


def _average_precision(actual: np.ndarray, score: np.ndarray) -> float:
    positives = int(np.sum(actual))
    if positives == 0:
        return 0.0
    order = np.argsort(-score, kind="stable")
    sorted_actual = actual[order]
    true_positive = np.cumsum(sorted_actual)
    ranks = np.arange(1, len(actual) + 1)
    return float(np.sum((true_positive / ranks) * sorted_actual) / positives)


def _f1(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    tp = int(np.sum(actual & predicted))
    fp = int(np.sum(~actual & predicted))
    fn = int(np.sum(actual & ~predicted))
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    return {
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / max(1e-12, precision + recall),
    }


def _threshold(actual: np.ndarray, score: np.ndarray) -> float:
    candidates = sorted(
        {
            0.0,
            0.05,
            0.10,
            0.20,
            0.35,
            0.50,
            *np.quantile(score, np.linspace(0.0, 1.0, 31)).tolist(),
        }
    )
    return max(
        candidates,
        key=lambda value: (
            _f1(actual, score >= value)["f1"],
            _f1(actual, score >= value)["precision"],
            value,
        ),
    )


def _metrics(
    mask: np.ndarray,
    actual_quantity: np.ndarray,
    event_score: np.ndarray,
    quantity_score: np.ndarray,
    thresholds: np.ndarray,
    output_names: list[str],
) -> dict[str, Any]:
    report: dict[str, Any] = {"rows": int(np.sum(mask)), "outputs": {}}
    for index, output in enumerate(output_names):
        actual = actual_quantity[mask, index]
        actual_event = actual > 0
        events = event_score[mask, index]
        predicted_event = events >= thresholds[index]
        predicted_quantity = np.where(predicted_event, np.maximum(0.0, quantity_score[mask, index]), 0.0)
        errors = np.abs(actual - predicted_quantity)
        positive = actual_event
        event = _f1(actual_event, predicted_event)
        prevalence = float(np.mean(actual_event))
        report["outputs"][output] = {
            "actual_mean": float(np.mean(actual)),
            "actual_p90": float(np.quantile(actual, 0.90)),
            "event_prevalence": prevalence,
            "event_average_precision": _average_precision(actual_event, events),
            "event_average_precision_uplift_over_prevalence": (
                _average_precision(actual_event, events) / max(1e-12, prevalence)
            ),
            "event_threshold": float(thresholds[index]),
            "event": event,
            "quantity_mae": float(np.mean(errors)),
            "quantity_zero_baseline_mae": float(np.mean(actual)),
            "quantity_positive_mae": float(np.mean(errors[positive])) if np.any(positive) else 0.0,
            "quantity_volume_ratio": float(np.sum(predicted_quantity) / max(1.0, np.sum(actual))),
            "quantity_wape": float(np.sum(errors) / max(1.0, np.sum(actual))),
        }
    values = list(report["outputs"].values())
    report["macro"] = {
        "event_average_precision": float(np.mean([value["event_average_precision"] for value in values])),
        "event_f1": float(np.mean([value["event"]["f1"] for value in values])),
        "quantity_mae": float(np.mean([value["quantity_mae"] for value in values])),
        "quantity_zero_baseline_mae": float(
            np.mean([value["quantity_zero_baseline_mae"] for value in values])
        ),
        "quantity_wape": float(np.mean([value["quantity_wape"] for value in values])),
    }
    return report


def _raw_predictions(prediction: np.ndarray, output_count: int) -> tuple[np.ndarray, np.ndarray]:
    event = np.clip(prediction[:, :output_count], 0.0, 1.0)
    quantity = np.maximum(0.0, np.expm1(prediction[:, output_count:]))
    return event, quantity


def _candidate_score(
    mask: np.ndarray,
    actual: np.ndarray,
    prediction: np.ndarray,
    output_count: int,
) -> float:
    event, quantity = _raw_predictions(prediction, output_count)
    prevalence = np.maximum(0.01, np.mean(actual[mask] > 0, axis=0))
    event_brier = np.mean(((event[mask] - (actual[mask] > 0)) ** 2) / prevalence)
    quantity_scale = np.maximum(1.0, np.mean(actual[mask], axis=0))
    quantity_mae = np.mean(np.abs(quantity[mask] - actual[mask]) / quantity_scale)
    return float(event_brier + quantity_mae)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rows",
        type=Path,
        default=Path("data/training/v22_opponent_supply_rows.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/models/v22_opponent_supply_model.json"),
    )
    parser.add_argument(
        "--validation-output",
        type=Path,
        default=Path("data/analysis/v22_opponent_supply_validation.json"),
    )
    parser.add_argument("--trees", type=int, default=18)
    parser.add_argument("--seed", type=int, default=20261001)
    args = parser.parse_args()
    rows_path = args.rows if args.rows.is_absolute() else ROOT / args.rows
    cache = json.loads(rows_path.read_text(encoding="utf-8"))
    if cache.get("format") != ROW_FORMAT:
        raise ValueError("rebuild V22 opponent-supply rows before training")
    rows = cache["rows"]
    items = list(cache["items"])
    horizons = [int(value) for value in cache["horizons"]]
    output_names = [f"h{horizon}_{item}" for horizon in horizons for item in items]
    x = np.asarray([row["features"] for row in rows], dtype=np.float64)
    quantity = np.asarray(
        [
            [float(row["labels"][f"h{horizon}"][item]) for horizon in horizons for item in items]
            for row in rows
        ],
        dtype=np.float64,
    )
    event = (quantity > 0).astype(np.float64)
    target = np.concatenate((event, np.log1p(quantity)), axis=1)
    split = np.asarray([row["split"] for row in rows])
    target_source = np.asarray([row["target_source"] for row in rows])
    day = np.asarray([int(row["day"]) for row in rows])
    margin = np.asarray([float(row["target_final_margin"]) for row in rows])
    train_mask = split == "train"
    validation_mask = split == "validation"
    test_mask = split == "test"
    weights = np.ones(len(rows), dtype=np.float64)

    candidates = (
        {"depth": 6, "min_leaf": 256},
        {"depth": 8, "min_leaf": 128},
    )
    candidate_reports = []
    forests = []
    predictions = []
    deviations = []
    for index, candidate in enumerate(candidates):
        print(f"training candidate {index + 1}/{len(candidates)}: {candidate}", flush=True)
        forest = train_forest(
            x[train_mask],
            target[train_mask],
            weights[train_mask],
            trees=args.trees,
            depth=int(candidate["depth"]),
            min_leaf=int(candidate["min_leaf"]),
            seed=args.seed + index * 100,
        )
        prediction, deviation = _predict_forest(forest, x)
        score = _candidate_score(validation_mask, quantity, prediction, len(output_names))
        candidate_reports.append({**candidate, "validation_score": score})
        forests.append(forest)
        predictions.append(prediction)
        deviations.append(deviation)
    selected_index = min(range(len(candidates)), key=lambda index: candidate_reports[index]["validation_score"])
    selected = candidates[selected_index]
    forest = forests[selected_index]
    prediction = predictions[selected_index]
    deviation = deviations[selected_index]
    event_score, quantity_score = _raw_predictions(prediction, len(output_names))
    thresholds = np.asarray(
        [
            _threshold(quantity[validation_mask, index] > 0, event_score[validation_mask, index])
            for index in range(len(output_names))
        ]
    )
    uncertainty_limit = np.quantile(
        np.mean(deviation[validation_mask], axis=1),
        0.90,
    )
    uncertainty = np.mean(deviation, axis=1)

    reports: dict[str, Any] = {
        "validation": _metrics(
            validation_mask,
            quantity,
            event_score,
            quantity_score,
            thresholds,
            output_names,
        ),
        "test": _metrics(
            test_mask,
            quantity,
            event_score,
            quantity_score,
            thresholds,
            output_names,
        ),
        "test_confident_90pct_validation_limit": _metrics(
            test_mask & (uncertainty <= uncertainty_limit),
            quantity,
            event_score,
            quantity_score,
            thresholds,
            output_names,
        ),
    }
    for source in sorted(set(target_source[test_mask])):
        reports[f"test_target_{source}"] = _metrics(
            test_mask & (target_source == source),
            quantity,
            event_score,
            quantity_score,
            thresholds,
            output_names,
        )
    for name, lower, upper in (("early", 3, 9), ("middle", 10, 17), ("late", 18, 26)):
        reports[f"test_{name}"] = _metrics(
            test_mask & (day >= lower) & (day <= upper),
            quantity,
            event_score,
            quantity_score,
            thresholds,
            output_names,
        )
    bottom = float(np.quantile(margin[test_mask], 0.25))
    reports["test_target_bottom_margin_quartile"] = _metrics(
        test_mask & (margin <= bottom),
        quantity,
        event_score,
        quantity_score,
        thresholds,
        output_names,
    )

    test_macro = reports["test"]["macro"]
    predictable = bool(
        test_macro["event_average_precision"] >= 0.20
        and test_macro["event_f1"] >= 0.20
        and test_macro["quantity_mae"] < test_macro["quantity_zero_baseline_mae"]
    )
    model = {
        "format": MODEL_FORMAT,
        "analytical_only": True,
        "runtime_enabled": False,
        "predictable_by_predeclared_gate": predictable,
        "feature_names": cache["feature_names"],
        "output_names": output_names,
        "event_thresholds": dict(zip(output_names, thresholds.tolist(), strict=True)),
        "uncertainty_limit": float(uncertainty_limit),
        "selected_hyperparameters": {**selected, "trees": args.trees, "seed": args.seed + selected_index * 100},
        "forest": forest,
        "training": {
            "episode_split": cache["split_episodes"],
            "rows": len(rows),
            "train_rows": int(np.sum(train_mask)),
            "validation_rows": int(np.sum(validation_mask)),
            "test_rows": int(np.sum(test_mask)),
            "target_source_sides": cache["target_source_sides"],
            "feature_privacy": cache["feature_privacy"],
            "label_note": cache["label_note"],
        },
    }
    validation = {
        "objective": "predict opponent SELL volume from public history only",
        "candidate_selection": "minimum validation event-Brier plus scaled quantity-MAE",
        "candidate_reports": candidate_reports,
        "selected_candidate": selected_index,
        "predictable_by_predeclared_gate": predictable,
        "bottom_margin_quartile_threshold": bottom,
        "reports": reports,
        "interpretation": {
            "facts": "validation selects configuration and thresholds; test is untouched during fitting",
            "inference": "predictable=true is necessary but not sufficient for policy value",
            "unverified": "price-forecast gain, closed-loop reward gain, and rating gain",
        },
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    validation_output = (
        args.validation_output if args.validation_output.is_absolute() else ROOT / args.validation_output
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    validation_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(model, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    validation_output.write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "selected": selected,
                "predictable_by_predeclared_gate": predictable,
                "validation_macro": reports["validation"]["macro"],
                "test_macro": reports["test"]["macro"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"model: {output}")
    print(f"validation: {validation_output}")


if __name__ == "__main__":
    main()
