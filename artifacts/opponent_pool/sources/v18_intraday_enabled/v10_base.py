"""Kaggriculture V10: future-state recovery on V9's safe executor.

V10 keeps V9's learned strategy forest and deterministic feasibility layer,
then corrects replay-measured closed-loop gaps: delayed Strawberry expansion,
a Day-12 portfolio ceiling, weak demand-conditioned herd allocation, excess
early fertilizer work, avoidable travel before watering, and slow mid/late
refill.  Every learned-target correction is gated by V9's Rank-1 atlas
confidence; low-confidence states retain the V9 fallback policy.

Feed emergencies, inventory requirements, market budgets, legal movement,
opening scripts, and liquidation remain deterministic.  V9 sales are isolated
from V10 field changes, except for the independently validated Day 6-10
fertilizer-to-capital conversion.
"""

from __future__ import annotations

import copy
import importlib.util
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
        Path.cwd() / "agents" / "v10",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (
                (candidate / "v9_base.py").is_file()
                and (candidate / "v8_base.py").is_file()
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
                and (candidate.parent / "v9" / "main.py").is_file()
            )
        ),
        Path.cwd(),
    )


def _load_v9_module():
    packaged = MODULE_DIR / "v9_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v9" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v10_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V9 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v9 = _load_v9_module()
v8 = v9.v8
v7 = v9.v7
v6 = v9.v6
v5 = v9.v5
v4 = v9.v4
v3 = v9.v3
base = v9.base
MODEL = v9.MODEL
POLICY_MODEL = v9.POLICY_MODEL
DECISION_MODEL = v9.DECISION_MODEL

CROPS = v9.CROPS
ANIMALS = v9.ANIMALS

# Rank-1 public-teacher P10 cash at the first observation of each day.  These
# values are a recovery envelope, not a desired cash objective.  Crop backlog
# can independently activate recovery, so low-price games do not rely on cash
# alone.  Source: data/analysis/v10_v9_teacher_gap.json.
RANK1_CASH_P10 = {
    6: 134.0,
    7: 507.0,
    8: 373.6,
    9: 1682.6,
    10: 579.8,
    11: 13104.4,
    12: 13769.6,
}


def _strategy_targets(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
) -> tuple[dict[str, int], dict[str, int], int, int, dict[str, float], int]:
    """Calibrate only unowned herd slots to Rank-1 demand portfolios."""
    animals, crops, hands, land, weights, pastures = v9._strategy_targets(
        obs, farm, opponent_farm, private
    )
    day = base._as_int(base._get(obs, "day", 0))
    if not 6 <= day <= 27:
        return animals, crops, hands, land, weights, pastures
    prediction = v8._expert_prediction(obs, farm, opponent_farm, private)
    if prediction is None or prediction[2] < 0.35:
        return animals, crops, hands, land, weights, pastures

    if day >= 20:
        # Rank 1 rotates expiring premium crops into short-horizon Wheat: its
        # median Wheat footprint rises 24 -> 35 -> 43 on Days 18/24/27.  The
        # V9 atlas keeps too many late Strawberry slots and misses that 72-hour
        # state.  This is only a floor for newly free cells; it neither removes
        # live crops nor bypasses the deterministic seed/budget executor.
        crops["WHEAT"] = max(crops["WHEAT"], min(42, 28 + 2 * (day - 20)))
        return animals, crops, hands, land, weights, pastures

    demand = base._demand_profile(obs)
    milk_demand = int(demand.get("MILK", 0))
    wool_demand = int(demand.get("WOOL", 0))
    owned = {animal: v4._owned_animals(farm, private, animal) for animal in ANIMALS}
    original_total = animals["COW"] + animals["SHEEP"]

    # Rank 1's median maximum herd rises from 6 to 14 Cows as Milk demand
    # rises from 0/1 to 6, while Sheep stays at two until Wool demand is known.
    # Before Day 13, preserve more option value because future shops are still
    # hidden.  The trajectory floor retains the common early Cow expansion.
    cow_floor = 4 if day <= 7 else (6 if day == 8 else (7 if day == 9 else 8))
    cow_cap = max(cow_floor, min(14, 6 + 2 * milk_demand))
    sheep_cap = min(10, 2 + max(0, wool_demand - 2)) if day <= 12 else min(10, 2 + wool_demand)

    sheep = max(owned["SHEEP"], min(animals["SHEEP"], sheep_cap))
    cow = max(owned["COW"], min(cow_cap, max(animals["COW"], original_total - sheep)))
    animals = {"GOOSE": 0, "COW": cow, "SHEEP": sheep}

    feed_floor = math.ceil((cow + sheep) * 1.2)
    crops["WHEAT"] = max(crops["WHEAT"], feed_floor)
    if day >= 10 and land >= 3:
        # Despite different openings, all three public leaders converge near
        # 69-71 productive cells on Day 12.  V9's inferred portfolio often
        # sums to exactly 64 and leaves eleven cells idle.  A target of 72
        # leaves three cells of routing slack and compensates for the observed
        # two-to-three-cell execution lag.  Preserve every
        # demand-specific target and fill only the missing portfolio mass with
        # Wheat, the safe feed reserve and shortest broadly useful rotation.
        productive_gap = 72 - (sum(crops.values()) + cow + sheep)
        crops["WHEAT"] += max(0, productive_gap)
    pastures = max(v8._pasture_count(farm), cow + sheep)
    return animals, crops, hands, land, weights, pastures


def _committed_crop(farm: Any, private: Any, crop: str) -> int:
    summary = base._farm_summary(farm)
    seeds = base._get(private, "seeds", {}) or {}
    return summary["crops"].get(crop, 0) + base._inventory_count(seeds, crop)


def _capital_recovery(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
) -> dict[str, Any]:
    """Return teacher-gap evidence for a bounded early recovery mode."""
    day = base._as_int(base._get(obs, "day", 0))
    if day not in RANK1_CASH_P10:
        return {"active": False, "reason": "outside-window", "confidence": 0.0}
    prediction = v8._expert_prediction(obs, farm, opponent_farm, private)
    if prediction is None:
        return {"active": False, "reason": "no-expert-anchor", "confidence": 0.0}
    short, _long, confidence, distance = prediction
    if confidence < 0.35:
        return {
            "active": False,
            "reason": "low-confidence",
            "confidence": float(confidence),
            "distance": float(distance),
        }
    strawberry_gap = float(short["STRAWBERRY"]) - _committed_crop(farm, private, "STRAWBERRY")
    wheat_gap = float(short["WHEAT"]) - _committed_crop(farm, private, "WHEAT")
    money = float(base._get(farm, "money", 0) or 0)
    cash_gap = RANK1_CASH_P10[day] - money
    crop_backlog = strawberry_gap >= 2.5 or wheat_gap >= 3.5
    cash_backlog = cash_gap > 0
    return {
        "active": bool(crop_backlog or cash_backlog),
        "reason": "crop-and-cash" if crop_backlog and cash_backlog else ("crop" if crop_backlog else "cash"),
        "confidence": float(confidence),
        "distance": float(distance),
        "strawberry_gap": round(strawberry_gap, 4),
        "wheat_gap": round(wheat_gap, 4),
        "cash_gap": round(cash_gap, 4),
    }


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
    day = base._as_int(base._get(obs, "day", 0))
    if day <= 10:
        tasks = [task for task in tasks if task.get("action", [None])[0] != "FERTILIZE"]
    elif day <= 26:
        focused: list[dict[str, Any]] = []
        tiles = base._get(farm, "tiles", []) or []
        for task in tasks:
            action = task.get("action", [None])[0]
            label = str(task.get("label", ""))
            if action == "PICKUP" and label in {
                "pickup-COW",
                "pickup-SHEEP",
                "pickup-GOOSE",
            }:
                # Purchased animals have a short shed lifetime.  A lower
                # priority let one Cow expire while three empty pastures were
                # available.  Emergency FEED (15400) still outranks this.
                task["priority"] = max(13500, int(task.get("priority", 0)))
            elif action == "PLACE" and label in {
                "place-COW",
                "place-SHEEP",
                "place-GOOSE",
            }:
                task["priority"] = max(13400, int(task.get("priority", 0)))
            elif action == "FERTILIZE":
                x, y = task["pos"]
                tile = tiles[y][x] if 0 <= y < len(tiles) and 0 <= x < len(tiles[y]) else None
                if base._get(tile, "crop") not in {"STRAWBERRY", "TOMATO"}:
                    continue
                task["priority"] = max(12700, int(task.get("priority", 0)))
            elif action == "WATER":
                # Emergency FEED remains 15400; routine FEED remains 12100.
                task["priority"] = max(12800, int(task.get("priority", 0)))
            elif (
                action == "PLANT"
                and 13 <= day <= 26
                and summary["productive"] < 70
            ):
                # Close the post-expansion utilization dip without delaying
                # routine feed.  Water and premium fertilizer still execute
                # first, and the rule disappears once the shared top-team
                # productive-state band has been recovered.
                task["priority"] = max(12000, int(task.get("priority", 0)))
            focused.append(task)
        tasks = focused
    strawberry_backlog = (
        crop_targets.get("STRAWBERRY", 0)
        - summary["crops"].get("STRAWBERRY", 0)
    )
    if 6 <= day <= 8 and strawberry_backlog >= 3:
        for task in tasks:
            if task.get("label") == "plant-STRAWBERRY":
                # Rank 1 plants the purchased Strawberry seeds immediately in
                # this window.  Emergency FEED/WATER tasks remain above this
                # priority; only routine work yields to the strategic backlog.
                task["priority"] = max(13500, int(task.get("priority", 0)))
    return tasks, reserved


def _force_early_fertilizer_sale(orders: list[list[Any]], private: Any, day: int) -> list[list[Any]]:
    if not 6 <= day <= 10:
        return orders[:10]
    stock = base._inventory_count(base._get(private, "shed", {}) or {}, "FERTILIZER")
    filtered = [
        list(order)
        for order in orders
        if not (order and order[0] == "SELL" and len(order) >= 2 and order[1] == "FERTILIZER")
    ]
    if stock:
        filtered.insert(0, ["SELL", "FERTILIZER", stock])
    return filtered[:10]


def _preposition_idle_workers(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
    positions: list[tuple[int, int]],
    inventories: list[Any],
    tasks: list[dict[str, Any]],
    actions: list[list[Any]],
    expert_prediction: Any = None,
) -> list[list[Any]]:
    """Route only empty, otherwise-idle units toward observable future work."""
    day = base._as_int(base._get(obs, "day", 0))
    if not 6 <= day <= 19:
        return actions
    prediction = expert_prediction or v8._expert_prediction(obs, farm, opponent_farm, private)
    if prediction is None or prediction[2] < 0.35:
        return actions

    candidates: dict[tuple[int, int], int] = {}
    for task in tasks:
        position = task.get("pos")
        action = task.get("action", ["PASS"])
        if (
            isinstance(position, tuple)
            and len(position) == 2
            and action
            and action[0] != "PASS"
        ):
            candidates[position] = max(candidates.get(position, 0), int(task.get("priority", 0)))
    if not candidates:
        return actions

    result = [list(action) for action in actions]
    claimed: set[tuple[int, int]] = set()
    for unit, action in enumerate(result):
        if action != ["PASS"] or unit >= len(positions) or unit >= len(inventories):
            continue
        if base._inventory_total(inventories[unit]) > 0:
            continue
        current = positions[unit]
        available = [position for position in candidates if position not in claimed and position != current]
        if not available:
            continue
        target = max(
            available,
            key=lambda position: (
                candidates[position] - 250 * base._manhattan(current, position),
                -base._manhattan(current, position),
                -position[1],
                -position[0],
            ),
        )
        claimed.add(target)
        result[unit] = base._movement(current, target, unit)
    return result


def _prefer_local_water(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
    positions: list[tuple[int, int]],
    inventories: list[Any],
    actions: list[list[Any]],
    expert_prediction: Any = None,
) -> list[list[Any]]:
    """Water the current tile before an empty worker starts a long route."""
    day = base._as_int(base._get(obs, "day", 0))
    if not 6 <= day <= 26:
        return actions
    prediction = expert_prediction or v8._expert_prediction(obs, farm, opponent_farm, private)
    if prediction is None or prediction[2] < 0.35:
        return actions
    hour = base._as_int(base._get(obs, "hour", 0))
    feed_urgent = any(
        base._get(tile, "animal") in base.ANIMAL_DATA
        and not bool(base._get(tile, "fed_today", False))
        and (base._as_int(base._get(tile, "consecutive_unfed", 0)) >= 1 or hour >= 18)
        for _x, _y, tile in base._iter_tiles(farm)
    )
    if feed_urgent:
        return actions

    tiles = base._get(farm, "tiles", []) or []
    result = [list(action) for action in actions]
    for unit, action in enumerate(result):
        if unit >= len(positions) or unit >= len(inventories):
            continue
        if not action or action[0] not in {"NORTH", "SOUTH", "EAST", "WEST", "PASS"}:
            continue
        if base._inventory_total(inventories[unit]) > 0:
            continue
        x, y = positions[unit]
        tile = tiles[y][x] if 0 <= y < len(tiles) and 0 <= x < len(tiles[y]) else None
        if base._tile_kind(tile) == "PLANT" and not bool(base._get(tile, "watered_today", False)):
            result[unit] = ["WATER"]
    return result


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
) -> tuple[list[list[Any]], dict[str, Any]]:
    recovery = _capital_recovery(obs, farm, opponent_farm, private)
    adjusted_orders = v9._market_plan(
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
    baseline_orders = list(v9.agent(obs).get("market", []) or [])
    baseline_sales = [
        list(order) for order in baseline_orders if order and order[0] == "SELL"
    ]
    adjusted_non_sales = [
        list(order) for order in adjusted_orders if not order or order[0] != "SELL"
    ]
    # Untouched Rank-1 episodes rejected replacing all recovery sales: it
    # reduced Wheat SELL F1 from 0.879 to 0.836.  Only the separately supported
    # fertilizer liquidation below is allowed to override V9's learned timing.
    # Recompute purchases with V10 targets, but isolate sales from field-task
    # changes so suppressing a FERTILIZE task cannot accidentally liquidate the
    # entire fertilizer inventory.
    orders = [*baseline_sales, *adjusted_non_sales]
    day = base._as_int(base._get(obs, "day", 0))
    return _force_early_fertilizer_sale(orders, private, day), recovery


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    safe = base._safe_observation(obs)
    if safe is None:
        return {"mode": "invalid", "confidence": 0.0}
    farm, opponent_farm, private = safe
    result = dict(v9.policy_diagnostics(obs))
    result["capital_recovery"] = _capital_recovery(obs, farm, opponent_farm, private)
    if result["capital_recovery"]["active"]:
        result["mode"] = "capital-recovery"
    return result


def agent(obs: Any) -> dict[str, Any]:
    """Return a teacher-gap-corrected action through V9's safe executor."""
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
    actions = v9._mission_assign(
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
    execution_prediction = v8._expert_prediction(obs, farm, opponent_farm, private)
    actions = _prefer_local_water(
        obs,
        farm,
        opponent_farm,
        private,
        positions,
        inventories,
        actions,
        execution_prediction,
    )
    actions = _preposition_idle_workers(
        obs,
        farm,
        opponent_farm,
        private,
        positions,
        inventories,
        tasks,
        actions,
        execution_prediction,
    )
    market, _recovery = _market_plan(
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
