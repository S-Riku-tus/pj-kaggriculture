"""Summarize Top-3 movement starts as multi-turn task-goal examples."""

from __future__ import annotations

import gc
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "data/training/v87_task_goal_sources"
OUTPUT = ROOT / "data/analysis/v87_task_goal_analysis.json"
SOURCES = ("rank1", "rank2", "rank3")
WORKER_X_INDEX = 78
WORKER_Y_INDEX = 79
LOOKAHEAD = 6


def _phase(day: int) -> str:
    if day <= 4:
        return "d00_04"
    if day <= 12:
        return "d05_12"
    if day <= 19:
        return "d13_19"
    if day <= 24:
        return "d20_24"
    return "d25_29"


def _blank() -> dict[str, Any]:
    return {
        "rows": 0,
        "completed": 0,
        "horizon_sum": 0.0,
        "endpoint_l1_sum": 0.0,
        "goals": Counter(),
        "operations": Counter(),
        "future24_money_gap_sum": 0.0,
        "future72_money_gap_sum": 0.0,
        "future24_productive_gap_sum": 0.0,
        "future72_productive_gap_sum": 0.0,
    }


def _add(bucket: dict[str, Any], row: dict[str, Any]) -> None:
    labels = row["labels"]
    goal = str(labels["goal"])
    operation = goal.split(":", 1)[0]
    completed = bool(labels["completed"])
    bucket["rows"] += 1
    bucket["completed"] += int(completed)
    bucket["goals"][goal] += 1
    bucket["operations"][operation] += 1
    bucket["future24_money_gap_sum"] += float(labels["future24_money_gap_ratio"])
    bucket["future72_money_gap_sum"] += float(labels["future72_money_gap_ratio"])
    bucket["future24_productive_gap_sum"] += float(labels["future24_productive_gap"])
    bucket["future72_productive_gap_sum"] += float(labels["future72_productive_gap"])
    if completed:
        bucket["horizon_sum"] += float(labels["horizon"]) * LOOKAHEAD
        features = row["features"]
        bucket["endpoint_l1_sum"] += abs(float(labels["endpoint_x"]) - float(features[WORKER_X_INDEX])) + abs(
            float(labels["endpoint_y"]) - float(features[WORKER_Y_INDEX])
        )


def _finalize(bucket: dict[str, Any]) -> dict[str, Any]:
    rows = int(bucket["rows"])
    completed = int(bucket["completed"])
    return {
        "rows": rows,
        "completion_rate": round(completed / max(1, rows), 5),
        "mean_completed_horizon": round(float(bucket["horizon_sum"]) / max(1, completed), 4),
        "mean_completed_endpoint_l1": round(float(bucket["endpoint_l1_sum"]) / max(1, completed), 5),
        "mean_future24_money_gap": round(float(bucket["future24_money_gap_sum"]) / max(1, rows), 5),
        "mean_future72_money_gap": round(float(bucket["future72_money_gap_sum"]) / max(1, rows), 5),
        "mean_future24_productive_gap": round(float(bucket["future24_productive_gap_sum"]) / max(1, rows), 5),
        "mean_future72_productive_gap": round(float(bucket["future72_productive_gap_sum"]) / max(1, rows), 5),
        "operation_counts": dict(bucket["operations"].most_common()),
        "goal_counts": dict(bucket["goals"].most_common(30)),
    }


def _operation_distribution(bucket: dict[str, Any]) -> dict[str, float]:
    total = max(1, int(bucket["rows"]))
    return {key: value / total for key, value in bucket["operations"].items()}


def _total_variation(left: dict[str, float], right: dict[str, float]) -> float:
    keys = set(left) | set(right)
    return 0.5 * sum(abs(left.get(key, 0.0) - right.get(key, 0.0)) for key in keys)


def main() -> None:
    buckets: defaultdict[str, dict[str, Any]] = defaultdict(_blank)
    split_episodes: defaultdict[str, set[str]] = defaultdict(set)
    source_episodes: defaultdict[str, set[str]] = defaultdict(set)
    for source in SOURCES:
        path = SOURCE_DIR / f"{source}.json"
        print(f"[{source}] loading {path}", flush=True)
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload["rows"]:
            result = str(row["result"])
            split = str(row["split"])
            phase = _phase(int(row["day"]))
            winner = bool(row["winner"])
            episode_id = str(row["episode_id"])
            source_episodes[source].add(episode_id)
            split_episodes[split].add(episode_id)
            _add(buckets["all"], row)
            _add(buckets[f"source:{source}:all"], row)
            _add(buckets[f"source:{source}:result:{result}"], row)
            _add(buckets[f"split:{split}:all"], row)
            if winner:
                _add(buckets["winners"], row)
                _add(buckets[f"source:{source}:winners"], row)
                _add(buckets[f"source:{source}:phase:{phase}:winners"], row)
                _add(buckets[f"split:{split}:winners"], row)
        del payload
        gc.collect()
        print(f"[{source}] summarized", flush=True)

    pairwise_tv: dict[str, float] = {}
    for left_index, left in enumerate(SOURCES):
        for right in SOURCES[left_index + 1 :]:
            left_dist = _operation_distribution(buckets[f"source:{left}:winners"])
            right_dist = _operation_distribution(buckets[f"source:{right}:winners"])
            pairwise_tv[f"{left}_vs_{right}"] = round(_total_variation(left_dist, right_dist), 5)
    result = {
        "format": "kaggriculture-v87-task-goal-analysis-v1",
        "definition": {
            "example": "first move after a non-move action",
            "completion": "first non-move non-PASS operation within six turns on the same day",
            "primary_teacher_filter": "winning Top-3 sides",
        },
        "episodes": {
            "by_source": {key: len(value) for key, value in source_episodes.items()},
            "by_split": {key: len(value) for key, value in split_episodes.items()},
        },
        "pairwise_winner_operation_total_variation": pairwise_tv,
        "buckets": {key: _finalize(value) for key, value in sorted(buckets.items())},
        "limits": [
            "route starts are observational and do not reveal rejected candidate tasks",
            "worker identity is only stable within a day",
            "endpoint distance is normalized board L1 distance",
            "future gaps are outcomes after the chosen route and are not causal values",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"episodes": result["episodes"], "tv": pairwise_tv}, indent=2))
    print(f"result: {OUTPUT}")


if __name__ == "__main__":
    main()
