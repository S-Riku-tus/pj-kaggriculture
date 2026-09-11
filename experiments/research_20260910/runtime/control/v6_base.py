"""Kaggriculture V6: earlier premium-capital formation on V5's executor.

The first V6 ablation preserves V5's adaptive animal portfolio and sequential
animal missions.  It advances the Strawberry capital schedule by roughly one
day and permits the first land expansion through the temporary utilization dip
created when opening Wheat is harvested.
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
        Path.cwd() / "agents" / "v6",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (
                (candidate / "v5_base.py").is_file()
                and (candidate / "v4_base.py").is_file()
                and (candidate / "v3_base.py").is_file()
                and (candidate / "v2_base.py").is_file()
                and (candidate / "feature_schema.py").is_file()
                and (candidate / "strategy_model.json").is_file()
            )
            or (
                (candidate / "main.py").is_file()
                and (candidate.parent / "v5" / "main.py").is_file()
            )
        ),
        Path.cwd(),
    )


def _load_v5_module():
    packaged = MODULE_DIR / "v5_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v5" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v6_executor_base", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V5 executor base: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v5 = _load_v5_module()
v4 = v5.v4
v3 = v5.v3
base = v5.base
MODEL = v5.MODEL
OPENING_ACTIONS = v5.OPENING_ACTIONS


def _strategy_targets(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
) -> tuple[dict[str, int], dict[str, int], int, int, dict[str, float], int]:
    v5_animals, crops, hands, target_land, weights, _v5_pasture_target = v5._strategy_targets(
        obs, farm, opponent_farm, private
    )
    day = base._as_int(base._get(obs, "day", 0))
    summary = base._farm_summary(farm)
    _learned_animals, learned_crops, _learned_hands, _learned_land, _learned_weights = v3._strategy_targets(
        obs, farm, opponent_farm, private
    )
    # Holdout ablations showed that reducing V5's herd scale removed more
    # Milk/Wool revenue than the freed crop cells recovered.
    animals = dict(v5_animals)
    pasture_target = _v5_pasture_target

    if day < 18:
        opponent = base._opponent_summary(opponent_farm)
        demand = base._demand_profile(obs)
        prices = base._get(base._get(obs, "market", {}) or {}, "prices", {}) or {}
        economic_crops = base._desired_crops(
            day,
            summary["crops"],
            animals["COW"] + animals["SHEEP"],
            opponent,
            demand,
            prices,
        )
        berry_floor = v4._schedule(
            day,
            ((0, 0), (4, 2), (5, 8), (6, 12), (8, 18), (9, 20), (11, 26), (12, 30), (14, 32)),
        )
        crops["STRAWBERRY"] = max(
            summary["crops"]["STRAWBERRY"],
            berry_floor,
            round(0.55 * learned_crops["STRAWBERRY"] + 0.45 * economic_crops["STRAWBERRY"]),
        )
    # Project the retained V5 portfolio into a denser workload-aware tile
    # budget while keeping the feed reserve as a hard floor.
    animal_total = animals["COW"] + animals["SHEEP"]
    feed_floor = math.ceil(animal_total * 1.2)
    utilization_goal = 0.84 if target_land == 1 else (0.90 if target_land == 2 else 0.91)
    capacity_goal = round(target_land * 25 * utilization_goal)
    non_wheat = (
        animal_total
        + crops["CARROT"]
        + crops["TOMATO"]
        + crops["STRAWBERRY"]
        + crops["MELON"]
    )
    wheat_capacity = max(feed_floor, capacity_goal - non_wheat)
    crops["WHEAT"] = min(55, max(feed_floor, min(learned_crops["WHEAT"], wheat_capacity), wheat_capacity))
    if day >= 27:
        crops["WHEAT"] = summary["crops"]["WHEAT"]

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
    tasks, reserved = v5._field_tasks(
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
    day = base._as_int(base._get(obs, "day", 0))
    hour = base._as_int(base._get(obs, "hour", 0))
    if day >= 27 or hour >= 23:
        return tasks, reserved

    seeds = base._get(private, "seeds", {}) or {}
    planted_today = Counter(
        base._get(tile, "crop")
        for _x, _y, tile in base._iter_tiles(farm)
        if base._tile_kind(tile) == "PLANT"
        and base._as_int(base._get(tile, "planted_day", -1), -1) == day
    )
    plant_tasks = [task for task in tasks if task.get("action", [None])[0] == "PLANT"]
    used_positions = {task["pos"] for task in plant_tasks}
    wheat_by_position = {
        task["pos"]: task
        for task in plant_tasks
        if task.get("action", [None, None])[:2] == ["PLANT", "WHEAT"]
    }
    board_size = len(base._get(farm, "tiles", []) or []) or 10
    free_positions = [
        (x, y)
        for x, y, tile in base._iter_tiles(farm)
        if tile is None and (x, y) not in reserved and (x, y) not in used_positions
    ]
    free_positions.sort(
        key=lambda pos: (
            min(base._manhattan(pos, shed) for shed in base._shed_tiles(board_size)),
            pos[1],
            pos[0],
        )
    )
    replacement_positions = [*wheat_by_position, *free_positions]
    replacements: list[dict[str, Any]] = []
    replaced_wheat: set[tuple[int, int]] = set()
    cursor = 0
    existing_plant_tasks = Counter(
        str(task.get("action", [None, "UNKNOWN"])[1])
        for task in plant_tasks
        if len(task.get("action", [])) > 1
    )
    for crop, cap, priority in (("STRAWBERRY", 12, 9750),):
        deficit = max(0, crop_targets[crop] - summary["crops"][crop])
        task_budget = min(
            deficit,
            base._inventory_count(seeds, crop),
            max(0, cap - planted_today[crop]),
        )
        extra_tasks = max(0, task_budget - existing_plant_tasks[crop])
        for _ in range(extra_tasks):
            if cursor >= len(replacement_positions):
                break
            pos = replacement_positions[cursor]
            cursor += 1
            if pos in wheat_by_position:
                replaced_wheat.add(pos)
            replacements.append(base._task(pos, ["PLANT", crop], priority, label=f"plant-{crop}"))
    if replaced_wheat:
        tasks = [
            task
            for task in tasks
            if not (
                task["pos"] in replaced_wheat
                and task.get("action", [None, None])[:2] == ["PLANT", "WHEAT"]
            )
        ]
    tasks.extend(replacements)
    return tasks, reserved


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
    # Start before V5's utilization filter, then apply a gate that recognizes
    # the opening Wheat-recycle dip while retaining a stricter third-quadrant
    # threshold.
    day = base._as_int(base._get(obs, "day", 0))
    purchase_targets = dict(crop_targets)
    seeds = base._get(private, "seeds", {}) or {}
    berry_committed = summary["crops"]["STRAWBERRY"] + base._inventory_count(seeds, "STRAWBERRY")
    berry_deficit = max(0, crop_targets["STRAWBERRY"] - berry_committed)
    if day <= 12 and berry_deficit >= 4:
        # V4/V5 allocate the current empty-cell seed budget in WHEAT-first
        # order.  During the short opening recycle window that leaves only one
        # or two Strawberry seeds for the day.  Defer discretionary Wheat seed
        # purchases until the premium-capital batch is committed; feed stock
        # remains protected independently by BUY_PRODUCT orders.
        purchase_targets["WHEAT"] = summary["crops"]["WHEAT"] + base._inventory_count(seeds, "WHEAT")

    orders = v4._market_plan(
        obs,
        farm,
        private,
        summary,
        animal_targets,
        purchase_targets,
        target_hands,
        target_land,
        weights,
        pasture_target,
        actions,
        reserved,
    )
    unlocked = summary["unlocked"]
    if any(order[0] == "BUY_LAND" for order in orders):
        utilization_gate = 0.58 if unlocked == 1 else 0.72
        planned_tiles = sum(animal_targets.values()) + sum(crop_targets.values())
        plan_gate = summary["capacity"] - (3 if unlocked == 1 else 2)
        if summary["utilization"] < utilization_gate or planned_tiles < plan_gate:
            orders = [order for order in orders if order[0] != "BUY_LAND"]
    return orders[:10]


def agent(obs: Any) -> dict[str, Any]:
    """Return an early-expanding action through V5's feasible executor."""
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
    actions = v5._assign_tasks(positions, inventories, tasks)
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
