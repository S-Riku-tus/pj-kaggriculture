"""Kaggriculture V5: adaptive portfolio on V4's feasible executor.

V5 keeps V4's pasture transactions, seed batching, crop recycling,
fertilizer logistics, assignment, and liquidation.  It removes independent
Cow/Sheep floors, blends learned and economic portfolio signals, allocates
remaining productive capacity to Wheat, and blocks plants that cannot be
watered before the daily refresh.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if "__file__" in globals():
    MODULE_DIR = Path(__file__).resolve().parent
else:
    _runtime_candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd() / "agents" / "v5",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (
                (candidate / "v4_base.py").is_file()
                and (candidate / "v3_base.py").is_file()
                and (candidate / "v2_base.py").is_file()
                and (candidate / "feature_schema.py").is_file()
                and (candidate / "strategy_model.json").is_file()
            )
            or (
                (candidate / "main.py").is_file()
                and (candidate.parent / "v4" / "main.py").is_file()
            )
        ),
        Path.cwd(),
    )


def _load_v4_module():
    packaged = MODULE_DIR / "v4_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v4" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v5_executor_base", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V4 executor base: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v4 = _load_v4_module()
v3 = v4.v3
base = v4.base
MODEL = v4.MODEL
OPENING_ACTIONS = v4.OPENING_ACTIONS
ANIMAL_SERVICE_LABELS = {"animal-harvest", "feed", "care", "collect-fertilizer"}
ANIMAL_SERVICE_ACTIONS = {"HARVEST", "FEED", "CARE", "COLLECT_FERTILIZER"}


def _owned_targets(farm: Any, private: Any) -> tuple[int, int]:
    return (
        v4._owned_animals(farm, private, "COW"),
        v4._owned_animals(farm, private, "SHEEP"),
    )


def _bounded_animal_mix(
    *,
    day: int,
    learned: dict[str, int],
    economic: dict[str, int],
    owned_cow: int,
    owned_sheep: int,
) -> dict[str, int]:
    """Project total scale and Cow/Sheep ratio without independent floors."""
    owned_total = owned_cow + owned_sheep
    if day >= 21:
        return {"GOOSE": 0, "COW": owned_cow, "SHEEP": owned_sheep}

    learned_total = learned["COW"] + learned["SHEEP"]
    economic_total = economic["COW"] + economic["SHEEP"]
    scale_floor = v4._schedule(
        day,
        ((0, 4), (6, 5), (8, 7), (10, 9), (12, 12), (14, 14), (16, 15)),
    )
    target_total = min(
        15,
        max(
            owned_total,
            scale_floor,
            round(0.80 * learned_total + 0.20 * economic_total),
        ),
    )
    learned_ratio = learned["COW"] / max(1, learned_total)
    economic_ratio = economic["COW"] / max(1, economic_total)
    cow_ratio = min(0.85, max(0.25, 0.75 * learned_ratio + 0.25 * economic_ratio))
    cow = round(target_total * cow_ratio)
    sheep = target_total - cow

    cow = max(owned_cow, cow)
    sheep = max(owned_sheep, sheep)
    while cow + sheep > 15:
        cow_room = cow - owned_cow
        sheep_room = sheep - owned_sheep
        if cow_room >= sheep_room and cow_room > 0:
            cow -= 1
        elif sheep_room > 0:
            sheep -= 1
        else:
            break
    return {"GOOSE": 0, "COW": cow, "SHEEP": sheep}


def _strategy_targets(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
) -> tuple[dict[str, int], dict[str, int], int, int, dict[str, float], int]:
    learned_animals, learned_crops, learned_hands, _learned_land, weights = v3._strategy_targets(
        obs, farm, opponent_farm, private
    )
    day = base._as_int(base._get(obs, "day", 0))
    summary = base._farm_summary(farm)
    opponent = base._opponent_summary(opponent_farm)
    demand = base._demand_profile(obs)
    prices = base._get(base._get(obs, "market", {}) or {}, "prices", {}) or {}
    owned_cow, owned_sheep = _owned_targets(farm, private)
    economic_animals = base._desired_animals(day, summary["animals"], opponent, demand, prices)
    animals = _bounded_animal_mix(
        day=day,
        learned=learned_animals,
        economic=economic_animals,
        owned_cow=owned_cow,
        owned_sheep=owned_sheep,
    )

    economic_crops = base._desired_crops(
        day,
        summary["crops"],
        animals["COW"] + animals["SHEEP"],
        opponent,
        demand,
        prices,
    )
    target_land = 1 if day < 5 else (2 if day < 9 else 3)
    crops = dict(learned_crops)
    if day < 18:
        berry_floor = v4._schedule(
            day,
            ((0, 0), (5, 2), (7, 12), (9, 18), (10, 20), (12, 26), (14, 28)),
        )
        crops["STRAWBERRY"] = max(
            summary["crops"]["STRAWBERRY"],
            berry_floor,
            round(0.65 * learned_crops["STRAWBERRY"] + 0.35 * economic_crops["STRAWBERRY"]),
        )
    else:
        crops["STRAWBERRY"] = summary["crops"]["STRAWBERRY"]
    if day >= 10:
        crops["MELON"] = summary["crops"]["MELON"]

    animal_total = animals["COW"] + animals["SHEEP"]
    feed_floor = math.ceil(animal_total * 1.2)
    utilization_goal = 0.84 if target_land == 1 else (0.90 if target_land == 2 else 0.86)
    capacity_goal = round(target_land * 25 * utilization_goal)
    filler_wheat = capacity_goal - animal_total - crops["STRAWBERRY"] - crops["MELON"]
    crops["WHEAT"] = min(55, max(feed_floor, learned_crops["WHEAT"], filler_wheat))
    if day >= 27:
        crops["WHEAT"] = summary["crops"]["WHEAT"]

    hands = max(
        learned_hands,
        v4._schedule(day, ((0, 5), (1, 2), (2, 3), (3, 4), (6, 7), (8, 10), (10, 11))),
    )
    hands = min(13, hands)
    pasture_target = min(15, max(animal_total, owned_cow + owned_sheep))
    return animals, crops, hands, target_land, weights, pasture_target


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
) -> tuple[list[dict[str, Any]], set[tuple[int, int]]]:
    tasks, reserved = v4._field_tasks(
        obs,
        farm,
        private,
        positions,
        inventories,
        summary,
        animal_targets,
        crop_targets,
        pasture_target,
    )
    hour = base._as_int(base._get(obs, "hour", 0))
    if hour >= 23:
        tasks = [task for task in tasks if task["action"][0] != "PLANT"]
    return _collapse_animal_missions(tasks), reserved


def _collapse_animal_missions(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expose only the next service step at each occupied animal tile."""
    ordinary: list[dict[str, Any]] = []
    by_tile: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for task in tasks:
        if str(task.get("label", "")) in ANIMAL_SERVICE_LABELS:
            by_tile.setdefault(task["pos"], []).append(task)
        else:
            ordinary.append(task)

    sequence = {"animal-harvest": 0, "feed": 1, "care": 2, "collect-fertilizer": 3}
    for candidates in by_tile.values():
        emergency_feed = next(
            (
                task
                for task in candidates
                if task.get("label") == "feed" and int(task.get("priority", 0)) >= 15400
            ),
            None,
        )
        chosen = emergency_feed or min(
            candidates,
            key=lambda task: (
                sequence[str(task.get("label", ""))],
                -int(task.get("priority", 0)),
            ),
        )
        ordinary.append(chosen)
    return ordinary


def _assignment_cost(
    unit: int,
    task: dict[str, Any],
    positions: list[tuple[int, int]],
    inventories: list[Any],
    density: Counter[tuple[int, int]],
) -> int:
    if not base._can_do(task, unit, inventories[unit]):
        return 10**8
    pos = positions[unit]
    target = task["pos"]
    distance = base._manhattan(pos, target)
    label = str(task.get("label", ""))
    action = task["action"][0]
    score = int(task["priority"]) - 420 * distance
    if distance == 0:
        score += 6800 if action in ANIMAL_SERVICE_ACTIONS else 2600
    elif distance == 1:
        score += 500
    if label.startswith("place-"):
        score += 1800
    if action == "FEED" and base._inventory_count(inventories[unit], "WHEAT"):
        score += 700
    score += min(1600, max(0, density[target] - 1) * 350)
    return -score * 100 + unit


def _assign_tasks(
    positions: list[tuple[int, int]], inventories: list[Any], tasks: list[dict[str, Any]]
) -> list[list[Any]]:
    actions: list[list[Any]] = [["PASS"] for _ in positions]
    if not positions or not tasks:
        return actions
    density: Counter[tuple[int, int]] = Counter(task["pos"] for task in tasks)
    impossible = 10**8
    dummy = 0
    if len(positions) <= len(tasks):
        columns: list[dict[str, Any] | None] = [*tasks, *([None] * len(positions))]
        cost = [
            [
                dummy if task is None else _assignment_cost(unit, task, positions, inventories, density)
                for task in columns
            ]
            for unit in range(len(positions))
        ]
        for unit, column in enumerate(v3._hungarian(cost)):
            if 0 <= column < len(tasks) and cost[unit][column] < min(dummy, impossible):
                task = tasks[column]
                actions[unit] = (
                    list(task["action"])
                    if positions[unit] == task["pos"]
                    else base._movement(positions[unit], task["pos"], unit)
                )
    else:
        columns: list[int | None] = [*range(len(positions)), *([None] * len(tasks))]
        cost = [
            [
                dummy if unit is None else _assignment_cost(unit, task, positions, inventories, density)
                for unit in columns
            ]
            for task in tasks
        ]
        for task_index, column in enumerate(v3._hungarian(cost)):
            if 0 <= column < len(positions) and cost[task_index][column] < min(dummy, impossible):
                unit = columns[column]
                if unit is None:
                    continue
                task = tasks[task_index]
                actions[unit] = (
                    list(task["action"])
                    if positions[unit] == task["pos"]
                    else base._movement(positions[unit], task["pos"], unit)
                )
    return actions


def _market_plan(
    obs: Any,
    farm: Any,
    private: Any,
    summary: dict[str, Any],
    animal_targets: dict[str, int],
    crop_targets: dict[str, int],
    target_hands: int,
    target_land: int,
    weights: dict[str, float],
    pasture_target: int,
    actions: list[list[Any]],
    reserved: set[tuple[int, int]],
) -> list[list[Any]]:
    orders = v4._market_plan(
        obs,
        farm,
        private,
        summary,
        animal_targets,
        crop_targets,
        target_hands,
        target_land,
        weights,
        pasture_target,
        actions,
        reserved,
    )
    if any(order[0] == "BUY_LAND" for order in orders):
        unlocked = summary["unlocked"]
        utilization_gate = 0.78 if unlocked == 1 else 0.74
        planned_tiles = sum(animal_targets.values()) + sum(crop_targets.values())
        if summary["utilization"] < utilization_gate or planned_tiles < summary["capacity"] - 2:
            orders = [order for order in orders if order[0] != "BUY_LAND"]
    return orders


def agent(obs: Any) -> dict[str, Any]:
    """Return an adaptive, feasibility-constrained action."""
    safe = base._safe_observation(obs)
    if safe is None:
        return {"farmer": ["PASS"], "hands": [], "market": []}
    farm, opponent_farm, private = safe
    opening = v3._safe_opening(obs, farm)
    if opening is not None:
        return opening

    summary = base._farm_summary(farm)
    animal_targets, crop_targets, target_hands, target_land, weights, pasture_target = _strategy_targets(
        obs, farm, opponent_farm, private
    )
    positions = [tuple(base._get(farm, "farmer", [0, 0]))]
    positions.extend(tuple(position) for position in (base._get(farm, "hands", []) or []))
    raw_inventories = list(base._get(private, "inventories", []) or [])
    inventories = [
        raw_inventories[index] if index < len(raw_inventories) else {}
        for index in range(len(positions))
    ]
    tasks, reserved = _field_tasks(
        obs,
        farm,
        private,
        positions,
        inventories,
        summary,
        animal_targets,
        crop_targets,
        pasture_target,
    )
    actions = _assign_tasks(positions, inventories, tasks)
    market = _market_plan(
        obs,
        farm,
        private,
        summary,
        animal_targets,
        crop_targets,
        target_hands,
        target_land,
        weights,
        pasture_target,
        actions,
        reserved,
    )
    return {
        "farmer": actions[0] if actions else ["PASS"],
        "hands": actions[1:],
        "market": market,
    }
