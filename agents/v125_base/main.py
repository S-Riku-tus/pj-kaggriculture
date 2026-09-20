"""V125 candidate A: a coherent three-quadrant economic plan.

The macro schedule is based on the Top1 family measured in the supplied 1,009
replay analysis: two cows and three sheep in the opening, strawberries from
day 2, three quadrants, and tomato/carrot rotations in already-owned land.
It is intentionally one complete candidate, not an average of Top1/2/3.

The schedule expresses portfolio goals.  V4's state-based task allocator
turns those goals into legal work from the current observation, so no replay
action suffix is attached to a state with different cash, seeds, workers, or
tile ages.  Every runtime feature below is observable to the acting player.
"""

from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

PLAN_NAME = "top1_three_quadrant_rotation_v1"
PLAN_SOURCE = "supplied replay aggregates; autonomous state-based execution"
FINAL_DAY = 29
PRICE_I0 = 10_000
LAST_DIAGNOSTICS: dict[int, dict[str, Any]] = {0: {}, 1: {}}
ADAPTIVE_STATE: dict[int, dict[str, Any]] = {0: {}, 1: {}}


def _module_dir() -> Path:
    if "__file__" in globals():
        return Path(__file__).resolve().parent
    candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd() / "agents" / "v125_base",
        Path.cwd(),
    )
    return next(
        (
            candidate.resolve()
            for candidate in candidates
            if (candidate / "v4_base.py").is_file()
            or (candidate.parent / "v4" / "main.py").is_file()
        ),
        Path.cwd(),
    )


def _load_v4() -> Any:
    module_dir = _module_dir()
    packaged = module_dir / "v4_base.py"
    repository = module_dir.parent / "v4" / "main.py"
    source = packaged if packaged.is_file() else repository
    spec = importlib.util.spec_from_file_location("_kaggriculture_v125_base_v4", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import V4 state executor: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


executor = _load_v4()
base = executor.base


def _schedule(day: int, points: tuple[tuple[int, int], ...]) -> int:
    value = points[0][1]
    for start, candidate in points:
        if day < start:
            break
        value = candidate
    return value


ANIMAL_SCHEDULE = {
    "COW": ((0, 2), (6, 6), (9, 9)),
    "SHEEP": ((0, 3), (18, 4)),
    "GOOSE": ((0, 0),),
}
CROP_SCHEDULE = {
    "WHEAT": (
        (0, 10), (2, 6), (3, 4), (4, 1), (5, 0), (6, 3),
        (9, 17), (10, 24), (11, 26), (13, 22), (16, 20),
        (18, 18), (21, 25), (24, 34), (26, 42),
    ),
    "STRAWBERRY": (
        (0, 0), (2, 2), (3, 4), (4, 8), (6, 19), (7, 23),
        (8, 24), (10, 26), (11, 27), (14, 30),
    ),
    "MELON": ((0, 6), (1, 10), (2, 12), (10, 6), (11, 2), (12, 0)),
    "TOMATO": ((0, 0), (11, 2), (12, 4), (13, 6), (14, 8)),
    "CARROT": ((0, 0), (18, 4), (20, 8), (22, 12), (24, 20), (26, 26)),
}
HANDS_SCHEDULE = ((0, 4), (2, 6), (6, 8), (9, 10), (10, 11))
LAND_SCHEDULE = ((0, 1), (6, 2), (9, 3))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _seat(observation: Mapping[str, Any]) -> int:
    return 1 if _integer(observation.get("player")) == 1 else 0


def plan_targets(day: int, summary: Mapping[str, Any]) -> dict[str, Any]:
    animals = {animal: _schedule(day, points) for animal, points in ANIMAL_SCHEDULE.items()}
    crops = {crop: _schedule(day, points) for crop, points in CROP_SCHEDULE.items()}

    # Never interpret a falling target as an instruction to destroy a still
    # productive long-lived crop. Rotation occurs only after harvest/exhaustion.
    if day >= 18:
        crops["STRAWBERRY"] = _integer(_mapping(summary.get("crops")).get("STRAWBERRY"))
    if day >= 12:
        crops["MELON"] = _integer(_mapping(summary.get("crops")).get("MELON"))
    if day >= 27:
        for crop in crops:
            crops[crop] = _integer(_mapping(summary.get("crops")).get(crop))
    return {
        "animals": animals,
        "crops": crops,
        "hands": _schedule(day, HANDS_SCHEDULE),
        "land": _schedule(day, LAND_SCHEDULE),
        "pastures": min(15, animals["COW"] + animals["SHEEP"]),
    }


def _future_production_days(kind: str, name: str, tile: Mapping[str, Any], day: int) -> list[int]:
    if kind == "crop":
        data = base.CROP_DATA.get(name)
        if not data:
            return []
        planted = _integer(tile.get("planted_day"), day)
        if not data["ongoing"]:
            return [planted + data["peak"]] if planted + data["peak"] <= FINAL_DAY else []
        return [
            planted + data["first"] + index * data["interval"]
            for index in range(data["max"])
            if day < planted + data["first"] + index * data["interval"] <= FINAL_DAY
        ]
    data = base.ANIMAL_DATA.get(name)
    if not data:
        return []
    placed = _integer(tile.get("placed_day"), day)
    first = placed + data["first"]
    return list(range(max(first, day + 1), FINAL_DAY + 1, data["interval"]))


def asset_ledger(observation: Mapping[str, Any], farm: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Describe owned productive assets using observation-time information only."""
    if farm is None:
        farms = list(observation.get("farms") or [])
        seat = _seat(observation)
        farm = _mapping(farms[seat]) if seat < len(farms) else {}
    day = _integer(observation.get("day"))
    ledger: list[dict[str, Any]] = []
    for x, y, tile_value in base._iter_tiles(farm):
        tile = _mapping(tile_value)
        crop = str(tile.get("crop")) if tile.get("crop") else None
        animal = str(tile.get("animal")) if tile.get("animal") else None
        if not crop and not animal:
            continue
        kind = "crop" if crop else "animal"
        name = crop or animal or ""
        future_days = _future_production_days(kind, name, tile, day)
        waiting = max(0, _integer(tile.get("yield_units")))
        entry = {
            "pos": [x, y],
            "kind": kind,
            "name": name,
            "next_production_day": future_days[0] if future_days else None,
            "effective_productions_remaining": len(future_days),
            "yield_waiting": waiting,
            "fertilized_until_day": _integer(tile.get("fertilized_until_day"), -1),
            "pending_care": _integer(tile.get("pending_care_bonus")),
            "maintenance_wheat": len(range(day, FINAL_DAY)) if animal else 0,
            "workload_actions": len(future_days) + int(bool(waiting)) + (2 * len(future_days) if animal else 0),
            "aftercrop_candidates": ["WHEAT", "CARROT"] if animal else (
                ["TOMATO", "CARROT", "WHEAT"] if crop in {"MELON", "WHEAT"} else ["WHEAT", "CARROT"]
            ),
        }
        ledger.append(entry)
    return ledger


def _product_for_tile(tile: Mapping[str, Any]) -> str | None:
    crop = tile.get("crop")
    if crop:
        return str(crop)
    animal = tile.get("animal")
    data = base.ANIMAL_DATA.get(animal)
    return str(data["product"]) if data else None


def observed_supply_forecast(observation: Mapping[str, Any], horizon_days: int = 3) -> dict[str, Any]:
    """Short scenario forecast from public farms, current market, and current shops."""
    day = _integer(observation.get("day"))
    products = tuple(base.PRODUCTS)
    public_supply: Counter[str] = Counter()
    waiting: Counter[str] = Counter()
    for farm_value in observation.get("farms") or []:
        farm = _mapping(farm_value)
        for _x, _y, tile_value in base._iter_tiles(farm):
            tile = _mapping(tile_value)
            product = _product_for_tile(tile)
            if product is None:
                continue
            waiting[product] += max(0, _integer(tile.get("yield_units")))
            name = str(tile.get("crop") or tile.get("animal") or "")
            kind = "crop" if tile.get("crop") else "animal"
            public_supply[product] += sum(
                day < event_day <= min(FINAL_DAY, day + horizon_days)
                for event_day in _future_production_days(kind, name, tile, day)
            )

    shops = list(_mapping(observation.get("town")).get("unlocked_shops") or [])
    daily_drain: Counter[str] = Counter({product: 1 for product in products if product != "FERTILIZER"})
    for shop in shops:  # Duplicate shops are deliberately counted separately.
        for product, quantity in base.SHOP_DEMAND.get(str(shop), {}).items():
            daily_drain[product] += 6 * _integer(quantity)
    market = _mapping(observation.get("market"))
    inventory = _mapping(market.get("inventory"))
    prices = _mapping(market.get("prices"))
    items: dict[str, Any] = {}
    for product in products:
        projected_supply = public_supply[product] + waiting[product]
        projected_drain = daily_drain[product] * horizon_days
        net = projected_supply - projected_drain
        current_price = max(1, _integer(prices.get(product), base.BASE_PRICE.get(product, 1)))
        # Scenario prices are deliberately approximate; they never inspect a
        # future state. They are logged and evaluated for error after a game.
        pressure = max(0.0, (_integer(inventory.get(product), PRICE_I0) - PRICE_I0 + net) / 100.0)
        items[product] = {
            "public_supply": projected_supply,
            "town_drain": projected_drain,
            "projected_net": net,
            "current_price": current_price,
            "scenario_prices": {
                "low_supply": current_price,
                "central": max(1, round(current_price / (1.0 + pressure * 0.03))),
                "high_supply": max(1, round(current_price / (1.0 + pressure * 0.07))),
            },
        }
    return {"as_of_day": day, "horizon_days": horizon_days, "items": items}


def _adaptive_state(observation: Mapping[str, Any]) -> dict[str, Any]:
    seat = _seat(observation)
    step = 24 * _integer(observation.get("day")) + _integer(observation.get("hour"))
    state = ADAPTIVE_STATE.setdefault(seat, {})
    if step == 0 or step < _integer(state.get("last_step"), -1):
        state.clear()
    state.setdefault("planned_exits", {})
    state.setdefault("trigger_counts", Counter())
    state["last_step"] = step
    return state


def _adaptive_targets(
    observation: Mapping[str, Any],
    summary: Mapping[str, Any],
    targets: Mapping[str, Any],
    forecast: Mapping[str, Any],
    state: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    adjusted = {
        "animals": dict(targets["animals"]),
        "crops": dict(targets["crops"]),
        "hands": targets["hands"],
        "land": targets["land"],
        "pastures": targets["pastures"],
    }
    rejected: list[dict[str, Any]] = []
    items = _mapping(forecast.get("items"))
    current_crops = _mapping(summary.get("crops"))
    current_animals = _mapping(summary.get("animals"))

    # Only suppress *additional* capital. Existing productive assets are not
    # destroyed by this congestion check.
    for crop, floor in (("STRAWBERRY", 62), ("TOMATO", 30), ("CARROT", 18)):
        price = _integer(_mapping(items.get(crop)).get("scenario_prices", {}).get("central"))
        if price and price <= floor:
            previous = _integer(adjusted["crops"].get(crop))
            adjusted["crops"][crop] = min(previous, _integer(current_crops.get(crop)))
            if adjusted["crops"][crop] < previous:
                rejected.append(
                    {"candidate": f"add-{crop}", "reason": "observed-supply-congestion", "price": price}
                )
                state["trigger_counts"]["supply_suppression"] += 1

    for animal, product, floor in (("COW", "MILK", 82), ("SHEEP", "WOOL", 102)):
        price = _integer(_mapping(items.get(product)).get("scenario_prices", {}).get("central"))
        if price and price <= floor:
            previous = _integer(adjusted["animals"].get(animal))
            adjusted["animals"][animal] = min(previous, _integer(current_animals.get(animal)))
            if adjusted["animals"][animal] < previous:
                rejected.append(
                    {"candidate": f"add-{animal}", "reason": "observed-product-congestion", "price": price}
                )
                state["trigger_counts"]["animal_suppression"] += 1

    planned_by_animal: Counter[str] = Counter(
        str(value.get("animal"))
        for value in _mapping(state.get("planned_exits")).values()
        if value.get("status") == "planned"
    )
    for animal, count in planned_by_animal.items():
        if animal in adjusted["animals"]:
            adjusted["animals"][animal] = max(
                0, min(adjusted["animals"][animal], _integer(current_animals.get(animal)) - count)
            )
    adjusted["pastures"] = min(
        15, _integer(adjusted["animals"].get("COW")) + _integer(adjusted["animals"].get("SHEEP"))
    )
    return adjusted, rejected


def _retirement_values(
    observation: Mapping[str, Any],
    tile: Mapping[str, Any],
    forecast: Mapping[str, Any],
) -> dict[str, Any]:
    day = _integer(observation.get("day"))
    animal = str(tile.get("animal"))
    data = base.ANIMAL_DATA[animal]
    product = str(data["product"])
    items = _mapping(forecast.get("items"))
    product_price = _integer(_mapping(items.get(product)).get("scenario_prices", {}).get("central"), 1)
    wheat_price = _integer(_mapping(items.get("WHEAT")).get("current_price"), 25)
    fertilizer_price = _integer(_mapping(items.get("FERTILIZER")).get("current_price"), 100)
    future = _future_production_days("animal", animal, tile, day)
    pending = _integer(tile.get("pending_care_bonus"))
    waiting = _integer(tile.get("yield_units"))
    maintain = (
        (2 * len(future) + pending + waiting) * product_price
        + max(0, FINAL_DAY - day) * 0.6 * fertilizer_price
        - max(0, FINAL_DAY - day) * wheat_price
        - 10 * (3 * len(future))
    )
    aftercrop = "CARROT" if day <= 26 else "WHEAT"
    crop_data = base.CROP_DATA[aftercrop]
    crop_price = _integer(_mapping(items.get(aftercrop)).get("scenario_prices", {}).get("central"), 1)
    matures = day + 2 + crop_data["peak"] <= FINAL_DAY
    exit_value = (
        crop_data["max"] * crop_price - crop_data["seed"] - 40
        if matures
        else -1_000_000
    )
    return {
        "animal": animal,
        "product": product,
        "maintain_value": round(maintain, 1),
        "exit_value": round(exit_value, 1),
        "aftercrop": aftercrop,
        "aftercrop_matures": matures,
    }


def _adaptive_task_overlay(
    tasks: list[dict[str, Any]],
    observation: Mapping[str, Any],
    farm: Mapping[str, Any],
    forecast: Mapping[str, Any],
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    day = _integer(observation.get("day"))
    step = 24 * day + _integer(observation.get("hour"))
    planned = _mapping(state.get("planned_exits"))
    tile_at = {(x, y): tile for x, y, tile in base._iter_tiles(farm)}

    # Close completed plans only after the animal has actually gone. A bare
    # pasture is then dug for the recorded aftercrop; accidental disappearances
    # with no prior plan are never relabelled as planned exits.
    for _key, record_value in list(planned.items()):
        record = record_value
        pos = tuple(record["pos"])
        tile = _mapping(tile_at.get(pos))
        if tile.get("animal") == record.get("animal"):
            continue
        if base._tile_kind(tile_at.get(pos)) == "PASTURE":
            record["status"] = "exited"
            record["realized_exit_step"] = step
            tasks.append(base._task(pos, ["DIG"], 12600, label="dig-planned-exit"))
        elif tile_at.get(pos) is None or tile.get("crop"):
            record["status"] = "converted"

    if 18 <= day <= 25:
        animal_counts = Counter(
            str(_mapping(tile).get("animal"))
            for tile in tile_at.values()
            if _mapping(tile).get("animal")
        )
        candidates: list[tuple[float, tuple[int, int], dict[str, Any], dict[str, Any]]] = []
        for pos, tile_value in tile_at.items():
            tile = _mapping(tile_value)
            animal = tile.get("animal")
            key = f"{pos[0]},{pos[1]}"
            if animal not in {"COW", "SHEEP"} or key in planned:
                continue
            if animal_counts[str(animal)] <= (5 if animal == "COW" else 2):
                continue
            # Do not sacrifice inventory, manure, or a CARE balance which can
            # still be paid out. The decision is reconsidered after collection.
            if (
                _integer(tile.get("yield_units"))
                or bool(tile.get("fertilizer_available"))
                or _integer(tile.get("pending_care_bonus"))
            ):
                continue
            values = _retirement_values(observation, tile, forecast)
            advantage = float(values["exit_value"]) - float(values["maintain_value"])
            if values["aftercrop_matures"] and advantage > 0:
                candidates.append((advantage, pos, dict(tile), values))
        if candidates:
            advantage, pos, tile, values = max(candidates, key=lambda value: (value[0], value[1]))
            key = f"{pos[0]},{pos[1]}"
            planned[key] = {
                "pos": list(pos),
                "animal": tile["animal"],
                "selected_at_step": step,
                "status": "planned",
                "last_harvest_verified": True,
                "fertilizer_collected": True,
                **values,
                "advantage": round(advantage, 1),
            }
            state["trigger_counts"]["planned_exit"] += 1

    active_positions = {
        tuple(record["pos"])
        for record in planned.values()
        if record.get("status") == "planned"
    }
    if active_positions:
        tasks[:] = [
            task
            for task in tasks
            if not (
                tuple(task["pos"]) in active_positions
                and str(task.get("label")) in {"feed", "care"}
            )
        ]

    # Score each fertilizer use against its observable sale opportunity and
    # transport cost. This can favor wheat, but does not target a count.
    items = _mapping(forecast.get("items"))
    fertilizer_price = _integer(_mapping(items.get("FERTILIZER")).get("current_price"), 100)
    filtered: list[dict[str, Any]] = []
    profitable_fertilize = 0
    for task in tasks:
        if str(task.get("label")) != "fertilize":
            filtered.append(task)
            continue
        tile = _mapping(tile_at.get(tuple(task["pos"])))
        crop = str(tile.get("crop") or "")
        price = _integer(_mapping(items.get(crop)).get("scenario_prices", {}).get("central"), 1)
        yield_left = max(0, _integer(base.CROP_DATA.get(crop, {}).get("max")) - _integer(tile.get("yield_units")))
        bonus_units = min(3 if crop == "WHEAT" else 1, yield_left)
        feed_shadow = price * 0.35 if crop == "WHEAT" else 0
        value = bonus_units * (price + feed_shadow)
        opportunity = fertilizer_price + 15
        if value > opportunity:
            scored = dict(task)
            scored["priority"] = 9900 + min(1800, round(value - opportunity))
            filtered.append(scored)
            profitable_fertilize += 1
    if not profitable_fertilize:
        filtered = [task for task in filtered if str(task.get("label")) != "pickup-fertilizer"]
    state["trigger_counts"]["profitable_fertilize_tasks"] += profitable_fertilize
    tasks[:] = filtered
    return list(planned.values())


def _extra_rotation_tasks(
    tasks: list[dict[str, Any]],
    observation: Mapping[str, Any],
    farm: Mapping[str, Any],
    private: Mapping[str, Any],
    summary: Mapping[str, Any],
    crop_targets: Mapping[str, int],
    reserved: set[tuple[int, int]],
) -> None:
    day = _integer(observation.get("day"))
    if day >= 27:
        return
    occupied_by_task = {
        tuple(task["pos"])
        for task in tasks
        if task.get("action") and task["action"][0] in {"PLANT", "BUILD_PASTURE"}
    }
    positions = [
        (x, y)
        for x, y, tile in base._iter_tiles(farm)
        if tile is None and (x, y) not in reserved and (x, y) not in occupied_by_task
    ]
    board_size = len(farm.get("tiles") or []) or 10
    positions.sort(
        key=lambda pos: (
            min(base._manhattan(pos, shed) for shed in base._shed_tiles(board_size)),
            pos[1],
            pos[0],
        )
    )
    seeds = _mapping(private.get("seeds"))
    current = _mapping(summary.get("crops"))
    already_today = Counter(
        str(base._get(tile, "crop"))
        for _x, _y, tile in base._iter_tiles(farm)
        if base._tile_kind(tile) == "PLANT"
        and _integer(base._get(tile, "planted_day"), -1) == day
    )
    cursor = 0
    for crop, cap, priority in (("TOMATO", 4, 9350), ("CARROT", 8, 9550)):
        deficit = max(0, _integer(crop_targets.get(crop)) - _integer(current.get(crop)))
        amount = min(deficit, _integer(seeds.get(crop)), max(0, cap - already_today[crop]))
        for _ in range(amount):
            if cursor >= len(positions):
                return
            tasks.append(base._task(positions[cursor], ["PLANT", crop], priority, label=f"plant-{crop}"))
            cursor += 1


def _order_cost(order: list[Any], observation: Mapping[str, Any], farm: Mapping[str, Any]) -> float:
    if not order:
        return 0.0
    op = order[0]
    amount = _integer(order[2], 1) if len(order) >= 3 else 1
    if op == "BUY_SEED" and len(order) >= 2:
        return base.CROP_DATA.get(order[1], {}).get("seed", 0) * amount
    if op == "BUY_ANIMAL" and len(order) >= 2:
        return base.ANIMAL_DATA.get(order[1], {}).get("cost", 0) * amount
    if op == "BUY_PRODUCT" and len(order) >= 2:
        prices = _mapping(_mapping(observation.get("market")).get("prices"))
        return max(1, _integer(prices.get(order[1]), 1)) * amount
    if op == "BUY_LAND":
        unlocked = len(farm.get("unlocked_quadrants") or [])
        return (1000, 2000, 4000)[min(2, max(0, unlocked - 1))]
    if op == "HIRE":
        return 0.0  # Fibonacci hire costs are tiny relative to this reserve estimate.
    return 0.0


def _market_plan(
    observation: Mapping[str, Any],
    farm: Mapping[str, Any],
    private: Mapping[str, Any],
    summary: Mapping[str, Any],
    targets: Mapping[str, Any],
    actions: list[list[Any]],
    reserved: set[tuple[int, int]],
) -> list[list[Any]]:
    day = _integer(observation.get("day"))
    hour = _integer(observation.get("hour"))
    if day == 0 and hour == 0:
        return [
            ["HIRE"], ["HIRE"], ["HIRE"], ["HIRE"],
            ["BUY_ANIMAL", "COW", 2],
            ["BUY_ANIMAL", "SHEEP", 3],
            ["BUY_SEED", "WHEAT", 10],
            # Five melons leave enough opening cash to feed every animal. The
            # sixth target is bought after fertilizer working capital arrives.
            ["BUY_SEED", "MELON", 5],
            # Unit actions precede the market, so this stock becomes usable at
            # hour 1. Four units plus the first fertilizer sale bridge the
            # opening herd until the first wheat harvest.
            ["BUY_PRODUCT", "WHEAT", 5],
        ]

    weights = {"rank1": 1.0, "rank2": 0.0, "rank3": 0.0}
    orders = executor._market_plan(
        observation,
        farm,
        private,
        dict(summary),
        dict(targets["animals"]),
        dict(targets["crops"]),
        _integer(targets["hands"]),
        _integer(targets["land"]),
        weights,
        _integer(targets["pastures"]),
        actions,
        reserved,
    )
    orders = [list(order) for order in orders]

    # Farm hands are day workers: the engine clears them every night.  V4's
    # inherited target is lower on days 1--5 and _shape_market only removes
    # excess HIREs; it never adds the missing ones.  Rebuild the order priority
    # so this plan actually funds its stated daily workload.
    current_hands = len(farm.get("hands") or [])
    existing_hires = sum(order and order[0] == "HIRE" for order in orders)
    missing_hires = max(0, _integer(targets["hands"]) - current_hands - existing_hires)
    if missing_hires:
        hires = [["HIRE"] for _ in range(missing_hires)]
        cashflow = [order for order in orders if order and order[0] in {"SELL", "BUY_PRODUCT"}]
        existing_workforce = [order for order in orders if order and order[0] == "HIRE"]
        investment = [
            order
            for order in orders
            if order and order[0] not in {"SELL", "BUY_PRODUCT", "HIRE"}
        ]
        orders = [*cashflow, *existing_workforce, *hires, *investment][:10]

    seeds = _mapping(private.get("seeds"))
    crop_counts = _mapping(summary.get("crops"))
    money = float(farm.get("money") or 0)
    budget = money - sum(_order_cost(order, observation, farm) for order in orders)
    reserve = 100 + 15 * _integer(summary.get("animal_total"))
    for crop, cap in (("TOMATO", 4), ("CARROT", 8)):
        if len(orders) >= 10:
            break
        deficit = max(
            0,
            _integer(targets["crops"].get(crop))
            - _integer(crop_counts.get(crop))
            - _integer(seeds.get(crop)),
        )
        cost = _integer(base.CROP_DATA[crop]["seed"])
        amount = min(cap, deficit, max(0, int((budget - reserve) // max(1, cost))))
        if amount:
            orders.append(["BUY_SEED", crop, amount])
            budget -= amount * cost
    return orders[:10]


def _diagnostics(
    observation: Mapping[str, Any],
    farm: Mapping[str, Any],
    targets: Mapping[str, Any],
    ledger: list[dict[str, Any]],
    forecast: Mapping[str, Any],
    *,
    rejected: list[dict[str, Any]] | None = None,
    planned_exits: list[dict[str, Any]] | None = None,
    trigger_counts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    step = 24 * _integer(observation.get("day")) + _integer(observation.get("hour"))
    forecast_items = _mapping(forecast.get("items"))
    inventory_value = 0.0
    maintenance = 0.0
    for asset in ledger:
        product = asset["name"]
        if asset["kind"] == "animal":
            product = str(base.ANIMAL_DATA[asset["name"]]["product"])
        price = _integer(
            _mapping(_mapping(forecast_items.get(product)).get("scenario_prices")).get("central"),
            base.BASE_PRICE.get(product, 1),
        )
        units_per_event = 2 if asset["kind"] == "animal" else 1
        inventory_value += (
            _integer(asset["yield_waiting"])
            + units_per_event * _integer(asset["effective_productions_remaining"])
        ) * price
        if asset["kind"] == "animal":
            wheat_price = _integer(_mapping(forecast_items.get("WHEAT")).get("current_price"), 25)
            maintenance += _integer(asset["maintenance_wheat"]) * wheat_price
    expected_terminal_cash = float(farm.get("money") or 0) + inventory_value - maintenance
    return {
        "step": step,
        "selected_plan": PLAN_NAME,
        "plan_source": PLAN_SOURCE,
        "targets": targets,
        "candidate_values": {"continue_base_plan": round(expected_terminal_cash, 1)},
        "supply_forecast": forecast,
        "rejected": rejected or [],
        "planned_exits": planned_exits or [],
        "aftercrop_plans": [
            {"pos": value.get("pos"), "crop": value.get("aftercrop"), "status": value.get("status")}
            for value in (planned_exits or [])
        ],
        "trigger_counts": dict(trigger_counts or {}),
        "asset_ledger": ledger,
    }


def _opening_working_capital_tasks(
    tasks: list[dict[str, Any]],
    observation: Mapping[str, Any],
    farm: Mapping[str, Any],
    positions: list[tuple[int, int]],
    inventories: list[Any],
) -> None:
    """Sell early fertilizer rather than consuming the herd's feed capital."""
    day = _integer(observation.get("day"))
    if day >= 7:
        return
    tasks[:] = [
        task
        for task in tasks
        if str(task.get("label")) not in {"fertilize", "pickup-fertilizer"}
    ]
    board_size = len(farm.get("tiles") or []) or 10
    for unit, (position, inventory) in enumerate(zip(positions, inventories, strict=True)):
        quantity = base._inventory_count(inventory, "FERTILIZER")
        if not quantity:
            continue
        tasks.append(
            base._task(
                base._nearest_shed(position, board_size),
                ["PLACE", "FERTILIZER", quantity],
                16600,
                unit=unit,
                label="return-opening-fertilizer",
            )
        )


def plan_action(observation: Mapping[str, Any], *, adaptive: bool = False) -> dict[str, Any]:
    """Build one action; adaptation is enabled only by the separate arm."""
    safe = base._safe_observation(observation)
    if safe is None:
        return {"farmer": ["PASS"], "hands": [], "market": []}
    farm_value, _opponent_farm, private_value = safe
    farm = _mapping(farm_value)
    private = _mapping(private_value)
    summary = base._farm_summary(farm)
    targets = plan_targets(_integer(observation.get("day")), summary)
    forecast = observed_supply_forecast(observation)
    state: dict[str, Any] | None = None
    rejected: list[dict[str, Any]] = []
    planned_exits: list[dict[str, Any]] = []
    if adaptive:
        state = _adaptive_state(observation)
        targets, rejected = _adaptive_targets(observation, summary, targets, forecast, state)
    positions = [tuple(farm.get("farmer") or [0, 0])]
    positions.extend(tuple(position) for position in farm.get("hands") or [])
    raw_inventories = list(private.get("inventories") or [])
    inventories = [
        raw_inventories[index] if index < len(raw_inventories) else {}
        for index in range(len(positions))
    ]
    tasks, reserved = executor._field_tasks(
        observation,
        farm,
        private,
        positions,
        inventories,
        summary,
        dict(targets["animals"]),
        dict(targets["crops"]),
        _integer(targets["pastures"]),
    )
    _opening_working_capital_tasks(tasks, observation, farm, positions, inventories)
    if adaptive and state is not None:
        planned_exits = _adaptive_task_overlay(tasks, observation, farm, forecast, state)
    _extra_rotation_tasks(tasks, observation, farm, private, summary, targets["crops"], reserved)
    actions = executor._assign_tasks(positions, inventories, tasks)
    market = _market_plan(observation, farm, private, summary, targets, actions, reserved)

    ledger = asset_ledger(observation, farm)
    LAST_DIAGNOSTICS[_seat(observation)] = _diagnostics(
        observation,
        farm,
        targets,
        ledger,
        forecast,
        rejected=rejected,
        planned_exits=planned_exits,
        trigger_counts=_mapping(state.get("trigger_counts")) if state is not None else {},
    )
    return {
        "farmer": actions[0] if actions else ["PASS"],
        "hands": actions[1:],
        "market": market,
    }


def agent(observation: Mapping[str, Any]) -> dict[str, Any]:
    return plan_action(observation, adaptive=False)


def latest_diagnostics(seat: int = 0) -> dict[str, Any]:
    return LAST_DIAGNOSTICS.get(1 if seat == 1 else 0, {})
