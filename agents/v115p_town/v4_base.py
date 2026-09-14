"""Kaggriculture V4: feasible expert strategy with route-dense execution.

V4 keeps V3's Rank-1 opening and Top-3 strategic model, but treats model
outputs as desired goals rather than executable orders.  A feasibility layer
projects those goals through pasture capacity, crop horizons, free tiles, and
small just-in-time purchase batches.  The executor then favors completing all
useful work at the current tile before paying for another trip across the farm.
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
        Path.cwd() / "agents" / "v4",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (
                (candidate / "v3_base.py").is_file()
                and (candidate / "v2_base.py").is_file()
                and (candidate / "feature_schema.py").is_file()
                and (candidate / "strategy_model.json").is_file()
            )
            or (
                (candidate / "main.py").is_file()
                and (candidate.parent / "v3" / "main.py").is_file()
                and (candidate.parent / "v2" / "main.py").is_file()
            )
        ),
        Path.cwd(),
    )


def _load_v3_module():
    packaged = MODULE_DIR / "v3_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v3" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v4_strategy_base", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V3 strategy base: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v3 = _load_v3_module()
base = v3.base
MODEL = v3.MODEL
OPENING_ACTIONS = v3.OPENING_ACTIONS


def _schedule(day: int, points: tuple[tuple[int, int], ...]) -> int:
    value = points[0][1]
    for start, candidate in points:
        if day < start:
            break
        value = candidate
    return value


def _owned_animals(farm: Any, private: Any, animal: str) -> int:
    return base._all_animal_count(farm, private, animal)


def _pasture_count(farm: Any) -> int:
    return sum(
        base._tile_kind(tile) == "PASTURE"
        for _x, _y, tile in base._iter_tiles(farm)
    )


def _pasture_target(day: int, animal_targets: dict[str, int], farm: Any, private: Any) -> int:
    # Rank 1/2/3 all build capacity before buying the corresponding animal.
    floor = _schedule(
        day,
        ((0, 4), (5, 5), (6, 6), (7, 8), (8, 10), (9, 11), (10, 12), (12, 13), (16, 14)),
    )
    owned = sum(_owned_animals(farm, private, animal) for animal in ("COW", "SHEEP"))
    return min(15, max(floor, owned, animal_targets["COW"] + animal_targets["SHEEP"]))


def _strategy_targets(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
) -> tuple[dict[str, int], dict[str, int], int, int, dict[str, float], int]:
    animals, crops, hands, _learned_land, weights = v3._strategy_targets(
        obs, farm, opponent_farm, private
    )
    day = base._as_int(base._get(obs, "day", 0))
    summary = base._farm_summary(farm)
    demand = base._demand_profile(obs)

    if day >= 3:
        cow_floor = _schedule(day, ((3, 2), (6, 3), (8, 5), (10, 7), (12, 8), (16, 9)))
        sheep_floor = _schedule(day, ((3, 2), (8, 3), (10, 4), (12, 5), (15, 6)))
        milk_demand = base._as_int(base._get(demand, "MILK", 0))
        wool_demand = base._as_int(base._get(demand, "WOOL", 0))
        if milk_demand >= wool_demand + 2:
            cow_floor += 1
        elif wool_demand >= milk_demand + 2:
            sheep_floor += 1

        animals["COW"] = max(animals["COW"], cow_floor, _owned_animals(farm, private, "COW"))
        animals["SHEEP"] = max(
            animals["SHEEP"], sheep_floor, _owned_animals(farm, private, "SHEEP")
        )
        while animals["COW"] + animals["SHEEP"] > 15:
            if animals["COW"] - cow_floor >= animals["SHEEP"] - sheep_floor:
                animals["COW"] -= 1
            else:
                animals["SHEEP"] -= 1

        wheat_floor = _schedule(
            day,
            ((3, 8), (6, 10), (10, 12), (12, 22), (14, 26), (18, 20), (21, 25), (24, 34), (26, 42)),
        )
        berry_floor = _schedule(day, ((3, 0), (5, 2), (7, 12), (9, 18), (10, 20), (12, 28), (14, 30)))
        feed_floor = math.ceil((animals["COW"] + animals["SHEEP"]) * 1.2)
        crops["WHEAT"] = max(crops["WHEAT"], wheat_floor, feed_floor)
        if day <= 17:
            crops["STRAWBERRY"] = max(crops["STRAWBERRY"], berry_floor)
        else:
            crops["STRAWBERRY"] = summary["crops"]["STRAWBERRY"]
        if day >= 10:
            # Existing Melon may remain productive; this prevents the state
            # target from being misread as an instruction to replace it.
            crops["MELON"] = summary["crops"]["MELON"]
        if day >= 27:
            crops["WHEAT"] = summary["crops"]["WHEAT"]

    target_land = 1 if day < 5 else (2 if day < 9 else 3)
    hands = max(hands, _schedule(day, ((0, 5), (1, 2), (2, 3), (3, 4), (6, 7), (8, 10), (10, 11))))
    hands = min(13, hands)
    pasture_target = _pasture_target(day, animals, farm, private)
    return animals, crops, hands, target_land, weights, pasture_target


def _animal_slots(farm: Any, target: int, board_size: int) -> list[tuple[int, int]]:
    existing = [
        (x, y)
        for x, y, tile in base._iter_tiles(farm)
        if base._tile_kind(tile) == "PASTURE"
    ]
    existing.sort(key=lambda pos: (base._manhattan(pos, base._nearest_shed(pos, board_size)), pos[1], pos[0]))
    selected = list(existing)
    candidates = [
        (x, y)
        for x, y, tile in base._iter_tiles(farm)
        if tile is None or base._tile_kind(tile) == "WEED"
    ]
    shed_tiles = base._shed_tiles(board_size)
    candidates.sort(
        key=lambda pos: (
            min(base._manhattan(pos, shed) for shed in shed_tiles),
            pos[1],
            pos[0],
        )
    )
    for pos in candidates:
        if len(selected) >= target:
            break
        if pos not in selected:
            selected.append(pos)
    return selected


def _ongoing_finished(tile: Any, day: int) -> bool:
    crop = base._get(tile, "crop")
    data = base.CROP_DATA.get(crop)
    if not data or not data["ongoing"]:
        return False
    final_age = data["first"] + data["interval"] * (data["max"] - 1)
    age = day - base._as_int(base._get(tile, "planted_day", day))
    return age >= final_age and base._as_int(base._get(tile, "yield_units", 0)) == 0


def _water_is_useful(tile: Any, day: int) -> bool:
    if _ongoing_finished(tile, day):
        return False
    if base._as_int(base._get(tile, "consecutive_unwatered", 0)) >= 1:
        return True
    crop = base._get(tile, "crop")
    data = base.CROP_DATA.get(crop)
    if data is None:
        return False
    age = day - base._as_int(base._get(tile, "planted_day", day))
    if not data["ongoing"]:
        return math.ceil(data["peak"] / 2) <= age <= data["peak"]
    return base._crop_due_next_refresh(tile, day) and base._as_int(
        base._get(tile, "fertilized_until_day", -1), -1
    ) >= day


def _task_key(task: dict[str, Any]) -> tuple[Any, ...]:
    return (task["pos"], tuple(task["action"]), task.get("unit"), task.get("required"))


def _add_plant_tasks(
    tasks: list[dict[str, Any]],
    obs: Any,
    farm: Any,
    private: Any,
    summary: dict[str, Any],
    crop_targets: dict[str, int],
    reserved: set[tuple[int, int]],
) -> None:
    day = base._as_int(base._get(obs, "day", 0))
    if day >= 27:
        return
    board_size = len(base._get(farm, "tiles", []) or []) or 10
    plant_positions = [
        (x, y)
        for x, y, tile in base._iter_tiles(farm)
        if tile is None and (x, y) not in reserved
    ]
    plant_positions.sort(
        key=lambda pos: (
            min(base._manhattan(pos, shed) for shed in base._shed_tiles(board_size)),
            pos[1],
            pos[0],
        )
    )
    seeds = base._get(private, "seeds", {}) or {}
    planted_today = Counter(
        base._get(tile, "crop")
        for _x, _y, tile in base._iter_tiles(farm)
        if base._tile_kind(tile) == "PLANT"
        and base._as_int(base._get(tile, "planted_day", -1), -1) == day
    )
    feed_floor = math.ceil(sum(summary["animals"].values()) * 1.2)
    crop_order = ("WHEAT", "STRAWBERRY", "MELON")
    daily_caps = {"WHEAT": 12, "STRAWBERRY": 10, "MELON": 11}
    cursor = 0
    for crop in crop_order:
        if crop == "MELON" and day >= 10:
            continue
        if crop == "STRAWBERRY" and day >= 18:
            continue
        deficit = max(0, crop_targets[crop] - summary["crops"][crop])
        remaining_daily = max(0, daily_caps[crop] - planted_today[crop])
        available = min(deficit, base._inventory_count(seeds, crop), remaining_daily)
        feed_shortage = crop == "WHEAT" and summary["crops"]["WHEAT"] < feed_floor
        priority = 9700 if crop == "STRAWBERRY" else (9600 if feed_shortage else 9000)
        for _ in range(available):
            if cursor >= len(plant_positions):
                return
            tasks.append(
                base._task(
                    plant_positions[cursor],
                    ["PLANT", crop],
                    priority,
                    label=f"plant-{crop}",
                )
            )
            cursor += 1


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
    day = base._as_int(base._get(obs, "day", 0))
    board_size = len(base._get(farm, "tiles", []) or []) or 10
    raw = base._field_tasks(
        obs,
        farm,
        private,
        positions,
        inventories,
        summary,
        animal_targets,
        crop_targets,
    )
    slots = _animal_slots(farm, pasture_target, board_size)
    reserved = set(slots)
    tile_at = {(x, y): tile for x, y, tile in base._iter_tiles(farm)}
    empty_pastures = sum(
        base._tile_kind(tile) == "PASTURE" and base._get(tile, "animal") is None
        for tile in tile_at.values()
    )
    carried_animals = sum(
        base._inventory_count(inventory, animal)
        for inventory in inventories
        for animal in ("COW", "SHEEP")
    )
    structures = _pasture_count(farm)
    missing_structures = max(0, pasture_target - structures)
    planned_builds = 0
    extra: list[dict[str, Any]] = []
    for pos in (candidate for candidate in slots if base._tile_kind(tile_at[candidate]) != "PASTURE"):
        if missing_structures <= 0:
            break
        tile = tile_at[pos]
        if base._tile_kind(tile) == "WEED":
            extra.append(base._task(pos, ["DIG"], 13300, label="dig-pasture-transaction"))
        elif tile is None:
            extra.append(base._task(pos, ["BUILD_PASTURE"], 12800, label="build-pasture-transaction"))
            planned_builds += 1
        missing_structures -= 1

    pickup_room = max(0, empty_pastures + planned_builds - carried_animals)
    pickup_kept = 0
    transformed: list[dict[str, Any]] = []
    priority_boost = {
        "care": 2600,
        "collect-fertilizer": 3000,
        "dig-weed": 4000,
        "fertilize": 900,
        "place-COW": 1800,
        "place-SHEEP": 1800,
    }
    fertilizer_pickups: list[dict[str, Any]] = []
    for original in raw:
        task = dict(original)
        task["action"] = list(original["action"])
        label = str(task.get("label", ""))
        pos = task["pos"]
        if label in {"dig-animal-slot", "build-pasture"} or label.startswith("plant-"):
            continue
        if label == "water" and not _water_is_useful(tile_at[pos], day):
            continue
        if label.startswith("pickup-") and label not in {"pickup-wheat", "pickup-fertilizer"}:
            if pickup_kept >= pickup_room:
                continue
            pickup_kept += 1
        if label == "pickup-fertilizer":
            fertilizer_pickups.append(task)
            continue
        if label == "dig-weed" and pos in reserved:
            continue
        task["priority"] = int(task["priority"]) + priority_boost.get(label, 0)
        transformed.append(task)

    # Three loaded fertilizer routes are enough to service the crop cluster;
    # one-unit trips were a major source of V2/V3 movement waste.
    fertilize_count = sum(task["action"][0] == "FERTILIZE" for task in transformed)
    if fertilize_count:
        stock = base._inventory_count(base._get(private, "shed", {}) or {}, "FERTILIZER")
        carriers = min(len(fertilizer_pickups), 3, math.ceil(fertilize_count / 3), stock)
        remaining = min(stock, fertilize_count)
        for task in fertilizer_pickups[:carriers]:
            load = max(1, min(4, math.ceil(remaining / max(1, carriers))))
            remaining -= load
            task["action"] = ["PICKUP", "FERTILIZER", load]
            task["priority"] = 10600
            transformed.append(task)

    for x, y, tile in base._iter_tiles(farm):
        if _ongoing_finished(tile, day):
            transformed.append(base._task((x, y), ["DIG"], 10800, label="dig-exhausted-crop"))

    transformed.extend(extra)
    _add_plant_tasks(transformed, obs, farm, private, summary, crop_targets, reserved)
    deduplicated: dict[tuple[Any, ...], dict[str, Any]] = {}
    for task in transformed:
        key = _task_key(task)
        previous = deduplicated.get(key)
        if previous is None or int(task["priority"]) > int(previous["priority"]):
            deduplicated[key] = task
    return list(deduplicated.values()), reserved


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
        score += 4200 if action in {"HARVEST", "FEED", "CARE", "COLLECT_FERTILIZER"} else 2600
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


def _estimated_budget(orders: list[list[Any]], obs: Any, farm: Any, private: Any) -> float:
    money = float(base._get(farm, "money", 0) or 0)
    prices = base._get(base._get(obs, "market", {}) or {}, "prices", {}) or {}
    shed = base._get(private, "shed", {}) or {}
    for order in orders:
        if order[0] == "SELL":
            quantity = min(order[2], base._inventory_count(shed, order[1]))
            money += quantity * max(1, base._as_int(base._get(prices, order[1], 1))) * 0.75
    return money


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
    day = base._as_int(base._get(obs, "day", 0))
    orders = base._market_plan(obs, farm, private, summary, animal_targets, crop_targets)
    orders = v3._shape_market(orders, obs, farm, private, target_hands, target_land, weights)
    planned_builds = sum(action and action[0] == "BUILD_PASTURE" for action in actions)
    structures_after = min(pasture_target, _pasture_count(farm) + planned_builds)
    owned_total = sum(_owned_animals(farm, private, animal) for animal in ("COW", "SHEEP"))
    animal_room = max(0, structures_after - owned_total)
    seeds = base._get(private, "seeds", {}) or {}
    reusable_tiles = sum(
        (tile is None or base._tile_kind(tile) == "WEED" or _ongoing_finished(tile, day))
        and (x, y) not in reserved
        for x, y, tile in base._iter_tiles(farm)
    )
    seed_room = max(
        0,
        reusable_tiles
        - sum(base._inventory_count(seeds, crop) for crop in ("WHEAT", "STRAWBERRY", "MELON")),
    )
    batches = {"WHEAT": 8, "STRAWBERRY": 6, "MELON": 4}
    filtered: list[list[Any]] = []
    for order in orders:
        order = list(order)
        if order[0] == "BUY_ANIMAL":
            amount = min(order[2], animal_room, 2)
            if amount <= 0:
                continue
            order[2] = amount
            animal_room -= amount
        elif order[0] == "BUY_SEED":
            crop = order[1]
            if (crop == "MELON" and day >= 10) or (crop == "STRAWBERRY" and day >= 18):
                continue
            amount = min(order[2], batches.get(crop, 4), seed_room)
            if amount <= 0:
                continue
            order[2] = amount
            seed_room -= amount
        filtered.append(order)

    unlocked = summary["unlocked"]
    if unlocked < target_land and not any(order[0] == "BUY_LAND" for order in filtered):
        land_cost = 1000 if unlocked == 1 else 2000
        reserve = 100 + summary["animal_total"] * 25
        if _estimated_budget(filtered, obs, farm, private) >= land_cost + reserve:
            insertion = next(
                (index for index, order in enumerate(filtered) if order[0] not in {"SELL", "BUY_PRODUCT"}),
                len(filtered),
            )
            filtered.insert(insertion, ["BUY_LAND"])
    return filtered[:10]


def agent(obs: Any) -> dict[str, Any]:
    """Return a feasibility-constrained action for every active worker."""
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
