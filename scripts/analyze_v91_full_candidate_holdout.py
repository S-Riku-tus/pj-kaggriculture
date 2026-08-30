"""Evaluate V90 against every feasible candidate on held-out episodes."""

from __future__ import annotations

import gc
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import analyze_v89_candidate_coverage as v89  # noqa: E402
from scripts import build_v90_candidate_rows as v90  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    _manifest,
    _replay_path,
)

MODEL = ROOT / "data/analysis/v90_candidate_ranker_model.json"
OUTPUT = ROOT / "data/analysis/v91_full_candidate_holdout.json"
ANALYSIS_FORMAT = "kaggriculture-v91-full-candidate-holdout-v1"


def _predict_tree(tree: list[Any], features: list[float]) -> float:
    node = tree
    while node[0] == "N":
        node = node[3] if features[int(node[1])] <= float(node[2]) else node[4]
    return float(node[1])


def _score(model: dict[str, Any], features: list[float]) -> float:
    return sum(_predict_tree(tree, features) for tree in model["forest"]) / len(model["forest"])


def _evaluate_group(
    model: dict[str, Any],
    row: dict[str, Any],
    farm: Any,
    positions: list[tuple[int, int]],
    inventories: list[Any],
    tasks: list[dict[str, Any]],
) -> dict[str, Any] | None:
    unit = int(row["unit"])
    if unit >= len(positions) or unit >= len(inventories):
        return None
    board_size = max(1, len(v89.base._get(farm, "tiles", []) or []))
    endpoint = (
        round(float(row["endpoint_x"]) * max(1, board_size - 1)),
        round(float(row["endpoint_y"]) * max(1, board_size - 1)),
    )
    teacher_goal = str(row["goal"])
    task_goals = [v89._task_goal(task, farm) for task in tasks]
    feasible = [index for index, task in enumerate(tasks) if v89.base._can_do(task, unit, inventories[unit])]
    positive = {
        index for index in feasible if task_goals[index] == teacher_goal and tasks[index].get("pos") == endpoint
    }
    if not positive:
        return None
    density = Counter(task["pos"] for task in tasks)
    maximum_priority = max(int(tasks[index].get("priority", 0)) for index in feasible)
    scores: dict[int, float] = {}
    costs: dict[int, int] = {}
    for index in feasible:
        candidate = v90._candidate_features(
            tasks[index],
            task_goals[index],
            unit,
            positions,
            inventories,
            density,
            maximum_priority,
        )
        features = [*row["features"], *candidate]
        scores[index] = _score(model, features)
        costs[index] = v89.v5._assignment_cost(unit, tasks[index], positions, inventories, density)
    model_order = sorted(feasible, key=lambda index: (-scores[index], costs[index], index))
    base_order = sorted(feasible, key=lambda index: (costs[index], index))
    base_choice = base_order[0]
    base_ranks = {index: rank for rank, index in enumerate(base_order, start=1)}
    ordered_scores = sorted(scores.values(), reverse=True)
    first_positive_rank = next(rank for rank, index in enumerate(model_order, start=1) if index in positive)
    return {
        "source": row["source"],
        "split": row["split"],
        "episode_id": row["episode_id"],
        "model_correct": model_order[0] in positive,
        "base_correct": base_choice in positive,
        "model_changed": model_order[0] != base_choice,
        "model_choice_base_rank": base_ranks[model_order[0]],
        "model_top3": any(index in positive for index in model_order[:3]),
        "reciprocal_rank": 1.0 / first_positive_rank,
        "score_gap": (ordered_scores[0] - ordered_scores[1] if len(ordered_scores) >= 2 else 1.0),
        "candidates": len(feasible),
    }


def _finalize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    episode_counts = Counter(str(row["episode_id"]) for row in rows)
    weights = [1.0 / episode_counts[str(row["episode_id"])] for row in rows]
    total_weight = sum(weights)

    def weighted(key: str, local: list[int] | None = None) -> float:
        indices = local if local is not None else list(range(len(rows)))
        denominator = sum(weights[index] for index in indices)
        return sum(float(rows[index][key]) * weights[index] for index in indices) / max(1e-12, denominator)

    result: dict[str, Any] = {
        "groups": len(rows),
        "episodes": len(episode_counts),
        "episode_balanced_model_top1": round(weighted("model_correct"), 5),
        "episode_balanced_v5_top1": round(weighted("base_correct"), 5),
        "episode_balanced_model_top3": round(weighted("model_top3"), 5),
        "episode_balanced_mrr": round(weighted("reciprocal_rank"), 5),
        "mean_full_feasible_candidates": round(weighted("candidates"), 3),
        "confidence_gap": [],
        "base_rank_consensus": [],
        "joint_consensus_gates": [],
    }
    for low, high in ((0.0, 0.03), (0.03, 0.07), (0.07, 0.12), (0.12, 1.01)):
        indices = [index for index, row in enumerate(rows) if low <= float(row["score_gap"]) < high]
        if indices:
            result["confidence_gap"].append(
                {
                    "range": [low, high],
                    "groups": len(indices),
                    "coverage": round(sum(weights[index] for index in indices) / total_weight, 5),
                    "top1": round(weighted("model_correct", indices), 5),
                }
            )
    for low_rank, high_rank in ((1, 1), (2, 3), (4, 5), (6, 8), (9, 10_000)):
        indices = [
            index
            for index, row in enumerate(rows)
            if low_rank <= int(row["model_choice_base_rank"]) <= high_rank
        ]
        if indices:
            result["base_rank_consensus"].append(
                {
                    "range": [low_rank, high_rank],
                    "groups": len(indices),
                    "coverage": round(sum(weights[index] for index in indices) / total_weight, 5),
                    "top1": round(weighted("model_correct", indices), 5),
                    "changed_rate": round(weighted("model_changed", indices), 5),
                }
            )
    for minimum_gap in (0.12, 0.16, 0.20, 0.24):
        for maximum_base_rank in (3, 5, 8, 12):
            switched = [
                index
                for index, row in enumerate(rows)
                if bool(row["model_changed"])
                and float(row["score_gap"]) >= minimum_gap
                and int(row["model_choice_base_rank"]) <= maximum_base_rank
            ]
            switched_set = set(switched)
            hybrid_numerator = sum(
                (
                    float(row["model_correct"])
                    if index in switched_set
                    else float(row["base_correct"])
                )
                * weights[index]
                for index, row in enumerate(rows)
            )
            result["joint_consensus_gates"].append(
                {
                    "minimum_gap": minimum_gap,
                    "maximum_base_rank": maximum_base_rank,
                    "switched_groups": len(switched),
                    "switch_coverage": round(
                        sum(weights[index] for index in switched) / total_weight,
                        5,
                    ),
                    "switch_top1": round(weighted("model_correct", switched), 5) if switched else None,
                    "hybrid_top1": round(hybrid_numerator / max(1e-12, total_weight), 5),
                }
            )
    return result


def main() -> None:
    model = json.loads(MODEL.read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = []
    sampled: Counter[str] = Counter()
    for source in v89.TEACHERS:
        manifests = {
            (str(row["episode_id"]), int(row["submission_seat"])): row for row in _manifest(v89.SOURCES[source])
        }
        print(f"[{source}] loading", flush=True)
        payload = json.loads((v89.SOURCE_DIR / f"{source}.json").read_text(encoding="utf-8"))
        by_episode: defaultdict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        for row in payload["rows"]:
            if (
                not row["winner"]
                or str(row["split"]) == "train"
                or not row["labels"]["completed"]
                or v89._sample_key(row) % v90.SAMPLE_MODULUS
            ):
                continue
            sampled[source] += 1
            labels = row["labels"]
            by_episode[(str(row["episode_id"]), int(row["seat"]))].append(
                {
                    "source": source,
                    "episode_id": str(row["episode_id"]),
                    "split": str(row["split"]),
                    "step": int(row["step"]),
                    "unit": int(row["unit"]),
                    "goal": str(labels["goal"]),
                    "endpoint_x": float(labels["endpoint_x"]),
                    "endpoint_y": float(labels["endpoint_y"]),
                    "features": row["features"],
                }
            )
        del payload
        gc.collect()
        for episode_index, (key, rows) in enumerate(by_episode.items(), start=1):
            if episode_index == 1 or episode_index % 25 == 0:
                print(f"[{source} {episode_index}/{len(by_episode)}]", flush=True)
            manifest = manifests.get(key)
            if manifest is None:
                continue
            replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
            state_cache: dict[int, Any] = {}
            for row in rows:
                step = int(row["step"])
                if step not in state_cache:
                    state_cache[step] = v89._state(replay, key[1], step)
                state = state_cache[step]
                if state is None:
                    continue
                _obs, farm, positions, inventories, tasks = state
                evaluated = _evaluate_group(model, row, farm, positions, inventories, tasks)
                if evaluated is not None:
                    results.append(evaluated)
            del replay
        gc.collect()

    buckets: dict[str, Any] = {}
    for split in ("validation", "test"):
        local = [row for row in results if row["split"] == split]
        buckets[split] = _finalize(local)
        for source in v89.TEACHERS:
            buckets[f"{split}:{source}"] = _finalize([row for row in local if row["source"] == source])
    result = {
        "format": ANALYSIS_FORMAT,
        "sample_modulus": v90.SAMPLE_MODULUS,
        "sampled_completed_routes": dict(sampled),
        "buckets": buckets,
        "limits": [
            "only held-out routes with an immediately feasible exact endpoint are scored",
            "all feasible V14 candidates are restored, including negatives unseen by V90 training",
            "individual ranking still precedes global multi-worker Hungarian interaction",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(buckets, ensure_ascii=False, indent=2))
    print(f"result: {OUTPUT}")


if __name__ == "__main__":
    main()
