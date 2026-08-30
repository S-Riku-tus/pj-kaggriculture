"""Train and validate a candidate-relative Top-3 task ranker."""

from __future__ import annotations

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

INPUT = ROOT / "data/training/v90_candidate_groups.json"
OUTPUT = ROOT / "data/analysis/v90_candidate_ranker_validation.json"
MODEL_OUTPUT = ROOT / "data/analysis/v90_candidate_ranker_model.json"
SOURCES = ("rank1", "rank2", "rank3")
TREES = 10
DEPTH = 7
MIN_LEAF = 50


def _load() -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    payload = json.loads(INPUT.read_text(encoding="utf-8"))
    values: defaultdict[str, list[Any]] = defaultdict(list)
    group_rows: list[list[int]] = []
    for group_index, group in enumerate(payload["rows"]):
        local: list[int] = []
        for candidate in group["candidates"]:
            row_index = len(values["x"])
            local.append(row_index)
            values["x"].append([*group["state_features"], *candidate["features"]])
            values["y"].append(float(candidate["positive"]))
            values["group"].append(group_index)
            values["base_rank"].append(int(candidate["base_rank"]))
        group_rows.append(local)
    groups = payload["rows"]
    return payload, {
        "x": np.asarray(values["x"], dtype=np.float64),
        "y": np.asarray(values["y"], dtype=np.float64),
        "group": np.asarray(values["group"], dtype=np.int64),
        "base_rank": np.asarray(values["base_rank"], dtype=np.int64),
        "group_rows": np.asarray(group_rows, dtype=object),
        "split": np.asarray([group["split"] for group in groups], dtype=object),
        "source": np.asarray([group["source"] for group in groups], dtype=object),
        "episode": np.asarray([str(group["episode_id"]) for group in groups], dtype=object),
    }


def _training_weights(data: dict[str, np.ndarray], train_groups: np.ndarray) -> np.ndarray:
    episode_counts = Counter(str(data["episode"][index]) for index in train_groups)
    weights = np.zeros(len(data["x"]), dtype=np.float64)
    for group_index in train_groups:
        rows = np.asarray(data["group_rows"][group_index], dtype=np.int64)
        positive = data["y"][rows] > 0.5
        group_weight = 1.0 / episode_counts[str(data["episode"][group_index])]
        positive_count = max(1, int(np.sum(positive)))
        negative_count = max(1, int(np.sum(~positive)))
        weights[rows[positive]] = 0.5 * group_weight / positive_count
        weights[rows[~positive]] = 0.5 * group_weight / negative_count
    nonzero = weights > 0
    weights[nonzero] /= np.mean(weights[nonzero])
    return weights


def _predict_tree(tree: list[Any], row: np.ndarray) -> float:
    node = tree
    while node[0] == "N":
        node = node[3] if row[node[1]] <= node[2] else node[4]
    return float(node[1])


def _predict(forest: list[list[Any]], x: np.ndarray) -> np.ndarray:
    return np.asarray(
        [sum(_predict_tree(tree, row) for tree in forest) / len(forest) for row in x],
        dtype=np.float64,
    )


def _group_weights(data: dict[str, np.ndarray], group_indices: np.ndarray) -> np.ndarray:
    counts = Counter(str(data["episode"][index]) for index in group_indices)
    weights = np.asarray([1.0 / counts[str(data["episode"][index])] for index in group_indices])
    return weights / np.mean(weights)


def _evaluate(data: dict[str, np.ndarray], group_indices: np.ndarray, scores: np.ndarray) -> dict[str, Any]:
    model_correct = []
    base_correct = []
    model_top3 = []
    reciprocal_rank = []
    gaps = []
    for group_index in group_indices:
        rows = np.asarray(data["group_rows"][group_index], dtype=np.int64)
        labels = data["y"][rows] > 0.5
        order = np.argsort(-scores[rows], kind="stable")
        model_correct.append(bool(labels[order[0]]))
        model_top3.append(bool(np.any(labels[order[:3]])))
        reciprocal_rank.append(1.0 / (next(rank for rank, index in enumerate(order, start=1) if labels[index])))
        base_choice = int(np.argmin(data["base_rank"][rows]))
        base_correct.append(bool(labels[base_choice]))
        ordered_scores = np.sort(scores[rows])[::-1]
        gaps.append(float(ordered_scores[0] - ordered_scores[1]) if len(ordered_scores) >= 2 else 1.0)
    weights = _group_weights(data, group_indices)
    model_correct_array = np.asarray(model_correct)
    gaps_array = np.asarray(gaps)
    result: dict[str, Any] = {
        "groups": len(group_indices),
        "episode_balanced_top1": round(float(np.average(model_correct_array, weights=weights)), 5),
        "row_top1": round(float(np.mean(model_correct_array)), 5),
        "v5_base_episode_balanced_top1": round(float(np.average(base_correct, weights=weights)), 5),
        "episode_balanced_top3": round(float(np.average(model_top3, weights=weights)), 5),
        "episode_balanced_mrr": round(float(np.average(reciprocal_rank, weights=weights)), 5),
        "confidence_gap": [],
    }
    for low, high in ((0.0, 0.03), (0.03, 0.07), (0.07, 0.12), (0.12, 1.01)):
        mask = (gaps_array >= low) & (gaps_array < high)
        if np.any(mask):
            result["confidence_gap"].append(
                {
                    "range": [low, high],
                    "groups": int(np.sum(mask)),
                    "coverage": round(float(np.average(mask, weights=weights)), 5),
                    "top1": round(
                        float(np.average(model_correct_array[mask], weights=weights[mask])),
                        5,
                    ),
                }
            )
    return result


def main() -> None:
    payload, data = _load()
    train_groups = np.flatnonzero(data["split"] == "train")
    training_weights = _training_weights(data, train_groups)
    train_rows = np.flatnonzero(training_weights > 0)
    print(
        f"training groups={len(train_groups)} rows={len(train_rows)} features={data['x'].shape[1]}",
        flush=True,
    )
    forest = train_forest(
        data["x"][train_rows],
        data["y"][train_rows, None],
        training_weights[train_rows],
        trees=TREES,
        depth=DEPTH,
        min_leaf=MIN_LEAF,
        seed=9001,
    )
    scores = _predict(forest, data["x"])
    evaluations: dict[str, Any] = {}
    for split in ("validation", "test"):
        split_groups = np.flatnonzero(data["split"] == split)
        evaluations[split] = _evaluate(data, split_groups, scores)
        for source in SOURCES:
            evaluations[f"{split}:{source}"] = _evaluate(
                data,
                np.flatnonzero((data["split"] == split) & (data["source"] == source)),
                scores,
            )
    result = {
        "format": "kaggriculture-v90-candidate-ranker-validation-v1",
        "input": {
            "groups": int(payload["groups"]),
            "groups_by_split": payload["groups_by_split"],
            "candidate_rows": len(data["x"]),
            "episode_disjoint_split": True,
        },
        "features": {
            "state": int(payload["state_feature_count"]),
            "candidate": len(payload["candidate_feature_names"]),
            "total": int(data["x"].shape[1]),
            "candidate_feature_names": payload["candidate_feature_names"],
        },
        "training": {"trees": TREES, "depth": DEPTH, "min_leaf": MIN_LEAF},
        "evaluations": evaluations,
        "limits": [
            "validation covers only routes with an immediately feasible exact endpoint",
            "each group retains the exact positive and at most eight hardest V5 negatives",
            "candidate scores are observational imitation targets, not causal task values",
            "runtime cost and full-Hungarian interaction remain untested",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    model = {
        "format": "kaggriculture-v90-candidate-ranker-model-v1",
        "enabled": False,
        "state_feature_count": int(payload["state_feature_count"]),
        "candidate_feature_names": payload["candidate_feature_names"],
        "forest": forest,
        "training": result["training"],
        "validation": evaluations["validation"],
        "test": evaluations["test"],
        "limits": result["limits"],
    }
    MODEL_OUTPUT.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
    print(
        json.dumps(
            {
                key: {
                    "model": value["episode_balanced_top1"],
                    "base": value["v5_base_episode_balanced_top1"],
                    "top3": value["episode_balanced_top3"],
                }
                for key, value in evaluations.items()
            },
            indent=2,
        )
    )
    print(f"result: {OUTPUT}")
    print(f"model: {MODEL_OUTPUT}")


if __name__ == "__main__":
    main()
