"""Kaggriculture V88: high-confidence task-goal reranking on V14.

The learned model never emits an action.  It may add a bounded priority bonus
to an already legal V14 task when a worker is starting a new movement route,
the exact future operation/asset goal exists, the state is in-distribution,
and held-out model probability is at least 0.55.  V14 retains task creation,
Hungarian assignment, movement, survival, market, and resource guarantees.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

if "__file__" in globals():
    MODULE_DIR = Path(__file__).resolve().parent
else:
    _runtime_candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd() / "agents" / "v88",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (candidate / "v14_base.py").is_file()
            or ((candidate / "main.py").is_file() and (candidate.parent / "v14" / "main.py").is_file())
        ),
        Path.cwd(),
    )


def _load_v14_module():
    packaged = MODULE_DIR / "v14_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v14" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v88_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V14 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v14 = _load_v14_module()
v11 = v14.v11
v9 = v14.v9
v3 = v14.v3
base = v14.base

MODEL_FORMAT = "kaggriculture-v87-task-goal-model-v1"
PRODUCTS = (
    "WHEAT",
    "CARROT",
    "TOMATO",
    "STRAWBERRY",
    "MELON",
    "EGG",
    "MILK",
    "WOOL",
    "FERTILIZER",
)
ANIMALS = ("GOOSE", "COW", "SHEEP")
CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
MOVES = {"NORTH", "SOUTH", "EAST", "WEST"}
PREVIOUS_OPS = (
    "START",
    "PASS",
    "WATER",
    "HARVEST",
    "FEED",
    "CARE",
    "COLLECT_FERTILIZER",
    "FERTILIZE",
    "PLANT",
    "PICKUP",
    "DROP",
    "PLACE",
    "DIG",
    "BUILD_PASTURE",
    "BUILD_COOP",
    "OTHER",
)
TILE_CLASSES = (
    "EMPTY",
    "LOCKED",
    "WEED",
    "COOP",
    "PASTURE",
    *(f"CROP_{crop}" for crop in CROPS),
    *(f"ANIMAL_{animal}" for animal in ANIMALS),
    "OTHER",
)

ENABLE_TASK_GOALS = False
MIN_GOAL_PROBABILITY = 0.55
TASK_GOAL_BONUS = 700
MAX_RERANKED_PRIORITY = 14_900
_SAFE_FIELD_TASKS = v11._field_tasks
RUNTIME_COUNTS = {"calls": 0, "confident_workers": 0, "ood_workers": 0, "boosted_tasks": 0}


def _load_model() -> dict[str, Any] | None:
    candidates = (
        MODULE_DIR / "task_goal_model.json",
        MODULE_DIR.parent.parent / "data" / "analysis" / "v87_task_goal_model.json",
    )
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue
        if (
            payload.get("format") == MODEL_FORMAT
            and int(payload.get("feature_count", 0)) == 124
            and payload.get("classes")
            and payload.get("forest")
            and payload.get("ood")
        ):
            return payload
    return None


TASK_GOAL_MODEL = _load_model()


def _predict_tree(tree: list[Any], features: list[float]) -> list[float]:
    node = tree
    while node[0] == "N":
        node = node[3] if features[int(node[1])] <= float(node[2]) else node[4]
    return [float(value) for value in node[1:]]


def _prediction(features: list[float]) -> tuple[str, float, bool] | None:
    if TASK_GOAL_MODEL is None or len(features) != 124:
        return None
    ood = TASK_GOAL_MODEL["ood"]
    distance = max(
        abs(features[int(index)] - float(center)) / max(1e-8, float(scale))
        for index, center, scale in zip(ood["indices"], ood["center"], ood["scale"], strict=True)
    )
    rows = [_predict_tree(tree, features) for tree in TASK_GOAL_MODEL["forest"]]
    classes = list(TASK_GOAL_MODEL["classes"])
    probabilities = [sum(row[index] for row in rows) / len(rows) for index in range(len(classes))]
    selected = max(range(len(classes)), key=probabilities.__getitem__)
    return classes[selected], probabilities[selected], distance > float(ood["threshold"])


def _previous_op(previous: list[Any] | None) -> str:
    value = str(previous[0]) if previous else "START"
    if value in MOVES:
        return "MOVE"
    return value if value in PREVIOUS_OPS else "OTHER"


def _tile_class(tile: Any) -> str:
    if tile is None:
        return "EMPTY"
    if tile == "LOCKED":
        return "LOCKED"
    crop = str(base._get(tile, "crop", "") or "")
    animal = str(base._get(tile, "animal", "") or "")
    if crop in CROPS:
        return f"CROP_{crop}"
    if animal in ANIMALS:
        return f"ANIMAL_{animal}"
    kind = str(base._get(tile, "kind", "OTHER") or "OTHER")
    return kind if kind in TILE_CLASSES else "OTHER"


def _tile_at(farm: Any, position: tuple[int, int]) -> Any:
    tiles = base._get(farm, "tiles", []) or []
    x, y = position
    if 0 <= y < len(tiles) and 0 <= x < len(tiles[y]):
        return tiles[y][x]
    return None


def _features(
    obs: Any,
    farm: Any,
    positions: list[tuple[int, int]],
    inventory: Any,
    unit: int,
    previous: list[Any] | None,
) -> list[float]:
    position = positions[unit]
    board_size = max(1, len(base._get(farm, "tiles", []) or []))
    previous_value = _previous_op(previous)
    if previous_value == "MOVE":
        previous_value = "OTHER"
    tile_value = _tile_class(_tile_at(farm, position))
    return [
        *[float(value) for value in v3.encode_observation(obs)],
        float(base._get(obs, "hour", 0) or 0) / 23.0,
        position[0] / max(1, board_size - 1),
        position[1] / max(1, board_size - 1),
        unit / max(1, len(positions) - 1),
        len(positions) / 14.0,
        *(min(3.0, base._inventory_count(inventory, item) / 10.0) for item in (*PRODUCTS, *ANIMALS)),
        *(float(previous_value == value) for value in PREVIOUS_OPS),
        *(float(tile_value == value) for value in TILE_CLASSES),
    ]


def _task_goal(task: dict[str, Any], farm: Any) -> str:
    action = list(task.get("action") or ["PASS"])
    operation = str(action[0])
    item = ""
    if operation in {"PLANT", "PLACE", "PICKUP"} and len(action) >= 2:
        item = str(action[1])
    else:
        tile = _tile_at(farm, task.get("pos", (0, 0)))
        item = str(base._get(tile, "crop", "") or base._get(tile, "animal", "") or base._get(tile, "kind", "") or "")
    return f"{operation}:{item or 'NONE'}"


def _rerank_tasks(
    tasks: list[dict[str, Any]],
    obs: Any,
    farm: Any,
    positions: list[tuple[int, int]],
    inventories: list[Any],
) -> list[dict[str, Any]]:
    RUNTIME_COUNTS["calls"] += 1
    if not ENABLE_TASK_GOALS or TASK_GOAL_MODEL is None:
        return tasks
    previous_actions = list(getattr(v9, "_MISSION_PREVIOUS_ACTIONS", []) or [])
    desired: list[tuple[int, str, float]] = []
    for unit, _position in enumerate(positions):
        previous = previous_actions[unit] if unit < len(previous_actions) else None
        if _previous_op(previous) == "MOVE" or unit >= len(inventories):
            continue
        predicted = _prediction(_features(obs, farm, positions, inventories[unit], unit, previous))
        if predicted is None:
            continue
        goal, probability, is_ood = predicted
        if is_ood:
            RUNTIME_COUNTS["ood_workers"] += 1
            continue
        if probability >= MIN_GOAL_PROBABILITY and goal not in {"INCOMPLETE:NONE", "OTHER"}:
            desired.append((unit, goal, probability))
            RUNTIME_COUNTS["confident_workers"] += 1
    if not desired:
        return tasks

    result: list[dict[str, Any]] = []
    for original in tasks:
        task = dict(original)
        task["action"] = list(original.get("action") or ["PASS"])
        priority = int(task.get("priority", 0))
        if priority >= 15_000:
            result.append(task)
            continue
        goal = _task_goal(task, farm)
        matching = [
            probability
            for unit, desired_goal, probability in desired
            if desired_goal == goal
            and base._manhattan(positions[unit], task.get("pos", positions[unit])) > 0
            and base._can_do(task, unit, inventories[unit])
        ]
        if matching:
            bonus = round(TASK_GOAL_BONUS * max(matching))
            task["priority"] = min(MAX_RERANKED_PRIORITY, priority + bonus)
            task["v88_goal_bonus"] = bonus
            RUNTIME_COUNTS["boosted_tasks"] += 1
        result.append(task)
    return result


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
    return _rerank_tasks(tasks, obs, farm, positions, inventories), reserved


v11._field_tasks = _field_tasks


def reset_runtime_counts() -> None:
    for key in RUNTIME_COUNTS:
        RUNTIME_COUNTS[key] = 0


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v14.policy_diagnostics(obs))
    result["v88_task_goals"] = {
        "enabled": ENABLE_TASK_GOALS,
        "model_loaded": TASK_GOAL_MODEL is not None,
        "minimum_probability": MIN_GOAL_PROBABILITY,
        "bonus": TASK_GOAL_BONUS,
        "runtime_counts": dict(RUNTIME_COUNTS),
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v14.agent(obs)
