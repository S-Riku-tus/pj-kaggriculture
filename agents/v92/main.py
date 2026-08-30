"""Kaggriculture V92: gated candidate-relative assignment on V14."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from agents.v88 import main as v88

MODULE_DIR = Path(__file__).resolve().parent
v14 = v88.v14
v11 = v14.v11
v9 = v14.v9
v5 = v14.v5
base = v14.base

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

ENABLE_CANDIDATE_RANKER = False
MIN_SCORE_GAP = 0.12
CANDIDATE_BONUS = 1_600
MAX_BASE_RANK: int | None = None
MAX_EFFECTIVE_PRIORITY = 14_900
_SAFE_FIELD_TASKS = v88._SAFE_FIELD_TASKS
_SAFE_ASSIGNMENT_COST = v5._assignment_cost
RUNTIME_COUNTS = {
    "calls": 0,
    "scored_workers": 0,
    "confident_workers": 0,
    "ood_workers": 0,
    "base_rank_rejected": 0,
    "annotated_tasks": 0,
}


def _load_json(name: str, fallback: str) -> dict[str, Any] | None:
    for path in (
        MODULE_DIR / name,
        MODULE_DIR.parent.parent / "data" / "analysis" / fallback,
    ):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue
    return None


CANDIDATE_MODEL = _load_json("candidate_ranker_model.json", "v90_candidate_ranker_model.json")
OOD_MODEL = _load_json("task_goal_model.json", "v87_task_goal_model.json")


def _predict_tree(tree: list[Any], features: list[float]) -> float:
    node = tree
    while node[0] == "N":
        node = node[3] if features[int(node[1])] <= float(node[2]) else node[4]
    return float(node[1])


def _score(features: list[float]) -> float:
    if CANDIDATE_MODEL is None:
        return 0.0
    forest = CANDIDATE_MODEL["forest"]
    return sum(_predict_tree(tree, features) for tree in forest) / len(forest)


def _is_ood(features: list[float]) -> bool:
    if OOD_MODEL is None:
        return True
    profile = OOD_MODEL["ood"]
    distance = max(
        abs(features[int(index)] - float(center)) / max(1e-8, float(scale))
        for index, center, scale in zip(profile["indices"], profile["center"], profile["scale"], strict=True)
    )
    return distance > float(profile["threshold"])


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
        base._manhattan(position, target) / 18.0,
        dx / 9.0,
        dy / 9.0,
        priority / 16_000.0,
        (priority - maximum_priority) / 8_000.0,
        min(1.0, density[target] / 10.0),
        float(position == target),
        float(required is not None and base._inventory_count(inventories[unit], required) > 0),
        *(float(operation == value) for value in OPERATIONS),
        *(float(item == value) for value in ITEMS),
    ]


def _annotate_tasks(
    tasks: list[dict[str, Any]],
    obs: Any,
    farm: Any,
    positions: list[tuple[int, int]],
    inventories: list[Any],
) -> list[dict[str, Any]]:
    RUNTIME_COUNTS["calls"] += 1
    if not ENABLE_CANDIDATE_RANKER or CANDIDATE_MODEL is None or OOD_MODEL is None or len(tasks) < 2:
        return tasks
    previous_actions = list(getattr(v9, "_MISSION_PREVIOUS_ACTIONS", []) or [])
    result = []
    for original in tasks:
        task = dict(original)
        task["action"] = list(original.get("action") or ["PASS"])
        result.append(task)
    density = Counter(task["pos"] for task in result)
    for unit, position in enumerate(positions):
        if unit >= len(inventories):
            continue
        previous = previous_actions[unit] if unit < len(previous_actions) else None
        if v88._previous_op(previous) == "MOVE":
            continue
        state_features = v88._features(obs, farm, positions, inventories[unit], unit, previous)
        if _is_ood(state_features):
            RUNTIME_COUNTS["ood_workers"] += 1
            continue
        feasible = [
            index
            for index, task in enumerate(result)
            if base._can_do(task, unit, inventories[unit]) and base._manhattan(position, task["pos"]) > 0
        ]
        if len(feasible) < 2:
            continue
        RUNTIME_COUNTS["scored_workers"] += 1
        maximum_priority = max(int(result[index].get("priority", 0)) for index in feasible)
        scores = {
            index: _score(
                [
                    *state_features,
                    *_candidate_features(
                        result[index],
                        v88._task_goal(result[index], farm),
                        unit,
                        positions,
                        inventories,
                        density,
                        maximum_priority,
                    ),
                ]
            )
            for index in feasible
        }
        ranked = sorted(feasible, key=lambda index: -scores[index])
        gap = scores[ranked[0]] - scores[ranked[1]]
        if gap < MIN_SCORE_GAP:
            continue
        if MAX_BASE_RANK is not None:
            base_order = sorted(
                feasible,
                key=lambda index: (
                    _SAFE_ASSIGNMENT_COST(unit, result[index], positions, inventories, density),
                    index,
                ),
            )
            base_rank = base_order.index(ranked[0]) + 1
            if base_rank > MAX_BASE_RANK:
                RUNTIME_COUNTS["base_rank_rejected"] += 1
                continue
        chosen = result[ranked[0]]
        priority = int(chosen.get("priority", 0))
        bonus = min(CANDIDATE_BONUS, max(0, MAX_EFFECTIVE_PRIORITY - priority))
        if bonus <= 0:
            continue
        bonus_by_unit = dict(chosen.get("v92_bonus_by_unit") or {})
        bonus_by_unit[unit] = bonus
        chosen["v92_bonus_by_unit"] = bonus_by_unit
        RUNTIME_COUNTS["confident_workers"] += 1
        RUNTIME_COUNTS["annotated_tasks"] += 1
    return result


def _assignment_cost(
    unit: int,
    task: dict[str, Any],
    positions: list[tuple[int, int]],
    inventories: list[Any],
    density: Counter[tuple[int, int]],
) -> int:
    cost = _SAFE_ASSIGNMENT_COST(unit, task, positions, inventories, density)
    bonus = int((task.get("v92_bonus_by_unit") or {}).get(unit, 0))
    return cost - bonus * 100


def _field_tasks(
    obs: Any,
    farm: Any,
    private: Any,
    positions: list[tuple[int, int]],
    inventories: list[Any],
    summary: dict[str, Any],
    animal_targets: dict[str, int],
    crop_targets: dict[str, int],
    pasture_target: int,
    opponent_farm: Any = None,
) -> tuple[list[dict[str, Any]], set[tuple[int, int]]]:
    tasks, reserved = _SAFE_FIELD_TASKS(
        obs,
        farm,
        private,
        positions,
        inventories,
        summary,
        animal_targets,
        crop_targets,
        pasture_target,
        opponent_farm,
    )
    return _annotate_tasks(tasks, obs, farm, positions, inventories), reserved


v11._field_tasks = _field_tasks
v5._assignment_cost = _assignment_cost


def reset_runtime_counts() -> None:
    for key in RUNTIME_COUNTS:
        RUNTIME_COUNTS[key] = 0


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v14.policy_diagnostics(obs))
    result["v92_candidate_ranker"] = {
        "enabled": ENABLE_CANDIDATE_RANKER,
        "model_loaded": CANDIDATE_MODEL is not None,
        "ood_loaded": OOD_MODEL is not None,
        "minimum_score_gap": MIN_SCORE_GAP,
        "maximum_base_rank": MAX_BASE_RANK,
        "bonus": CANDIDATE_BONUS,
        "runtime_counts": dict(RUNTIME_COUNTS),
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v14.agent(obs)
