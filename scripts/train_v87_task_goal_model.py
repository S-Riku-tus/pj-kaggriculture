"""Validate state-to-task-goal prediction on episode-disjoint Top-3 routes."""

from __future__ import annotations

import gc
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.train_v3_strategy import train_forest  # noqa: E402

SOURCE_DIR = ROOT / "data/training/v87_task_goal_sources"
OUTPUT = ROOT / "data/analysis/v87_task_goal_validation.json"
MODEL_OUTPUT = ROOT / "data/analysis/v87_task_goal_model.json"
SOURCES = ("rank1", "rank2", "rank3")
WORKER_X_INDEX = 78
WORKER_Y_INDEX = 79
CLASS_LIMIT = 22
TRAIN_MODULUS = 40
EVAL_MODULUS = 15
TREES = 10
DEPTH = 7
MIN_LEAF = 40


def _sample_key(row: dict[str, Any]) -> int:
    episode = str(row["episode_id"])
    episode_value = int(episode) if episode.isdigit() else sum(map(ord, episode))
    return episode_value * 1_000_003 + int(row["step"]) * 37 + int(row["unit"]) * 101


def _load_sample() -> dict[str, Any]:
    values: defaultdict[str, list[Any]] = defaultdict(list)
    full_counts: defaultdict[str, Counter[str]] = defaultdict(Counter)
    full_rows: Counter[str] = Counter()
    for source in SOURCES:
        path = SOURCE_DIR / f"{source}.json"
        print(f"loading {source}", flush=True)
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload["rows"]:
            if not row["winner"]:
                continue
            split = str(row["split"])
            goal = str(row["labels"]["goal"])
            full_counts[split][goal] += 1
            full_rows[split] += 1
            modulus = TRAIN_MODULUS if split == "train" else EVAL_MODULUS
            if _sample_key(row) % modulus:
                continue
            labels = row["labels"]
            features = row["features"]
            values["x"].append(features)
            values["goal"].append(goal)
            values["split"].append(split)
            values["source"].append(source)
            values["episode"].append(str(row["episode_id"]))
            values["completed"].append(bool(labels["completed"]))
            values["continuous"].append(
                [
                    float(labels["endpoint_x"]) - float(features[WORKER_X_INDEX]),
                    float(labels["endpoint_y"]) - float(features[WORKER_Y_INDEX]),
                    float(labels["horizon"]),
                    float(labels["future24_money_gap_ratio"]),
                    float(labels["future72_money_gap_ratio"]),
                    float(labels["future24_productive_gap"]),
                    float(labels["future72_productive_gap"]),
                ]
            )
        del payload
        gc.collect()
    return {
        "x": np.asarray(values["x"], dtype=np.float64),
        "goal": np.asarray(values["goal"], dtype=object),
        "split": np.asarray(values["split"], dtype=object),
        "source": np.asarray(values["source"], dtype=object),
        "episode": np.asarray(values["episode"], dtype=object),
        "completed": np.asarray(values["completed"], dtype=bool),
        "continuous": np.asarray(values["continuous"], dtype=np.float64),
        "full_counts": full_counts,
        "full_rows": full_rows,
    }


def _episode_weights(episodes: np.ndarray) -> np.ndarray:
    counts = Counter(str(value) for value in episodes)
    weights = np.asarray([1.0 / counts[str(value)] for value in episodes])
    return weights / np.mean(weights)


def _predict_tree(tree: list[Any], row: np.ndarray) -> np.ndarray:
    node = tree
    while node[0] == "N":
        node = node[3] if row[node[1]] <= node[2] else node[4]
    return np.asarray(node[1:], dtype=np.float64)


def _predict(forest: list[list[Any]], x: np.ndarray, outputs: int) -> np.ndarray:
    prediction = np.empty((len(x), outputs), dtype=np.float64)
    for row_index, row in enumerate(x):
        prediction[row_index] = np.mean([_predict_tree(tree, row) for tree in forest], axis=0)
    return prediction


def _weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    return float(np.average(values.astype(np.float64), weights=weights))


def _classification_metrics(
    truth: np.ndarray,
    prediction: np.ndarray,
    probabilities: np.ndarray,
    classes: list[str],
    weights: np.ndarray,
) -> dict[str, Any]:
    correct = truth == prediction
    recalls = []
    for name in classes:
        mask = truth == name
        if np.any(mask):
            recalls.append(_weighted_mean(correct[mask], weights[mask]))
    confidence = np.max(probabilities, axis=1)
    calibration = []
    for low, high in ((0.0, 0.4), (0.4, 0.55), (0.55, 0.7), (0.7, 0.85), (0.85, 1.01)):
        mask = (confidence >= low) & (confidence < high)
        if np.any(mask):
            calibration.append(
                {
                    "range": [low, high],
                    "rows": int(np.sum(mask)),
                    "confidence": round(_weighted_mean(confidence[mask], weights[mask]), 4),
                    "accuracy": round(_weighted_mean(correct[mask], weights[mask]), 4),
                }
            )
    return {
        "rows": len(truth),
        "episode_balanced_accuracy": round(_weighted_mean(correct, weights), 5),
        "row_accuracy": round(float(np.mean(correct)), 5),
        "episode_balanced_macro_recall": round(float(np.mean(recalls)), 5),
        "calibration": calibration,
    }


def _operation_metrics(truth: np.ndarray, prediction: np.ndarray, weights: np.ndarray) -> dict[str, float]:
    truth_operations = np.asarray([value.split(":", 1)[0] for value in truth])
    predicted_operations = np.asarray([value.split(":", 1)[0] for value in prediction])
    correct = truth_operations == predicted_operations
    return {
        "episode_balanced_accuracy": round(_weighted_mean(correct, weights), 5),
        "row_accuracy": round(float(np.mean(correct)), 5),
    }


def _evaluate(
    data: dict[str, Any],
    mask: np.ndarray,
    prediction: np.ndarray,
    classes: list[str],
    train_prior: np.ndarray,
    ood: np.ndarray,
) -> dict[str, Any]:
    indices = np.flatnonzero(mask)
    truth_raw = data["goal"][indices]
    truth = np.asarray([value if value in classes else "OTHER" for value in truth_raw])
    probabilities = prediction[indices, : len(classes)]
    predicted = np.asarray([classes[index] for index in np.argmax(probabilities, axis=1)])
    weights = _episode_weights(data["episode"][indices])
    baseline_name = classes[int(np.argmax(train_prior))]
    baseline = np.full(len(indices), baseline_name, dtype=object)
    metrics = _classification_metrics(truth, predicted, probabilities, classes, weights)
    metrics["operation"] = _operation_metrics(truth, predicted, weights)
    metrics["majority_baseline"] = _classification_metrics(
        truth,
        baseline,
        np.tile(train_prior, (len(indices), 1)),
        classes,
        weights,
    )
    completed = data["completed"][indices]
    actual_continuous = data["continuous"][indices]
    predicted_continuous = prediction[indices, len(classes) :]
    completed_weights = weights[completed]
    metrics["continuous"] = {
        "completed_endpoint_dx_mae": round(
            _weighted_mean(
                np.abs(actual_continuous[completed, 0] - predicted_continuous[completed, 0]),
                completed_weights,
            ),
            5,
        ),
        "completed_endpoint_dy_mae": round(
            _weighted_mean(
                np.abs(actual_continuous[completed, 1] - predicted_continuous[completed, 1]),
                completed_weights,
            ),
            5,
        ),
        "completed_horizon_mae_turns": round(
            6
            * _weighted_mean(
                np.abs(actual_continuous[completed, 2] - predicted_continuous[completed, 2]),
                completed_weights,
            ),
            5,
        ),
    }
    metrics["ood"] = {
        "rows": int(np.sum(ood[indices])),
        "rate": round(float(np.mean(ood[indices])), 5),
    }
    for label, local_mask in (("in_distribution", ~ood[indices]), ("out_of_distribution", ood[indices])):
        if np.any(local_mask):
            metrics["ood"][label] = round(_weighted_mean((truth == predicted)[local_mask], weights[local_mask]), 5)
    metrics["confidence_gates"] = {}
    confidence = np.max(probabilities, axis=1)
    for threshold in (0.30, 0.40, 0.55):
        confident = confidence >= threshold
        if np.any(confident):
            metrics["confidence_gates"][str(threshold)] = {
                "rows": int(np.sum(confident)),
                "coverage": round(_weighted_mean(confident, weights), 5),
                "goal_accuracy": round(
                    _weighted_mean((truth == predicted)[confident], weights[confident]),
                    5,
                ),
                "operation_accuracy": _operation_metrics(truth[confident], predicted[confident], weights[confident])[
                    "episode_balanced_accuracy"
                ],
            }
    return metrics


def main() -> None:
    data = _load_sample()
    train_mask = data["split"] == "train"
    train_goal_counts = Counter(str(value) for value in data["goal"][train_mask])
    classes = [name for name, _count in train_goal_counts.most_common(CLASS_LIMIT - 1)]
    classes.append("OTHER")
    class_index = {name: index for index, name in enumerate(classes)}
    train_goals = np.asarray([value if value in class_index else "OTHER" for value in data["goal"]])
    one_hot = np.zeros((len(data["x"]), len(classes)), dtype=np.float64)
    one_hot[np.arange(len(one_hot)), [class_index[value] for value in train_goals]] = 1.0
    outputs = np.column_stack((one_hot, data["continuous"]))
    train_weights = _episode_weights(data["episode"][train_mask])
    print(
        f"training rows={int(np.sum(train_mask))} features={data['x'].shape[1]} outputs={outputs.shape[1]}",
        flush=True,
    )
    forest = train_forest(
        data["x"][train_mask],
        outputs[train_mask],
        train_weights,
        trees=TREES,
        depth=DEPTH,
        min_leaf=MIN_LEAF,
        seed=8701,
    )
    prediction = _predict(forest, data["x"], outputs.shape[1])

    train_prior = np.average(one_hot[train_mask], axis=0, weights=train_weights)
    train_x = data["x"][train_mask]
    median = np.median(train_x, axis=0)
    q25 = np.quantile(train_x, 0.25, axis=0)
    q75 = np.quantile(train_x, 0.75, axis=0)
    usable = q75 - q25 > 1e-6
    z = np.max(
        np.abs((data["x"][:, usable] - median[usable]) / (q75[usable] - q25[usable])),
        axis=1,
    )
    threshold = float(np.quantile(z[train_mask], 0.99))
    ood = z > threshold

    evaluations: dict[str, Any] = {}
    for split in ("validation", "test"):
        split_mask = data["split"] == split
        evaluations[split] = _evaluate(data, split_mask, prediction, classes, train_prior, ood)
        for source in SOURCES:
            evaluations[f"{split}:{source}"] = _evaluate(
                data,
                split_mask & (data["source"] == source),
                prediction,
                classes,
                train_prior,
                ood,
            )

    result = {
        "format": "kaggriculture-v87-task-goal-validation-v1",
        "sample": {
            "full_winner_rows": dict(data["full_rows"]),
            "sample_rows": Counter(str(value) for value in data["split"]),
            "train_modulus": TRAIN_MODULUS,
            "evaluation_modulus": EVAL_MODULUS,
            "episode_balanced_training": True,
        },
        "classes": classes,
        "training": {"trees": TREES, "depth": DEPTH, "min_leaf": MIN_LEAF},
        "ood": {
            "definition": "diagonal-IQR max distance above the train 99th percentile",
            "threshold": round(threshold, 5),
            "usable_features": int(np.sum(usable)),
        },
        "evaluations": evaluations,
        "limits": [
            "direct goal prediction cannot compare unchosen candidate tasks",
            "the compact global state omits the complete spatial board layout",
            "source identity is excluded from features and prediction",
            "future-state labels remain observational outcomes, not causal advantages",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=dict), encoding="utf-8")
    model = {
        "format": "kaggriculture-v87-task-goal-model-v1",
        "enabled": False,
        "feature_count": int(data["x"].shape[1]),
        "classes": classes,
        "continuous_targets": [
            "endpoint_dx",
            "endpoint_dy",
            "horizon",
            "future24_money_gap_ratio",
            "future72_money_gap_ratio",
            "future24_productive_gap",
            "future72_productive_gap",
        ],
        "forest": forest,
        "ood": {
            "indices": [int(index) for index in np.flatnonzero(usable)],
            "center": [round(float(value), 8) for value in median[usable]],
            "scale": [round(float(value), 8) for value in (q75 - q25)[usable]],
            "threshold": round(threshold, 8),
        },
        "gate": {
            "minimum_probability": 0.40,
            "validation": evaluations["validation"]["confidence_gates"]["0.4"],
            "test": evaluations["test"]["confidence_gates"]["0.4"],
        },
        "training": result["training"],
        "limits": result["limits"],
    }
    MODEL_OUTPUT.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
    concise = {
        key: {
            "accuracy": value["episode_balanced_accuracy"],
            "baseline": value["majority_baseline"]["episode_balanced_accuracy"],
            "ood_rate": value["ood"]["rate"],
        }
        for key, value in evaluations.items()
    }
    print(json.dumps(concise, indent=2))
    print(f"result: {OUTPUT}")
    print(f"model: {MODEL_OUTPUT}")


if __name__ == "__main__":
    main()
