"""Leakage-safe features, saved-model inference, and action constraints.

This module is deliberately independent of the V124/V125 replay router.  The
only arm that imports C0 is the explicit B/A overlay; the independent BC agent
uses this module and its learned checkpoints only.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from functools import cache
from pathlib import Path
from typing import Any

try:
    import numpy as np
except (ImportError, OSError):  # Kaggle's validation image may not provide a usable NumPy wheel.
    np = None  # type: ignore[assignment]

CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
PRODUCTS = CROPS + ("EGG", "MILK", "WOOL", "FERTILIZER")
ANIMALS = ("GOOSE", "COW", "SHEEP")
ITEMS = PRODUCTS + ANIMALS
PRODUCT_FOR_ANIMAL = {"GOOSE": "EGG", "COW": "MILK", "SHEEP": "WOOL"}
PRODUCTION_SCHEDULE = {
    "WHEAT": (2, 0),
    "CARROT": (2, 0),
    "TOMATO": (8, 1),
    "STRAWBERRY": (10, 2),
    "MELON": (10, 0),
    "EGG": (4, 1),
    "MILK": (8, 2),
    "WOOL": (6, 3),
}
SHOP_NAMES = (
    "BAKERY",
    "PIZZA_SHOP",
    "BRUNCH_SPOT",
    "YARN_STORE",
    "ICE_CREAM_SHOP",
    "PET_CAFE",
    "SMOOTHIE_SHOP",
    "FARMERS_MARKET",
)
MOVE_OPS = ("NORTH", "SOUTH", "EAST", "WEST")
WORK_OPS = (
    "FEED",
    "CARE",
    "WATER",
    "FERTILIZE",
    "HARVEST",
    "COLLECT_FERTILIZER",
    "PICKUP",
    "PLACE",
    "DROP",
    "PLANT",
    "DIG",
)
SIMPLE_FIELD_OPS = (
    "PASS",
    *MOVE_OPS,
    "WATER",
    "HARVEST",
    "FERTILIZE",
    "CARE",
    "FEED",
    "COLLECT_FERTILIZER",
    "DIG",
    "DROP",
    "BUILD_COOP",
    "BUILD_PASTURE",
)
ACTOR_TOKENS = (
    SIMPLE_FIELD_OPS
    + tuple(f"PLANT:{item}" for item in CROPS)
    + tuple(f"PICKUP:{item}" for item in ITEMS)
    + tuple(f"PLACE:{item}" for item in ITEMS)
)
MARKET_TOKENS = (
    "EOS",
    "HIRE",
    "BUY_LAND",
    *tuple(f"BUY_SEED:{item}" for item in CROPS),
    "BUY_PRODUCT:WHEAT",
    "BUY_PRODUCT:FERTILIZER",
    *tuple(f"BUY_ANIMAL:{item}" for item in ANIMALS),
    *tuple(f"SELL:{item}" for item in PRODUCTS),
)

# Frozen from kaggle-environments 1.32.7.  It is used only for deterministic
# candidate scoring; engine execution remains the authority.
MARKET_PARAMS: dict[str, dict[str, Any]] = {
    "WHEAT": {
        "base": 25,
        "I0": 10000,
        "T": 400,
        "below_func": "sqrt",
        "above_func": "log",
        "below_target": 0.8,
        "above_target": 0.2,
    },
    "CARROT": {
        "base": 35,
        "I0": 10000,
        "T": 450,
        "below_func": "hinge",
        "above_func": "sqrt",
        "below_target": 1.0,
        "above_target": 0.7,
    },
    "TOMATO": {
        "base": 60,
        "I0": 10000,
        "T": 200,
        "below_func": "hinge",
        "above_func": "sqrt",
        "below_target": 0.4,
        "above_target": 0.6,
    },
    "STRAWBERRY": {
        "base": 120,
        "I0": 10000,
        "T": 100,
        "below_func": "sqrt",
        "above_func": "linear",
        "below_target": 0.7,
        "above_target": 1.6,
    },
    "MELON": {
        "base": 250,
        "I0": 10000,
        "T": 300,
        "below_func": "log",
        "above_func": "sq",
        "below_target": 0.2,
        "above_target": 3.6,
    },
    "EGG": {
        "base": 50,
        "I0": 10000,
        "T": 332,
        "below_func": "hinge",
        "above_func": "log",
        "below_target": 0.4,
        "above_target": 0.2,
    },
    "MILK": {
        "base": 160,
        "I0": 10000,
        "T": 122,
        "below_func": "sqrt",
        "above_func": "linear",
        "below_target": 0.6,
        "above_target": 1.6,
    },
    "WOOL": {
        "base": 200,
        "I0": 10000,
        "T": 105,
        "below_func": "log",
        "above_func": "sq",
        "below_target": 0.2,
        "above_target": 3.2,
    },
    "FERTILIZER": {
        "base": 100,
        "I0": 10000,
        "T": 200,
        "below_func": "linear",
        "above_func": "linear",
        "below_target": 0.4,
        "above_target": 0.4,
    },
}


def _map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _seq(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, str | bytes) else ()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def canonical_step(observation: Mapping[str, Any]) -> int:
    return 24 * int(_number(observation.get("day"))) + int(_number(observation.get("hour")))


def market_price(item: str, inventory: int) -> int:
    p = MARKET_PARAMS[item]
    base, initial, scale = p["base"], p["I0"], p["T"]
    delta = abs(initial - inventory)
    func = p["below_func"] if inventory < initial else p["above_func"]
    target = p["below_target"] if inventory < initial else p["above_target"]

    def shape(name: str, value: float) -> float:
        if name == "linear":
            return value
        if name == "sq":
            return value * value
        if name == "sqrt":
            return math.sqrt(max(0.0, value))
        if name == "hinge":
            unit = max(0.0, value) / scale if scale > 0 else max(0.0, value)
            return unit + 8.0 * max(0.0, unit - 1.0) ** 2
        return math.log1p(max(0.0, value))

    amplitude = target * base / max(shape(func, scale), 1e-9)
    price = base + amplitude * shape(func, delta) if inventory < initial else base - amplitude * shape(func, delta)
    return max(1, int(round(price)))


class MarketHistory:
    """Public market history plus the focal player's past emitted orders."""

    def __init__(self) -> None:
        self.inventory: list[dict[str, int]] = []
        self.own_orders: list[list[list[Any]]] = []
        self.own_sell_cumulative: dict[str, list[float]] = {item: [] for item in PRODUCTS}

    def update(self, observation: Mapping[str, Any], own_orders: Sequence[Any] | None = None) -> None:
        market = _map(observation.get("market"))
        inventory = _map(market.get("inventory"))
        step = canonical_step(observation)
        snapshot = {item: int(_number(inventory.get(item))) for item in PRODUCTS}
        if not self.inventory or step >= len(self.inventory):
            self.inventory.append(snapshot)
            orders = [list(x) for x in (own_orders or ()) if isinstance(x, list | tuple)]
            self.own_orders.append(orders)
            sold = {item: 0.0 for item in PRODUCTS}
            for order in orders:
                if len(order) >= 3 and order[0] == "SELL" and order[1] in sold:
                    sold[str(order[1])] += max(0.0, _number(order[2]))
            for item in PRODUCTS:
                prior = self.own_sell_cumulative[item][-1] if self.own_sell_cumulative[item] else 0.0
                self.own_sell_cumulative[item].append(prior + sold[item])
        else:
            self.inventory[step] = snapshot

    def delta(self, item: str, lag: int) -> float:
        if not self.inventory:
            return 0.0
        current = self.inventory[-1].get(item, 0)
        prior = self.inventory[max(0, len(self.inventory) - 1 - lag)].get(item, current)
        return float(current - prior)

    def own_sell(self, item: str, lag: int) -> float:
        values = self.own_sell_cumulative[item]
        if not values:
            return 0.0
        before = len(values) - lag - 1
        return values[-1] - (values[before] if before >= 0 else 0.0)


@cache
def state_feature_names() -> tuple[str, ...]:
    names = ["day", "hour", "player", "remaining", "day_sin", "day_cos", "hour_sin", "hour_cos"]
    for item in PRODUCTS:
        names.extend((f"market_inventory:{item}", f"market_price:{item}"))
    names.extend(f"shop_count:{shop}" for shop in SHOP_NAMES)
    for seat in range(2):
        prefix = f"farm{seat}"
        names.extend(
            (
                f"{prefix}:money",
                f"{prefix}:workers",
                f"{prefix}:unlocked",
                f"{prefix}:hires_today",
                f"{prefix}:mean_x",
                f"{prefix}:mean_y",
                f"{prefix}:empty",
                f"{prefix}:locked",
                f"{prefix}:weed",
                f"{prefix}:plant",
                f"{prefix}:animal",
                f"{prefix}:yield",
                f"{prefix}:maintenance_due",
            )
        )
        names.extend(f"{prefix}:crop:{item}" for item in CROPS)
        names.extend(f"{prefix}:animal:{item}" for item in ANIMALS)
        for item in PRODUCTS:
            names.extend(
                (
                    f"{prefix}:public_age:{item}",
                    f"{prefix}:public_yield:{item}",
                    f"{prefix}:public_maintenance:{item}",
                    f"{prefix}:production_phase:{item}",
                )
            )
    names.extend(f"private:shed:{item}" for item in ITEMS)
    names.extend(f"private:seed:{item}" for item in CROPS)
    names.extend(f"private:carried:{item}" for item in ITEMS)
    names.extend(("private:carried_total", "private:shed_total"))
    for lag in (1, 4, 24):
        for item in PRODUCTS:
            names.extend((f"history:market_delta:{lag}:{item}", f"history:own_sell:{lag}:{item}"))
    return tuple(names)


def _production_phase(item: str, age: float) -> float:
    first, interval = PRODUCTION_SCHEDULE.get(item, (1, 0))
    if age < first:
        return max(0.0, age) / max(1.0, float(first))
    return 1.0 if interval <= 0 else ((age - first) % interval) / float(interval)


def _farm_summary(farm: Mapping[str, Any], day: float) -> list[float]:
    farmer = _seq(farm.get("farmer"))
    positions = [farmer, *_seq(farm.get("hands"))]
    xs = [_number(p[0]) for p in positions if len(_seq(p)) >= 2]
    ys = [_number(p[1]) for p in positions if len(_seq(p)) >= 2]
    empty = locked = weed = plants = animals = 0
    total_yield = maintenance = 0.0
    crop_counts = {item: 0 for item in CROPS}
    animal_counts = {item: 0 for item in ANIMALS}
    public_ages: dict[str, list[float]] = {item: [] for item in PRODUCTS}
    public_yield = {item: 0.0 for item in PRODUCTS}
    public_maintenance = {item: 0.0 for item in PRODUCTS}
    production_phase: dict[str, list[float]] = {item: [] for item in PRODUCTS}
    for row in _seq(farm.get("tiles")):
        for tile in _seq(row):
            if tile is None:
                empty += 1
            elif tile == "LOCKED":
                locked += 1
            elif isinstance(tile, Mapping):
                kind = tile.get("kind")
                if kind == "WEED":
                    weed += 1
                elif kind == "PLANT":
                    plants += 1
                    crop = str(tile.get("crop"))
                    crop_counts[crop] = crop_counts.get(crop, 0) + 1
                    tile_yield = _number(tile.get("yield_units"))
                    due = float(not bool(tile.get("watered_today")))
                    age = max(0.0, day - _number(tile.get("planted_day"), day))
                    total_yield += tile_yield
                    maintenance += due
                    if crop in public_ages:
                        public_ages[crop].append(age)
                        public_yield[crop] += tile_yield
                        public_maintenance[crop] += due
                        production_phase[crop].append(_production_phase(crop, age))
                elif kind in {"COOP", "PASTURE"}:
                    animals += 1
                    animal = tile.get("animal")
                    if animal:
                        animal = str(animal)
                        product = PRODUCT_FOR_ANIMAL.get(animal)
                        animal_counts[animal] = animal_counts.get(animal, 0) + 1
                        due = float(not bool(tile.get("fed_today")))
                        age = max(0.0, day - _number(tile.get("placed_day"), day))
                        maintenance += due
                        if product:
                            public_ages[product].append(age)
                            public_yield[product] += _number(tile.get("yield_units"))
                            public_maintenance[product] += due
                            production_phase[product].append(_production_phase(product, age))
                        public_ages["FERTILIZER"].append(age)
                        public_yield["FERTILIZER"] += float(bool(tile.get("fertilizer_available")))
                        public_maintenance["FERTILIZER"] += due
                        production_phase["FERTILIZER"].append(min(1.0, age / 6.0))
                    total_yield += _number(tile.get("yield_units"))
    return [
        math.log1p(max(0.0, _number(farm.get("money")))),
        len(positions) / 16.0,
        len(_seq(farm.get("unlocked_quadrants"))) / 4.0,
        _number(farm.get("hires_today")) / 16.0,
        (sum(xs) / max(1, len(xs))) / 9.0,
        (sum(ys) / max(1, len(ys))) / 9.0,
        empty / 100.0,
        locked / 100.0,
        weed / 100.0,
        plants / 100.0,
        animals / 100.0,
        total_yield / 500.0,
        maintenance / 100.0,
        *(crop_counts[item] / 100.0 for item in CROPS),
        *(animal_counts[item] / 100.0 for item in ANIMALS),
        *(
            value
            for item in PRODUCTS
            for value in (
                (sum(public_ages[item]) / max(1, len(public_ages[item]))) / 30.0,
                public_yield[item] / 100.0,
                public_maintenance[item] / 100.0,
                sum(production_phase[item]) / max(1, len(production_phase[item])),
            )
        ),
    ]


def state_features(observation: Mapping[str, Any], history: MarketHistory | None = None) -> np.ndarray:
    day = _number(observation.get("day"))
    hour = _number(observation.get("hour"))
    features = [
        day / 29.0,
        hour / 23.0,
        _number(observation.get("player")),
        (719.0 - canonical_step(observation)) / 719.0,
        math.sin(2 * math.pi * day / 30.0),
        math.cos(2 * math.pi * day / 30.0),
        math.sin(2 * math.pi * hour / 24.0),
        math.cos(2 * math.pi * hour / 24.0),
    ]
    market = _map(observation.get("market"))
    inventory, prices = _map(market.get("inventory")), _map(market.get("prices"))
    for item in PRODUCTS:
        features.extend((math.asinh(_number(inventory.get(item))) / 8.0, _number(prices.get(item)) / 500.0))
    shops = [str(x) for x in _seq(_map(observation.get("town")).get("unlocked_shops"))]
    features.extend(shops.count(shop) / 8.0 for shop in SHOP_NAMES)
    farms = _seq(observation.get("farms"))
    for seat in range(2):
        features.extend(_farm_summary(_map(farms[seat]) if seat < len(farms) else {}, day))
    private = _map(observation.get("private"))
    shed = _map(private.get("shed"))
    seeds = _map(private.get("seeds"))
    inventories = [_map(value) for value in _seq(private.get("inventories"))]
    features.extend(math.log1p(max(0.0, _number(shed.get(item)))) / 8.0 for item in ITEMS)
    features.extend(math.log1p(max(0.0, _number(seeds.get(item)))) / 6.0 for item in CROPS)
    carried = {item: sum(_number(inv.get(item)) for inv in inventories) for item in ITEMS}
    features.extend(math.log1p(max(0.0, carried[item])) / 6.0 for item in ITEMS)
    features.extend(
        (
            math.log1p(sum(max(0.0, value) for value in carried.values())) / 8.0,
            math.log1p(sum(max(0.0, _number(value)) for value in shed.values())) / 8.0,
        )
    )
    for lag in (1, 4, 24):
        for item in PRODUCTS:
            features.extend(
                (
                    (history.delta(item, lag) if history else 0.0) / 100.0,
                    (history.own_sell(item, lag) if history else 0.0) / 100.0,
                )
            )
    if len(features) != len(state_feature_names()):
        raise ValueError(f"state feature mismatch: {len(features)} != {len(state_feature_names())}")
    return np.asarray(features, dtype=np.float32) if np is not None else features


@cache
def actor_feature_names() -> tuple[str, ...]:
    names = [*state_feature_names(), "actor:index", "actor:x", "actor:y"]
    names.extend(f"actor:inventory:{item}" for item in ITEMS)
    names.extend(f"actor:tile_kind:{item}" for item in ("EMPTY", "LOCKED", "WEED", "PLANT", "COOP", "PASTURE"))
    names.extend(f"actor:tile_crop:{item}" for item in CROPS)
    names.extend(f"actor:tile_animal:{item}" for item in ANIMALS)
    names.extend(("actor:tile_yield", "actor:watered", "actor:fed", "actor:cared", "actor:fertilized"))
    names.extend(
        (
            "actor:tile_age",
            "actor:deadline_remaining",
            "actor:consecutive_unwatered",
            "actor:consecutive_unfed",
            "actor:pending_care_bonus",
            "actor:fertilizer_available",
            "actor:inventory_total",
            "actor:shed_distance",
        )
    )
    return tuple(names)


def actor_features(
    observation: Mapping[str, Any], actor_index: int, history: MarketHistory | None = None
) -> np.ndarray:
    base = state_features(observation, history).tolist()
    seat = int(_number(observation.get("player")))
    farms = _seq(observation.get("farms"))
    farm = _map(farms[seat]) if seat < len(farms) else {}
    positions = [_seq(farm.get("farmer")), *_seq(farm.get("hands"))]
    position = _seq(positions[actor_index]) if actor_index < len(positions) else ()
    x = int(_number(position[0])) if len(position) >= 2 else 0
    y = int(_number(position[1])) if len(position) >= 2 else 0
    inventories = _seq(_map(observation.get("private")).get("inventories"))
    inventory = _map(inventories[actor_index]) if actor_index < len(inventories) else {}
    tiles = _seq(farm.get("tiles"))
    row = _seq(tiles[y]) if 0 <= y < len(tiles) else ()
    tile = row[x] if 0 <= x < len(row) else "LOCKED"
    kind = "EMPTY" if tile is None else str(tile.get("kind")) if isinstance(tile, Mapping) else "LOCKED"
    tile_map = _map(tile)
    values = [actor_index / 16.0, x / 9.0, y / 9.0]
    values.extend(math.log1p(max(0.0, _number(inventory.get(item)))) / 6.0 for item in ITEMS)
    values.extend(float(kind == candidate) for candidate in ("EMPTY", "LOCKED", "WEED", "PLANT", "COOP", "PASTURE"))
    values.extend(float(tile_map.get("crop") == item) for item in CROPS)
    values.extend(float(tile_map.get("animal") == item) for item in ANIMALS)
    values.extend(
        (
            _number(tile_map.get("yield_units")) / 100.0,
            float(bool(tile_map.get("watered_today"))),
            float(bool(tile_map.get("fed_today"))),
            float(bool(tile_map.get("cared_today"))),
            float(_number(tile_map.get("fertilized_until_day"), -1) >= _number(observation.get("day"))),
        )
    )
    placed_day = tile_map.get("planted_day", tile_map.get("placed_day", observation.get("day", 0)))
    deadline = _number(tile_map.get("max_lifespan_step"), canonical_step(observation))
    values.extend(
        (
            max(0.0, _number(observation.get("day")) - _number(placed_day)) / 30.0,
            max(0.0, deadline - canonical_step(observation)) / 720.0,
            _number(tile_map.get("consecutive_unwatered")) / 3.0,
            _number(tile_map.get("consecutive_unfed")) / 3.0,
            _number(tile_map.get("pending_care_bonus")) / 10.0,
            float(bool(tile_map.get("fertilizer_available"))),
            math.log1p(sum(max(0.0, _number(value)) for value in inventory.values())) / 6.0,
            (abs(x - 4.5) + abs(y - 4.5)) / 9.0,
        )
    )
    array = np.asarray(base + values, dtype=np.float32)
    if array.size != len(actor_feature_names()):
        raise ValueError(f"actor feature mismatch: {array.size} != {len(actor_feature_names())}")
    return array


@cache
def bc_actor_feature_names() -> tuple[str, ...]:
    return actor_feature_names() + tuple(f"actor:previous:{token}" for token in ACTOR_TOKENS)


def bc_actor_features(
    observation: Mapping[str, Any],
    actor_index: int,
    previous_token: str,
    history: MarketHistory | None = None,
) -> np.ndarray:
    values = actor_features(observation, actor_index, history).tolist()
    values.extend(float(previous_token == token) for token in ACTOR_TOKENS)
    return np.asarray(values, dtype=np.float32)


@cache
def market_feature_names() -> tuple[str, ...]:
    return state_feature_names() + ("market:slot",) + tuple(f"market:previous:{token}" for token in MARKET_TOKENS)


def market_features(
    observation: Mapping[str, Any], slot: int, previous_token: str, history: MarketHistory | None = None
) -> np.ndarray:
    values = state_features(observation, history).tolist()
    values.append(slot / 9.0)
    values.extend(float(previous_token == token) for token in MARKET_TOKENS)
    return np.asarray(values, dtype=np.float32)


class SavedMLP:
    """Small ReLU encoder and linear head stored without pickle."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(f"required learned model is missing: {self.path}")
        if self.path.suffix == ".npz":
            if np is None:
                raise ImportError("NumPy is required to load an .npz model")
            with np.load(self.path, allow_pickle=False) as data:
                self.mean = data["mean"].astype(np.float32)
                self.scale = data["scale"].astype(np.float32)
                self.w1 = data["w1"].astype(np.float32)
                self.b1 = data["b1"].astype(np.float32)
                self.w2 = data["w2"].astype(np.float32)
                self.b2 = data["b2"].astype(np.float32)
                self.classes = [str(value) for value in data["classes"]] if "classes" in data else []
        else:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self.mean = payload["mean"]
            self.scale = payload["scale"]
            self.w1 = payload["w1"]
            self.b1 = payload["b1"]
            self.w2 = payload["w2"]
            self.b2 = payload["b2"]
            self.classes = [str(value) for value in payload.get("classes", [])]
        self.metadata_path = self.path.with_suffix(".json") if self.path.suffix == ".npz" else None
        self.metadata = (
            json.loads(self.metadata_path.read_text(encoding="utf-8")) if self.metadata_path.is_file() else {}
        ) if self.metadata_path is not None else {}

    def logits(self, features: np.ndarray) -> np.ndarray:
        if np is not None and hasattr(self.mean, "shape"):
            x = (np.asarray(features, dtype=np.float32) - self.mean) / self.scale
            hidden = np.maximum(0.0, x @ self.w1 + self.b1)
            return hidden @ self.w2 + self.b2
        values = [
            (float(value) - float(mean)) / float(scale)
            for value, mean, scale in zip(features, self.mean, self.scale, strict=True)
        ]
        hidden = [
            max(
                0.0,
                float(bias)
                + sum(value * float(row[column]) for value, row in zip(values, self.w1, strict=True)),
            )
            for column, bias in enumerate(self.b1)
        ]
        return [
            float(bias)
            + sum(value * float(row[column]) for value, row in zip(hidden, self.w2, strict=True))
            for column, bias in enumerate(self.b2)
        ]

    def probabilities(self, features: np.ndarray) -> np.ndarray:
        logits = self.logits(features)
        if np is not None and hasattr(logits, "shape"):
            logits -= np.max(logits)
            exp = np.exp(np.clip(logits, -30.0, 30.0))
            return exp / max(float(exp.sum()), 1e-9)
        maximum = max(logits)
        exp = [math.exp(min(30.0, max(-30.0, value - maximum))) for value in logits]
        total = max(sum(exp), 1e-9)
        return [value / total for value in exp]


def action_token(action: Any) -> str:
    values = list(action) if isinstance(action, list | tuple) else ["PASS"]
    if not values:
        return "PASS"
    op = str(values[0])
    if op in {"PLANT", "PICKUP", "PLACE"} and len(values) >= 2:
        return f"{op}:{values[1]}"
    return op if op in SIMPLE_FIELD_OPS else "PASS"


def market_token(order: Any) -> str:
    values = list(order) if isinstance(order, list | tuple) else []
    if not values:
        return "EOS"
    op = str(values[0])
    if op in {"HIRE", "BUY_LAND"}:
        return op
    if len(values) >= 2:
        return f"{op}:{values[1]}"
    return "EOS"


def token_action(token: str, quantity: int = 1) -> list[Any]:
    if ":" not in token:
        return [token]
    op, item = token.split(":", 1)
    return [op, item, max(1, int(quantity))] if op in {"PICKUP", "PLACE"} else [op, item]


def token_order(token: str, quantity: int = 1) -> list[Any]:
    if token in {"HIRE", "BUY_LAND"}:
        return [token]
    op, item = token.split(":", 1)
    return [op, item, max(1, int(quantity))]


def actor_context(
    observation: Mapping[str, Any], actor_index: int
) -> tuple[Mapping[str, Any], tuple[int, int], Mapping[str, Any], Any]:
    seat = int(_number(observation.get("player")))
    farms = _seq(observation.get("farms"))
    farm = _map(farms[seat]) if seat < len(farms) else {}
    positions = [_seq(farm.get("farmer")), *_seq(farm.get("hands"))]
    pos = _seq(positions[actor_index]) if actor_index < len(positions) else (0, 0)
    x, y = (int(_number(pos[0])), int(_number(pos[1]))) if len(pos) >= 2 else (0, 0)
    inventories = _seq(_map(observation.get("private")).get("inventories"))
    inventory = _map(inventories[actor_index]) if actor_index < len(inventories) else {}
    rows = _seq(farm.get("tiles"))
    row = _seq(rows[y]) if 0 <= y < len(rows) else ()
    tile = row[x] if 0 <= x < len(row) else "LOCKED"
    return farm, (x, y), inventory, tile


def shed_access(position: tuple[int, int]) -> bool:
    return position in {(4, 4), (5, 4), (4, 5), (5, 5)}


def legal_actor_tokens(
    observation: Mapping[str, Any], actor_index: int, reserved: Mapping[str, int] | None = None
) -> set[str]:
    farm, (x, y), inventory, tile = actor_context(observation, actor_index)
    private = _map(observation.get("private"))
    shed = _map(private.get("shed"))
    seeds = _map(private.get("seeds"))
    reserved = reserved or {}
    legal = {"PASS"}
    if y > 0:
        legal.add("NORTH")
    if y < 9:
        legal.add("SOUTH")
    if x > 0:
        legal.add("WEST")
    if x < 9:
        legal.add("EAST")
    tile_map = _map(tile)
    kind = tile_map.get("kind")
    if tile is None:
        for crop in CROPS:
            if _number(seeds.get(crop)) - _number(reserved.get(f"seed:{crop}")) > 0:
                legal.add(f"PLANT:{crop}")
        legal.update(("BUILD_COOP", "BUILD_PASTURE"))
    if kind in {"WEED", "PLANT", "COOP", "PASTURE"} and not tile_map.get("animal"):
        legal.add("DIG")
    if kind == "PLANT":
        if not tile_map.get("watered_today"):
            legal.add("WATER")
        if _number(tile_map.get("yield_units")) > 0:
            legal.add("HARVEST")
        if _number(inventory.get("FERTILIZER")) > 0:
            legal.add("FERTILIZE")
    if kind in {"COOP", "PASTURE"}:
        if tile_map.get("animal"):
            if not tile_map.get("fed_today") and _number(inventory.get("WHEAT")) > 0:
                legal.add("FEED")
            if tile_map.get("fed_today") and not tile_map.get("cared_today"):
                legal.add("CARE")
            if tile_map.get("fertilizer_available"):
                legal.add("COLLECT_FERTILIZER")
        else:
            compatible = ("GOOSE",) if kind == "COOP" else ("COW", "SHEEP")
            legal.update(f"PLACE:{animal}" for animal in compatible if _number(inventory.get(animal)) > 0)
    if shed_access((x, y)):
        for item in ITEMS:
            available = _number(shed.get(item)) - _number(reserved.get(f"shed:{item}"))
            if available > 0:
                legal.add(f"PICKUP:{item}")
        withdrawn = sum(
            _number(value) for key, value in reserved.items() if key.startswith("shed:") and key != "shed:deposit"
        )
        occupied = sum(_number(value) for value in shed.values()) - withdrawn + _number(reserved.get("shed:deposit"))
        if occupied < 100 and sum(_number(value) for value in inventory.values()) > 0:
            legal.add("DROP")
            legal.update(f"PLACE:{item}" for item in ITEMS if _number(inventory.get(item)) > 0)
    return legal


def work_legal_ops(observation: Mapping[str, Any], actor_index: int) -> set[str]:
    return {
        token.split(":", 1)[0]
        for token in legal_actor_tokens(observation, actor_index)
        if token.split(":", 1)[0] in WORK_OPS
    }


def reserve_actor_token(reserved: dict[str, int], token: str, quantity: int = 1) -> None:
    if token.startswith("PLANT:"):
        reserved[f"seed:{token.split(':', 1)[1]}"] = reserved.get(f"seed:{token.split(':', 1)[1]}", 0) + 1
    elif token.startswith("PICKUP:"):
        key = f"shed:{token.split(':', 1)[1]}"
        reserved[key] = reserved.get(key, 0) + max(1, quantity)


def make_actor_probe(observation: Mapping[str, Any], actor_index: int, action: Sequence[Any]) -> dict[str, Any]:
    _farm, position, inventory, tile = actor_context(observation, actor_index)
    tile_map = _map(tile)
    return {
        "actor_index": actor_index,
        "action": list(action),
        "position": list(position),
        "inventory": {str(key): _number(value) for key, value in inventory.items()},
        "tile": dict(tile_map) if tile_map else tile,
    }


def actor_probe_succeeded(observation: Mapping[str, Any], probe: Mapping[str, Any]) -> bool:
    actor_index = int(_number(probe.get("actor_index")))
    action = list(_seq(probe.get("action")))
    if not action or action[0] == "PASS":
        return False
    _farm, position, inventory, tile = actor_context(observation, actor_index)
    before_position = tuple(int(_number(value)) for value in _seq(probe.get("position"))[:2])
    before_inventory = _map(probe.get("inventory"))
    before_tile = _map(probe.get("tile"))
    after_tile = _map(tile)
    op = str(action[0])
    if op in MOVE_OPS:
        return position != before_position
    if op == "PICKUP" and len(action) >= 2:
        return _number(inventory.get(str(action[1]))) > _number(before_inventory.get(str(action[1])))
    if op in {"PLACE", "DROP"}:
        return sum(_number(value) for value in inventory.values()) < sum(
            _number(value) for value in before_inventory.values()
        )
    if op == "PLANT":
        return after_tile.get("kind") == "PLANT" and after_tile.get("crop") == (action[1] if len(action) > 1 else None)
    if op == "BUILD_COOP":
        return after_tile.get("kind") == "COOP"
    if op == "BUILD_PASTURE":
        return after_tile.get("kind") == "PASTURE"
    if op == "WATER":
        return bool(after_tile.get("watered_today"))
    if op == "FEED":
        return bool(after_tile.get("fed_today"))
    if op == "CARE":
        return bool(after_tile.get("cared_today"))
    if op == "FERTILIZE":
        return _number(after_tile.get("fertilized_until_day"), -1) > _number(
            before_tile.get("fertilized_until_day"), -1
        )
    if op == "COLLECT_FERTILIZER":
        return _number(inventory.get("FERTILIZER")) > _number(before_inventory.get("FERTILIZER"))
    if op == "HARVEST":
        return sum(_number(value) for value in inventory.values()) > sum(
            _number(value) for value in before_inventory.values()
        ) or _number(after_tile.get("yield_units")) < _number(before_tile.get("yield_units"))
    if op == "DIG":
        return tile != probe.get("tile")
    return False


def safe_action_shape(action: Mapping[str, Any], hand_count: int) -> dict[str, Any]:
    farmer = list(action.get("farmer") or ["PASS"])
    hands = [list(value or ["PASS"]) for value in _seq(action.get("hands"))]
    hands = (hands + [["PASS"]] * hand_count)[:hand_count]
    market = [list(value) for value in _seq(action.get("market")) if isinstance(value, list | tuple)][:10]
    return {"farmer": farmer, "hands": hands, "market": market}
