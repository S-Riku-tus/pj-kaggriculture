"""Shared, observation-only feature schema for V3 training and inference."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

SCHEMA_VERSION = 1

CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
ANIMALS = ("GOOSE", "COW", "SHEEP")
PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER")
MODEL_CROPS = ("WHEAT", "STRAWBERRY", "MELON")
MODEL_ANIMALS = ("COW", "SHEEP")
MODEL_PRODUCTS = ("WHEAT", "STRAWBERRY", "MELON", "MILK", "WOOL", "FERTILIZER")
OUTPUT_NAMES = ("WHEAT", "STRAWBERRY", "MELON", "COW", "SHEEP", "HANDS", "LAND")

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


def get_value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    getter = getattr(obj, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except (AttributeError, TypeError):
            pass
    return getattr(obj, key, default)


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def inventory_count(inventory: Any, item: str) -> int:
    return max(0, as_int(get_value(inventory, item, 0)))


def iter_tiles(farm: Any):
    for y, row in enumerate(get_value(farm, "tiles", []) or []):
        for x, tile in enumerate(row):
            yield x, y, tile


def farm_summary(farm: Any, day: int | None = None) -> dict[str, Any]:
    crops = {crop: 0 for crop in CROPS}
    animals = {animal: 0 for animal in ANIMALS}
    crop_age_sum = {crop: 0 for crop in MODEL_CROPS}
    crop_age_count = {crop: 0 for crop in MODEL_CROPS}
    empty_structures = 0
    weeds = 0
    unwatered = 0
    unfed = 0
    ready_yield = 0
    fertilizer_ready = 0
    for _x, _y, tile in iter_tiles(farm):
        kind = get_value(tile, "kind") if tile not in (None, "LOCKED") else None
        crop = get_value(tile, "crop")
        animal = get_value(tile, "animal")
        if kind == "PLANT" and crop in crops:
            crops[crop] += 1
            if crop in crop_age_sum:
                crop_age_sum[crop] += max(0, (day or 0) - as_int(get_value(tile, "planted_day", 0)))
                crop_age_count[crop] += 1
            if not bool(get_value(tile, "watered_today", False)):
                unwatered += 1
            if as_int(get_value(tile, "yield_units", 0)) > 0:
                ready_yield += 1
        elif animal in animals:
            animals[animal] += 1
            if not bool(get_value(tile, "fed_today", False)):
                unfed += 1
            if as_int(get_value(tile, "yield_units", 0)) > 0:
                ready_yield += 1
            if bool(get_value(tile, "fertilizer_available", False)):
                fertilizer_ready += 1
        elif kind in {"COOP", "PASTURE"}:
            empty_structures += 1
        elif kind == "WEED":
            weeds += 1
    unlocked = len(get_value(farm, "unlocked_quadrants", []) or [])
    productive = sum(crops.values()) + sum(animals.values())
    capacity = max(25, unlocked * 25)
    mean_crop_age = {
        crop: crop_age_sum[crop] / max(1, crop_age_count[crop]) for crop in MODEL_CROPS
    }
    return {
        "crops": crops,
        "animals": animals,
        "productive": productive,
        "capacity": capacity,
        "utilization": productive / capacity,
        "unlocked": unlocked,
        "empty_structures": empty_structures,
        "weeds": weeds,
        "unwatered": unwatered,
        "unfed": unfed,
        "ready_yield": ready_yield,
        "fertilizer_ready": fertilizer_ready,
        "mean_crop_age": mean_crop_age,
    }


def demand_profile(obs: Any) -> Counter[str]:
    demand: Counter[str] = Counter()
    town = get_value(obs, "town", {}) or {}
    for shop in get_value(town, "unlocked_shops", []) or []:
        demand.update(SHOP_DEMAND.get(str(shop), {}))
    return demand


FEATURE_NAMES = (
    "day",
    "days_left",
    "phase_opening",
    "phase_branch",
    "phase_compound",
    "phase_harvest",
    "money_log",
    "land",
    "utilization",
    "hands",
    "hires_today",
    *(f"own_crop_{crop}" for crop in CROPS),
    *(f"own_animal_{animal}" for animal in ANIMALS),
    "own_empty_structures",
    "own_weeds",
    "own_unwatered",
    "own_unfed",
    "own_ready_yield",
    "own_fertilizer_ready",
    *(f"own_crop_age_{crop}" for crop in MODEL_CROPS),
    *(f"shed_{item}" for item in MODEL_PRODUCTS),
    *(f"carried_{item}" for item in MODEL_PRODUCTS),
    *(f"seed_{crop}" for crop in MODEL_CROPS),
    *(f"demand_{item}" for item in PRODUCTS if item != "FERTILIZER"),
    "shop_count",
    *(f"price_{item}" for item in PRODUCTS),
    *(f"market_inventory_{item}" for item in MODEL_PRODUCTS),
    "opp_land",
    "opp_utilization",
    *(f"opp_crop_{crop}" for crop in CROPS),
    *(f"opp_animal_{animal}" for animal in ANIMALS),
)


def _scaled_count(value: int, scale: float) -> float:
    return min(4.0, max(0.0, value / scale))


def encode_observation(obs: Any) -> list[float]:
    farms = get_value(obs, "farms", []) or []
    player = as_int(get_value(obs, "player", 0))
    if not farms or not 0 <= player < len(farms):
        return [0.0] * len(FEATURE_NAMES)
    day = as_int(get_value(obs, "day", 0))
    own = farms[player]
    opponent = farms[1 - player] if len(farms) > 1 else own
    # The day is passed separately by observations, while farm_summary remains
    # usable on plain replay dictionaries and Kaggle Struct objects.
    own_summary = farm_summary(own, day)
    opponent_summary = farm_summary(opponent, day)
    private = get_value(obs, "private", {}) or {}
    shed = get_value(private, "shed", {}) or {}
    seeds = get_value(private, "seeds", {}) or {}
    inventories = get_value(private, "inventories", []) or []
    market = get_value(obs, "market", {}) or {}
    prices = get_value(market, "prices", {}) or {}
    market_inventory = get_value(market, "inventory", {}) or {}
    demand = demand_profile(obs)
    shops = get_value(get_value(obs, "town", {}) or {}, "unlocked_shops", []) or []

    values: list[float] = [
        day / 29.0,
        (29 - day) / 29.0,
        float(day <= 2),
        float(3 <= day <= 7),
        float(8 <= day <= 20),
        float(day >= 21),
        min(2.0, math.log1p(max(0.0, float(get_value(own, "money", 0) or 0))) / 12.0),
        own_summary["unlocked"] / 4.0,
        own_summary["utilization"],
        len(get_value(own, "hands", []) or []) / 14.0,
        as_int(get_value(own, "hires_today", 0)) / 14.0,
    ]
    values.extend(_scaled_count(own_summary["crops"][crop], 50.0) for crop in CROPS)
    values.extend(_scaled_count(own_summary["animals"][animal], 16.0) for animal in ANIMALS)
    values.extend(
        (
            _scaled_count(own_summary["empty_structures"], 12.0),
            _scaled_count(own_summary["weeds"], 20.0),
            _scaled_count(own_summary["unwatered"], 75.0),
            _scaled_count(own_summary["unfed"], 20.0),
            _scaled_count(own_summary["ready_yield"], 75.0),
            _scaled_count(own_summary["fertilizer_ready"], 20.0),
        )
    )
    values.extend(_scaled_count(own_summary["mean_crop_age"][crop], 30.0) for crop in MODEL_CROPS)
    values.extend(_scaled_count(inventory_count(shed, item), 100.0) for item in MODEL_PRODUCTS)
    values.extend(
        _scaled_count(sum(inventory_count(inventory, item) for inventory in inventories), 50.0)
        for item in MODEL_PRODUCTS
    )
    values.extend(_scaled_count(inventory_count(seeds, crop), 50.0) for crop in MODEL_CROPS)
    values.extend(_scaled_count(inventory_count(demand, item), 8.0) for item in PRODUCTS if item != "FERTILIZER")
    values.append(min(1.5, len(shops) / 8.0))
    values.extend(
        min(4.0, max(0.0, float(get_value(prices, item, BASE_PRICE[item]) or 0) / BASE_PRICE[item]))
        for item in PRODUCTS
    )
    values.extend(
        min(2.0, math.log1p(max(0, as_int(get_value(market_inventory, item, 0)))) / math.log(10001.0))
        for item in MODEL_PRODUCTS
    )
    values.extend((opponent_summary["unlocked"] / 4.0, opponent_summary["utilization"]))
    values.extend(_scaled_count(opponent_summary["crops"][crop], 50.0) for crop in CROPS)
    values.extend(_scaled_count(opponent_summary["animals"][animal], 16.0) for animal in ANIMALS)
    if len(values) != len(FEATURE_NAMES):
        raise RuntimeError(f"feature schema mismatch: {len(values)} != {len(FEATURE_NAMES)}")
    return values


def portfolio_label(farm: Any, *, hands: int | None = None) -> list[float]:
    summary = farm_summary(farm)
    return [
        float(summary["crops"]["WHEAT"]),
        float(summary["crops"]["STRAWBERRY"]),
        float(summary["crops"]["MELON"]),
        float(summary["animals"]["COW"]),
        float(summary["animals"]["SHEEP"]),
        float(len(get_value(farm, "hands", []) or []) if hands is None else hands),
        float(summary["unlocked"]),
    ]
