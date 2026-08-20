"""Kaggriculture closed-loop economic rule agent v1.

The submission is deliberately self-contained: Kaggle only needs this file and
calls ``agent(obs)`` once per turn.  The policy keeps no mutable module state,
so it is safe when the same file occupies both seats in a local match.
"""

from __future__ import annotations

import math
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

MOVE_FOR_DELTA = {
    (0, -1): "NORTH",
    (0, 1): "SOUTH",
    (1, 0): "EAST",
    (-1, 0): "WEST",
}


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Read both ordinary dictionaries and Kaggle's Struct-like objects."""
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


def _is_shed_tile(pos: tuple[int, int], board_size: int) -> bool:
    return pos in set(_shed_tiles(board_size))


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
    return _as_int(_get(inventory, item, 0))


def _inventory_total(inventory: Any, items: tuple[str, ...] | None = None) -> int:
    if not isinstance(inventory, dict):
        try:
            inventory = dict(inventory)
        except (TypeError, ValueError):
            return 0
    if items is None:
        return sum(max(0, _as_int(n)) for n in inventory.values())
    return sum(max(0, _as_int(inventory.get(item, 0))) for item in items)


def _farm_summary(farm: Any) -> dict[str, Any]:
    crops = {crop: 0 for crop in CROP_DATA}
    animals = {animal: 0 for animal in ANIMAL_DATA}
    empty_structures = 0
    weeds = 0
    occupied = 0
    for _x, _y, tile in _iter_tiles(farm):
        if tile is None or tile == "LOCKED":
            continue
        occupied += 1
        kind = _tile_kind(tile)
        if kind == "PLANT":
            crop = _get(tile, "crop")
            if crop in crops:
                crops[crop] += 1
        elif kind == "WEED":
            weeds += 1
        else:
            animal = _get(tile, "animal")
            if animal in animals:
                animals[animal] += 1
            elif kind in ("COOP", "PASTURE"):
                empty_structures += 1
    return {
        "crops": crops,
        "animals": animals,
        "animal_total": sum(animals.values()),
        "empty_structures": empty_structures,
        "weeds": weeds,
        "occupied": occupied,
    }


def _opponent_profile(farm: Any) -> dict[str, Any]:
    summary = _farm_summary(farm)
    animals = summary["animals"]
    crops = summary["crops"]
    return {
        "cow_heavy": animals["COW"] >= 6 or animals["COW"] >= animals["SHEEP"] + 4,
        "sheep_heavy": animals["SHEEP"] >= 6,
        "strawberry_heavy": crops["STRAWBERRY"] >= 16,
        "melon_heavy": crops["MELON"] >= 12,
        "summary": summary,
    }


def _desired_animals(day: int, opponent: dict[str, Any]) -> dict[str, int]:
    if day < 4:
        targets = {"COW": 0, "SHEEP": 0, "GOOSE": 0}
    elif day < 9:
        targets = {"COW": 4, "SHEEP": 1, "GOOSE": 0}
    elif day < 15:
        targets = {"COW": 6, "SHEEP": 3, "GOOSE": 0}
    else:
        targets = {"COW": 8, "SHEEP": 4, "GOOSE": 0}

    # Shared premium markets punish mirror strategies.  This is intentionally a
    # small adjustment; v1 adapts without throwing away an established economy.
    if opponent["cow_heavy"] and day >= 9:
        targets["COW"] = min(targets["COW"], 5)
        targets["SHEEP"] = max(targets["SHEEP"], 5 if day < 15 else 6)
    if opponent["sheep_heavy"] and day >= 9:
        targets["SHEEP"] = min(targets["SHEEP"], 3)
        targets["COW"] = max(targets["COW"], 7 if day >= 15 else 6)
    return targets


def _desired_crops(
    day: int,
    animal_count: int,
    current: dict[str, int],
    opponent: dict[str, Any],
) -> dict[str, int]:
    # About 1.25 peak-watered wheat tiles sustain one animal indefinitely.
    feed_wheat = int(math.ceil(animal_count * 1.25)) if animal_count else 0
    if day <= 3:
        return {"WHEAT": 10, "CARROT": 8, "STRAWBERRY": 0, "TOMATO": 0, "MELON": 0}
    if day <= 8:
        targets = {"WHEAT": max(10, feed_wheat), "CARROT": 5, "STRAWBERRY": 8, "TOMATO": 0, "MELON": 0}
    elif day <= 18:
        strawberry = 12 if opponent["strawberry_heavy"] else 16
        targets = {
            "WHEAT": max(12, feed_wheat),
            "CARROT": 5,
            "STRAWBERRY": strawberry,
            "TOMATO": 4 if opponent["strawberry_heavy"] else 0,
            "MELON": 0,
        }
    elif day <= 25:
        # A newly planted strawberry cannot be harvested before the season ends.
        targets = {
            "WHEAT": max(12, feed_wheat),
            "CARROT": 8,
            "STRAWBERRY": current["STRAWBERRY"],
            "TOMATO": current["TOMATO"],
            "MELON": current["MELON"],
        }
    elif day <= 26:
        targets = {
            "WHEAT": current["WHEAT"],
            "CARROT": 10,
            "STRAWBERRY": current["STRAWBERRY"],
            "TOMATO": current["TOMATO"],
            "MELON": current["MELON"],
        }
    else:
        targets = dict(current)
    return targets


def _all_inventory_count(private: Any, item: str) -> int:
    total = _inventory_count(_get(private, "shed", {}) or {}, item)
    for inv in _get(private, "inventories", []) or []:
        total += _inventory_count(inv, item)
    return total


def _all_animal_count(farm: Any, private: Any, animal: str) -> int:
    placed = _farm_summary(farm)["animals"][animal]
    return placed + _all_inventory_count(private, animal)


def _market_sales(
    obs: Any,
    farm: Any,
    private: Any,
    animal_count: int,
) -> list[list[Any]]:
    day = _as_int(_get(obs, "day", 0))
    step = _as_int(_get(obs, "step", day * 24))
    shed = _get(private, "shed", {}) or {}
    market = _get(obs, "market", {}) or {}
    prices = _get(market, "prices", {}) or {}
    shed_total = _inventory_total(shed)
    pressure = shed_total >= 78
    final_liquidation = day >= 28
    just_after_town_tick = step % 4 == 1
    orders: list[list[Any]] = []

    # Feed is survival-critical.  Keep roughly three days in reserve, but sell
    # all excess wheat so the shed cannot silently overflow at end of day.
    wheat = _inventory_count(shed, "WHEAT")
    wheat_reserve = animal_count * (2 if day >= 27 else 3)
    sell_wheat = wheat if final_liquidation else max(0, wheat - wheat_reserve)
    if sell_wheat > 0 and (final_liquidation or pressure or _as_int(_get(prices, "WHEAT", 0)) >= 20):
        orders.append(["SELL", "WHEAT", sell_wheat])

    for item in ("CARROT", "TOMATO", "EGG"):
        count = _inventory_count(shed, item)
        if count > 0:
            orders.append(["SELL", item, count])

    premium_threshold = {"STRAWBERRY": 105, "MELON": 190, "MILK": 140, "WOOL": 175}
    premium_batch = {"STRAWBERRY": 4, "MELON": 3, "MILK": 4, "WOOL": 3}
    for item in PREMIUM_PRODUCTS:
        count = _inventory_count(shed, item)
        price = _as_int(_get(prices, item, 0))
        if count <= 0:
            continue
        if final_liquidation:
            amount = count
        elif pressure:
            amount = min(count, max(premium_batch[item], shed_total - 70))
        elif just_after_town_tick and price >= premium_threshold[item]:
            amount = min(count, premium_batch[item])
        else:
            continue
        orders.append(["SELL", item, amount])

    fertilizer = _inventory_count(shed, "FERTILIZER")
    keep_fertilizer = 0 if final_liquidation else 8
    if fertilizer > keep_fertilizer and (pressure or final_liquidation):
        orders.append(["SELL", "FERTILIZER", fertilizer - keep_fertilizer])
    return orders


def _market_plan(
    obs: Any,
    farm: Any,
    private: Any,
    my_summary: dict[str, Any],
    opponent: dict[str, Any],
    animal_targets: dict[str, int],
    crop_targets: dict[str, int],
) -> list[list[Any]]:
    day = _as_int(_get(obs, "day", 0))
    hour = _as_int(_get(obs, "hour", 0))
    money = float(_get(farm, "money", 0) or 0)
    animal_count = my_summary["animal_total"]
    target_hands = 8 if day == 0 else 10
    existing_hands = len(_get(farm, "hands", []) or [])
    orders: list[list[Any]] = []

    # Hands disappear overnight.  Hire first thing each day.  Day 0 reserves two
    # of the ten market slots for the opening cash-crop seeds.
    if hour == 0 and existing_hands < target_hands:
        if day == 0:
            if _inventory_count(_get(private, "seeds", {}) or {}, "WHEAT") == 0:
                orders.append(["BUY_SEED", "WHEAT", 10])
            if _inventory_count(_get(private, "seeds", {}) or {}, "CARROT") == 0:
                orders.append(["BUY_SEED", "CARROT", 8])
        orders.extend([["HIRE"] for _ in range(min(target_hands - existing_hands, 10 - len(orders)))])
        return orders[:10]

    sales = _market_sales(obs, farm, private, animal_count)
    orders.extend(sales[:10])
    prices = _get(_get(obs, "market", {}) or {}, "prices", {}) or {}
    # Sales are processed before later orders, so include conservative expected
    # proceeds in the local budget calculation.
    budget = money
    shed = _get(private, "shed", {}) or {}
    for order in orders:
        if order[0] == "SELL":
            budget += min(order[2], _inventory_count(shed, order[1])) * max(1, _as_int(_get(prices, order[1], 1), 1))
    reserve = 250 + animal_count * 25

    # Emergency feed stock comes before expansion and capital purchases.
    total_wheat = _all_inventory_count(private, "WHEAT")
    desired_wheat_stock = animal_count * 2
    if animal_count and total_wheat < desired_wheat_stock and len(orders) < 10:
        amount = desired_wheat_stock - total_wheat
        unit_price = max(1, _as_int(_get(prices, "WHEAT", 25), 25))
        affordable = max(0, int((budget - reserve) // unit_price))
        amount = min(amount, affordable)
        if amount > 0:
            orders.append(["BUY_PRODUCT", "WHEAT", amount])
            budget -= amount * unit_price

    unlocked = len(_get(farm, "unlocked_quadrants", []) or [])
    land_cost = (1000, 2000, 4000)
    land_day = (4, 10, 18)
    if unlocked < 4 and day >= land_day[unlocked - 1] and len(orders) < 10:
        cost = land_cost[unlocked - 1]
        occupancy_trigger = 17 + 18 * (unlocked - 1)
        if budget >= cost + reserve + 350 and my_summary["occupied"] >= occupancy_trigger:
            orders.append(["BUY_LAND"])
            budget -= cost

    # Buy livestock in stages.  Cows are considered first, except against a
    # cow-heavy opponent where the target calculation shifts capital to sheep.
    animal_order = ("SHEEP", "COW") if opponent["cow_heavy"] else ("COW", "SHEEP")
    for animal in animal_order:
        if len(orders) >= 10 or day >= 22:
            break
        have = _all_animal_count(farm, private, animal)
        deficit = max(0, animal_targets[animal] - have)
        cost = ANIMAL_DATA[animal]["cost"]
        affordable = max(0, int((budget - reserve) // cost))
        amount = min(deficit, affordable)
        if amount > 0:
            orders.append(["BUY_ANIMAL", animal, amount])
            budget -= amount * cost

    # Seeds are bought only for real deficits (plants + already-owned seeds).
    # Quantity is grouped into one order per crop to preserve the 10-order cap.
    seeds = _get(private, "seeds", {}) or {}
    for crop in ("WHEAT", "STRAWBERRY", "CARROT", "TOMATO", "MELON"):
        if len(orders) >= 10:
            break
        deficit = crop_targets[crop] - my_summary["crops"][crop] - _inventory_count(seeds, crop)
        if deficit <= 0:
            continue
        cost = CROP_DATA[crop]["seed"]
        affordable = max(0, int((budget - reserve) // cost))
        amount = min(deficit, affordable)
        if amount > 0:
            orders.append(["BUY_SEED", crop, amount])
            budget -= amount * cost
    return orders[:10]


def _animal_due_next_refresh(tile: Any, day: int) -> bool:
    animal = _get(tile, "animal")
    if animal not in ANIMAL_DATA:
        return False
    data = ANIMAL_DATA[animal]
    age_next_day = day + 1 - _as_int(_get(tile, "placed_day", day))
    return age_next_day >= data["first"] and (age_next_day - data["first"]) % data["interval"] == 0


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
    unlocked_positions = [(x, y) for x, y, tile in _iter_tiles(farm) if tile != "LOCKED"]
    shed = _shed_tiles(board_size)
    unlocked_positions.sort(
        key=lambda pos: (
            min(_manhattan(pos, access) for access in shed),
            -pos[0],
            -pos[1],
        )
    )
    return unlocked_positions[:count]


def _movement(pos: tuple[int, int], target: tuple[int, int], unit_index: int) -> list[str]:
    dx = target[0] - pos[0]
    dy = target[1] - pos[1]
    if dx == 0 and dy == 0:
        return ["PASS"]
    # Alternating tie-breaks prevent every worker from tracing the same L-shaped
    # route while remaining completely deterministic.
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
    positions: list[tuple[int, int]],
    inventories: list[Any],
    tasks: list[dict[str, Any]],
) -> list[list[Any]]:
    actions: list[list[Any]] = [["PASS"] for _ in positions]
    free_units = set(range(len(positions)))

    # Pick the globally nearest eligible worker/task pair within the most urgent
    # priority band.  Task-by-task coordinate ordering caused workers to cross
    # the entire farm and let mature fields decay while en route.
    remaining = list(tasks)
    while free_units and remaining:
        best: tuple[tuple[Any, ...], int, int] | None = None
        for task_index, task in enumerate(remaining):
            for unit_index in free_units:
                if not _can_do(task, unit_index, inventories[unit_index]):
                    continue
                distance = _manhattan(positions[unit_index], task["pos"])
                key = (
                    task["priority"],
                    -distance,
                    -task["pos"][1],
                    -task["pos"][0],
                    -unit_index,
                    task["label"],
                )
                if best is None or key > best[0]:
                    best = (key, task_index, unit_index)
        if best is None:
            break
        _key, task_index, chosen = best
        task = remaining.pop(task_index)
        if positions[chosen] == task["pos"]:
            actions[chosen] = list(task["action"])
        else:
            actions[chosen] = _movement(positions[chosen], task["pos"], chosen)
        free_units.remove(chosen)
    return actions


def _field_tasks(
    obs: Any,
    farm: Any,
    private: Any,
    positions: list[tuple[int, int]],
    inventories: list[Any],
    my_summary: dict[str, Any],
    animal_targets: dict[str, int],
    crop_targets: dict[str, int],
) -> list[dict[str, Any]]:
    day = _as_int(_get(obs, "day", 0))
    hour = _as_int(_get(obs, "hour", 0))
    board_size = len(_get(farm, "tiles", []) or []) or 10
    tasks: list[dict[str, Any]] = []
    animal_tiles: list[tuple[int, int, Any]] = []
    plant_tiles: list[tuple[int, int, Any]] = []

    for x, y, tile in _iter_tiles(farm):
        kind = _tile_kind(tile)
        if kind == "PLANT":
            plant_tiles.append((x, y, tile))
        elif _get(tile, "animal") in ANIMAL_DATA:
            animal_tiles.append((x, y, tile))

    # Inventory that can become cash should reach the shed before optional work,
    # especially late in the final day when end-of-day storage is too late.
    harvest_items = tuple(item for item in PRODUCTS if item not in ("WHEAT", "FERTILIZER"))
    for i, (pos, inv) in enumerate(zip(positions, inventories, strict=True)):
        carried_goods = _inventory_total(inv, harvest_items)
        if carried_goods > 0 and (day >= 29 or carried_goods >= 4 or hour >= 20):
            priority = 17000 if day >= 29 else (8200 if hour >= 20 else 5600)
            tasks.append(_task(_nearest_shed(pos, board_size), ["DROP"], priority, unit=i, label="drop-goods"))

    # Irreversible losses dominate every optional investment task.
    for x, y, tile in animal_tiles:
        if not bool(_get(tile, "fed_today", False)):
            emergency = _as_int(_get(tile, "consecutive_unfed", 0)) >= 1 or hour >= 18
            tasks.append(_task((x, y), ["FEED"], 15100 if emergency else 11900, required="WHEAT", label="feed"))
        if not bool(_get(tile, "cared_today", False)):
            tasks.append(_task((x, y), ["CARE"], 9100 if hour >= 18 else 7200, label="care"))

        yield_units = _as_int(_get(tile, "yield_units", 0))
        animal = _get(tile, "animal")
        pending = _as_int(_get(tile, "pending_care_bonus", 0))
        overflow_risk = (
            _animal_due_next_refresh(tile, day) and yield_units + 1 + pending >= ANIMAL_DATA[animal]["max_held"]
        )
        if yield_units > 0 and (yield_units >= 3 or overflow_risk or day >= 28):
            harvest_priority = 16000 if day >= 29 else (11500 if overflow_risk else 8600)
            tasks.append(_task((x, y), ["HARVEST"], harvest_priority, label="animal-harvest"))

        if bool(_get(tile, "fertilizer_available", False)) and my_summary["crops"]["STRAWBERRY"] > 0:
            tasks.append(_task((x, y), ["COLLECT_FERTILIZER"], 4700, label="collect-fertilizer"))

    for x, y, tile in plant_tiles:
        crop = _get(tile, "crop")
        data = CROP_DATA.get(crop)
        if data is None:
            continue
        age = day - _as_int(_get(tile, "planted_day", day))
        yield_units = _as_int(_get(tile, "yield_units", 0))
        final_harvest = day >= 29 and yield_units > 0 and age >= data["first"]
        if data["ongoing"]:
            harvestable = yield_units > 0 and (yield_units >= 2 or day >= 27)
        else:
            harvestable = yield_units > 0 and age >= data["peak"]
        if harvestable or final_harvest:
            # Mature one-time crops have a narrow collection window.  Once they
            # reach peak age, harvesting is safer than spending another full day
            # chasing the last watering bonus.
            harvest_priority = 16500 if final_harvest else (11300 if not data["ongoing"] else 8800)
            tasks.append(_task((x, y), ["HARVEST"], harvest_priority, label="crop-harvest"))

        if not bool(_get(tile, "watered_today", False)):
            emergency = _as_int(_get(tile, "consecutive_unwatered", 0)) >= 1 or hour >= 18
            # Mature one-time crops are watered once more before harvest so their
            # peak-window bonus is not forfeited.
            tasks.append(_task((x, y), ["WATER"], 14800 if emergency else 10400, label="water"))

        if (
            crop in ("STRAWBERRY", "TOMATO")
            and _crop_due_next_refresh(tile, day)
            and _as_int(_get(tile, "fertilized_until_day", -1), -1) < day
        ):
            tasks.append(_task((x, y), ["FERTILIZE"], 9900, required="FERTILIZER", label="fertilize"))

    # Deterministic near-shed livestock layout.  Six slots are protected during
    # the opening cash-crop phase so animals need not dig up a mature field.
    desired_animal_total = sum(animal_targets.values())
    reserve_count = max(6 if day < 4 else 0, desired_animal_total)
    animal_slots = _animal_slots(farm, reserve_count, board_size)
    animal_slot_set = set(animal_slots)
    current_structures = my_summary["animal_total"] + my_summary["empty_structures"]
    owned_animals = sum(_all_animal_count(farm, private, a) for a in ANIMAL_DATA)
    structures_needed = max(0, min(desired_animal_total, owned_animals) - current_structures)

    for pos in animal_slots:
        x, y = pos
        tile = _get(farm, "tiles", [])[y][x]
        if structures_needed <= 0:
            break
        if _tile_kind(tile) == "WEED":
            tasks.append(_task(pos, ["DIG"], 7800, label="dig-animal-slot"))
            structures_needed -= 1
        elif tile is None:
            tasks.append(_task(pos, ["BUILD_PASTURE"], 7600, label="build-pasture"))
            structures_needed -= 1

    empty_pastures = [
        (x, y) for x, y, tile in _iter_tiles(farm) if _tile_kind(tile) == "PASTURE" and _get(tile, "animal") is None
    ]
    carriers: dict[str, list[int]] = {animal: [] for animal in ANIMAL_DATA}
    for i, inv in enumerate(inventories):
        for animal in ("COW", "SHEEP", "GOOSE"):
            if _inventory_count(inv, animal) > 0:
                carriers[animal].append(i)

    pasture_index = 0
    for animal in ("COW", "SHEEP"):
        for unit_index in carriers[animal]:
            if pasture_index >= len(empty_pastures):
                break
            pos = empty_pastures[pasture_index]
            pasture_index += 1
            tasks.append(
                _task(pos, ["PLACE", animal], 11600, required=animal, unit=unit_index, label=f"place-{animal}")
            )

    # Weeds outside reserved livestock slots are cleared only when normal work is
    # under control.  This keeps random weeds from derailing the daily schedule.
    for x, y, tile in _iter_tiles(farm):
        if _tile_kind(tile) == "WEED" and (x, y) not in animal_slot_set:
            tasks.append(_task((x, y), ["DIG"], 5200, label="dig-weed"))

    # Plant only on non-reserved empty cells, and never issue more simultaneous
    # PLANT commands than the observation's seed count (the engine rejects every
    # request for a crop when aggregate demand exceeds available seeds).
    plant_positions = [(x, y) for x, y, tile in _iter_tiles(farm) if tile is None and (x, y) not in animal_slot_set]
    plant_positions.sort(
        key=lambda pos: (
            min(_manhattan(pos, shed) for shed in _shed_tiles(board_size)),
            pos[1],
            pos[0],
        )
    )
    seeds = _get(private, "seeds", {}) or {}
    cursor = 0
    for crop in ("WHEAT", "STRAWBERRY", "CARROT", "TOMATO", "MELON"):
        deficit = max(0, crop_targets[crop] - my_summary["crops"][crop])
        available = min(deficit, _inventory_count(seeds, crop))
        for _ in range(available):
            if cursor >= len(plant_positions):
                break
            tasks.append(_task(plant_positions[cursor], ["PLANT", crop], 6500, label=f"plant-{crop}"))
            cursor += 1

    # Shed logistics are unit-specific so simultaneous pickups cannot overclaim
    # the same item.  First deploy purchased animals, then distribute feed, then
    # fertilizer to workers who can reach scheduled premium-crop tasks.
    shed = _get(private, "shed", {}) or {}
    claimed_units: set[int] = set()
    animal_stock = {animal: _inventory_count(shed, animal) for animal in ("COW", "SHEEP", "GOOSE")}
    for animal in ("COW", "SHEEP", "GOOSE"):
        for _ in range(animal_stock[animal]):
            candidates = [
                i
                for i, inv in enumerate(inventories)
                if i not in claimed_units
                and sum(_inventory_count(inv, a) for a in ANIMAL_DATA) == 0
                and _inventory_total(inv, harvest_items) == 0
            ]
            if not candidates:
                break
            unit_index = min(
                candidates,
                key=lambda i: (_manhattan(positions[i], _nearest_shed(positions[i], board_size)), i),
            )
            claimed_units.add(unit_index)
            target = _nearest_shed(positions[unit_index], board_size)
            tasks.append(_task(target, ["PICKUP", animal, 1], 11300, unit=unit_index, label=f"pickup-{animal}"))

    unfed = sum(1 for _x, _y, tile in animal_tiles if not bool(_get(tile, "fed_today", False)))
    wheat_in_shed = _inventory_count(shed, "WHEAT")
    candidates = [
        i
        for i, inv in enumerate(inventories)
        if i not in claimed_units
        and _inventory_count(inv, "WHEAT") == 0
        and sum(_inventory_count(inv, a) for a in ANIMAL_DATA) == 0
        and _inventory_total(inv, harvest_items) == 0
    ]
    if unfed > 0 and wheat_in_shed > 0 and candidates:
        carrier_count = min(len(candidates), unfed, wheat_in_shed)
        remaining = wheat_in_shed
        for unit_index in candidates[:carrier_count]:
            carriers_left = carrier_count - len(claimed_units.intersection(candidates))
            load = max(1, min(3, int(math.ceil(remaining / max(1, carriers_left)))))
            remaining -= load
            claimed_units.add(unit_index)
            target = _nearest_shed(positions[unit_index], board_size)
            tasks.append(_task(target, ["PICKUP", "WHEAT", load], 12200, unit=unit_index, label="pickup-wheat"))
            if remaining <= 0:
                break

    fertilizer_needed = sum(1 for task in tasks if task["action"][0] == "FERTILIZE")
    fertilizer_stock = _inventory_count(shed, "FERTILIZER")
    if fertilizer_needed and fertilizer_stock:
        for unit_index in range(len(positions)):
            if fertilizer_stock <= 0:
                break
            inv = inventories[unit_index]
            if unit_index in claimed_units or _inventory_count(inv, "FERTILIZER") > 0:
                continue
            target = _nearest_shed(positions[unit_index], board_size)
            tasks.append(_task(target, ["PICKUP", "FERTILIZER", 1], 10100, unit=unit_index, label="pickup-fertilizer"))
            claimed_units.add(unit_index)
            fertilizer_stock -= 1

    return tasks


def _safe_observation(obs: Any) -> tuple[Any, Any, Any] | None:
    farms = _get(obs, "farms", []) or []
    player = _as_int(_get(obs, "player", 0))
    if not farms or not (0 <= player < len(farms)):
        return None
    farm = farms[player]
    opponent = farms[1 - player] if len(farms) >= 2 else farm
    private = _get(obs, "private", {}) or {}
    return farm, opponent, private


def agent(obs: Any) -> dict[str, Any]:
    """Return one legal, observation-driven action for every active unit."""
    safe = _safe_observation(obs)
    if safe is None:
        return {"farmer": ["PASS"], "hands": [], "market": []}
    farm, opponent_farm, private = safe

    my_summary = _farm_summary(farm)
    opponent = _opponent_profile(opponent_farm)
    day = _as_int(_get(obs, "day", 0))
    animal_targets = _desired_animals(day, opponent)
    crop_targets = _desired_crops(day, my_summary["animal_total"], my_summary["crops"], opponent)

    positions = [tuple(_get(farm, "farmer", [0, 0]))]
    positions.extend(tuple(pos) for pos in (_get(farm, "hands", []) or []))
    raw_inventories = list(_get(private, "inventories", []) or [])
    inventories = [raw_inventories[i] if i < len(raw_inventories) else {} for i in range(len(positions))]

    tasks = _field_tasks(
        obs,
        farm,
        private,
        positions,
        inventories,
        my_summary,
        animal_targets,
        crop_targets,
    )
    unit_actions = _assign_tasks(positions, inventories, tasks)
    market = _market_plan(
        obs,
        farm,
        private,
        my_summary,
        opponent,
        animal_targets,
        crop_targets,
    )

    return {
        "farmer": unit_actions[0] if unit_actions else ["PASS"],
        "hands": unit_actions[1:],
        "market": market,
    }
