"""Shared strategy-skill features and replay labels."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

try:
    from .contracts import CROP_RULES, crop_harvestability
except ImportError:
    from contracts import CROP_RULES, crop_harvestability  # type: ignore


SKILLS = (
    "NONE",
    "ANIMAL_SERVICE_WITH_CONTINUATION",
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
    "unfed_animals",
    "uncared_animals",
    "crop_count",
    "harvestable_crops",
    "immature_positive_yield_crops",
    "empty_owned_tiles",
    "hand_count",
    "remaining_steps",
    "wheat_price",
    "max_product_price",
)
FEATURE_SCALE = (
    29.0,
    23.0,
    100000.0,
    100000.0,
    100000.0,
    100.0,
    100.0,
    100.0,
    100.0,
    100.0,
    100.0,
    100.0,
    100.0,
    100.0,
    100.0,
    50.0,
    719.0,
    100.0,
    300.0,
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
    animals = unfed = uncared = crops = harvestable = immature = empty = 0
    for row in farm.get("tiles") or []:
        for tile in row:
            if tile is None:
                empty += 1
            if not isinstance(tile, Mapping):
                continue
            if tile.get("animal"):
                animals += 1
                unfed += int(not bool(tile.get("fed_today")))
                uncared += int(not bool(tile.get("cared_today")))
            if tile.get("kind") == "PLANT":
                crops += 1
                crop = str(tile.get("crop") or "")
                age = int(_number(observation.get("day"))) - int(_number(tile.get("planted_day")))
                positive = _number(tile.get("yield_units")) > 0
                first = int(CROP_RULES.get(crop, {}).get("first_yield_day", 10**9))
                harvestable += int(positive and age >= first)
                immature += int(positive and age < first)
    money = _number(farm.get("money"))
    opponent_money = _number(opponent.get("money"))
    prices = (observation.get("market") or {}).get("prices") or {}
    raw = [
        _number(observation.get("day")),
        _number(observation.get("hour")),
        money,
        opponent_money,
        money - opponent_money,
        _number(shed.get("WHEAT")),
        sum(max(0.0, _number(value)) for value in shed.values()),
        sum(max(0.0, _number(inventory.get("WHEAT"))) for inventory in inventories),
        animals,
        unfed,
        uncared,
        crops,
        harvestable,
        immature,
        empty,
        len(farm.get("hands") or []),
        719 - (24 * int(_number(observation.get("day"))) + int(_number(observation.get("hour")))),
        _number(prices.get("WHEAT")),
        max([_number(value) for value in prices.values()] or [0.0]),
    ]
    return [value / scale for value, scale in zip(raw, FEATURE_SCALE, strict=True)]


def label_skill(observation: Mapping[str, Any], action: Mapping[str, Any]) -> str:
    units = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
    unit_ops = [str(value[0]) for value in units if value]
    orders = [value for value in action.get("market") or [] if value]
    market_ops = [str(value[0]) for value in orders]
    if any(op in {"FEED", "CARE", "COLLECT_FERTILIZER"} for op in unit_ops):
        return "ANIMAL_SERVICE_WITH_CONTINUATION"
    if any(op in {"HARVEST", "DIG"} for op in unit_ops):
        return "HARVEST_AND_LAND_CONVERSION"
    if any(op in {"SELL", "BUY_SEED", "BUY_PRODUCT", "BUY_ANIMAL", "BUY_LAND", "HIRE"} for op in market_ops):
        return "SELL_AND_REINVEST"
    return "NONE"


def applicable_skills(observation: Mapping[str, Any]) -> dict[str, bool]:
    farm = observation["farms"][int(_number(observation.get("player")))]
    harvest = any(
        crop_harvestability(observation, actor).applicable for actor in range(1 + len(farm.get("hands") or []))
    )
    animal = any(
        isinstance(tile, Mapping) and tile.get("animal") and not bool(tile.get("fed_today"))
        for row in farm.get("tiles") or []
        for tile in row
    )
    shed = observation.get("private", {}).get("shed", {})
    sell = any(_number(value) > 0 for key, value in shed.items() if key not in {"GOOSE", "COW", "SHEEP"})
    return {
        "ANIMAL_SERVICE_WITH_CONTINUATION": animal,
        "HARVEST_AND_LAND_CONVERSION": harvest,
        "SELL_AND_REINVEST": sell,
    }


__all__ = ["FEATURE_NAMES", "SKILLS", "applicable_skills", "label_skill", "strategy_features"]
