"""Build compact candidate-relative ranking groups from V89 teacher states."""

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
from scripts.train_v12_relative_policy import (  # noqa: E402
    _manifest,
    _replay_path,
)

OUTPUT = ROOT / "data/training/v90_candidate_groups.json"
SAMPLE_MODULUS = 60
MAX_NEGATIVES = 8
OPERATIONS = (
    "WATER",
    "FEED",
    "FERTILIZE",
    "HARVEST",
    "PLANT",
    "DROP",
    "PLACE",
    "COLLECT_FERTILIZER",
    "DIG",
    "BUILD_PASTURE",
    "PICKUP",
    "CARE",
    "BUILD_COOP",
    "OTHER",
)
ITEMS = (
    "NONE",
    "WHEAT",
    "CARROT",
    "TOMATO",
    "STRAWBERRY",
    "MELON",
    "GOOSE",
    "COW",
    "SHEEP",
    "EGG",
    "MILK",
    "WOOL",
    "FERTILIZER",
    "WEED",
    "PASTURE",
    "COOP",
    "PLANT",
    "OTHER",
)
CANDIDATE_FEATURE_NAMES = (
    "distance",
    "delta_x",
    "delta_y",
    "priority",
    "priority_gap",
    "tile_density",
    "same_tile",
    "required_in_inventory",
    *(f"operation_{value.lower()}" for value in OPERATIONS),
    *(f"item_{value.lower()}" for value in ITEMS),
)


def _candidate_features(
    task: dict[str, Any],
    goal: str,
    unit: int,
    positions: list[tuple[int, int]],
    inventories: list[Any],
    density: Counter[tuple[int, int]],
    maximum_priority: int,
) -> list[float]:
    operation, item = goal.split(":", 1)
    operation = operation if operation in OPERATIONS else "OTHER"
    item = item if item in ITEMS else "OTHER"
    position = positions[unit]
    target = task["pos"]
    dx, dy = target[0] - position[0], target[1] - position[1]
    priority = int(task.get("priority", 0))
    required = task.get("required")
    return [
        v89.base._manhattan(position, target) / 18.0,
        dx / 9.0,
        dy / 9.0,
        priority / 16_000.0,
        (priority - maximum_priority) / 8_000.0,
        min(1.0, density[target] / 10.0),
        float(position == target),
        float(required is not None and v89.base._inventory_count(inventories[unit], required) > 0),
        *(float(operation == value) for value in OPERATIONS),
        *(float(item == value) for value in ITEMS),
    ]


def _group(
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
    positives = [
        index for index in feasible if task_goals[index] == teacher_goal and tasks[index].get("pos") == endpoint
    ]
    if not positives:
        return None
    density = Counter(task["pos"] for task in tasks)
    ranked = sorted(
        feasible,
        key=lambda index: v89.v5._assignment_cost(unit, tasks[index], positions, inventories, density),
    )
    ranks = {index: rank for rank, index in enumerate(ranked, start=1)}
    negatives = [index for index in ranked if index not in positives][:MAX_NEGATIVES]
    selected = [*positives[:2], *negatives]
    maximum_priority = max(int(tasks[index].get("priority", 0)) for index in feasible)
    candidates = []
    for index in selected:
        features = _candidate_features(
            tasks[index],
            task_goals[index],
            unit,
            positions,
            inventories,
            density,
            maximum_priority,
        )
        if len(features) != len(CANDIDATE_FEATURE_NAMES):
            raise RuntimeError("candidate feature mismatch")
        candidates.append(
            {
                "features": features,
                "positive": index in positives,
                "base_rank": ranks[index],
                "goal": task_goals[index],
            }
        )
    return {
        "source": row["source"],
        "episode_id": row["episode_id"],
        "split": row["split"],
        "step": row["step"],
        "day": row["day"],
        "unit": unit,
        "teacher_goal": teacher_goal,
        "state_features": row["features"],
        "candidates": candidates,
        "full_feasible_candidates": len(feasible),
        "best_positive_base_rank": min(ranks[index] for index in positives),
    }


def main() -> None:
    groups: list[dict[str, Any]] = []
    route_sample: Counter[str] = Counter()
    coverage: Counter[str] = Counter()
    for source in v89.TEACHERS:
        manifests = {
            (str(row["episode_id"]), int(row["submission_seat"])): row for row in _manifest(v89.SOURCES[source])
        }
        print(f"[{source}] loading", flush=True)
        payload = json.loads((v89.SOURCE_DIR / f"{source}.json").read_text(encoding="utf-8"))
        by_episode: defaultdict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        for row in payload["rows"]:
            if not row["winner"] or not row["labels"]["completed"] or v89._sample_key(row) % SAMPLE_MODULUS:
                continue
            route_sample[source] += 1
            labels = row["labels"]
            by_episode[(str(row["episode_id"]), int(row["seat"]))].append(
                {
                    "source": source,
                    "episode_id": str(row["episode_id"]),
                    "split": str(row["split"]),
                    "step": int(row["step"]),
                    "day": int(row["day"]),
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
                made = _group(row, farm, positions, inventories, tasks)
                if made is not None:
                    groups.append(made)
                    coverage[source] += 1
            del replay
        gc.collect()

    result = {
        "format": "kaggriculture-v90-candidate-groups-v1",
        "sample_modulus": SAMPLE_MODULUS,
        "state_feature_count": 124,
        "candidate_feature_names": list(CANDIDATE_FEATURE_NAMES),
        "route_sample": dict(route_sample),
        "groups": len(groups),
        "groups_by_source": dict(coverage),
        "groups_by_split": dict(Counter(group["split"] for group in groups)),
        "episode_disjoint_split": True,
        "rows": groups,
        "limits": [
            "training groups require the exact teacher endpoint to be immediately feasible",
            "up to two positives and eight hardest V5-cost negatives are retained",
            "the model will rank existing deterministic tasks and cannot create a missing task",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(
        json.dumps(
            {
                "route_sample": dict(route_sample),
                "groups": len(groups),
                "groups_by_source": dict(coverage),
                "groups_by_split": result["groups_by_split"],
            },
            indent=2,
        )
    )
    print(f"result: {OUTPUT}")


if __name__ == "__main__":
    main()
