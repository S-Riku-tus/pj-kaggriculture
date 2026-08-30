"""V58: held-out-validated daily role continuity goal on V14.

The learned kNN layer predicts day-level Top-3 role/future-state goals only.
When in-domain and the predicted same-role rate is high, an existing animal or
crop role receives a one-score tie-break in V14's deterministic assignment.
Legality, emergency priority, inventory, routing, and market logic are inherited
unchanged. OOD and disabled states fall back exactly to V14.
"""

from __future__ import annotations

import heapq
import importlib.util
import json
import math
import sys
from pathlib import Path
from statistics import median
from typing import Any

if "__file__" in globals():
    MODULE_DIR = Path(__file__).resolve().parent
else:
    _runtime_candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd() / "agents" / "v58",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (candidate / "v14_base.py").is_file()
            or (
                (candidate / "main.py").is_file()
                and (candidate.parent / "v14" / "main.py").is_file()
            )
        ),
        Path.cwd(),
    )


def _load_v14_module():
    packaged = MODULE_DIR / "v14_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v14" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v58_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V14 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v14 = _load_v14_module()
v11 = v14.v11
v9 = v14.v9
v5 = v14.v5
base = v14.base

MODEL_FORMAT = "kaggriculture-v58-role-portfolio-knn-v1"
ENABLE_ROLE_CONTINUITY = False
ACTIVE_DAYS = range(6, 13)
MIN_SAME_ROLE_TARGET = 0.70
ROLE_SCORE_BONUS = 1
ROLE_TYPES = {"ANIMAL", "CROP"}
_SAFE_FIELD_TASKS = v11._field_tasks
_SAFE_MISSION_ASSIGN = v9._mission_assign
_SAFE_ASSIGNMENT_COST = v5._assignment_cost
_PREDICTION_DAY = -1
_CURRENT_PREDICTION: dict[str, Any] = {"active": False, "reason": "not-evaluated"}
_LAST_STEP = -1
_LAST_UNIT_COUNT = -1
_WORKER_ROLES: dict[int, str] = {}


def _load_model() -> dict[str, Any] | None:
    try:
        payload = json.loads((MODULE_DIR / "role_portfolio_model.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if payload.get("format") != MODEL_FORMAT:
        return None
    if not payload.get("training") or not payload.get("features") or not payload.get("labels"):
        return None
    return payload


MODEL = _load_model()


def _context(obs: Any, farm: Any, opponent: Any) -> dict[str, float]:
    own = base._farm_summary(farm)
    other = base._farm_summary(opponent)
    demand = base._demand_profile(obs)
    own_money = float(base._get(farm, "money", 0) or 0)
    other_money = float(base._get(opponent, "money", 0) or 0)
    town = base._get(obs, "town", {}) or {}
    return {
        "day": float(base._get(obs, "day", 0) or 0),
        "hands": float(len(base._get(farm, "hands", []) or [])),
        "own_animals": float(own["animal_total"]),
        "own_crops": float(sum(own["crops"].values())),
        "own_productive": float(own["productive"]),
        "own_money": own_money,
        "opponent_animals": float(other["animal_total"]),
        "opponent_crops": float(sum(other["crops"].values())),
        "opponent_productive": float(other["productive"]),
        "money_gap_ratio": (own_money - other_money) / max(1.0, own_money + other_money),
        "milk_demand": float(demand.get("MILK", 0)),
        "wool_demand": float(demand.get("WOOL", 0)),
        "wheat_demand": float(demand.get("WHEAT", 0)),
        "strawberry_demand": float(demand.get("STRAWBERRY", 0)),
        "unlocked_shops": float(len(base._get(town, "unlocked_shops", []) or [])),
    }


def _predict(obs: Any, farm: Any, opponent: Any) -> dict[str, Any]:
    if not ENABLE_ROLE_CONTINUITY or MODEL is None:
        return {"active": False, "reason": "disabled-or-missing"}
    day = base._as_int(base._get(obs, "day", 0))
    if day not in ACTIVE_DAYS:
        return {"active": False, "reason": "outside-active-days"}
    context = _context(obs, farm, opponent)
    vector = []
    for name in MODEL["features"]:
        scale = MODEL["feature_scales"][name]
        vector.append((context[name] - float(scale["center"])) / float(scale["scale"]))

    def distance(row: dict[str, Any]) -> float:
        return math.sqrt(
            sum(
                (left - float(right)) ** 2
                for left, right in zip(vector, row["vector"], strict=True)
            )
            / len(vector)
        )

    nearest = heapq.nsmallest(
        int(MODEL["neighbors"]),
        ((distance(row), row) for row in MODEL["training"]),
        key=lambda value: value[0],
    )
    nearest_distance = nearest[0][0]
    if nearest_distance > float(MODEL["ood_threshold"]):
        return {
            "active": False,
            "reason": "ood",
            "nearest_distance": nearest_distance,
        }
    labels = {
        name: median(float(row["labels"][index]) for _distance, row in nearest)
        for index, name in enumerate(MODEL["labels"])
    }
    same_role = labels["same_role_transition_rate"]
    return {
        "active": same_role >= MIN_SAME_ROLE_TARGET,
        "reason": "active" if same_role >= MIN_SAME_ROLE_TARGET else "low-continuity-target",
        "nearest_distance": nearest_distance,
        "labels": labels,
    }


def _task_role(task: dict[str, Any]) -> str | None:
    label = str(task.get("label", ""))
    op = str((task.get("action") or ["PASS"])[0])
    if label in {"animal-harvest", "feed", "care", "collect-fertilizer"} or label.startswith("place-"):
        return "ANIMAL"
    if label in {"crop-harvest", "water", "fertilize"} or label.startswith("plant-"):
        return "CROP"
    if op in {"FEED", "CARE", "COLLECT_FERTILIZER", "PLACE"}:
        return "ANIMAL"
    if op in {"WATER", "PLANT", "FERTILIZE"}:
        return "CROP"
    return None


def _action_role(action: list[Any], previous: str | None) -> str | None:
    op = str(action[0]) if action else "PASS"
    if op in {"FEED", "CARE", "COLLECT_FERTILIZER", "PLACE"}:
        return "ANIMAL"
    if op in {"WATER", "PLANT", "FERTILIZE"}:
        return "CROP"
    if op == "HARVEST":
        return previous
    return None


def _assignment_cost(
    unit: int,
    task: dict[str, Any],
    positions: list[tuple[int, int]],
    inventories: list[Any],
    density: Any,
) -> int:
    value = _SAFE_ASSIGNMENT_COST(unit, task, positions, inventories, density)
    if (
        unit > 0
        and _CURRENT_PREDICTION.get("active")
        and (task_role := _task_role(task)) in ROLE_TYPES
        and _WORKER_ROLES.get(unit) == task_role
    ):
        value -= ROLE_SCORE_BONUS * 100
    return value


v5._assignment_cost = _assignment_cost


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
    global _PREDICTION_DAY, _CURRENT_PREDICTION
    day = base._as_int(base._get(obs, "day", 0))
    if day != _PREDICTION_DAY:
        _PREDICTION_DAY = day
        _CURRENT_PREDICTION = _predict(obs, farm, opponent_farm or farm)
    return _SAFE_FIELD_TASKS(
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


v11._field_tasks = _field_tasks


def _mission_assign(
    positions: list[tuple[int, int]],
    inventories: list[Any],
    tasks: list[dict[str, Any]],
    step: int = 0,
) -> list[list[Any]]:
    global _LAST_STEP, _LAST_UNIT_COUNT
    if step != _LAST_STEP + 1 or step // 24 != _LAST_STEP // 24 or len(positions) != _LAST_UNIT_COUNT:
        _WORKER_ROLES.clear()
    actions = _SAFE_MISSION_ASSIGN(positions, inventories, tasks, step)
    for unit, action in enumerate(actions):
        if unit == 0:
            continue
        role = _action_role(action, _WORKER_ROLES.get(unit))
        if role is not None:
            _WORKER_ROLES[unit] = role
    _LAST_STEP = step
    _LAST_UNIT_COUNT = len(positions)
    return actions


v9._mission_assign = _mission_assign


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v14.policy_diagnostics(obs))
    safe = base._safe_observation(obs)
    prediction = (
        _predict(obs, safe[0], safe[1])
        if safe is not None
        else {"active": False, "reason": "invalid-observation"}
    )
    result["v58_role_continuity"] = {
        **prediction,
        "enabled": ENABLE_ROLE_CONTINUITY,
        "score_bonus": ROLE_SCORE_BONUS,
        "role_types": sorted(ROLE_TYPES),
        "minimum_same_role_target": MIN_SAME_ROLE_TARGET,
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v14.agent(obs)
