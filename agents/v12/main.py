"""Kaggriculture V12: conservative relative strategy on V11's safe core.

The learned layer chooses only future portfolio goals in a single branch that
improved both 24-hour and 72-hour winner-trajectory fidelity on calibration
episodes and remained better on the untouched test episodes.  Every unsupported
or out-of-distribution state falls back to V11.

Two deterministic executor corrections are independent feature flags: Wheat
pickup quantities are capped by observable unfed demand, and an idle/moving
worker finishes CARE on its current fed animal unless another animal is in an
observable survival emergency.  Legality, budgets, selling, routing, and the
opening remain inherited from V11/V10.
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
        Path.cwd() / "agents" / "v12",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if ((candidate / "v11_base.py").is_file() and (candidate / "relative_policy_model.json").is_file())
            or ((candidate / "main.py").is_file() and (candidate.parent / "v11" / "main.py").is_file())
        ),
        Path.cwd(),
    )


def _load_v11_module():
    packaged = MODULE_DIR / "v11_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v11" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v12_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V11 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v11 = _load_v11_module()
v10 = v11.v10
v9 = v11.v9
v8 = v11.v8
v4 = v11.v4
v3 = v11.v3
base = v11.base

CROPS = v11.CROPS
ANIMALS = v11.ANIMALS
POLICY_FORMAT = "kaggriculture-v12-relative-policy-v1"
PORTFOLIO = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "COW", "SHEEP")
FOCUS = ("MILK", "WOOL", "STRAWBERRY", "WHEAT")
FOCUS_ASSET = {"MILK": "COW", "WOOL": "SHEEP", "STRAWBERRY": "STRAWBERRY", "WHEAT": "WHEAT"}
BASE_PRICE = {"MILK": 160, "WOOL": 200, "STRAWBERRY": 120, "WHEAT": 25}

ENABLE_RELATIVE_POLICY = False
# Both logistics experiments remain callable for reproducible ablation, but
# local paired diagnostics found lower feed coverage / displaced harvest work.
# They are therefore rejected from the release policy until redesigned.
ENABLE_WHEAT_BATCH_FIX = False
ENABLE_LOCAL_ANIMAL_COMPLETION = False


def _load_policy() -> dict[str, Any] | None:
    path = MODULE_DIR / "relative_policy_model.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if payload.get("format") != POLICY_FORMAT or tuple(payload.get("portfolio", ())) != PORTFOLIO:
        return None
    return payload


RELATIVE_POLICY = _load_policy()


def _phase(day: int) -> str:
    for lower, upper in ((6, 9), (10, 11), (12, 13), (14, 17), (18, 21), (22, 24), (25, 27)):
        if lower <= day <= upper:
            return f"{lower}-{upper}"
    return "outside"


def _public_portfolio(farm: Any) -> dict[str, float]:
    summary = base._farm_summary(farm)
    return {
        **{crop: float(summary["crops"].get(crop, 0)) for crop in CROPS},
        "COW": float(summary["animals"].get("COW", 0)),
        "SHEEP": float(summary["animals"].get("SHEEP", 0)),
    }


def _relative_context(obs: Any, farm: Any, opponent_farm: Any) -> dict[str, Any]:
    demand = base._demand_profile(obs)
    prices = base._get(base._get(obs, "market", {}) or {}, "prices", {}) or {}
    own = _public_portfolio(farm)
    opponent = _public_portfolio(opponent_farm)
    scores: dict[str, float] = {}
    for product in FOCUS:
        asset = FOCUS_ASSET[product]
        scale = 16.0 if asset in {"COW", "SHEEP"} else 50.0
        scores[product] = (
            float(demand.get(product, 0))
            + float(base._get(prices, product, BASE_PRICE[product]) or 0) / BASE_PRICE[product]
            - 0.35 * opponent[asset] / scale
        )
    focus = max(FOCUS, key=lambda product: (scores[product], -FOCUS.index(product)))
    asset = FOCUS_ASSET[focus]
    crowded = own[asset] + opponent[asset] >= (15.0 if asset in {"COW", "SHEEP"} else 48.0)
    own_money = float(base._get(farm, "money", 0) or 0)
    opponent_money = float(base._get(opponent_farm, "money", 0) or 0)
    ordered_scores = sorted(scores.values(), reverse=True)
    return {
        "key": f"{_phase(base._as_int(base._get(obs, 'day', 0)))}|{focus}|{'crowded' if crowded else 'open'}",
        "money_gap_ratio": (own_money - opponent_money) / max(1.0, own_money + opponent_money),
        "focus_margin": ordered_scores[0] - ordered_scores[1],
        "own_focus": own[asset],
        "opponent_focus": opponent[asset],
    }


def _relative_prediction(obs: Any, farm: Any, opponent_farm: Any, private: Any) -> dict[str, Any]:
    if not ENABLE_RELATIVE_POLICY or RELATIVE_POLICY is None:
        return {"active": False, "reason": "disabled-or-missing"}
    anchor = v8._expert_prediction(obs, farm, opponent_farm, private)
    if anchor is None or float(anchor[2]) < 0.35:
        return {"active": False, "reason": "low-atlas-confidence"}
    context = _relative_context(obs, farm, opponent_farm)
    branch = (RELATIVE_POLICY.get("selection") or {}).get(context["key"])
    if not isinstance(branch, dict):
        return {"active": False, "reason": "unsupported-branch", "context": context}
    for feature, bounds in (branch.get("ranges") or {}).items():
        value = float(context.get(feature, math.inf))
        if len(bounds) != 2 or not float(bounds[0]) <= value <= float(bounds[1]):
            return {"active": False, "reason": f"ood-{feature}", "context": context}
    return {
        "active": True,
        "reason": "active",
        "context": context,
        "expert": branch.get("expert"),
        "profile": branch.get("profile"),
        "atlas_confidence": float(anchor[2]),
    }


def _strategy_targets(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
) -> tuple[dict[str, int], dict[str, int], int, int, dict[str, float], int]:
    animals, crops, hands, land, weights, pastures = v11._strategy_targets(obs, farm, opponent_farm, private)
    prediction = _relative_prediction(obs, farm, opponent_farm, private)
    if not prediction["active"]:
        return animals, crops, hands, land, weights, pastures

    profile = prediction["profile"]
    day = base._as_int(base._get(obs, "day", 0))
    # The selected branch supports both horizons.  Move gradually from its
    # immediate target toward the strategic target across the four-day phase.
    long_mix = min(0.35, max(0.0, (day - 10) / 3.0 * 0.35))
    desired = {
        item: round((1.0 - long_mix) * float(profile["h24"][item]) + long_mix * float(profile["h72"][item]))
        for item in PORTFOLIO
    }
    summary = base._farm_summary(farm)
    baseline_mass = sum(animals.values()) + sum(crops.values())
    owned = {animal: v4._owned_animals(farm, private, animal) for animal in ("COW", "SHEEP")}
    animals["GOOSE"] = 0
    animals["COW"] = max(owned["COW"], desired["COW"])
    animals["SHEEP"] = max(owned["SHEEP"], desired["SHEEP"])

    crops["STRAWBERRY"] = max(summary["crops"]["STRAWBERRY"], desired["STRAWBERRY"])
    crops["MELON"] = max(summary["crops"]["MELON"], min(crops["MELON"], desired["MELON"]))
    # Carrot/Tomato branches remain V11-controlled; this relative profile did
    # not pass a separate validation gate for overriding them.
    non_wheat = sum(animals.values()) + sum(crops[crop] for crop in CROPS if crop != "WHEAT")
    feed_floor = math.ceil((animals["COW"] + animals["SHEEP"]) * 1.2)
    crops["WHEAT"] = max(feed_floor, baseline_mass - non_wheat)
    pastures = max(v8._pasture_count(farm), animals["COW"] + animals["SHEEP"])
    return animals, crops, hands, land, weights, pastures


def _rightsize_wheat_pickups(
    tasks: list[dict[str, Any]], farm: Any, private: Any, inventories: list[Any]
) -> list[dict[str, Any]]:
    if not ENABLE_WHEAT_BATCH_FIX:
        return tasks
    pickup_tasks = [task for task in tasks if task.get("label") == "pickup-wheat"]
    if not pickup_tasks:
        return tasks
    unfed = sum(
        base._get(tile, "animal") in base.ANIMAL_DATA and not bool(base._get(tile, "fed_today", False))
        for _x, _y, tile in base._iter_tiles(farm)
    )
    carried = sum(base._inventory_count(inventory, "WHEAT") for inventory in inventories)
    stock = base._inventory_count(base._get(private, "shed", {}) or {}, "WHEAT")
    remaining = min(stock, max(0, unfed - carried))
    kept: list[dict[str, Any]] = [task for task in tasks if task.get("label") != "pickup-wheat"]
    carriers = min(len(pickup_tasks), math.ceil(remaining / 2))
    for index, original in enumerate(pickup_tasks[:carriers]):
        slots_left = carriers - index
        load = min(3, max(1, math.ceil(remaining / max(1, slots_left))))
        remaining -= load
        task = dict(original)
        task["action"] = ["PICKUP", "WHEAT", load]
        kept.append(task)
    return kept


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
    opponent_farm: Any = None,
) -> tuple[list[dict[str, Any]], set[tuple[int, int]]]:
    tasks, reserved = v11._field_tasks(
        obs,
        farm,
        private,
        positions,
        inventories,
        summary,
        animal_targets,
        crop_targets,
        pasture_target,
        opponent_farm,
    )
    return _rightsize_wheat_pickups(tasks, farm, private, inventories), reserved


def _complete_local_animal_service(
    obs: Any,
    farm: Any,
    positions: list[tuple[int, int]],
    actions: list[list[Any]],
) -> list[list[Any]]:
    if not ENABLE_LOCAL_ANIMAL_COMPLETION:
        return actions
    hour = base._as_int(base._get(obs, "hour", 0))
    emergency = any(
        base._get(tile, "animal") in base.ANIMAL_DATA
        and not bool(base._get(tile, "fed_today", False))
        and (base._as_int(base._get(tile, "consecutive_unfed", 0)) >= 1 or hour >= 18)
        for _x, _y, tile in base._iter_tiles(farm)
    )
    if emergency:
        return actions
    tiles = base._get(farm, "tiles", []) or []
    result = [list(action) for action in actions]
    for unit, action in enumerate(result):
        if unit >= len(positions) or not action or action[0] not in {"NORTH", "SOUTH", "EAST", "WEST", "PASS"}:
            continue
        x, y = positions[unit]
        tile = tiles[y][x] if 0 <= y < len(tiles) and 0 <= x < len(tiles[y]) else None
        if (
            base._get(tile, "animal") in base.ANIMAL_DATA
            and bool(base._get(tile, "fed_today", False))
            and not bool(base._get(tile, "cared_today", False))
        ):
            result[unit] = ["CARE"]
    return result


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v11.policy_diagnostics(obs))
    safe = base._safe_observation(obs)
    if safe is None:
        return result
    farm, opponent_farm, private = safe
    result["v12_relative"] = _relative_prediction(obs, farm, opponent_farm, private)
    result["v12_executor"] = {
        "wheat_batch_fix": ENABLE_WHEAT_BATCH_FIX,
        "local_animal_completion": ENABLE_LOCAL_ANIMAL_COMPLETION,
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
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
    inventories = [raw_inventories[index] if index < len(raw_inventories) else {} for index in range(len(positions))]
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
        opponent_farm,
    )
    actions = v9._mission_assign(
        positions,
        inventories,
        tasks,
        base._as_int(
            base._get(
                obs,
                "step",
                base._as_int(base._get(obs, "day", 0)) * 24 + base._as_int(base._get(obs, "hour", 0)),
            )
        ),
    )
    execution_prediction = v8._expert_prediction(obs, farm, opponent_farm, private)
    actions = v10._prefer_local_water(
        obs, farm, opponent_farm, private, positions, inventories, actions, execution_prediction
    )
    actions = _complete_local_animal_service(obs, farm, positions, actions)
    actions = v10._preposition_idle_workers(
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
    market, _recovery = v11._market_plan(
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
    result = {"farmer": actions[0] if actions else ["PASS"], "hands": actions[1:], "market": market}
    if expert_opening is not None:
        scripted, _copy_market = expert_opening
        result["farmer"] = scripted["farmer"]
        result["hands"] = scripted["hands"]
    return result
