"""Round5 strategy features and explicitly analyst-authored replay labels."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

try:
    from .contracts import ANIMAL_RULES, CROP_RULES, actor_positions, harvestability, next_animal_production_day, tile_at
except ImportError:
    from contracts import ANIMAL_RULES, CROP_RULES, actor_positions, harvestability, next_animal_production_day, tile_at  # type: ignore

SKILLS = (
    "NONE",
    "ANIMAL_LIFECYCLE_REALIZATION",
    "HARVEST_AND_LAND_CONVERSION",
    "SELL_AND_REINVEST",
)
FEATURE_NAMES = (
    "day",
    "hour",
    "own_money",
    "opponent_money",
    "margin",
    "shed_wheat",
    "shed_load",
    "carried_wheat",
    "animal_count",
    "goose_count",
    "cow_count",
    "sheep_count",
    "unfed_animals",
    "unfed_once_animals",
    "uncared_animals",
    "animal_yield_total",
    "egg_yield",
    "milk_yield",
    "wool_yield",
    "actors_on_positive_animal_yield",
    "minimum_days_to_animal_production",
    "crop_count",
    "harvestable_crops",
    "immature_positive_yield_crops",
    "empty_owned_tiles",
    "hand_count",
    "remaining_steps",
    "wheat_price",
    "egg_price",
    "milk_price",
    "wool_price",
    "max_product_price",
    "committed_feed_today",
    "unreserved_wheat",
    "shed_animal_products",
    "seed_total",
)
FEATURE_SCALE = (
    29.0, 23.0, 100000.0, 100000.0, 100000.0, 100.0, 100.0, 100.0,
    100.0, 50.0, 50.0, 50.0, 100.0, 100.0, 100.0, 600.0, 100.0, 100.0,
    100.0, 50.0, 30.0, 100.0, 100.0, 100.0, 100.0, 50.0, 719.0, 300.0,
    300.0, 300.0, 300.0, 300.0, 100.0, 100.0, 100.0, 100.0,
)


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def strategy_features(observation: Mapping[str, Any]) -> list[float]:
    seat = int(_number(observation.get("player")))
    farms = list(observation.get("farms") or [])
    farm = farms[seat] if seat < len(farms) else {}
    opponent = farms[1 - seat] if len(farms) == 2 else {}
    private = observation.get("private") or {}
    shed = private.get("shed") or {}
    inventories = list(private.get("inventories") or [])
    day = int(_number(observation.get("day")))
    animal_counts = {name: 0 for name in ANIMAL_RULES}
    product_yields = {str(rule["product"]): 0 for rule in ANIMAL_RULES.values()}
    animals = unfed = unfed_once = uncared = animal_yield = crops = harvestable = immature = empty = 0
    production_days: list[int] = []
    committed_feed = 0
    for row in farm.get("tiles") or []:
        for tile in row:
            if tile is None:
                empty += 1
            if not isinstance(tile, Mapping):
                continue
            if tile.get("animal"):
                animal = str(tile.get("animal"))
                animals += 1
                animal_counts[animal] = animal_counts.get(animal, 0) + 1
                is_unfed = not bool(tile.get("fed_today"))
                unfed += int(is_unfed)
                unfed_once += int(is_unfed and int(_number(tile.get("consecutive_unfed"))) >= 1)
                uncared += int(not bool(tile.get("cared_today")))
                value = max(0, int(_number(tile.get("yield_units"))))
                animal_yield += value
                product_yields[str(ANIMAL_RULES.get(animal, {}).get("product", ""))] = value + product_yields.get(str(ANIMAL_RULES.get(animal, {}).get("product", "")), 0)
                next_day = next_animal_production_day(tile, day)
                if next_day is not None:
                    production_days.append(max(0, next_day - day))
                committed_feed += int(is_unfed and (value > 0 or next_day is not None and next_day <= 29))
            elif tile.get("kind") == "PLANT":
                crops += 1
                crop = str(tile.get("crop") or "")
                age = day - int(_number(tile.get("planted_day")))
                positive = _number(tile.get("yield_units")) > 0
                first = int(CROP_RULES.get(crop, {}).get("first_yield_day", 10**9))
                harvestable += int(positive and age >= first)
                immature += int(positive and age < first)
    positions = actor_positions(observation)
    actors_on_yield = sum(
        int(isinstance(tile_at(observation, position), Mapping) and bool(tile_at(observation, position).get("animal")) and _number(tile_at(observation, position).get("yield_units")) > 0)
        for position in positions
    )
    money = _number(farm.get("money"))
    opponent_money = _number(opponent.get("money"))
    prices = (observation.get("market") or {}).get("prices") or {}
    carried_wheat = sum(max(0.0, _number(inventory.get("WHEAT"))) for inventory in inventories)
    accessible_wheat = _number(shed.get("WHEAT")) + carried_wheat
    raw = [
        day,
        _number(observation.get("hour")),
        money,
        opponent_money,
        money - opponent_money,
        _number(shed.get("WHEAT")),
        sum(max(0.0, _number(value)) for value in shed.values()),
        carried_wheat,
        animals,
        animal_counts.get("GOOSE", 0),
        animal_counts.get("COW", 0),
        animal_counts.get("SHEEP", 0),
        unfed,
        unfed_once,
        uncared,
        animal_yield,
        product_yields.get("EGG", 0),
        product_yields.get("MILK", 0),
        product_yields.get("WOOL", 0),
        actors_on_yield,
        min(production_days) if production_days else 30,
        crops,
        harvestable,
        immature,
        empty,
        len(farm.get("hands") or []),
        719 - (24 * day + int(_number(observation.get("hour")))),
        _number(prices.get("WHEAT")),
        _number(prices.get("EGG")),
        _number(prices.get("MILK")),
        _number(prices.get("WOOL")),
        max([_number(value) for value in prices.values()] or [0.0]),
        committed_feed,
        max(0.0, accessible_wheat - committed_feed),
        sum(_number(shed.get(item)) for item in ("EGG", "MILK", "WOOL")),
        sum(_number(value) for value in (private.get("seeds") or {}).values()),
    ]
    return [value / scale for value, scale in zip(raw, FEATURE_SCALE, strict=True)]


def action_skill_set(observation: Mapping[str, Any], action: Mapping[str, Any]) -> set[str]:
    units = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
    positions = actor_positions(observation)
    skills: set[str] = set()
    for actor, value in enumerate(units):
        if not value:
            continue
        op = str(value[0])
        tile = tile_at(observation, positions[actor]) if actor < len(positions) else None
        if op in {"FEED", "CARE", "COLLECT_FERTILIZER"} or (op == "HARVEST" and isinstance(tile, Mapping) and tile.get("animal")):
            skills.add("ANIMAL_LIFECYCLE_REALIZATION")
        elif op in {"HARVEST", "DIG"}:
            skills.add("HARVEST_AND_LAND_CONVERSION")
    for order in action.get("market") or []:
        if not order:
            continue
        op = str(order[0])
        item = str(order[1]) if len(order) > 1 else ""
        if op == "BUY_ANIMAL" or (op == "SELL" and item in {"EGG", "MILK", "WOOL"}):
            skills.add("ANIMAL_LIFECYCLE_REALIZATION")
        elif op in {"SELL", "BUY_SEED", "BUY_PRODUCT", "BUY_LAND", "HIRE"}:
            skills.add("SELL_AND_REINVEST")
    return skills


def label_skill(observation: Mapping[str, Any], action: Mapping[str, Any]) -> str:
    """Deterministic analyst label; action_skill_set retains simultaneous intents."""
    skills = action_skill_set(observation, action)
    for candidate in SKILLS[1:]:
        if candidate in skills:
            return candidate
    return "NONE"


def applicable_skills(observation: Mapping[str, Any]) -> dict[str, bool]:
    farm = observation["farms"][int(_number(observation.get("player")))]
    harvest = any(harvestability(observation, actor).applicable for actor in range(1 + len(farm.get("hands") or [])))
    animal = any(isinstance(tile, Mapping) and tile.get("animal") for row in farm.get("tiles") or [] for tile in row)
    shed = observation.get("private", {}).get("shed", {})
    sell = any(_number(value) > 0 for key, value in shed.items() if key not in {"GOOSE", "COW", "SHEEP"})
    return {"ANIMAL_LIFECYCLE_REALIZATION": animal, "HARVEST_AND_LAND_CONVERSION": harvest, "SELL_AND_REINVEST": sell}


__all__ = ["FEATURE_NAMES", "SKILLS", "action_skill_set", "applicable_skills", "label_skill", "strategy_features"]
