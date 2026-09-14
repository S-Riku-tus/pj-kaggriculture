"""Kaggriculture V9: expert decision intent on V8's safe executor.

V9 keeps V8's Top-3 trajectory atlas, opening, feasibility checks, and
liquidation.  A Rank-1 decision model controls only held-out-validated macro
decisions: near-term BUY/WAIT intent, land timing, and SELL/WAIT with batch
size.  Top-3 manifold distance and forest disagreement gate every learned
override.  Unknown states therefore return continuously to V8/V7 rather than
forcing an expert action.

Field execution stays deterministic.  A stateless mission scheduler pins a
worker already standing on an animal-service cluster to the next feasible
HARVEST/FEED/CARE/COLLECT step when emergencies leave enough workers.  This
preserves safety while reducing the observed FEED-to-move route break.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

if "__file__" in globals():
    MODULE_DIR = Path(__file__).resolve().parent
else:
    _runtime_candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd() / "agents" / "v9",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (
                (candidate / "v8_base.py").is_file()
                and (candidate / "v7_base.py").is_file()
                and (candidate / "v6_base.py").is_file()
                and (candidate / "v5_base.py").is_file()
                and (candidate / "v4_base.py").is_file()
                and (candidate / "v3_base.py").is_file()
                and (candidate / "v2_base.py").is_file()
                and (candidate / "feature_schema.py").is_file()
                and (candidate / "strategy_model.json").is_file()
            )
            or (
                (candidate / "main.py").is_file()
                and (candidate.parent / "v8" / "main.py").is_file()
            )
        ),
        Path.cwd(),
    )


def _load_v8_module():
    packaged = MODULE_DIR / "v8_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v8" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v9_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V8 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v8 = _load_v8_module()
v7 = v8.v7
v6 = v8.v6
v5 = v8.v5
v4 = v8.v4
v3 = v8.v3
base = v8.base
MODEL = v8.MODEL
POLICY_MODEL = v8.POLICY_MODEL
EXPERT_OPENING = v8.EXPERT_OPENING
OPENING_ACTIONS = v8.OPENING_ACTIONS

CROPS = v8.CROPS
ANIMALS = v8.ANIMALS
MARKET_ITEMS = ("WHEAT", "STRAWBERRY", "MELON", "MILK", "WOOL", "FERTILIZER")
INTENT_NAMES = (
    "BUY_COW_12",
    "BUY_SHEEP_12",
    "WAIT_ANIMAL_12",
    "BUY_LAND_24",
    "BUILD_PASTURE_12",
    "PLANT_STRAWBERRY_12",
    "PLANT_WHEAT_12",
    "COW_QTY_12",
    "SHEEP_QTY_12",
    "STRAWBERRY_QTY_12",
    "WHEAT_QTY_12",
)
BINARY_INTENTS = INTENT_NAMES[:7]
DECISION_FORMAT = "kaggriculture-v9-decision-policy-v1"
BASE_PRICES = base.BASE_PRICE

# Explicit component switches make the causal validation in
# ``scripts/run_v9_ablation.py`` reproducible.  Submission defaults keep all
# validated V9 components enabled.
ENABLE_DECISION_POLICY = True
ENABLE_MARKET_POLICY = True
ENABLE_MISSION_CONTINUITY = False
# ``None`` means all validation-selected controls.  A named subset is useful
# both for conservative deployment and reproducible component attribution.
ACTIVE_INTENT_CONTROLS: frozenset[str] | None = frozenset(
    {
        "WAIT_ANIMAL_12",
        "BUY_LAND_24",
        "BUILD_PASTURE_12",
        "PLANT_STRAWBERRY_12",
        "PLANT_WHEAT_12",
    }
)
_MISSION_LAST_STEP = -1
_MISSION_PREVIOUS_ACTIONS: list[list[Any]] = []

INTENT_EXTRA_FEATURE_NAMES = (
    "known_shop_fraction",
    "unknown_shop_fraction",
    "days_to_next_shop",
    "milk_minus_wool_demand",
    "milk_minus_wool_price",
    "animal_structure_room",
    "animal_slot_room",
    "opponent_animal_advantage",
    "milk_market_displacement",
    "wool_market_displacement",
    "shed_pressure",
    "recovery_pressure",
    "land_slack",
    "cash_after_feed",
    "opponent_milk_supply_belief",
    "opponent_wool_supply_belief",
)
INTENT_FEATURE_NAMES = (*v8.POLICY_FEATURE_NAMES, *INTENT_EXTRA_FEATURE_NAMES)
MARKET_EXTRA_FEATURE_NAMES = (
    *(f"item_{item}" for item in MARKET_ITEMS),
    "item_stock",
    "item_price_ratio",
    "item_market_displacement",
    "item_own_capacity",
    "item_opponent_capacity",
    "item_town_demand",
    "item_opponent_hidden_supply",
    "town_consumption_now",
    "town_consumption_just_happened",
    "turns_to_town_consumption",
    "liquidation_progress",
)
MARKET_FEATURE_NAMES = (*INTENT_FEATURE_NAMES, *MARKET_EXTRA_FEATURE_NAMES)

ITEM_SOURCE = {
    "WHEAT": ("crop", "WHEAT"),
    "STRAWBERRY": ("crop", "STRAWBERRY"),
    "MELON": ("crop", "MELON"),
    "MILK": ("animal", "COW"),
    "WOOL": ("animal", "SHEEP"),
    "FERTILIZER": ("animal", "ALL"),
}


def _load_decision_model() -> dict[str, Any] | None:
    try:
        payload = json.loads((MODULE_DIR / "decision_policy_model.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if payload.get("format") != DECISION_FORMAT:
        return None
    if tuple(payload.get("intent_feature_names", ())) != INTENT_FEATURE_NAMES:
        return None
    if tuple(payload.get("market_feature_names", ())) != MARKET_FEATURE_NAMES:
        return None
    if tuple(payload.get("intent_names", ())) != INTENT_NAMES:
        return None
    forests = payload.get("forests", {}) or {}
    if not forests.get("intent") or not forests.get("market"):
        return None
    return payload


DECISION_MODEL = _load_decision_model()


def _demand(obs: Any) -> dict[str, int]:
    return dict(base._demand_profile(obs))


def _item_capacity(summary: dict[str, Any], item: str) -> int:
    source_type, source = ITEM_SOURCE[item]
    if source_type == "crop":
        return int(summary["crops"].get(source, 0))
    if source == "ALL":
        return int(summary["animal_total"])
    return int(summary["animals"].get(source, 0))


def _opponent_hidden_supply_belief(farm: Any, item: str, day: int) -> float:
    """Stateless upper-pressure proxy from public production ages and tile stock."""
    source_type, source = ITEM_SOURCE[item]
    pressure = 0.0
    for _x, _y, tile in base._iter_tiles(farm):
        if source_type == "animal":
            animal = base._get(tile, "animal")
            if source != "ALL" and animal != source:
                continue
            if source == "ALL" and animal not in base.ANIMAL_DATA:
                continue
            if animal not in base.ANIMAL_DATA:
                continue
            data = base.ANIMAL_DATA[animal]
            age = max(0, day - base._as_int(base._get(tile, "placed_day", day)))
            cycles = 0 if age < data["first"] else 1 + (age - data["first"]) // data["interval"]
            visible = base._as_int(base._get(tile, "yield_units", 0))
            pressure += max(0.0, cycles - visible) + 0.25 * visible
        else:
            if base._tile_kind(tile) != "PLANT" or base._get(tile, "crop") != source:
                continue
            age = max(0, day - base._as_int(base._get(tile, "planted_day", day)))
            data = base.CROP_DATA[source]
            if data["ongoing"]:
                cycles = 0 if age < data["first"] else 1 + (age - data["first"]) // data["interval"]
            else:
                cycles = float(age >= data["first"])
            pressure += max(0.0, cycles - base._as_int(base._get(tile, "yield_units", 0)))
    return min(4.0, pressure / 24.0)


def _intent_features(obs: Any, farm: Any, opponent_farm: Any, private: Any) -> list[float]:
    values = list(v8._policy_features(obs, farm, opponent_farm, private))
    day = base._as_int(base._get(obs, "day", 0))
    summary = base._farm_summary(farm)
    opponent = base._farm_summary(opponent_farm)
    demand = _demand(obs)
    market = base._get(obs, "market", {}) or {}
    inventory = base._get(market, "inventory", {}) or {}
    prices = base._get(market, "prices", {}) or {}
    shops = list(base._get(base._get(obs, "town", {}) or {}, "unlocked_shops", []) or [])
    known = min(8, len(shops))
    next_unlock = 3 - (day % 3) if day < 24 else 30
    pasture_count = v8._pasture_count(farm)
    owned_total = sum(v4._owned_animals(farm, private, animal) for animal in ANIMALS)
    shed = base._get(private, "shed", {}) or {}
    inventories = base._get(private, "inventories", []) or []
    shed_total = base._inventory_total(shed)
    detailed = v3.schema.farm_summary(farm, day)
    recovery = detailed["unfed"] * 2 + detailed["unwatered"] + summary["weeds"]
    wheat = base._all_inventory_count(private, "WHEAT")
    feed_cost = max(0, summary["animal_total"] * 2 - wheat) * max(
        1, base._as_int(base._get(prices, "WHEAT", BASE_PRICES["WHEAT"]))
    )
    money = max(0.0, float(base._get(farm, "money", 0) or 0))
    milk_demand = int(demand.get("MILK", 0))
    wool_demand = int(demand.get("WOOL", 0))
    values.extend(
        (
            known / 8.0,
            (8 - known) / 8.0,
            min(1.0, next_unlock / 6.0),
            max(-1.0, min(1.0, (milk_demand - wool_demand) / 6.0)),
            max(
                -2.0,
                min(
                    2.0,
                    float(base._get(prices, "MILK", BASE_PRICES["MILK"])) / BASE_PRICES["MILK"]
                    - float(base._get(prices, "WOOL", BASE_PRICES["WOOL"])) / BASE_PRICES["WOOL"],
                ),
            ),
            min(1.5, max(0, pasture_count - owned_total) / 8.0),
            min(1.5, max(0, 16 - owned_total) / 16.0),
            max(-1.0, min(1.0, (opponent["animal_total"] - summary["animal_total"]) / 16.0)),
            max(-2.0, min(2.0, (base._as_int(base._get(inventory, "MILK", 10000)) - 10000) / 150.0)),
            max(-2.0, min(2.0, (base._as_int(base._get(inventory, "WOOL", 10000)) - 10000) / 150.0)),
            min(2.0, (shed_total + sum(base._inventory_total(inv) for inv in inventories)) / 100.0),
            min(2.0, recovery / 30.0),
            min(1.5, max(0, summary["capacity"] - summary["productive"]) / 75.0),
            max(-1.0, min(20.0, (money - feed_cost) / 1000.0)),
            _opponent_hidden_supply_belief(opponent_farm, "MILK", day),
            _opponent_hidden_supply_belief(opponent_farm, "WOOL", day),
        )
    )
    if len(values) != len(INTENT_FEATURE_NAMES):
        raise RuntimeError(f"V9 intent feature mismatch: {len(values)} != {len(INTENT_FEATURE_NAMES)}")
    return values


def _market_features(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
    item: str,
    intent_prefix: list[float] | None = None,
) -> list[float]:
    values = list(intent_prefix) if intent_prefix is not None else _intent_features(obs, farm, opponent_farm, private)
    day = base._as_int(base._get(obs, "day", 0))
    hour = base._as_int(base._get(obs, "hour", 0))
    summary = base._farm_summary(farm)
    opponent = base._farm_summary(opponent_farm)
    market = base._get(obs, "market", {}) or {}
    prices = base._get(market, "prices", {}) or {}
    inventory = base._get(market, "inventory", {}) or {}
    shed = base._get(private, "shed", {}) or {}
    demand = _demand(obs)
    phase = hour % 4
    values.extend(float(item == candidate) for candidate in MARKET_ITEMS)
    values.extend(
        (
            min(2.0, base._inventory_count(shed, item) / 50.0),
            min(4.0, max(0.0, float(base._get(prices, item, BASE_PRICES[item])) / BASE_PRICES[item])),
            max(-3.0, min(3.0, (base._as_int(base._get(inventory, item, 10000)) - 10000) / 250.0)),
            min(2.0, _item_capacity(summary, item) / 32.0),
            min(2.0, _item_capacity(opponent, item) / 32.0),
            min(2.0, int(demand.get(item, 0)) / 8.0),
            _opponent_hidden_supply_belief(opponent_farm, item, day),
            float(phase == 0),
            float(phase == 1),
            (4 - phase) % 4 / 3.0,
            max(0.0, min(1.0, (day - 24) / 5.0)),
        )
    )
    if len(values) != len(MARKET_FEATURE_NAMES):
        raise RuntimeError(f"V9 market feature mismatch: {len(values)} != {len(MARKET_FEATURE_NAMES)}")
    return values


def _predict_tree(tree: list[Any], features: list[float]) -> list[float]:
    node = tree
    while node[0] == "N":
        node = node[3] if features[int(node[1])] <= float(node[2]) else node[4]
    return [float(value) for value in node[1:]]


def _predict_forest(forest: list[list[Any]], features: list[float], outputs: int) -> tuple[list[float], list[float]]:
    rows = [_predict_tree(tree, features) for tree in forest]
    if not rows:
        return [0.0] * outputs, [math.inf] * outputs
    means = [sum(row[index] for row in rows) / len(rows) for index in range(outputs)]
    deviations = [
        math.sqrt(sum((row[index] - means[index]) ** 2 for row in rows) / len(rows))
        for index in range(outputs)
    ]
    return means, deviations


def _model_confidence(features: list[float], deviations: list[float], kind: str) -> float:
    if DECISION_MODEL is None:
        return 0.0
    day = round(features[v8.POLICY_FEATURE_NAMES.index("day")] * 29)
    hour_block = round(features[v8.POLICY_FEATURE_NAMES.index("hour_block")] * 3)
    manifold, _distance = v8._distance_confidence(features, day, hour_block * 6)
    scales = DECISION_MODEL.get("output_scales", {}).get(kind, [1.0] * len(deviations))
    normalized = [
        min(4.0, deviation / max(0.05, float(scale)))
        for deviation, scale in zip(deviations, scales, strict=True)
    ]
    uncertainty = sum(normalized) / max(1, len(normalized))
    reference = max(0.05, float(DECISION_MODEL.get("uncertainty_p90", {}).get(kind, 1.0)))
    agreement = min(1.0, max(0.0, 1.15 - 0.55 * uncertainty / reference))
    return manifold * agreement


def _intent_prediction(obs: Any, farm: Any, opponent_farm: Any, private: Any) -> dict[str, Any] | None:
    if DECISION_MODEL is None:
        return None
    day = base._as_int(base._get(obs, "day", 0))
    if not 3 <= day <= 26:
        return None
    features = _intent_features(obs, farm, opponent_farm, private)
    means, deviations = _predict_forest(
        DECISION_MODEL["forests"]["intent"], features, len(INTENT_NAMES)
    )
    confidence = _model_confidence(features, deviations, "intent")
    return {
        "values": dict(zip(INTENT_NAMES, means, strict=True)),
        "deviations": dict(zip(INTENT_NAMES, deviations, strict=True)),
        "confidence": confidence,
    }


def _selected_intent(name: str) -> bool:
    if DECISION_MODEL is None:
        return False
    if ACTIVE_INTENT_CONTROLS is not None and name not in ACTIVE_INTENT_CONTROLS:
        return False
    return bool(DECISION_MODEL.get("selection", {}).get("intent", {}).get(name, False))


def _intent_threshold(name: str) -> float:
    if DECISION_MODEL is None:
        return 0.5
    return float(DECISION_MODEL.get("thresholds", {}).get("intent", {}).get(name, 0.5))


def _strategy_targets(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
) -> tuple[dict[str, int], dict[str, int], int, int, dict[str, float], int]:
    animals, crops, hands, land, weights, pastures = v8._strategy_targets(obs, farm, opponent_farm, private)
    if not ENABLE_DECISION_POLICY:
        return animals, crops, hands, land, weights, pastures
    prediction = _intent_prediction(obs, farm, opponent_farm, private)
    if prediction is None or prediction["confidence"] < 0.35:
        return animals, crops, hands, land, weights, pastures

    values = prediction["values"]
    confidence = float(prediction["confidence"])
    owned = {animal: v4._owned_animals(farm, private, animal) for animal in ANIMALS}
    current_total = sum(owned.values())

    wait_selected = _selected_intent("WAIT_ANIMAL_12")
    buy_signal = {
        animal: values[f"BUY_{animal}_12"] >= _intent_threshold(f"BUY_{animal}_12")
        for animal in ANIMALS
    }
    wait_signal = values["WAIT_ANIMAL_12"] >= _intent_threshold("WAIT_ANIMAL_12")
    # Cow and sheep purchases compete for the same irreversible pasture slots.
    # Apply the learned herd decision only when both held-out classifiers passed
    # selection; mixing one learned cap with one fallback target biases the mix.
    buy_pair_selected = all(_selected_intent(f"BUY_{animal}_12") for animal in ANIMALS)
    if buy_pair_selected:
        for animal in ANIMALS:
            quantity = max(0.0, values[f"{animal}_QTY_12"])
            if buy_signal[animal]:
                allowance = max(1, math.ceil(quantity - 0.10))
            else:
                allowance = 0 if confidence >= 0.58 else 1
            animals[animal] = max(owned[animal], min(animals[animal], owned[animal] + allowance))
    # Keep one irreversible slot only while future Town draws remain unknown
    # and the learned policy also recommends waiting.  This is deliberately a
    # soft portfolio cap, not an hourly freeze of all animal purchases.
    shops = len(base._get(base._get(obs, "town", {}) or {}, "unlocked_shops", []) or [])
    day = base._as_int(base._get(obs, "day", 0))
    if wait_selected and day < 18 and shops < 6 and wait_signal and confidence >= 0.55:
        optionality_cap = max(current_total, 15)
        while animals["COW"] + animals["SHEEP"] > optionality_cap:
            reducible = [animal for animal in ANIMALS if animals[animal] > owned[animal]]
            if not reducible:
                break
            animal = max(reducible, key=lambda name: animals[name] - owned[name])
            animals[animal] -= 1

    summary = base._farm_summary(farm)
    if _selected_intent("BUY_LAND_24") and confidence >= 0.50:
        if values["BUY_LAND_24"] < _intent_threshold("BUY_LAND_24"):
            land = summary["unlocked"]
        else:
            land = min(land, summary["unlocked"] + 1)

    crop_specs = (
        ("STRAWBERRY", "PLANT_STRAWBERRY_12", "STRAWBERRY_QTY_12"),
        ("WHEAT", "PLANT_WHEAT_12", "WHEAT_QTY_12"),
    )
    seeds = base._get(private, "seeds", {}) or {}
    for crop, binary_name, quantity_name in crop_specs:
        if not _selected_intent(binary_name) or confidence < 0.62:
            continue
        current = summary["crops"].get(crop, 0)
        committed = base._inventory_count(seeds, crop)
        if values[binary_name] < _intent_threshold(binary_name):
            crops[crop] = max(current, min(crops[crop], current + committed + 2))
        else:
            allowance = max(1, math.ceil(max(0.0, values[quantity_name]) - 0.10))
            crops[crop] = max(current, min(crops[crop], current + committed + allowance))

    if buy_pair_selected:
        feed_floor = math.ceil((animals["COW"] + animals["SHEEP"]) * 1.2)
        crops["WHEAT"] = max(crops["WHEAT"], feed_floor)
        pastures = max(v8._pasture_count(farm), animals["COW"] + animals["SHEEP"])
    return animals, crops, hands, land, weights, pastures


def _mission_assign(
    positions: list[tuple[int, int]],
    inventories: list[Any],
    tasks: list[dict[str, Any]],
    step: int = 0,
) -> list[list[Any]]:
    """Continue an observed animal-service chain, then assign other work.

    A same-tile task alone is not evidence of a continuing mission.  V9 only
    pins HARVEST->FEED->CARE->COLLECT_FERTILIZER when that exact preceding
    action was issued to the same stable worker index.
    """
    global _MISSION_LAST_STEP, _MISSION_PREVIOUS_ACTIONS
    if not ENABLE_MISSION_CONTINUITY:
        return v5._assign_tasks(positions, inventories, tasks)
    if step <= _MISSION_LAST_STEP or len(_MISSION_PREVIOUS_ACTIONS) != len(positions):
        _MISSION_PREVIOUS_ACTIONS = []
    actions: list[list[Any]] = [["PASS"] for _ in positions]
    if not positions:
        _MISSION_LAST_STEP = step
        _MISSION_PREVIOUS_ACTIONS = []
        return actions
    emergency_count = sum(int(task.get("priority", 0)) >= 15000 for task in tasks)
    pin_budget = max(0, len(positions) - emergency_count)
    if len(positions) >= 8 and _MISSION_PREVIOUS_ACTIONS:
        pin_budget = max(1, pin_budget)
    continuation = {
        "HARVEST": "FEED",
        "FEED": "CARE",
        "CARE": "COLLECT_FERTILIZER",
    }
    pinned_units: set[int] = set()
    pinned_tasks: set[int] = set()
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for unit, previous in enumerate(_MISSION_PREVIOUS_ACTIONS):
        previous_op = str(previous[0]) if previous else "PASS"
        expected = continuation.get(previous_op)
        if expected is None:
            continue
        for task_index, task in enumerate(tasks):
            action = task.get("action") or []
            if not action or str(action[0]) != expected or positions[unit] != task.get("pos"):
                continue
            if not base._can_do(task, unit, inventories[unit]):
                continue
            candidates.append((unit, task_index, task))
            break
    for unit, task_index, task in sorted(
        candidates,
        key=lambda candidate: -int(candidate[2].get("priority", 0)),
    )[:pin_budget]:
        actions[unit] = list(task["action"])
        pinned_units.add(unit)
        pinned_tasks.add(task_index)

    remaining_units = [index for index in range(len(positions)) if index not in pinned_units]
    if not remaining_units:
        _MISSION_LAST_STEP = step
        _MISSION_PREVIOUS_ACTIONS = [list(action) for action in actions]
        return actions
    remap = {original: compact for compact, original in enumerate(remaining_units)}
    remaining_tasks: list[dict[str, Any]] = []
    for task_index, original in enumerate(tasks):
        if task_index in pinned_tasks:
            continue
        task = dict(original)
        task["action"] = list(original["action"])
        unit = task.get("unit")
        if isinstance(unit, int):
            if unit not in remap:
                continue
            task["unit"] = remap[unit]
        remaining_tasks.append(task)
    compact_actions = v5._assign_tasks(
        [positions[index] for index in remaining_units],
        [inventories[index] for index in remaining_units],
        remaining_tasks,
    )
    for original, action in zip(remaining_units, compact_actions, strict=True):
        actions[original] = action
    _MISSION_LAST_STEP = step
    _MISSION_PREVIOUS_ACTIONS = [list(action) for action in actions]
    return actions


def _market_prediction(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
    item: str,
) -> tuple[float, float, float] | None:
    if DECISION_MODEL is None:
        return None
    features = _market_features(obs, farm, opponent_farm, private, item)
    means, deviations = _predict_forest(DECISION_MODEL["forests"]["market"], features, 2)
    return (
        min(1.0, max(0.0, means[0])),
        min(1.0, max(0.0, means[1])),
        _model_confidence(features, deviations, "market"),
    )


def _market_selected(item: str) -> bool:
    if DECISION_MODEL is None:
        return False
    # Rank 1 normally liquidates opening Melons before this model's Day-5
    # window; only four untouched-test stock states remained.  That is not
    # enough evidence to replace V8's safe rule.
    if item == "MELON":
        return False
    return bool(DECISION_MODEL.get("selection", {}).get("market", {}).get(item, False))


def _market_threshold(item: str) -> float:
    if DECISION_MODEL is None:
        return 0.5
    return float(DECISION_MODEL.get("thresholds", {}).get("market", {}).get(item, 0.5))


def _purchase_cost(orders: list[list[Any]], farm: Any, obs: Any) -> float:
    prices = base._get(base._get(obs, "market", {}) or {}, "prices", {}) or {}
    hires = base._as_int(base._get(farm, "hires_today", 0))
    unlocked = len(base._get(farm, "unlocked_quadrants", []) or [])
    total = 0.0
    for order in orders:
        if not order:
            continue
        verb = order[0]
        if verb == "BUY_PRODUCT":
            total += base._as_int(order[2]) * max(1, base._as_int(base._get(prices, order[1], 1)))
        elif verb == "BUY_SEED":
            total += base._as_int(order[2]) * int(base.CROP_DATA[order[1]]["seed"])
        elif verb == "BUY_ANIMAL":
            total += base._as_int(order[2]) * int(base.ANIMAL_DATA[order[1]]["cost"])
        elif verb == "HIRE":
            total += base._hire_cost(hires)
            hires += 1
        elif verb == "BUY_LAND":
            total += 1000 if unlocked == 1 else (2000 if unlocked == 2 else 4000)
            unlocked += 1
    return total


def _market_plan(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
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
    orders = v8._market_plan(
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
    day = base._as_int(base._get(obs, "day", 0))
    if not ENABLE_MARKET_POLICY or DECISION_MODEL is None or day < 5 or day >= 27:
        return orders[:10]

    shed = base._get(private, "shed", {}) or {}
    shed_total = base._inventory_total(shed)
    money = float(base._get(farm, "money", 0) or 0)
    financing_needed = _purchase_cost(orders, farm, obs) > max(0.0, money - 100.0)
    existing_sales = {order[1]: list(order) for order in orders if order and order[0] == "SELL"}
    non_sales = [order for order in orders if not order or order[0] != "SELL"]
    learned_sales: list[list[Any]] = []

    for item in MARKET_ITEMS:
        stock = base._inventory_count(shed, item)
        existing = existing_sales.get(item)
        if not stock:
            continue
        hard_sale = (
            shed_total >= 84
            or money < 250
            or financing_needed
            or (item == "FERTILIZER" and day < 7)
            or (item == "WHEAT" and day >= 28)
        )
        if not _market_selected(item):
            if existing is not None:
                learned_sales.append(existing)
            continue
        prediction = _market_prediction(obs, farm, opponent_farm, private, item)
        if prediction is None:
            if existing is not None:
                learned_sales.append(existing)
            continue
        sell_probability, fraction, confidence = prediction
        threshold = _market_threshold(item)
        hold_threshold = min(0.35, threshold * 0.60)
        if hard_sale or confidence < 0.42:
            if existing is not None:
                learned_sales.append(existing)
        elif sell_probability >= threshold:
            amount = max(1, min(stock, round(stock * max(0.15, fraction))))
            learned_sales.append(["SELL", item, amount])
        elif sell_probability > hold_threshold and existing is not None:
            learned_sales.append(existing)

    # Preserve deterministic sales for products outside the learned set.
    learned_set = set(MARKET_ITEMS)
    learned_sales.extend(
        order for item, order in existing_sales.items() if item not in learned_set
    )
    return [*learned_sales, *non_sales][:10]


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    safe = base._safe_observation(obs)
    if safe is None:
        return {"mode": "invalid", "confidence": 0.0}
    farm, opponent_farm, private = safe
    intent = _intent_prediction(obs, farm, opponent_farm, private)
    atlas = v8.policy_diagnostics(obs)
    result: dict[str, Any] = {"atlas": atlas, "mode": "safe", "confidence": 0.0}
    if intent is not None:
        result.update(
            {
                "mode": "decision" if intent["confidence"] >= 0.50 else "blend",
                "confidence": intent["confidence"],
                "intent": intent["values"],
            }
        )
    return result


def agent(obs: Any) -> dict[str, Any]:
    """Return a confidence-gated expert decision through deterministic execution."""
    safe = base._safe_observation(obs)
    if safe is None:
        return {"farmer": ["PASS"], "hands": [], "market": []}
    farm, opponent_farm, private = safe
    opening = v3._safe_opening(obs, farm)
    if opening is not None:
        return copy.deepcopy(opening)
    expert_opening = v8._safe_expert_opening(obs, farm)
    if expert_opening is not None and expert_opening[1]:
        return expert_opening[0]

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
    tasks, reserved = v8._field_tasks(
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
    actions = _mission_assign(
        positions,
        inventories,
        tasks,
        base._as_int(
            base._get(
                obs,
                "step",
                base._as_int(base._get(obs, "day", 0)) * 24
                + base._as_int(base._get(obs, "hour", 0)),
            )
        ),
    )
    market = _market_plan(
        obs,
        farm,
        opponent_farm,
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
    result = {
        "farmer": actions[0] if actions else ["PASS"],
        "hands": actions[1:],
        "market": market,
    }
    if expert_opening is not None:
        scripted, _copy_market = expert_opening
        result["farmer"] = scripted["farmer"]
        result["hands"] = scripted["hands"]
    return result
