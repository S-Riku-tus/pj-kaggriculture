"""Train an episode-disjoint gate for accepting a whole joint assignment change."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v92 import main as v92  # noqa: E402
from scripts.train_v3_strategy import train_forest  # noqa: E402

META_INPUT = ROOT / "data/analysis/joint_assignment_meta_validation_dense.json"
TEST_INPUT = ROOT / "data/analysis/joint_assignment_holdout_dense.json"
OUTPUT = ROOT / "data/analysis/joint_assignment_gate_validation.json"
MODEL_OUTPUT = ROOT / "data/analysis/joint_assignment_gate_model.json"
TREES = 32
DEPTH = 5
MIN_LEAF = 8

AGGREGATE_FEATURES = (
    "day",
    "hour",
    "hands",
    "tasks",
    "current_money_gap_ratio",
    "current_productive_gap",
    "eligible_workers",
    "ood_workers",
    "joint_changed_units",
    "joint_mean_model_gain",
    "joint_minimum_model_gain",
    "joint_maximum_model_gain",
    "joint_priority_delta",
    "joint_distance_delta",
    "joint_emergency_displaced",
    "joint_immediate_displaced",
    "joint_same_operation_rate",
    "independent_duplicate_choices",
    *(f"joint_after_{operation.lower()}" for operation in v92.OPERATIONS),
)
FEATURE_NAMES = (*v92.v14.v3.FEATURE_NAMES, *AGGREGATE_FEATURES)


def _episode_bucket(value: str) -> int:
    return (int(value) if value.isdigit() else sum(map(ord, value))) % 5


def _features(row: dict[str, Any]) -> list[float]:
    meta = row["meta"]
    operations = meta.get("joint_after_operations") or {}
    aggregates = [
        float(row["day"]) / 29.0,
        float(row["hour"]) / 23.0,
        float(row["hands"]) / 14.0,
        min(3.0, float(row["tasks"]) / 80.0),
        float(row["current_money_gap_ratio"]),
        float(row["current_productive_gap"]) / 75.0,
        float(meta["eligible_workers"]) / 14.0,
        float(meta["ood_workers"]) / 14.0,
        float(meta["joint_changed_units"]) / 14.0,
        float(meta["joint_mean_model_gain"]),
        float(meta["joint_minimum_model_gain"]),
        float(meta["joint_maximum_model_gain"]),
        float(meta["joint_priority_delta"]) / 16_000.0,
        float(meta["joint_distance_delta"]) / 36.0,
        float(meta["joint_emergency_displaced"]) / 14.0,
        float(meta["joint_immediate_displaced"]) / 14.0,
        float(meta["joint_same_operation_rate"]),
        float(meta["independent_duplicate_choices"]) / 14.0,
        *(float(operations.get(operation, 0)) / 14.0 for operation in v92.OPERATIONS),
    ]
    values = [*[float(value) for value in row["global_features"]], *aggregates]
    if len(values) != len(FEATURE_NAMES):
        raise RuntimeError(f"feature mismatch: {len(values)} != {len(FEATURE_NAMES)}")
    return values


def _predict_tree(tree: list[Any], features: np.ndarray) -> float:
    node = tree
    while node[0] == "N":
        node = node[3] if features[int(node[1])] <= float(node[2]) else node[4]
    return float(node[1])


def _predict(forest: list[list[Any]], x: np.ndarray) -> np.ndarray:
    return np.asarray(
        [sum(_predict_tree(tree, features) for tree in forest) / len(forest) for features in x],
        dtype=np.float64,
    )


def _weights(rows: list[dict[str, Any]], indices: np.ndarray) -> np.ndarray:
    counts = Counter(rows[index]["episode_id"] for index in indices)
    values = np.asarray([1.0 / counts[rows[index]["episode_id"]] for index in indices], dtype=np.float64)
    return values / max(1e-12, float(np.mean(values)))


def _training_weights(rows: list[dict[str, Any]], indices: np.ndarray, labels: np.ndarray) -> np.ndarray:
    values = _weights(rows, indices)
    positive = labels[indices] > 0.5
    positive_total = float(np.sum(values[positive]))
    negative_total = float(np.sum(values[~positive]))
    if positive_total <= 0 or negative_total <= 0:
        raise RuntimeError("joint gate requires both positive and non-positive examples")
    values[positive] *= 0.5 / positive_total
    values[~positive] *= 0.5 / negative_total
    return values / np.mean(values)


def _evaluate(
    rows: list[dict[str, Any]],
    indices: np.ndarray,
    scores: np.ndarray,
    threshold: float,
    in_domain: np.ndarray,
) -> dict[str, Any]:
    if len(indices) == 0:
        return {"states": 0, "episodes": 0}
    weights = _weights(rows, indices)
    accepted = np.asarray(
        [
            rows[index]["meta"]["joint_changed_units"] > 0
            and rows[index]["meta"]["joint_emergency_displaced"] == 0
            and rows[index]["meta"]["joint_immediate_displaced"] == 0
            and float(scores[index]) >= threshold
            and bool(in_domain[index])
            for index in indices
        ],
        dtype=bool,
    )
    deltas = np.asarray([float(rows[index]["meta"]["joint_teacher_exact_delta"]) for index in indices])
    base = np.asarray([float(rows[index]["methods"]["baseline"]["worker_exact"]) for index in indices])
    joint = np.asarray([float(rows[index]["methods"]["joint_blend"]["worker_exact"]) for index in indices])
    hybrid = np.where(accepted, joint, base)
    denominator = float(np.sum(weights))
    accepted_weight = float(np.sum(weights[accepted]))
    result: dict[str, Any] = {
        "states": len(indices),
        "episodes": len({rows[index]["episode_id"] for index in indices}),
        "threshold": threshold,
        "acceptance_coverage": round(accepted_weight / denominator, 5),
        "accepted_states": int(np.sum(accepted)),
        "ood_rate": round(float(np.average(~in_domain[indices], weights=weights)), 5),
        "positive_precision": (
            round(float(np.sum(weights[accepted & (deltas > 0)])) / accepted_weight, 5)
            if accepted_weight
            else None
        ),
        "negative_rate": (
            round(float(np.sum(weights[accepted & (deltas < 0)])) / accepted_weight, 5)
            if accepted_weight
            else None
        ),
        "baseline_worker_exact": round(float(np.sum(base * weights)) / denominator, 5),
        "hybrid_worker_exact": round(float(np.sum(hybrid * weights)) / denominator, 5),
        "worker_exact_gain": round(float(np.sum((hybrid - base) * weights)) / denominator, 5),
        "by_source": {},
        "by_future72_money_bin": {},
    }
    for source in ("rank1", "rank2", "rank3"):
        mask = np.asarray([rows[index]["source"] == source for index in indices])
        if not np.any(mask):
            continue
        local_weight = weights[mask]
        result["by_source"][source] = {
            "states": int(np.sum(mask)),
            "acceptance_coverage": round(float(np.sum(local_weight[accepted[mask]])) / float(np.sum(local_weight)), 5),
            "worker_exact_gain": round(
                float(np.sum((hybrid[mask] - base[mask]) * local_weight)) / float(np.sum(local_weight)),
                5,
            ),
        }
    for money_bin in ("lt_-0.25", "-0.25_0", "0_0.25", "ge_0.25"):
        mask = np.asarray([rows[index]["future72_money_bin"] == money_bin for index in indices])
        if not np.any(mask):
            continue
        local_weight = weights[mask]
        result["by_future72_money_bin"][money_bin] = {
            "states": int(np.sum(mask)),
            "acceptance_coverage": round(float(np.sum(local_weight[accepted[mask]])) / float(np.sum(local_weight)), 5),
            "worker_exact_gain": round(
                float(np.sum((hybrid[mask] - base[mask]) * local_weight)) / float(np.sum(local_weight)),
                5,
            ),
        }
    return result


def _select_threshold(
    rows: list[dict[str, Any]],
    tune: np.ndarray,
    scores: np.ndarray,
    in_domain: np.ndarray,
) -> tuple[float, list[dict[str, Any]], str]:
    thresholds = sorted(
        {
            0.45,
            0.50,
            0.55,
            0.60,
            0.65,
            0.70,
            0.75,
            0.80,
            0.85,
            0.90,
            *(
                round(float(value), 6)
                for value in np.quantile(scores[tune], np.linspace(0.50, 0.95, 10))
            ),
        }
    )
    reports = [_evaluate(rows, tune, scores, threshold, in_domain) for threshold in thresholds]
    eligible = [
        report
        for report in reports
        if report["acceptance_coverage"] >= 0.005
        and report["worker_exact_gain"] > 0
        and report["positive_precision"] is not None
        and report["positive_precision"] >= 0.75
        and report["negative_rate"] is not None
        and report["negative_rate"] <= 0.05
        and all(value["worker_exact_gain"] >= 0 for value in report["by_source"].values())
    ]
    if not eligible:
        return 1.01, reports, "no tuning threshold passed precision, tail, minimum 0.5% coverage, and source gates"
    selected = max(eligible, key=lambda report: (report["worker_exact_gain"], report["acceptance_coverage"]))
    return float(selected["threshold"]), reports, "selected on meta-validation only"


def main() -> None:
    meta_payload = json.loads(META_INPUT.read_text(encoding="utf-8"))
    test_payload = json.loads(TEST_INPUT.read_text(encoding="utf-8"))
    rows = [
        *(row for row in meta_payload["rows"] if row["split"] == "validation"),
        *(row for row in test_payload["rows"] if row["split"] == "test"),
    ]
    x = np.asarray([_features(row) for row in rows], dtype=np.float64)
    labels = np.asarray([float(row["meta"]["joint_teacher_exact_delta"] > 0) for row in rows], dtype=np.float64)
    changed = np.asarray([int(row["meta"]["joint_changed_units"]) > 0 for row in rows])
    fit = np.asarray(
        [
            index
            for index, row in enumerate(rows)
            if row["split"] == "validation" and _episode_bucket(row["episode_id"]) <= 2 and changed[index]
        ],
        dtype=np.int64,
    )
    tune = np.asarray(
        [
            index
            for index, row in enumerate(rows)
            if row["split"] == "validation" and _episode_bucket(row["episode_id"]) >= 3
        ],
        dtype=np.int64,
    )
    test = np.asarray([index for index, row in enumerate(rows) if row["split"] == "test"], dtype=np.int64)
    weights = _training_weights(rows, fit, labels)
    forest = train_forest(
        x[fit],
        labels[fit, None],
        weights,
        trees=TREES,
        depth=DEPTH,
        min_leaf=MIN_LEAF,
        seed=10101,
    )
    scores = _predict(forest, x)
    used_indices: set[int] = set()

    def collect_indices(node: list[Any]) -> None:
        if node[0] != "N":
            return
        used_indices.add(int(node[1]))
        collect_indices(node[3])
        collect_indices(node[4])

    for tree in forest:
        collect_indices(tree)
    ood_indices = np.asarray(sorted(used_indices), dtype=np.int64)
    centers = np.median(x[fit][:, ood_indices], axis=0)
    q25 = np.quantile(x[fit][:, ood_indices], 0.25, axis=0)
    q75 = np.quantile(x[fit][:, ood_indices], 0.75, axis=0)
    scales = np.maximum(1e-6, (q75 - q25) * 0.7413)
    distances = np.max(np.abs(x[:, ood_indices] - centers) / scales, axis=1)
    ood_threshold = float(np.quantile(distances[fit], 0.99))
    in_domain = distances <= ood_threshold
    threshold, threshold_reports, selection_reason = _select_threshold(rows, tune, scores, in_domain)
    evaluations = {
        "meta_fit": _evaluate(rows, fit, scores, threshold, in_domain),
        "meta_validation": _evaluate(rows, tune, scores, threshold, in_domain),
        "untouched_test": _evaluate(rows, test, scores, threshold, in_domain),
    }
    test_report = evaluations["untouched_test"]
    promotion_screen = {
        "passed": bool(
            threshold <= 1.0
            and test_report["worker_exact_gain"] > 0
            and test_report["negative_rate"] is not None
            and test_report["negative_rate"] <= 0.05
            and all(value["worker_exact_gain"] >= 0 for value in test_report["by_source"].values())
            and all(
                value["worker_exact_gain"] >= 0
                for value in test_report["by_future72_money_bin"].values()
            )
        ),
        "requires_closed_loop": True,
    }
    result = {
        "format": "kaggriculture-joint-assignment-gate-validation-v1",
        "input": {
            "meta_validation": str(META_INPUT.relative_to(ROOT)),
            "untouched_test": str(TEST_INPUT.relative_to(ROOT)),
        },
        "episode_partition": {
            "meta_fit": "original validation episodes with stable bucket 0-2",
            "meta_validation": "original validation episodes with stable bucket 3-4",
            "untouched_test": "original test episodes; reporting only",
        },
        "features": {"count": len(FEATURE_NAMES), "names": FEATURE_NAMES},
        "training": {"trees": TREES, "depth": DEPTH, "min_leaf": MIN_LEAF, "fit_changed_states": len(fit)},
        "selected_threshold": threshold,
        "ood": {
            "method": "maximum robust distance on forest-used features",
            "indices": ood_indices.tolist(),
            "center": centers.tolist(),
            "scale": scales.tolist(),
            "threshold": ood_threshold,
        },
        "selection_reason": selection_reason,
        "threshold_screen": threshold_reports,
        "evaluations": evaluations,
        "promotion_screen": promotion_screen,
        "limits": [
            "the target is teacher endpoint improvement, not counterfactual game reward",
            "the level-two gate is trained only on previously held-out validation episodes",
            "untouched test results cannot be used to retune the threshold",
            "a passing offline screen still requires new-seed and distinct-opponent closed-loop tests",
        ],
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    model = {
        "format": "kaggriculture-joint-assignment-gate-model-v1",
        "enabled": False,
        "feature_names": FEATURE_NAMES,
        "threshold": threshold,
        "ood": result["ood"],
        "forest": forest,
        "training": result["training"],
        "validation": evaluations["meta_validation"],
        "test": evaluations["untouched_test"],
        "promotion_screen": promotion_screen,
    }
    MODEL_OUTPUT.write_text(json.dumps(model, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(
        json.dumps(
            {
                "threshold": threshold,
                "evaluations": evaluations,
                "promotion_screen": promotion_screen,
            },
            indent=2,
        )
    )
    print(f"result: {OUTPUT}")
    print(f"model: {MODEL_OUTPUT}")


if __name__ == "__main__":
    main()
