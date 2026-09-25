"""Train and export a standard-library logistic task ranker on paired forks."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY_ROOT = ROOT / "agents/round10_task_learning_20260924"


def sha256_file(path: Path) -> str:
    digest_value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest_value.update(block)
    return digest_value.hexdigest()


def digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sigmoid(score: float) -> float:
    if score >= 0:
        return 1.0 / (1.0 + math.exp(-min(score, 60.0)))
    exp_score = math.exp(max(score, -60.0))
    return exp_score / (1.0 + exp_score)


def log_loss(rows: list[dict[str, Any]], weights: list[float], bias: float) -> float:
    losses = []
    for row in rows:
        probability = sigmoid(bias + sum(w * x for w, x in zip(weights, row["standardized"], strict=True)))
        probability = min(max(probability, 1e-9), 1 - 1e-9)
        label = row["label"]
        losses.append(-(label * math.log(probability) + (1 - label) * math.log(1 - probability)))
    return mean(losses) if losses else 0.0


def split_groups(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    groups = sorted({str(row["group_id"]) for row in rows}, key=lambda value: digest(value))
    if len(groups) < 3:
        raise ValueError("at least three opponent:seed groups are required")
    sizes = {
        "train": max(1, int(len(groups) * 0.60)),
        "validation": max(1, int(len(groups) * 0.20)),
    }
    sizes["test"] = len(groups) - sizes["train"] - sizes["validation"]
    if sizes["test"] < 1:
        sizes["train"] -= 1
        sizes["test"] = 1
    positive_groups = {
        group
        for group in groups
        if any(row["group_id"] == group and row["label"] == 1 for row in rows)
    }
    result: dict[str, list[str]] = {"train": [], "validation": [], "test": []}
    allocation = ("train", "validation", "test", "train")
    for index, group in enumerate(sorted(positive_groups, key=lambda value: digest(value))):
        preferred = allocation[index % len(allocation)]
        available = preferred if len(result[preferred]) < sizes[preferred] else "train"
        result[available].append(group)
    for group in groups:
        if group in positive_groups:
            continue
        target = next(name for name in ("train", "validation", "test") if len(result[name]) < sizes[name])
        result[target].append(group)
    return result


def evaluate(rows: list[dict[str, Any]], model: dict[str, Any], threshold: float) -> dict[str, Any]:
    predictions = []
    for row in rows:
        vector = row["vector"]
        standardized = [
            (value - center) / scale
            for value, center, scale in zip(vector, model["means"], model["scales"], strict=True)
        ]
        probability = sigmoid(
            model["bias"] + sum(weight * value for weight, value in zip(model["weights"], standardized, strict=True))
        )
        selected = probability >= threshold
        predictions.append({**row, "probability": probability, "selected": selected})
    selected = [row for row in predictions if row["selected"]]
    positives = sum(row["label"] for row in predictions)
    correct = sum(int((row["probability"] >= 0.5) == bool(row["label"])) for row in predictions)
    return {
        "rows": len(predictions),
        "positive_labels": positives,
        "accuracy_at_0_5": correct / len(predictions) if predictions else 0.0,
        "selected": len(selected),
        "selected_positive": sum(row["label"] for row in selected),
        "selected_mean_margin_delta": mean(row["margin_delta"] for row in selected) if selected else 0.0,
        "selected_total_margin_delta": sum(row["margin_delta"] for row in selected),
        "all_mean_margin_delta": mean(row["margin_delta"] for row in predictions) if predictions else 0.0,
        "predictions": predictions,
    }


def rule_select(row: dict[str, Any]) -> bool:
    features = row["features"]
    return row["crop"] in {"MELON", "STRAWBERRY"} and (
        float(features["crop_price_300"]) * 300.0 > float(features["fertilizer_price_150"]) * 150.0
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("labels_csv", type=Path)
    parser.add_argument("--model", type=Path, default=POLICY_ROOT / "model.json")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=600)
    parser.add_argument("--learning-rate", type=float, default=0.08)
    parser.add_argument("--l2", type=float, default=0.02)
    args = parser.parse_args()
    labels_path = args.labels_csv if args.labels_csv.is_absolute() else ROOT / args.labels_csv
    with labels_path.open(encoding="utf-8-sig", newline="") as stream:
        raw_rows = list(csv.DictReader(stream))
    rows = []
    feature_names: list[str] | None = None
    excluded: dict[str, int] = {"error": 0, "prefix_mismatch": 0, "execution_not_established": 0}
    for raw in raw_rows:
        if raw.get("error"):
            excluded["error"] += 1
            continue
        if int(raw.get("prefix_match", 0) or 0) != 1:
            excluded["prefix_mismatch"] += 1
            continue
        if int(raw.get("execution_established", 0) or 0) != 1:
            excluded["execution_not_established"] += 1
            continue
        features = json.loads(raw["features_json"])
        if feature_names is None:
            feature_names = list(features)
        if list(features) != feature_names:
            raise ValueError("feature order mismatch")
        delta = float(raw["margin_delta"])
        rows.append(
            {
                "candidate_id": raw["candidate_id"],
                "group_id": raw["group_id"],
                "opponent_id": raw["opponent_id"],
                "seed": int(raw["seed"]),
                "seat": int(raw["seat"]),
                "crop": raw["crop"],
                "features": features,
                "vector": [float(features[name]) for name in feature_names],
                "margin_delta": delta,
                "label": int(delta > 0.0),
            }
        )
    if not rows or feature_names is None:
        raise ValueError("no established training labels")
    splits = split_groups(rows)
    split_rows = {
        name: [row for row in rows if row["group_id"] in groups]
        for name, groups in splits.items()
    }
    train = split_rows["train"]
    means = [mean(row["vector"][index] for row in train) for index in range(len(feature_names))]
    scales = [max(pstdev(row["vector"][index] for row in train), 1e-6) for index in range(len(feature_names))]
    for row in rows:
        row["standardized"] = [
            (value - center) / scale for value, center, scale in zip(row["vector"], means, scales, strict=True)
        ]
    weights = [0.0] * len(feature_names)
    initial_bias = 0.0
    bias = initial_bias
    initial_hash = digest({"weights": weights, "bias": bias})
    curve = []
    for epoch in range(args.epochs + 1):
        if epoch % 20 == 0 or epoch == args.epochs:
            curve.append(
                {
                    "epoch": epoch,
                    "train_log_loss": log_loss(train, weights, bias),
                    "validation_log_loss": log_loss(split_rows["validation"], weights, bias),
                }
            )
        if epoch == args.epochs:
            break
        grad_weights = [0.0] * len(weights)
        grad_bias = 0.0
        for row in train:
            probability = sigmoid(bias + sum(w * x for w, x in zip(weights, row["standardized"], strict=True)))
            error = probability - row["label"]
            grad_bias += error
            for index, value in enumerate(row["standardized"]):
                grad_weights[index] += error * value
        size = max(1, len(train))
        bias -= args.learning_rate * grad_bias / size
        for index in range(len(weights)):
            gradient = grad_weights[index] / size + args.l2 * weights[index]
            weights[index] -= args.learning_rate * gradient
    core_model = {
        "format": "round10-standard-library-logistic-v1",
        "feature_names": feature_names,
        "means": means,
        "scales": scales,
        "weights": weights,
        "bias": bias,
    }
    validation_candidates = []
    for threshold_int in range(20, 96, 5):
        threshold = threshold_int / 100.0
        metrics = evaluate(split_rows["validation"], core_model, threshold)
        validation_candidates.append(
            (
                float(metrics["selected_total_margin_delta"]),
                -int(metrics["selected"]),
                threshold,
                metrics,
            )
        )
    _value, _negative_count, threshold, validation_metrics = max(validation_candidates)
    model = {
        **core_model,
        "threshold": threshold,
        "training": {
            "source_sha256": sha256_file(labels_path),
            "rows": len(rows),
            "unweighted_labels": True,
            "epochs": args.epochs,
            "updates": args.epochs,
            "learning_rate": args.learning_rate,
            "l2": args.l2,
            "group_split": splits,
            "group_split_method": "deterministic positive-group stratification; seats/candidates remain grouped",
            "threshold_selection": "maximize validation selected total margin delta; tie -> fewer selections",
        },
    }
    final_hash = digest({"weights": weights, "bias": bias})
    model_path = args.model if args.model.is_absolute() else ROOT / args.model
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    metrics = {
        name: evaluate(values, model, threshold)
        for name, values in split_rows.items()
    }
    for value in metrics.values():
        value.pop("predictions")
    rule_metrics = {}
    oracle_metrics = {}
    for name, values in split_rows.items():
        selected = [row for row in values if rule_select(row)]
        oracle = [row for row in values if row["margin_delta"] > 0]
        rule_metrics[name] = {
            "selected": len(selected),
            "selected_total_margin_delta": sum(row["margin_delta"] for row in selected),
            "selected_mean_margin_delta": mean(row["margin_delta"] for row in selected) if selected else 0.0,
        }
        oracle_metrics[name] = {
            "diagnostic_only_future_labels": True,
            "selected": len(oracle),
            "selected_total_margin_delta": sum(row["margin_delta"] for row in oracle),
        }
    report = {
        "training_completed": True,
        "included_rows": len(rows),
        "excluded": excluded,
        "positive_rate": sum(row["label"] for row in rows) / len(rows),
        "initial_weight_sha256": initial_hash,
        "final_weight_sha256": final_hash,
        "model_file_sha256": sha256_file(model_path),
        "curve": curve,
        "threshold": threshold,
        "validation_threshold_metrics": {
            key: value for key, value in validation_metrics.items() if key != "predictions"
        },
        "learned_metrics": metrics,
        "rule_metrics": rule_metrics,
        "oracle_diagnostic": oracle_metrics,
        "model": model,
    }
    report_path = args.report if args.report.is_absolute() else ROOT / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    predictions = []
    for split, values in split_rows.items():
        result = evaluate(values, model, threshold)
        for row in result["predictions"]:
            predictions.append(
                {
                    "split": split,
                    "candidate_id": row["candidate_id"],
                    "group_id": row["group_id"],
                    "opponent_id": row["opponent_id"],
                    "seed": row["seed"],
                    "seat": row["seat"],
                    "crop": row["crop"],
                    "margin_delta": row["margin_delta"],
                    "label": row["label"],
                    "probability": row["probability"],
                    "selected": int(row["selected"]),
                    "rule_selected": int(rule_select(row)),
                }
            )
    predictions_path = args.predictions if args.predictions.is_absolute() else ROOT / args.predictions
    predictions_path.parent.mkdir(parents=True, exist_ok=True)
    with predictions_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(predictions[0]))
        writer.writeheader()
        writer.writerows(predictions)
    display_keys = ("included_rows", "positive_rate", "threshold", "learned_metrics", "rule_metrics")
    print(json.dumps({key: report[key] for key in display_keys}, indent=2))
    print(f"model: {model_path}")


if __name__ == "__main__":
    main()
