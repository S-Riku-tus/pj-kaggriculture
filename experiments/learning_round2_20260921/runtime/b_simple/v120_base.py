"""v120: public-live-replay case policy, re-routed from current state each turn.

The model contains only same-turn observation features and actions from public
competition replays. Runtime selection never uses episode/submission identity,
ratings, rewards, outcomes, or future observations.
"""

from __future__ import annotations

import gzip
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ITEMS = tuple("WHEAT CARROT TOMATO STRAWBERRY MELON EGG MILK WOOL FERTILIZER GOOSE COW SHEEP".split())
CROPS = ITEMS[:5]
PRODUCTS = ITEMS[:9]
ANIMALS = ITEMS[9:]
SHOP_NAMES = tuple(
    "BAKERY BRUNCH_SPOT FARMERS_MARKET ICE_CREAM_SHOP PET_CAFE PIZZA_SHOP SMOOTHIE_SHOP YARN_STORE".split()
)
SHOP_DEMAND = ((0, 5), (0, 3, 5), (0, 1, 2, 3), (0, 3, 6), (1, 1), (0, 2, 6), (3, 6), (7, 7))
MAX_UNITS = 24
FEATURE_LENGTH = 558

_MODEL: dict[str, Any] | None = None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clip(value: Any, low: int, high: int) -> int:
    return max(low, min(high, _integer(value)))


def _board(farm: Mapping[str, Any]) -> list[Any]:
    board: list[Any] = []
    for row in farm.get("tiles") or []:
        board.extend(list(row or []))
    return (board[:100] + ["LOCKED"] * 100)[:100]


def _tile_code(tile: Any) -> int:
    if tile == "LOCKED":
        return 0
    if tile is None:
        return 1
    data = _mapping(tile)
    if data.get("kind") == "WEED":
        return 2
    crop = str(data.get("crop", ""))
    if crop in CROPS:
        return 3 + CROPS.index(crop)
    animal = str(data.get("animal", ""))
    if animal in ANIMALS:
        return 10 + ANIMALS.index(animal)
    if data.get("kind") == "COOP":
        return 8
    if data.get("kind") == "PASTURE":
        return 9
    return 13


def _tile_yield(tile: Any) -> int:
    return _clip(_mapping(tile).get("yield_units", 0), 0, 300)


def _tile_flags(tile: Any, day: int) -> int:
    data = _mapping(tile)
    flags = int(bool(data.get("watered_today")))
    flags |= int(_integer(data.get("fertilized_until_day", -1), -1) >= day) << 1
    flags |= int(bool(data.get("fed_today"))) << 2
    flags |= int(bool(data.get("cared_today"))) << 3
    flags |= int(bool(data.get("fertilizer_available"))) << 4
    return flags


def _farm_summary(farm: Mapping[str, Any]) -> list[int]:
    counts = {item: 0 for item in (*CROPS, *ANIMALS)}
    yields = {item: 0 for item in PRODUCTS}
    weeds = 0
    empty = 0
    for tile in _board(farm):
        if tile is None:
            empty += 1
            continue
        data = _mapping(tile)
        if data.get("kind") == "WEED":
            weeds += 1
        crop = str(data.get("crop", ""))
        animal = str(data.get("animal", ""))
        if crop in counts:
            counts[crop] += 1
            yields[crop] += _tile_yield(tile)
        if animal in counts:
            counts[animal] += 1
            product = {"GOOSE": "EGG", "COW": "MILK", "SHEEP": "WOOL"}[animal]
            yields[product] += _tile_yield(tile)
    return [
        _clip(len(farm.get("unlocked_quadrants") or []), 0, 4),
        _clip(len(farm.get("hands") or []), 0, MAX_UNITS - 1),
        _clip(farm.get("hires_today", 0), 0, 100),
        *(_clip(counts[item], 0, 100) for item in (*CROPS, *ANIMALS)),
        *(_clip(yields[item], 0, 500) for item in PRODUCTS),
        _clip(weeds, 0, 100),
        _clip(empty, 0, 100),
    ]


def _position_code(position: Any) -> int:
    value = list(position or [-1, -1])
    if len(value) < 2:
        return 0
    x = _integer(value[0], -1)
    y = _integer(value[1], -1)
    return 1 + y * 10 + x if 0 <= x < 10 and 0 <= y < 10 else 0


def feature_vector(observation: Mapping[str, Any]) -> list[int]:
    """Build the fixed-width vector using information available at this turn."""
    player = _integer(observation.get("player", 0))
    farms = list(observation.get("farms") or [])
    own = _mapping(farms[player]) if 0 <= player < len(farms) else {}
    rival_index = 1 - player
    rival = _mapping(farms[rival_index]) if 0 <= rival_index < len(farms) else {}
    private = _mapping(observation.get("private"))
    market = _mapping(observation.get("market"))
    prices = _mapping(market.get("prices"))
    market_inventory = _mapping(market.get("inventory"))
    own_board = _board(own)
    rival_board = _board(rival)
    day = _integer(observation.get("day", _integer(observation.get("step", 0)) // 24))

    own_money = _integer(own.get("money", 0))
    rival_money = _integer(rival.get("money", 0))
    vector: list[int] = [own_money // 100, rival_money // 100, (own_money - rival_money) // 100]
    vector.extend(_clip(prices.get(item, 0), 0, 1_000) for item in PRODUCTS)
    vector.extend((_clip(market_inventory.get(item, 10_000), 0, 30_000) - 10_000) // 50 for item in PRODUCTS)

    unlocked_shops = list(_mapping(observation.get("town")).get("unlocked_shops") or [])
    shop_counts = [unlocked_shops.count(name) for name in SHOP_NAMES]
    vector.extend(shop_counts)
    demand = [0] * len(PRODUCTS)
    for count, products in zip(shop_counts, SHOP_DEMAND, strict=False):
        for product_index in products:
            demand[product_index] += count
    vector.extend(demand[:8])
    vector.extend(_farm_summary(own))
    vector.extend(_farm_summary(rival))

    shed = _mapping(private.get("shed"))
    seeds = _mapping(private.get("seeds"))
    inventories = list(private.get("inventories") or [])
    carried = {item: 0 for item in ITEMS}
    for inventory in inventories:
        for item, amount in _mapping(inventory).items():
            if item in carried:
                carried[item] += _integer(amount)
    vector.extend(_clip(shed.get(item, 0), 0, 1_000) for item in ITEMS)
    vector.extend(_clip(seeds.get(item, 0), 0, 1_000) for item in CROPS)
    vector.extend(_clip(carried[item], 0, 1_000) for item in ITEMS)

    units = [own.get("farmer")]
    units.extend(list(own.get("hands") or []))
    padded_units = units[:MAX_UNITS] + [None] * max(0, MAX_UNITS - len(units))
    vector.extend(_position_code(position) for position in padded_units)
    vector.extend(_tile_code(own_board[code - 1]) if code else 0 for code in map(_position_code, padded_units))
    vector.extend(_tile_code(tile) for tile in own_board)
    vector.extend(_tile_yield(tile) for tile in own_board)
    vector.extend(_tile_flags(tile, day) for tile in own_board)
    vector.extend(_tile_code(tile) for tile in rival_board)
    if len(vector) != FEATURE_LENGTH:
        raise RuntimeError(f"v120 feature width changed: {len(vector)} != {FEATURE_LENGTH}")
    return vector


def unit_count(observation: Mapping[str, Any]) -> int:
    player = _integer(observation.get("player", 0))
    farms = list(observation.get("farms") or [])
    farm = _mapping(farms[player]) if 0 <= player < len(farms) else {}
    return 1 + len(farm.get("hands") or [])


def feature_distance(query: Sequence[int], candidate: Sequence[int]) -> int:
    """Weighted distance emphasizing unit geometry and executable own state."""
    distance = 4 * sum(abs(query[i] - candidate[i]) for i in range(0, 3))
    distance += sum(abs(query[i] - candidate[i]) for i in range(3, 21))
    distance += 50 * sum(abs(query[i] - candidate[i]) for i in range(21, 37))
    distance += 15 * sum(abs(query[i] - candidate[i]) for i in range(37, 81))
    distance += 20 * sum(abs(query[i] - candidate[i]) for i in range(81, 110))
    for i in range(110, 134):
        left, right = query[i], candidate[i]
        if left == right:
            continue
        if left == 0 or right == 0:
            distance += 300
        else:
            distance += 20 * (abs((left - 1) % 10 - (right - 1) % 10) + abs((left - 1) // 10 - (right - 1) // 10))
    distance += 100 * sum(query[i] != candidate[i] for i in range(134, 158))
    distance += 20 * sum(query[i] != candidate[i] for i in range(158, 258))
    distance += 2 * sum(abs(query[i] - candidate[i]) for i in range(258, 358))
    distance += 5 * sum(query[i] != candidate[i] for i in range(358, 458))
    distance += 4 * sum(query[i] != candidate[i] for i in range(458, 558))
    return distance


def _model_paths() -> list[Path]:
    paths: list[Path] = []
    if "__file__" in globals():
        paths.append(Path(__file__).resolve().with_name("model.json.gz"))
    paths.extend(Path(entry) / "model.json.gz" for entry in reversed(sys.path) if entry)
    paths.extend((Path("agents/v120/model.json.gz"), Path("/kaggle_simulations/agent/model.json.gz")))
    return paths


def _load_model() -> dict[str, Any]:
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    for path in _model_paths():
        if path.is_file():
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                model = json.load(stream)
            if _integer(model.get("feature_length")) != FEATURE_LENGTH:
                raise RuntimeError("v120 model feature schema mismatch")
            _MODEL = model
            return model
    raise FileNotFoundError("v120 model.json.gz was not found")


def _normalize_output(proposed: Any, observation: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(proposed)
    count = unit_count(observation) - 1
    farmer = list(raw.get("farmer") or ["PASS"])
    hands = [list(action or ["PASS"]) for action in (raw.get("hands") or [])]
    hands = (hands + [["PASS"]] * count)[:count]
    market = [list(order) for order in (raw.get("market") or []) if isinstance(order, list | tuple)]
    return {"farmer": farmer, "hands": hands, "market": market[:10]}


def agent(observation: Mapping[str, Any], configuration: Any = None) -> dict[str, Any]:
    del configuration
    try:
        step = _integer(observation.get("step", 0))
        steps = _load_model().get("steps") or []
        candidates = list(steps[step] or []) if 0 <= step < len(steps) else []
        if not candidates:
            return _normalize_output({}, observation)
        query = feature_vector(observation)
        count = unit_count(observation)
        compatible = [row for row in candidates if _integer(row[0]) == count]
        chosen = min(compatible or candidates, key=lambda row: feature_distance(query, row[1]))
        return _normalize_output(chosen[2], observation)
    except Exception:
        return _normalize_output({}, observation)
