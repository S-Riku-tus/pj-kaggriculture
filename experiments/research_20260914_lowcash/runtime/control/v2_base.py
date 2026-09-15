"""Kaggriculture adaptive economic agent v2.

V2 keeps the observation-only, single-file runtime of v1 while replacing its
slow cash-crop opening with the productive-capital pattern measured in public
top-agent replays.  The policy is deterministic and has no mutable module state.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

CROP_DATA = {
    "WHEAT": {"seed": 10, "first": 2, "peak": 4, "interval": 0, "max": 6, "ongoing": False},
    "CARROT": {"seed": 20, "first": 2, "peak": 3, "interval": 0, "max": 4, "ongoing": False},
    "TOMATO": {"seed": 50, "first": 8, "peak": 8, "interval": 1, "max": 4, "ongoing": True},
    "STRAWBERRY": {"seed": 100, "first": 10, "peak": 10, "interval": 2, "max": 4, "ongoing": True},
    "MELON": {"seed": 80, "first": 10, "peak": 12, "interval": 0, "max": 6, "ongoing": False},
}

ANIMAL_DATA = {
    "GOOSE": {"cost": 300, "product": "EGG", "first": 4, "interval": 1, "max_held": 4},
    "COW": {"cost": 400, "product": "MILK", "first": 8, "interval": 2, "max_held": 6},
    "SHEEP": {"cost": 500, "product": "WOOL", "first": 6, "interval": 3, "max_held": 6},
}

PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER")
PREMIUM_PRODUCTS = ("STRAWBERRY", "MELON", "MILK", "WOOL")
BASE_PRICE = {
    "WHEAT": 25,
    "CARROT": 35,
    "TOMATO": 60,
    "STRAWBERRY": 120,
    "MELON": 250,
    "EGG": 50,
    "MILK": 160,
    "WOOL": 200,
    "FERTILIZER": 100,
}
SHOP_DEMAND = {
    "BAKERY": {"EGG": 1, "WHEAT": 1},
    "PIZZA_SHOP": {"MILK": 1, "TOMATO": 1, "WHEAT": 1},
    "BRUNCH_SPOT": {"EGG": 1, "WHEAT": 1, "STRAWBERRY": 1},
    "YARN_STORE": {"WOOL": 2},
    "ICE_CREAM_SHOP": {"STRAWBERRY": 1, "MILK": 1, "WHEAT": 1},
    "PET_CAFE": {"CARROT": 2},
    "SMOOTHIE_SHOP": {"STRAWBERRY": 1, "MILK": 1},
    "FARMERS_MARKET": {"WHEAT": 1, "CARROT": 1, "TOMATO": 1, "STRAWBERRY": 1},
}
MOVE_FOR_DELTA = {(0, -1): "NORTH", (0, 1): "SOUTH", (1, 0): "EAST", (-1, 0): "WEST"}


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    getter = getattr(obj, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except (TypeError, AttributeError):
            pass
    return getattr(obj, key, default)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _tile_kind(tile: Any) -> str | None:
    return _get(tile, "kind") if isinstance(tile, dict) or hasattr(tile, "get") else None


def _iter_tiles(farm: Any):
    for y, row in enumerate(_get(farm, "tiles", []) or []):
        for x, tile in enumerate(row):
            yield x, y, tile


def _manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _shed_tiles(board_size: int) -> list[tuple[int, int]]:
    half = board_size // 2
    return [(half - 1, half - 1), (half, half - 1), (half - 1, half), (half, half)]


def _nearest_shed(pos: tuple[int, int], board_size: int) -> tuple[int, int]:
    return min(_shed_tiles(board_size), key=lambda p: (_manhattan(pos, p), p[1], p[0]))


def _task(
    pos: tuple[int, int],
    action: list[Any],
    priority: int,
    *,
    required: str | None = None,
    unit: int | None = None,
    label: str = "",
) -> dict[str, Any]:
    return {
        "pos": pos,
        "action": action,
        "priority": priority,
        "required": required,
        "unit": unit,
        "label": label,
    }


def _inventory_count(inventory: Any, item: str) -> int:
    return max(0, _as_int(_get(inventory, item, 0)))


def _inventory_total(inventory: Any, items: tuple[str, ...] | None = None) -> int:
    if not isinstance(inventory, dict):
        try:
            inventory = dict(inventory)
        except (TypeError, ValueError):
            return 0
    if items is None:
        return sum(max(0, _as_int(value)) for value in inventory.values())
    return sum(max(0, _as_int(inventory.get(item, 0))) for item in items)


def _farm_summary(farm: Any) -> dict[str, Any]:
    crops = {crop: 0 for crop in CROP_DATA}
    animals = {animal: 0 for animal in ANIMAL_DATA}
    empty_structures = 0
    weeds = 0
    for _x, _y, tile in _iter_tiles(farm):
        kind = _tile_kind(tile)
        if kind == "PLANT" and _get(tile, "crop") in crops:
            crops[_get(tile, "crop")] += 1
        elif _get(tile, "animal") in animals:
            animals[_get(tile, "animal")] += 1
        elif kind in ("COOP", "PASTURE"):
            empty_structures += 1
        elif kind == "WEED":
            weeds += 1
    unlocked = len(_get(farm, "unlocked_quadrants", []) or [])
    productive = sum(crops.values()) + sum(animals.values())
    capacity = max(25, 25 * unlocked)
    return {
        "crops": crops,
        "animals": animals,
        "animal_total": sum(animals.values()),
        "empty_structures": empty_structures,
        "weeds": weeds,
        "unlocked": unlocked,
        "capacity": capacity,
        "productive": productive,
        "utilization": productive / capacity,
    }


def _demand_profile(obs: Any) -> Counter[str]:
    demand: Counter[str] = Counter()
    shops = _get(_get(obs, "town", {}) or {}, "unlocked_shops", []) or []
    for shop in shops:
        demand.update(SHOP_DEMAND.get(str(shop), {}))
    return demand


def _opponent_summary(farm: Any) -> dict[str, Any]:
    return _farm_summary(farm)


def _desired_animals(
    day: int,
    current: dict[str, int],
    opponent: dict[str, Any],
    demand: Counter[str],
    prices: Any,
) -> dict[str, int]:
    if day < 8:
        return {"COW": 2, "SHEEP": 2, "GOOSE": 0}

    cow = max(6, min(16, 4 + 2 * _as_int(_get(demand, "MILK", 0))))
    yarn_shops = _as_int(_get(demand, "WOOL", 0)) // 2
    sheep = max(2, min(9, 2 + 2 * yarn_shops))
    opponent_animals = opponent["animals"]
    milk_price = _as_int(_get(prices, "MILK", BASE_PRICE["MILK"]))
    wool_price = _as_int(_get(prices, "WOOL", BASE_PRICE["WOOL"]))

    # Price is a useful shared-market congestion signal, but Town demand remains
    # the main driver.  Adjustments are deliberately small to avoid oscillation.
    if milk_price < 90 and opponent_animals["COW"] >= 8:
        cow -= 2
    elif milk_price > 230:
        cow += 1
    if wool_price < 110 and opponent_animals["SHEEP"] >= 6:
        sheep -= 1
    elif wool_price > 270:
        sheep += 1

    cow = max(5, min(16, cow))
    sheep = max(2, min(9, sheep))
    # Expand at a bounded rate so a newly revealed demand signal cannot consume
    # the entire day's cash before Strawberry and land capacity are funded.
    cow = min(cow, 2 + 2 * (day - 7))
    sheep = min(sheep, 2 + (day - 7))
    if day >= 21:
        # New animals cannot reliably repay construction, feed, and routing this
        # late.  Existing animals remain managed until liquidation.
        cow = current["COW"]
        sheep = current["SHEEP"]
    return {"COW": cow, "SHEEP": sheep, "GOOSE": 0}


def _desired_crops(
    day: int,
    current: dict[str, int],
    animal_count: int,
    opponent: dict[str, Any],
    demand: Counter[str],
    prices: Any,
) -> dict[str, int]:
    feed_wheat = int(math.ceil(animal_count * 1.25)) if animal_count else 0
    if day == 0:
        wheat = 6
    elif day <= 7:
        wheat = max(10 if day <= 4 else 12, feed_wheat)
    elif day <= 10:
        wheat = max(10, feed_wheat)
    elif day <= 17:
        wheat = max(25, feed_wheat)
    elif day <= 20:
        wheat = max(20, feed_wheat)
    elif day <= 23:
        wheat = max(35, feed_wheat)
    elif day <= 26:
        wheat = max(44, feed_wheat)
    else:
        wheat = current["WHEAT"]

    melon = 11 if day <= 9 else 0
    if day < 5:
        strawberry = 0
    elif day <= 7:
        strawberry = 12
    elif day <= 10:
        strawberry = 20
    elif day <= 20:
        strawberry = max(16, min(42, 16 + 5 * _as_int(_get(demand, "STRAWBERRY", 0))))
        berry_price = _as_int(_get(prices, "STRAWBERRY", BASE_PRICE["STRAWBERRY"]))
        if berry_price < 65 and opponent["crops"]["STRAWBERRY"] >= 28:
            strawberry = max(16, strawberry - 6)
        elif berry_price > 190:
            strawberry = min(42, strawberry + 3)
    else:
        # Let existing ongoing crops finish, but rotate freed cells into wheat.
        strawberry = current["STRAWBERRY"]

    if day >= 27:
        melon = current["MELON"]
        strawberry = current["STRAWBERRY"]
    return {"WHEAT": wheat, "CARROT": 0, "TOMATO": 0, "STRAWBERRY": strawberry, "MELON": melon}


def _all_inventory_count(private: Any, item: str) -> int:
    total = _inventory_count(_get(private, "shed", {}) or {}, item)
    for inventory in _get(private, "inventories", []) or []:
        total += _inventory_count(inventory, item)
    return total


def _all_animal_count(farm: Any, private: Any, animal: str) -> int:
    return _farm_summary(farm)["animals"][animal] + _all_inventory_count(private, animal)


def _hire_cost(index: int) -> int:
    if index <= 1:
        return 1
    previous, current = 1, 1
    for _ in range(2, index + 1):
        previous, current = current, previous + current
    return current


def _target_hands(day: int) -> int:
    if day == 0:
        return 5
    if day == 1:
        return 2
    if day == 2:
        return 3
    if day <= 5:
        return 4
    if day <= 7:
        return 7
    if day <= 9:
        return 10
    if day <= 27:
        return 12
    return 11 if day == 28 else 8


def _market_sales(obs: Any, farm: Any, private: Any, animal_count: int) -> list[list[Any]]:
    day = _as_int(_get(obs, "day", 0))
    step = _as_int(_get(obs, "step", day * 24))
    money = float(_get(farm, "money", 0) or 0)
    shed = _get(private, "shed", {}) or {}
    prices = _get(_get(obs, "market", {}) or {}, "prices", {}) or {}
    shed_total = _inventory_total(shed)
    pressure = shed_total >= 72
    liquidation = day >= 27
    cash_hungry = (day <= 12 and money < 1200) or money < 250
    town_window = step % 4 == 1
    orders: list[list[Any]] = []

    wheat = _inventory_count(shed, "WHEAT")
    if day >= 29:
        wheat_reserve = 0
    elif day == 28:
        wheat_reserve = animal_count
    else:
        wheat_reserve = max(6, animal_count * 2)
    wheat_excess = max(0, wheat - wheat_reserve)
    if wheat_excess and (liquidation or pressure or cash_hungry or _as_int(_get(prices, "WHEAT", 0)) >= 20):
        orders.append(["SELL", "WHEAT", wheat_excess])

    for item in ("CARROT", "TOMATO", "EGG"):
        count = _inventory_count(shed, item)
        if count:
            orders.append(["SELL", item, count])

    floors = {"STRAWBERRY": 55, "MELON": 100, "MILK": 65, "WOOL": 80}
    for item in PREMIUM_PRODUCTS:
        count = _inventory_count(shed, item)
        if not count:
            continue
        price = _as_int(_get(prices, item, 0))
        sell_now = liquidation or pressure or cash_hungry or count >= 8 or (town_window and price >= floors[item])
        if sell_now:
            keep = 0 if liquidation or pressure or cash_hungry else 3
            orders.append(["SELL", item, max(1, count - keep)])

    fertilizer = _inventory_count(shed, "FERTILIZER")
    keep_fertilizer = 0 if liquidation or day < 7 else 6
    if fertilizer > keep_fertilizer:
        orders.append(["SELL", "FERTILIZER", fertilizer - keep_fertilizer])
    return orders[:10]


def _opening_orders(private: Any) -> list[list[Any]]:
    seeds = _get(private, "seeds", {}) or {}
    shed = _get(private, "shed", {}) or {}
    orders: list[list[Any]] = []
    if _inventory_count(seeds, "WHEAT") == 0:
        orders.append(["BUY_SEED", "WHEAT", 6])
    if _inventory_count(seeds, "MELON") == 0:
        orders.append(["BUY_SEED", "MELON", 11])
    if _inventory_count(shed, "COW") == 0:
        orders.append(["BUY_ANIMAL", "COW", 2])
    if _inventory_count(shed, "SHEEP") == 0:
        orders.append(["BUY_ANIMAL", "SHEEP", 2])
    if _inventory_count(shed, "WHEAT") == 0:
        orders.append(["BUY_PRODUCT", "WHEAT", 4])
    orders.extend([["HIRE"] for _ in range(max(0, 10 - len(orders)))])
    return orders[:10]


def _market_plan(
    obs: Any,
    farm: Any,
    private: Any,
    summary: dict[str, Any],
    animal_targets: dict[str, int],
    crop_targets: dict[str, int],
) -> list[list[Any]]:
    day = _as_int(_get(obs, "day", 0))
    hour = _as_int(_get(obs, "hour", 0))
    if day == 0 and hour == 0:
        return _opening_orders(private)

    money = float(_get(farm, "money", 0) or 0)
    animal_count = summary["animal_total"]
    orders = _market_sales(obs, farm, private, animal_count)
    prices = _get(_get(obs, "market", {}) or {}, "prices", {}) or {}
    shed = _get(private, "shed", {}) or {}
    budget = money
    for order in orders:
        if order[0] == "SELL":
            quoted = min(order[2], _inventory_count(shed, order[1])) * max(1, _as_int(_get(prices, order[1], 1)))
            budget += quoted * 0.75

    # Feed stock is the only hard budget constraint.  Fertilizer sales from the
    # opening animals finance these purchases before the first wheat harvest.
    total_wheat = _all_inventory_count(private, "WHEAT")
    desired_wheat_stock = animal_count * (1 if day >= 28 else 2)
    if day < 29 and animal_count and total_wheat < desired_wheat_stock and len(orders) < 10:
        price = max(1, _as_int(_get(prices, "WHEAT", 25), 25))
        amount = min(desired_wheat_stock - total_wheat, max(0, int((budget - 20) // price)))
        if amount:
            orders.append(["BUY_PRODUCT", "WHEAT", amount])
            budget -= amount * price

    # Hire to the observed top-agent workload curve.  More than ten workers are
    # added across consecutive turns once the three-quadrant farm is dense.
    target_hands = _target_hands(day)
    hires_today = _as_int(_get(farm, "hires_today", len(_get(farm, "hands", []) or [])))
    while hires_today < target_hands and len(orders) < 10:
        cost = _hire_cost(hires_today)
        if budget < cost + 15:
            break
        orders.append(["HIRE"])
        budget -= cost
        hires_today += 1

    if day >= 27:
        return orders[:10]

    reserve = 50 + animal_count * max(10, _as_int(_get(prices, "WHEAT", 25)))
    unlocked = summary["unlocked"]
    planned_tiles = sum(crop_targets.values()) + sum(animal_targets.values())
    if unlocked < 3 and len(orders) < 10:
        land_cost = 1000 if unlocked == 1 else 2000
        minimum_day = 4 if unlocked == 1 else 8
        utilization_gate = 0.90 if unlocked == 1 else 0.84
        plan_gate = summary["capacity"] + 2 if unlocked == 1 else summary["capacity"] - 2
        if (
            day >= minimum_day
            and summary["utilization"] >= utilization_gate
            and planned_tiles >= plan_gate
            and budget >= land_cost + reserve
        ):
            orders.append(["BUY_LAND"])
            budget -= land_cost

    if day < 21:
        for animal in ("COW", "SHEEP"):
            if len(orders) >= 10:
                break
            have = _all_animal_count(farm, private, animal)
            deficit = max(0, animal_targets[animal] - have)
            cost = ANIMAL_DATA[animal]["cost"]
            amount = min(deficit, max(0, int((budget - reserve) // cost)))
            if amount:
                orders.append(["BUY_ANIMAL", animal, amount])
                budget -= amount * cost

    seeds = _get(private, "seeds", {}) or {}
    for crop in ("WHEAT", "STRAWBERRY", "MELON"):
        if len(orders) >= 10:
            break
        deficit = crop_targets[crop] - summary["crops"][crop] - _inventory_count(seeds, crop)
        if deficit <= 0:
            continue
        cost = CROP_DATA[crop]["seed"]
        amount = min(deficit, max(0, int((budget - reserve) // cost)))
        if amount:
            orders.append(["BUY_SEED", crop, amount])
            budget -= amount * cost
    return orders[:10]


def _animal_due_next_refresh(tile: Any, day: int) -> bool:
    animal = _get(tile, "animal")
    if animal not in ANIMAL_DATA:
        return False
    data = ANIMAL_DATA[animal]
    next_age = day + 1 - _as_int(_get(tile, "placed_day", day))
    return next_age >= data["first"] and (next_age - data["first"]) % data["interval"] == 0


def _crop_due_next_refresh(tile: Any, day: int) -> bool:
    crop = _get(tile, "crop")
    if crop not in CROP_DATA or not CROP_DATA[crop]["ongoing"]:
        return False
    data = CROP_DATA[crop]
    next_age = day + 1 - _as_int(_get(tile, "planted_day", day))
    if next_age < data["first"]:
        return False
    production_index = (next_age - data["first"]) // data["interval"] + 1
    return (next_age - data["first"]) % data["interval"] == 0 and production_index <= data["max"]


def _animal_slots(farm: Any, count: int, board_size: int) -> list[tuple[int, int]]:
    positions = [(x, y) for x, y, tile in _iter_tiles(farm) if tile != "LOCKED"]
    shed = _shed_tiles(board_size)
    positions.sort(key=lambda pos: (min(_manhattan(pos, access) for access in shed), -pos[0], -pos[1]))
    return positions[:count]


def _movement(pos: tuple[int, int], target: tuple[int, int], unit_index: int) -> list[str]:
    dx = target[0] - pos[0]
    dy = target[1] - pos[1]
    if dx == 0 and dy == 0:
        return ["PASS"]
    horizontal_first = abs(dx) > abs(dy) or (abs(dx) == abs(dy) and unit_index % 2 == 0)
    if horizontal_first and dx:
        delta = (1 if dx > 0 else -1, 0)
    elif dy:
        delta = (0, 1 if dy > 0 else -1)
    else:
        delta = (1 if dx > 0 else -1, 0)
    return [MOVE_FOR_DELTA[delta]]


def _can_do(task: dict[str, Any], unit_index: int, inventory: Any) -> bool:
    if task["unit"] is not None and task["unit"] != unit_index:
        return False
    required = task["required"]
    return required is None or _inventory_count(inventory, required) > 0


def _assign_tasks(
    positions: list[tuple[int, int]], inventories: list[Any], tasks: list[dict[str, Any]]
) -> list[list[Any]]:
    actions: list[list[Any]] = [["PASS"] for _ in positions]
    free_units = set(range(len(positions)))
    remaining = list(tasks)
    while free_units and remaining:
        best: tuple[tuple[Any, ...], int, int] | None = None
        for task_index, task in enumerate(remaining):
            for unit_index in free_units:
                if not _can_do(task, unit_index, inventories[unit_index]):
                    continue
                distance = _manhattan(positions[unit_index], task["pos"])
                key = (task["priority"], -distance, -task["pos"][1], -task["pos"][0], -unit_index, task["label"])
                if best is None or key > best[0]:
                    best = (key, task_index, unit_index)
        if best is None:
            break
        _key, task_index, unit_index = best
        task = remaining.pop(task_index)
        actions[unit_index] = (
            list(task["action"])
            if positions[unit_index] == task["pos"]
            else _movement(positions[unit_index], task["pos"], unit_index)
        )
        free_units.remove(unit_index)
    return actions


def _field_tasks(
    obs: Any,
    farm: Any,
    private: Any,
    positions: list[tuple[int, int]],
    inventories: list[Any],
    summary: dict[str, Any],
    animal_targets: dict[str, int],
    crop_targets: dict[str, int],
) -> list[dict[str, Any]]:
    day = _as_int(_get(obs, "day", 0))
    hour = _as_int(_get(obs, "hour", 0))
    board_size = len(_get(farm, "tiles", []) or []) or 10
    remaining_turns = 24 - hour
    tasks: list[dict[str, Any]] = []
    animal_tiles: list[tuple[int, int, Any]] = []
    plant_tiles: list[tuple[int, int, Any]] = []
    for x, y, tile in _iter_tiles(farm):
        if _tile_kind(tile) == "PLANT":
            plant_tiles.append((x, y, tile))
        elif _get(tile, "animal") in ANIMAL_DATA:
            animal_tiles.append((x, y, tile))

    if day >= 29:
        cash_items = PRODUCTS
    elif day >= 27:
        # Wheat is still operational feed through Day 28; returning its carriers
        # as if they held sale goods prevents every FEED task from executing.
        cash_items = tuple(item for item in PRODUCTS if item != "WHEAT")
    else:
        cash_items = tuple(item for item in PRODUCTS if item not in ("WHEAT", "FERTILIZER"))
    for unit_index, (pos, inventory) in enumerate(zip(positions, inventories, strict=True)):
        carried = _inventory_total(inventory, cash_items)
        if carried and (day >= 27 or carried >= 4 or hour >= 20):
            priority = 19000 if day >= 29 else (17200 if day >= 27 else 8200)
            tasks.append(
                _task(_nearest_shed(pos, board_size), ["DROP"], priority, unit=unit_index, label="drop-goods")
            )

    for x, y, tile in animal_tiles:
        pos = (x, y)
        yield_units = _as_int(_get(tile, "yield_units", 0))
        animal = _get(tile, "animal")
        distance_home = _manhattan(pos, _nearest_shed(pos, board_size))
        can_cash_final = distance_home + 3 <= remaining_turns
        if yield_units and (day >= 27 or yield_units >= 3 or _animal_due_next_refresh(tile, day)):
            if day < 29 or can_cash_final:
                tasks.append(_task(pos, ["HARVEST"], 18100 if day >= 29 else 14500, label="animal-harvest"))
        if day < 29 and not bool(_get(tile, "fed_today", False)):
            emergency = _as_int(_get(tile, "consecutive_unfed", 0)) >= 1 or hour >= 18
            priority = 15400 if emergency else (13200 if day >= 28 and _animal_due_next_refresh(tile, day) else 12100)
            tasks.append(_task(pos, ["FEED"], priority, required="WHEAT", label="feed"))
        if day < 29 and not bool(_get(tile, "cared_today", False)):
            useful = day < 28 or _animal_due_next_refresh(tile, day)
            if useful:
                tasks.append(_task(pos, ["CARE"], 9300 if hour >= 18 else 7400, label="care"))
        if day < 29 and bool(_get(tile, "fertilizer_available", False)):
            # Early fertilizer is working capital for feed; later it either
            # doubles crop output or becomes a saleable by-product.  Missing a
            # daily collection destroys that value because it does not stack.
            collect_priority = 11100 if day <= 4 else 8300
            tasks.append(_task(pos, ["COLLECT_FERTILIZER"], collect_priority, label="collect-fertilizer"))

    for x, y, tile in plant_tiles:
        pos = (x, y)
        crop = _get(tile, "crop")
        data = CROP_DATA.get(crop)
        if data is None:
            continue
        age = day - _as_int(_get(tile, "planted_day", day))
        yield_units = _as_int(_get(tile, "yield_units", 0))
        distance_home = _manhattan(pos, _nearest_shed(pos, board_size))
        can_cash_final = distance_home + 3 <= remaining_turns
        harvestable = yield_units > 0 and (
            (data["ongoing"] and (yield_units >= 2 or day >= 27))
            or (not data["ongoing"] and age >= data["peak"])
        )
        if harvestable and (day < 29 or can_cash_final):
            priority = 18300 if day >= 29 else (14600 if day >= 27 else (11400 if not data["ongoing"] else 9000))
            tasks.append(_task(pos, ["HARVEST"], priority, label="crop-harvest"))
        if day < 29 and not bool(_get(tile, "watered_today", False)):
            useful_final_water = (
                day < 28 or _crop_due_next_refresh(tile, day) or (not data["ongoing"] and yield_units > 0)
            )
            if useful_final_water:
                emergency = _as_int(_get(tile, "consecutive_unwatered", 0)) >= 1 or hour >= 18
                tasks.append(_task(pos, ["WATER"], 15100 if emergency else 10600, label="water"))
        fertilized_until = _as_int(_get(tile, "fertilized_until_day", -1), -1)
        ongoing_due = data["ongoing"] and _crop_due_next_refresh(tile, day)
        bonus_start = math.ceil(data["peak"] / 2)
        one_time_due = not data["ongoing"] and bonus_start - 1 <= age < data["peak"]
        if day < 27 and fertilized_until < day and (ongoing_due or one_time_due):
            priority = 10100 if crop == "STRAWBERRY" else 8700
            tasks.append(_task(pos, ["FERTILIZE"], priority, required="FERTILIZER", label="fertilize"))

    desired_animals = sum(animal_targets.values())
    animal_slots = _animal_slots(farm, desired_animals, board_size)
    slot_set = set(animal_slots)
    structures = summary["animal_total"] + summary["empty_structures"]
    owned_animals = sum(_all_animal_count(farm, private, animal) for animal in ANIMAL_DATA)
    structures_needed = max(0, min(desired_animals, owned_animals) - structures) if day < 21 else 0
    for pos in animal_slots:
        if structures_needed <= 0:
            break
        x, y = pos
        tile = _get(farm, "tiles", [])[y][x]
        if _tile_kind(tile) == "WEED":
            tasks.append(_task(pos, ["DIG"], 8000, label="dig-animal-slot"))
            structures_needed -= 1
        elif tile is None:
            tasks.append(_task(pos, ["BUILD_PASTURE"], 7800, label="build-pasture"))
            structures_needed -= 1

    empty_pastures = [
        (x, y) for x, y, tile in _iter_tiles(farm) if _tile_kind(tile) == "PASTURE" and _get(tile, "animal") is None
    ]
    carriers: dict[str, list[int]] = {animal: [] for animal in ANIMAL_DATA}
    for unit_index, inventory in enumerate(inventories):
        for animal in ANIMAL_DATA:
            if _inventory_count(inventory, animal):
                carriers[animal].append(unit_index)
    pasture_index = 0
    if day < 21:
        for animal in ("COW", "SHEEP"):
            for unit_index in carriers[animal]:
                if pasture_index >= len(empty_pastures):
                    break
                pos = empty_pastures[pasture_index]
                pasture_index += 1
                tasks.append(
                    _task(pos, ["PLACE", animal], 11800, required=animal, unit=unit_index, label=f"place-{animal}")
                )

    if day < 27:
        for x, y, tile in _iter_tiles(farm):
            if _tile_kind(tile) == "WEED" and (x, y) not in slot_set:
                tasks.append(_task((x, y), ["DIG"], 5400, label="dig-weed"))

        plant_positions = [(x, y) for x, y, tile in _iter_tiles(farm) if tile is None and (x, y) not in slot_set]
        plant_positions.sort(
            key=lambda pos: (min(_manhattan(pos, shed) for shed in _shed_tiles(board_size)), pos[1], pos[0])
        )
        seeds = _get(private, "seeds", {}) or {}
        planted_today = Counter(
            _get(tile, "crop")
            for _x, _y, tile in plant_tiles
            if _as_int(_get(tile, "planted_day", -1), -1) == day
        )
        daily_plant_cap = {"WHEAT": 10, "STRAWBERRY": 8, "MELON": 11}
        cursor = 0
        for crop in ("WHEAT", "STRAWBERRY", "MELON"):
            deficit = max(0, crop_targets[crop] - summary["crops"][crop])
            remaining_daily = max(0, daily_plant_cap[crop] - planted_today[crop])
            available = min(deficit, _inventory_count(seeds, crop), remaining_daily)
            for _ in range(available):
                if cursor >= len(plant_positions):
                    break
                tasks.append(_task(plant_positions[cursor], ["PLANT", crop], 8500, label=f"plant-{crop}"))
                cursor += 1

    shed = _get(private, "shed", {}) or {}
    claimed_units: set[int] = set()
    harvest_items = tuple(item for item in PRODUCTS if item not in ("WHEAT", "FERTILIZER"))
    if day < 21:
        for animal in ("COW", "SHEEP", "GOOSE"):
            for _ in range(_inventory_count(shed, animal)):
                candidates = [
                    unit_index
                    for unit_index, inventory in enumerate(inventories)
                    if unit_index not in claimed_units
                    and sum(_inventory_count(inventory, item) for item in ANIMAL_DATA) == 0
                    and _inventory_total(inventory, harvest_items) == 0
                ]
                if not candidates:
                    break
                unit_index = min(
                    candidates,
                    key=lambda index: (
                        _manhattan(positions[index], _nearest_shed(positions[index], board_size)),
                        index,
                    ),
                )
                claimed_units.add(unit_index)
                tasks.append(
                    _task(
                        _nearest_shed(positions[unit_index], board_size),
                        ["PICKUP", animal, 1],
                        11600,
                        unit=unit_index,
                        label=f"pickup-{animal}",
                    )
                )

    if day < 29:
        unfed = sum(1 for _x, _y, tile in animal_tiles if not bool(_get(tile, "fed_today", False)))
        wheat_stock = _inventory_count(shed, "WHEAT")
        candidates = [
            unit_index
            for unit_index, inventory in enumerate(inventories)
            if unit_index not in claimed_units
            and _inventory_count(inventory, "WHEAT") == 0
            and sum(_inventory_count(inventory, animal) for animal in ANIMAL_DATA) == 0
            and _inventory_total(inventory, harvest_items) == 0
        ]
        carrier_count = min(len(candidates), unfed, wheat_stock)
        remaining = wheat_stock
        for offset, unit_index in enumerate(candidates[:carrier_count]):
            load = max(1, min(3, math.ceil(remaining / max(1, carrier_count - offset))))
            remaining -= load
            claimed_units.add(unit_index)
            tasks.append(
                _task(
                    _nearest_shed(positions[unit_index], board_size),
                    ["PICKUP", "WHEAT", load],
                    12600,
                    unit=unit_index,
                    label="pickup-wheat",
                )
            )

    fertilizer_tasks = sum(task["action"][0] == "FERTILIZE" for task in tasks)
    fertilizer_stock = _inventory_count(shed, "FERTILIZER")
    if fertilizer_tasks and fertilizer_stock:
        for unit_index, inventory in enumerate(inventories):
            if fertilizer_stock <= 0:
                break
            if unit_index in claimed_units or _inventory_count(inventory, "FERTILIZER"):
                continue
            claimed_units.add(unit_index)
            fertilizer_stock -= 1
            tasks.append(
                _task(
                    _nearest_shed(positions[unit_index], board_size),
                    ["PICKUP", "FERTILIZER", 1],
                    10300,
                    unit=unit_index,
                    label="pickup-fertilizer",
                )
            )
    return tasks


def _safe_observation(obs: Any) -> tuple[Any, Any, Any] | None:
    farms = _get(obs, "farms", []) or []
    player = _as_int(_get(obs, "player", 0))
    if not farms or not 0 <= player < len(farms):
        return None
    farm = farms[player]
    opponent = farms[1 - player] if len(farms) >= 2 else farm
    return farm, opponent, _get(obs, "private", {}) or {}


def agent(obs: Any) -> dict[str, Any]:
    """Return one observation-driven action for every active unit."""
    safe = _safe_observation(obs)
    if safe is None:
        return {"farmer": ["PASS"], "hands": [], "market": []}
    farm, opponent_farm, private = safe
    summary = _farm_summary(farm)
    opponent = _opponent_summary(opponent_farm)
    demand = _demand_profile(obs)
    prices = _get(_get(obs, "market", {}) or {}, "prices", {}) or {}
    day = _as_int(_get(obs, "day", 0))
    animal_targets = _desired_animals(day, summary["animals"], opponent, demand, prices)
    crop_targets = _desired_crops(day, summary["crops"], summary["animal_total"], opponent, demand, prices)

    positions = [tuple(_get(farm, "farmer", [0, 0]))]
    positions.extend(tuple(position) for position in (_get(farm, "hands", []) or []))
    raw_inventories = list(_get(private, "inventories", []) or [])
    inventories = [raw_inventories[index] if index < len(raw_inventories) else {} for index in range(len(positions))]
    tasks = _field_tasks(
        obs,
        farm,
        private,
        positions,
        inventories,
        summary,
        animal_targets,
        crop_targets,
    )
    actions = _assign_tasks(positions, inventories, tasks)
    return {
        "farmer": actions[0] if actions else ["PASS"],
        "hands": actions[1:],
        "market": _market_plan(obs, farm, private, summary, animal_targets, crop_targets),
    }
