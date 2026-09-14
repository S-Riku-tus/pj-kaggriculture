"""Kaggriculture V8: confidence-gated Top-3 strategy distillation.

V8 uses Rank 1's coherent opening and trajectory as its primary behavioural
teacher.  Rank 2 and Rank 3 replays define the robust progress envelope used
to detect states where direct imitation is unsafe.  A compact multi-horizon
forest predicts absolute future portfolio anchors, never a repeatedly applied
action delta.  Outside the expert envelope the agent falls back continuously
to V7's validated observation-only controller.

The learned component controls strategic targets and two demand-conditioned
crop rotations.  Field safety, animal missions, feed reserves, transaction
feasibility, and liquidation remain in the deterministic V6/V7 executor.
"""

from __future__ import annotations

import copy
import importlib.util
import json
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
        Path.cwd() / "agents" / "v8",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (
                (candidate / "v7_base.py").is_file()
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
                and (candidate.parent / "v7" / "main.py").is_file()
            )
        ),
        Path.cwd(),
    )


def _load_v7_module():
    packaged = MODULE_DIR / "v7_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v7" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v8_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V7 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v7 = _load_v7_module()
v6 = v7.v6
v5 = v7.v5
v4 = v7.v4
v3 = v7.v3
base = v7.base
MODEL = v7.MODEL
OPENING_ACTIONS = v7.OPENING_ACTIONS

CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
ANIMALS = ("COW", "SHEEP")
TARGET_NAMES = (*CROPS, *ANIMALS, "HANDS", "LAND", "PASTURES")
POLICY_FEATURE_NAMES = (
    *v3.FEATURE_NAMES,
    "hour_block",
    "hours_left_in_day",
    "money_linear",
    "opponent_money_log",
    "money_share",
    "productive_linear",
    "capacity_gap",
    "pastures_linear",
    "wheat_stock_linear",
    "feed_coverage",
)
POLICY_FORMAT = "kaggriculture-v8-expert-atlas-v1"
ROTATION_CROPS = ("TOMATO", "CARROT")


def _load_policy_model() -> dict[str, Any] | None:
    try:
        payload = json.loads((MODULE_DIR / "expert_policy_model.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if payload.get("format") != POLICY_FORMAT:
        return None
    if tuple(payload.get("feature_names", ())) != POLICY_FEATURE_NAMES:
        return None
    if tuple(payload.get("target_names", ())) != TARGET_NAMES:
        return None
    forests = payload.get("forests", {})
    if not forests.get("h24") or not forests.get("h72"):
        return None
    return payload


POLICY_MODEL = _load_policy_model()


def _load_expert_opening() -> dict[tuple[int, int], dict[str, Any]]:
    try:
        payload = json.loads((MODULE_DIR / "expert_opening_actions.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if payload.get("format") != "kaggriculture-v8-rank1-opening-v1":
        return {}
    entries: dict[tuple[int, int], dict[str, Any]] = {}
    for entry in payload.get("entries", []):
        try:
            key = (int(entry["day"]), int(entry["hour"]))
        except (KeyError, TypeError, ValueError):
            return {}
        entries[key] = entry
    return entries


EXPERT_OPENING = _load_expert_opening()


def _safe_expert_opening(obs: Any, farm: Any) -> tuple[dict[str, Any], bool] | None:
    """Replay only the high-consensus Rank-1 prefix from its expected route."""
    day = base._as_int(base._get(obs, "day", 0))
    hour = base._as_int(base._get(obs, "hour", 0))
    entry = EXPERT_OPENING.get((day, hour))
    if entry is None:
        return None
    expected = entry.get("expected_positions", {}) or {}
    farmer = list(base._get(farm, "farmer", [0, 0]) or [0, 0])
    hands = [list(position) for position in (base._get(farm, "hands", []) or [])]
    if farmer != expected.get("farmer") or hands != expected.get("hands"):
        return None
    action = entry.get("action")
    if not isinstance(action, dict):
        return None
    copy_market = float(entry.get("market_consensus", entry.get("action_consensus", 0.0))) >= 0.75
    return copy.deepcopy(action), copy_market


def _pasture_count(farm: Any) -> int:
    return sum(base._tile_kind(tile) == "PASTURE" for _x, _y, tile in base._iter_tiles(farm))


def _policy_features(obs: Any, farm: Any, opponent_farm: Any, private: Any) -> list[float]:
    """Encode observation-only progress and affordability for the expert atlas."""
    values = list(v3.encode_observation(obs))
    hour = base._as_int(base._get(obs, "hour", 0))
    summary = base._farm_summary(farm)
    money = max(0.0, float(base._get(farm, "money", 0) or 0))
    opponent_money = max(0.0, float(base._get(opponent_farm, "money", 0) or 0))
    wheat_stock = base._all_inventory_count(private, "WHEAT")
    animal_total = summary["animal_total"]
    values.extend(
        (
            min(1.0, (hour // 6) / 3.0),
            min(1.0, max(0, 23 - hour) / 23.0),
            min(20.0, money / 1000.0),
            min(2.0, math.log1p(opponent_money) / 12.0),
            money / max(1.0, money + opponent_money),
            min(1.5, summary["productive"] / 75.0),
            min(1.5, max(0, summary["capacity"] - summary["productive"]) / 75.0),
            min(1.5, _pasture_count(farm) / 15.0),
            min(3.0, wheat_stock / 32.0),
            min(4.0, wheat_stock / max(1, animal_total)),
        )
    )
    if len(values) != len(POLICY_FEATURE_NAMES):
        raise RuntimeError(f"V8 feature mismatch: {len(values)} != {len(POLICY_FEATURE_NAMES)}")
    return values


def _predict_tree(tree: list[Any], features: list[float]) -> list[float]:
    node = tree
    while node[0] == "N":
        node = node[3] if features[int(node[1])] <= float(node[2]) else node[4]
    return [float(value) for value in node[1:]]


def _predict_forest(forest: list[list[Any]], features: list[float]) -> tuple[list[float], list[float]]:
    rows = [_predict_tree(tree, features) for tree in forest]
    if not rows:
        return [0.0] * len(TARGET_NAMES), [math.inf] * len(TARGET_NAMES)
    means = [sum(row[index] for row in rows) / len(rows) for index in range(len(TARGET_NAMES))]
    deviations = [
        math.sqrt(sum((row[index] - means[index]) ** 2 for row in rows) / len(rows))
        for index in range(len(TARGET_NAMES))
    ]
    return means, deviations


def _profile_key(day: int, hour: int) -> str:
    return f"{day}:{min(3, max(0, hour // 6))}"


def _distance_confidence(features: list[float], day: int, hour: int) -> tuple[float, float]:
    if POLICY_MODEL is None:
        return 0.0, math.inf
    profile = (POLICY_MODEL.get("profiles", {}) or {}).get(_profile_key(day, hour))
    if not isinstance(profile, dict):
        return 0.0, math.inf
    indices = [int(value) for value in profile.get("feature_indices", [])]
    centers = [float(value) for value in profile.get("center", [])]
    scales = [max(1e-6, float(value)) for value in profile.get("scale", [])]
    if not indices or not (len(indices) == len(centers) == len(scales)):
        return 0.0, math.inf
    z = [
        min(8.0, abs(features[index] - center) / scale)
        for index, center, scale in zip(indices, centers, scales, strict=True)
    ]
    distance = math.sqrt(sum(value * value for value in z) / len(z))
    p50 = float(profile.get("distance_p50", 1.0))
    p90 = max(p50 + 1e-6, float(profile.get("distance_p90", p50 + 1.0)))
    p99 = max(p90 + 1e-6, float(profile.get("distance_p99", p90 + 1.0)))
    if distance <= p50:
        confidence = 1.0
    elif distance <= p90:
        confidence = 1.0 - 0.35 * (distance - p50) / (p90 - p50)
    elif distance <= p99:
        confidence = 0.65 - 0.50 * (distance - p90) / (p99 - p90)
    else:
        confidence = max(0.0, 0.15 * math.exp(-(distance - p99)))
    return confidence, distance


def _prediction_confidence(deviations: list[float], horizon: str) -> float:
    if POLICY_MODEL is None:
        return 0.0
    scales = [max(1.0, float(value)) for value in POLICY_MODEL.get("target_scales", [1.0] * len(TARGET_NAMES))]
    uncertainty = sum(
        min(4.0, deviation / scale)
        for deviation, scale in zip(deviations, scales, strict=True)
    ) / len(scales)
    reference = max(0.05, float(POLICY_MODEL.get("uncertainty_p90", {}).get(horizon, 0.5)))
    return min(1.0, max(0.0, 1.15 - 0.50 * uncertainty / reference))


def _expert_prediction(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
) -> tuple[dict[str, float], dict[str, float], float, float] | None:
    if POLICY_MODEL is None:
        return None
    day = base._as_int(base._get(obs, "day", 0))
    hour = base._as_int(base._get(obs, "hour", 0))
    if not 3 <= day <= 26:
        return None
    features = _policy_features(obs, farm, opponent_farm, private)
    short, short_deviation = _predict_forest(POLICY_MODEL["forests"]["h24"], features)
    long, long_deviation = _predict_forest(POLICY_MODEL["forests"]["h72"], features)
    manifold_confidence, distance = _distance_confidence(features, day, hour)
    model_confidence = min(
        _prediction_confidence(short_deviation, "h24"),
        _prediction_confidence(long_deviation, "h72"),
    )
    confidence = manifold_confidence * (0.65 + 0.35 * model_confidence)
    return (
        dict(zip(TARGET_NAMES, short, strict=True)),
        dict(zip(TARGET_NAMES, long, strict=True)),
        min(1.0, max(0.0, confidence)),
        distance,
    )


def _blend_target(safe: int, short: float, long: float, confidence: float, *, change_limit: int) -> int:
    # Long-horizon agreement may advance only a bounded fraction of an asset;
    # the absolute short anchor prevents the repeated-delta failure mode.
    long_support = min(short + change_limit, long)
    expert = 0.82 * short + 0.18 * max(short, long_support)
    return round((1.0 - confidence) * safe + confidence * expert)


def _strategy_targets(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
) -> tuple[dict[str, int], dict[str, int], int, int, dict[str, float], int]:
    safe_animals, safe_crops, safe_hands, safe_land, weights, safe_pastures = v7._strategy_targets(
        obs, farm, opponent_farm, private
    )
    prediction = _expert_prediction(obs, farm, opponent_farm, private)
    if prediction is None:
        return safe_animals, safe_crops, safe_hands, safe_land, weights, safe_pastures

    short, long, confidence, _distance = prediction
    day = base._as_int(base._get(obs, "day", 0))
    summary = base._farm_summary(farm)
    crops: dict[str, int] = {}
    crop_limits = {"WHEAT": 10, "CARROT": 10, "TOMATO": 4, "STRAWBERRY": 8, "MELON": 4}
    for crop in CROPS:
        target = _blend_target(
            safe_crops.get(crop, 0),
            short[crop],
            long[crop],
            confidence,
            change_limit=crop_limits[crop],
        )
        crops[crop] = max(summary["crops"].get(crop, 0), min(55, target))

    owned = {animal: v4._owned_animals(farm, private, animal) for animal in ANIMALS}
    animals = {"GOOSE": 0}
    for animal in ANIMALS:
        target = _blend_target(
            safe_animals[animal],
            short[animal],
            long[animal],
            confidence,
            change_limit=2,
        )
        animals[animal] = max(owned[animal], min(16, target))
    while animals["COW"] + animals["SHEEP"] > 16:
        cow_room = animals["COW"] - owned["COW"]
        sheep_room = animals["SHEEP"] - owned["SHEEP"]
        if cow_room >= sheep_room and cow_room > 0:
            animals["COW"] -= 1
        elif sheep_room > 0:
            animals["SHEEP"] -= 1
        else:
            break

    feed_floor = math.ceil((animals["COW"] + animals["SHEEP"]) * 1.2)
    crops["WHEAT"] = max(crops["WHEAT"], feed_floor)
    if day >= 19:
        for crop in ("TOMATO", "STRAWBERRY", "MELON"):
            crops[crop] = summary["crops"].get(crop, 0)
    if day >= 27:
        for crop in ("WHEAT", "CARROT"):
            crops[crop] = summary["crops"].get(crop, 0)

    hands = max(
        1,
        min(14, _blend_target(safe_hands, short["HANDS"], long["HANDS"], confidence, change_limit=2)),
    )
    current_land = summary["unlocked"]
    land = max(
        current_land,
        min(3, _blend_target(safe_land, short["LAND"], long["LAND"], confidence, change_limit=1)),
    )
    pastures = max(
        _pasture_count(farm),
        animals["COW"] + animals["SHEEP"],
        min(
            16,
            _blend_target(
                safe_pastures,
                short["PASTURES"],
                long["PASTURES"],
                confidence,
                change_limit=2,
            ),
        ),
    )
    return animals, crops, hands, land, weights, pastures


def _add_rotation_tasks(
    tasks: list[dict[str, Any]],
    reserved: set[tuple[int, int]],
    obs: Any,
    farm: Any,
    private: Any,
    summary: dict[str, Any],
    crop_targets: dict[str, int],
) -> None:
    day = base._as_int(base._get(obs, "day", 0))
    hour = base._as_int(base._get(obs, "hour", 0))
    if day >= 27 or hour >= 23:
        return
    existing_positions = {
        task["pos"] for task in tasks if task.get("action", [None])[0] == "PLANT"
    }
    free = [
        (x, y)
        for x, y, tile in base._iter_tiles(farm)
        if tile is None and (x, y) not in reserved and (x, y) not in existing_positions
    ]
    board_size = len(base._get(farm, "tiles", []) or []) or 10
    free.sort(
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
    caps = {"TOMATO": 6, "CARROT": 12}
    priorities = {"TOMATO": 9680, "CARROT": 9520}
    for crop in ROTATION_CROPS:
        if crop == "TOMATO" and day >= 19:
            continue
        deficit = max(0, crop_targets[crop] - summary["crops"].get(crop, 0))
        count = min(
            deficit,
            base._inventory_count(seeds, crop),
            max(0, caps[crop] - planted_today[crop]),
            len(free),
        )
        for _ in range(count):
            tasks.append(base._task(free.pop(0), ["PLANT", crop], priorities[crop], label=f"plant-{crop}"))


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
    tasks, reserved = v6._field_tasks(
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
    day = base._as_int(base._get(obs, "day", 0))
    # V2's table uses the end of Melon's watering window (age 12) as `peak`,
    # although its capped yield reaches six at age 10.  All three leading
    # policies cash the opening Melons at that effective maximum and recycle
    # the cells.  Waiting two extra days delays both the third-land refill and
    # the capital that finances it.
    early_melons: dict[tuple[int, int], Any] = {
        (x, y): tile
        for x, y, tile in base._iter_tiles(farm)
        if base._tile_kind(tile) == "PLANT"
        and base._get(tile, "crop") == "MELON"
        and day - base._as_int(base._get(tile, "planted_day", day)) >= 10
        and base._as_int(base._get(tile, "yield_units", 0)) > 0
    }
    if early_melons:
        tasks = [
            task
            for task in tasks
            if not (task.get("label") == "crop-harvest" and task.get("pos") in early_melons)
        ]
        tasks.extend(
            base._task(pos, ["HARVEST"], 14800, label="crop-harvest")
            for pos in early_melons
        )
    rapid_refill = (
        10 <= day <= 12
        and summary["unlocked"] >= 3
        and summary["productive"] < 68
    )
    late_rotation = (
        21 <= day <= 26
        and summary["unlocked"] >= 3
        and summary["productive"] < 68
    )
    for task in tasks:
        unit = task.get("unit")
        if (
            task.get("label") == "drop-goods"
            and isinstance(unit, int)
            and 0 <= unit < len(inventories)
            and base._inventory_count(inventories[unit], "MELON") > 0
        ):
            task["priority"] = max(15600, int(task.get("priority", 0)))
        elif rapid_refill and str(task.get("label", "")).startswith("plant-"):
            # Rank 1 temporarily places expansion planting above ordinary
            # CARE/COLLECT work, while emergency watering and FEED remain
            # higher.  The next observation gives every fresh plant emergency
            # watering priority, so this ordering completes rather than
            # abandons the transaction.
            task["priority"] = max(14000, int(task.get("priority", 0)))
        elif late_rotation and str(task.get("label", "")) in {"plant-WHEAT", "plant-CARROT"}:
            # As ongoing Strawberry/Tomato tiles expire, the leaders promptly
            # rotate released capacity into short-horizon staples.  Keep this
            # below routine FEED so late utilization never trades away herd
            # survival.
            task["priority"] = max(11800, int(task.get("priority", 0)))
    _add_rotation_tasks(tasks, reserved, obs, farm, private, summary, crop_targets)
    return tasks, reserved


def _orders_budget(orders: list[list[Any]], obs: Any, farm: Any, private: Any) -> float:
    budget = float(base._get(farm, "money", 0) or 0)
    prices = base._get(base._get(obs, "market", {}) or {}, "prices", {}) or {}
    shed = base._get(private, "shed", {}) or {}
    hires = base._as_int(base._get(farm, "hires_today", 0))
    unlocked = len(base._get(farm, "unlocked_quadrants", []) or [])
    fixed_animal_cost = {"GOOSE": 300, "COW": 400, "SHEEP": 500}
    for order in orders:
        verb = order[0]
        if verb == "SELL":
            amount = min(base._inventory_count(shed, order[1]), base._as_int(order[2]))
            budget += 0.75 * amount * max(1, base._as_int(base._get(prices, order[1], 1)))
        elif verb == "BUY_PRODUCT":
            budget -= base._as_int(order[2]) * max(1, base._as_int(base._get(prices, order[1], 1)))
        elif verb == "BUY_SEED":
            budget -= base._as_int(order[2]) * int(base.CROP_DATA[order[1]]["seed"])
        elif verb == "BUY_ANIMAL":
            budget -= base._as_int(order[2]) * fixed_animal_cost.get(str(order[1]), 0)
        elif verb == "HIRE":
            budget -= base._hire_cost(hires)
            hires += 1
        elif verb == "BUY_LAND":
            budget -= 1000 if unlocked == 1 else (2000 if unlocked == 2 else 4000)
            unlocked += 1
    return budget


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
    orders = v6._market_plan(
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
    if day >= 27 or len(orders) >= 10:
        return orders[:10]
    seeds = base._get(private, "seeds", {}) or {}
    available_tiles = sum(
        tile is None and (x, y) not in reserved for x, y, tile in base._iter_tiles(farm)
    )
    committed = sum(base._inventory_count(seeds, crop) for crop in CROPS)
    seed_room = max(0, available_tiles - committed)
    budget = _orders_budget(orders, obs, farm, private)
    reserve = 100 + summary["animal_total"] * 25
    caps = {"TOMATO": 6, "CARROT": 10}
    for crop in ROTATION_CROPS:
        if len(orders) >= 10 or seed_room <= 0 or (crop == "TOMATO" and day >= 19):
            continue
        deficit = max(
            0,
            crop_targets[crop] - summary["crops"].get(crop, 0) - base._inventory_count(seeds, crop),
        )
        cost = int(base.CROP_DATA[crop]["seed"])
        amount = min(deficit, caps[crop], seed_room, max(0, int((budget - reserve) // cost)))
        if amount:
            orders.append(["BUY_SEED", crop, amount])
            budget -= amount * cost
            seed_room -= amount
    return orders[:10]


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    """Return deterministic, observation-only V8 strategy diagnostics."""
    safe = base._safe_observation(obs)
    if safe is None:
        return {"mode": "invalid", "confidence": 0.0, "distance": math.inf}
    farm, opponent_farm, private = safe
    prediction = _expert_prediction(obs, farm, opponent_farm, private)
    if prediction is None:
        return {"mode": "safe", "confidence": 0.0, "distance": math.inf}
    short, long, confidence, distance = prediction
    mode = "expert" if confidence >= 0.65 else ("blend" if confidence >= 0.20 else "safe")
    return {
        "mode": mode,
        "confidence": confidence,
        "distance": distance,
        "h24": short,
        "h72": long,
    }


def agent(obs: Any) -> dict[str, Any]:
    """Return a Top-3-informed action through the safe deterministic executor."""
    safe = base._safe_observation(obs)
    if safe is None:
        return {"farmer": ["PASS"], "hands": [], "market": []}
    farm, opponent_farm, private = safe
    opening = v3._safe_opening(obs, farm)
    if opening is not None:
        return copy.deepcopy(opening)
    expert_opening = _safe_expert_opening(obs, farm)
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
    actions = v5._assign_tasks(positions, inventories, tasks)
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
