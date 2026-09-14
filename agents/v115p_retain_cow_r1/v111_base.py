"""Kaggriculture V111: held-out future-goal gates over V110.

V110 remains the complete trajectory and deterministic execution policy.  A
small ridge model, trained only on public states from the top-three replay
corpus, predicts the seven-component farm change 72 turns ahead.  The model
is deliberately unable to emit field actions.

One bounded decision may consume that goal: when YARN first appears as shop
three, the final planned two-Cow purchase
  may become two Sheep.  Purchase, shed pickup, and both placements are
  rewritten only after deterministic feasibility checks.

A prefix-compatible second-shop YARN veto was implemented as a hypothesis but
is disabled: it failed to reproduce across both episode and action-lineage
validation protocols.

The rejected 24-turn model is never consulted.  Non-finite, out-of-support,
missing, or mechanically unexpected states execute unchanged V110.  V109's
critical-state deterministic fallback remains the final safety tier.
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
        Path.cwd() / "agents" / "v111",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (candidate / "strategy_model.json").is_file()
            and (
                (candidate / "v110_base.py").is_file()
                or (candidate.parent / "v110" / "main.py").is_file()
            )
        ),
        Path.cwd(),
    )


def _load_module(name: str, packaged_name: str, repository_source: Path):
    packaged = MODULE_DIR / packaged_name
    source = packaged if packaged.is_file() else repository_source
    spec = importlib.util.spec_from_file_location(name, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V111 dependency: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load_module(
    "_kaggriculture_v111_base",
    "v110_base.py",
    MODULE_DIR.parent / "v110" / "main.py",
)

MODEL = json.loads((MODULE_DIR / "strategy_model.json").read_text(encoding="utf-8"))

PORTFOLIO = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "COW", "SHEEP")
PRODUCT = {
    "WHEAT": "WHEAT",
    "CARROT": "CARROT",
    "TOMATO": "TOMATO",
    "STRAWBERRY": "STRAWBERRY",
    "MELON": "MELON",
    "COW": "MILK",
    "SHEEP": "WOOL",
}
BASE_PRICE = {
    "WHEAT": 25.0,
    "CARROT": 35.0,
    "TOMATO": 60.0,
    "STRAWBERRY": 120.0,
    "MELON": 250.0,
    "MILK": 160.0,
    "WOOL": 200.0,
}
MARKET_SCALE = {
    "WHEAT": 400.0,
    "CARROT": 450.0,
    "TOMATO": 200.0,
    "STRAWBERRY": 100.0,
    "MELON": 300.0,
    "MILK": 122.0,
    "WOOL": 105.0,
}
SHOP_PRODUCTS = {
    "BAKERY": ("EGG", "WHEAT"),
    "PIZZA_SHOP": ("MILK", "TOMATO", "WHEAT"),
    "BRUNCH_SPOT": ("EGG", "WHEAT", "STRAWBERRY"),
    "YARN_STORE": ("WOOL",),
    "ICE_CREAM_SHOP": ("STRAWBERRY", "MILK", "WHEAT"),
    "PET_CAFE": ("CARROT",),
    "SMOOTHIE_SHOP": ("STRAWBERRY", "MILK"),
    "FARMERS_MARKET": ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY"),
}

# These thresholds are frozen before inspecting candidate-vs-opponent scores.
# Their held-out teacher audit is produced by evaluate_v111_strategy_gates.py.
OOD_MAX_ABS_Z = 4.0
SECOND_YARN_MILK_VETO = -1.5
THIRD_YARN_WOOL_GATE = 2.0
ENABLE_SECOND_YARN_VETO = False
LATE_PURCHASE_STEP = 248
LATE_ANIMAL_QUANTITY = 2
SHEEP_UNIT_COST = 500.0
MINIMUM_CASH_AFTER_PURCHASE = 500.0

_RUNTIME: dict[int, dict[str, Any]] = {}


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    getter = getattr(obj, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except (AttributeError, TypeError):
            pass
    return getattr(obj, key, default)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _step(obs: Any) -> int:
    raw = _get(obs, "step", None)
    if raw is not None:
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            pass
    return max(0, 24 * _as_int(_get(obs, "day", 0)) + _as_int(_get(obs, "hour", 0)))


def _seat(obs: Any) -> int:
    return 1 if _as_int(_get(obs, "player", 0)) == 1 else 0


def _farms(obs: Any) -> tuple[Any | None, Any | None]:
    farms = list(_get(obs, "farms", []) or [])
    seat = _seat(obs)
    if len(farms) < 2 or seat >= len(farms):
        return None, None
    return farms[seat], farms[1 - seat]


def _new_state(step: int = -1) -> dict[str, Any]:
    return {
        "last_step": step,
        "route_override": None,
        "route_gate": None,
        "late_goal": None,
        "conversion": None,
        "last_model": None,
        "last_fallback_reason": None,
        "decision_counts": Counter(),
    }


def _state_for(obs: Any) -> dict[str, Any]:
    seat = _seat(obs)
    step = _step(obs)
    state = _RUNTIME.get(seat)
    if state is None or step == 0 or step < int(state.get("last_step", -1)):
        state = _new_state(step)
        _RUNTIME[seat] = state
    else:
        state["last_step"] = step
    return state


def _iter_tiles(farm: Any):
    for row in _get(farm, "tiles", []) or []:
        if isinstance(row, dict):
            yield row
            continue
        for tile in row or []:
            if isinstance(tile, dict):
                yield tile


def _portfolio(farm: Any) -> dict[str, float]:
    counts: Counter[str] = Counter()
    for tile in _iter_tiles(farm):
        crop = _get(tile, "crop")
        animal = _get(tile, "animal")
        if crop in PORTFOLIO:
            counts[str(crop)] += 1
        if animal in PORTFOLIO:
            counts[str(animal)] += 1
    return {item: float(counts[item]) for item in PORTFOLIO}


def _demand_per_day(shops: list[str], product: str) -> float:
    demand = 1.0
    for shop in shops:
        products = SHOP_PRODUCTS.get(shop, ())
        if product in products:
            demand += 12.0 if len(products) == 1 else 6.0
    return demand


def _clone_distance(own: Any, opponent: Any) -> float:
    own_assets = _portfolio(own)
    opponent_assets = _portfolio(opponent)
    distance = sum(abs(own_assets[item] - opponent_assets[item]) for item in PORTFOLIO)
    distance += 2.0 * abs(len(_get(own, "hands", []) or []) - len(_get(opponent, "hands", []) or []))
    distance += 3.0 * abs(
        len(set(_get(own, "unlocked_quadrants", []) or []))
        - len(set(_get(opponent, "unlocked_quadrants", []) or []))
    )
    return float(distance)


def _features(obs: Any) -> list[float] | None:
    own, opponent = _farms(obs)
    if own is None or opponent is None:
        return None
    step = _step(obs)
    own_assets = _portfolio(own)
    opponent_assets = _portfolio(opponent)
    shops = [str(value) for value in (_get(_get(obs, "town", {}) or {}, "unlocked_shops", []) or [])]
    market = _get(obs, "market", {}) or {}
    prices = _get(market, "prices", {}) or {}
    inventory = _get(market, "inventory", {}) or {}
    own_money = float(_get(own, "money", 0.0) or 0.0)
    opponent_money = float(_get(opponent, "money", 0.0) or 0.0)
    values = [
        step / 24.0,
        (719 - step) / 24.0,
        own_money,
        opponent_money,
        own_money - opponent_money,
        float(len(_get(own, "hands", []) or [])),
        float(len(_get(opponent, "hands", []) or [])),
        float(len(set(_get(own, "unlocked_quadrants", []) or []))),
        float(len(set(_get(opponent, "unlocked_quadrants", []) or []))),
        float(len(shops)),
        _clone_distance(own, opponent),
    ]
    values.extend(own_assets[item] for item in PORTFOLIO)
    values.extend(opponent_assets[item] for item in PORTFOLIO)
    for item in PORTFOLIO:
        product = PRODUCT[item]
        values.extend(
            (
                _demand_per_day(shops, product),
                float(_get(prices, product, BASE_PRICE[product]) or 0.0) / BASE_PRICE[product],
                (float(_get(inventory, product, 10_000) or 10_000) - 10_000.0)
                / MARKET_SCALE[product],
            )
        )
    if len(values) != len(MODEL["features"]) or not all(math.isfinite(value) for value in values):
        return None
    return values


def _predict_72(obs: Any) -> tuple[list[float], float] | None:
    features = _features(obs)
    if features is None:
        return None
    center = MODEL["feature_mean"]
    scale = MODEL["feature_std"]
    z = [(value - float(mean)) / float(std) for value, mean, std in zip(features, center, scale, strict=True)]
    coefficients = MODEL["models"]["72"]["coefficients"]
    design = [1.0, *z]
    prediction = []
    for target, target_scale in enumerate(MODEL["target_scales"]):
        value = sum(float(row[target]) * feature for row, feature in zip(coefficients, design, strict=True))
        prediction.append(value * float(target_scale))
    return prediction, max(abs(value) for value in z)


def _shops(obs: Any) -> list[str]:
    town = _get(obs, "town", {}) or {}
    return [str(value) for value in (_get(town, "unlocked_shops", []) or [])]


def _update_strategy_goal(obs: Any, state: dict[str, Any]) -> None:
    step = _step(obs)
    if step not in {153, 216}:
        return
    prediction = _predict_72(obs)
    if prediction is None:
        state["last_fallback_reason"] = "missing-or-non-finite-features"
        state["decision_counts"]["model-unavailable"] += 1
        return
    target, max_z = prediction
    tilt = float(target[-1] - target[-2])
    state["last_model"] = {
        "step": step,
        "horizon": 72,
        "animal_tilt": tilt,
        "max_abs_z": max_z,
        "in_support": max_z <= OOD_MAX_ABS_Z,
    }
    if max_z > OOD_MAX_ABS_Z:
        state["last_fallback_reason"] = "strategy-model-ood"
        state["decision_counts"]["ood-to-v110"] += 1
        return
    shops = _shops(obs)
    if (
        ENABLE_SECOND_YARN_VETO
        and step == 153
        and len(shops) >= 2
        and shops[0] != "YARN_STORE"
        and shops[1] == "YARN_STORE"
        and tilt <= SECOND_YARN_MILK_VETO
    ):
        state["route_override"] = "default"
        state["route_gate"] = {
            "step": step,
            "reason": "heldout-72h-milk-veto-of-second-yarn",
            "animal_tilt": tilt,
            "max_abs_z": max_z,
        }
        state["decision_counts"]["second-yarn-veto"] += 1
        return
    if (
        step == 216
        and len(shops) >= 3
        and shops[2] == "YARN_STORE"
        and "YARN_STORE" not in shops[:2]
        and tilt >= THIRD_YARN_WOOL_GATE
    ):
        state["late_goal"] = {
            "step": step,
            "reason": "heldout-72h-third-yarn-wool-goal",
            "animal_tilt": tilt,
            "max_abs_z": max_z,
        }
        state["decision_counts"]["third-yarn-goal"] += 1


def _private(obs: Any) -> Any:
    return _get(obs, "private", {}) or {}


def _shed_count(obs: Any, item: str) -> int:
    return _as_int(_get(_get(_private(obs), "shed", {}) or {}, item, 0))


def _inventories(obs: Any) -> list[Any]:
    return list(_get(_private(obs), "inventories", []) or [])


def _fallback_latched(obs: Any) -> bool:
    try:
        return bool(base.base.policy_diagnostics(obs).get("fallback_latched", False))
    except Exception:
        return True


def _replace_order(order: Any, old: str, new: str, quantity: int) -> bool:
    if not isinstance(order, list) or len(order) < 3:
        return False
    if order[0] != "BUY_ANIMAL" or order[1] != old or _as_int(order[2]) != quantity:
        return False
    order[1] = new
    return True


def _actor_actions(action: dict[str, Any]) -> list[list[Any]]:
    farmer = action.get("farmer")
    hands = list(action.get("hands") or [])
    return [farmer if isinstance(farmer, list) else ["PASS"], *hands]


def _rewrite_late_animals(obs: Any, action: Any, state: dict[str, Any]) -> Any:
    if not isinstance(action, dict) or state.get("late_goal") is None or _fallback_latched(obs):
        return action
    step = _step(obs)
    own, _ = _farms(obs)
    conversion = state.get("conversion")

    if conversion is None:
        if step != LATE_PURCHASE_STEP or own is None:
            return action
        minimum_cash = SHEEP_UNIT_COST * LATE_ANIMAL_QUANTITY + MINIMUM_CASH_AFTER_PURCHASE
        if float(_get(own, "money", 0.0) or 0.0) < minimum_cash:
            state["last_fallback_reason"] = "late-sheep-cash-reserve"
            state["decision_counts"]["mechanical-to-v110"] += 1
            return action
        result = copy.deepcopy(action)
        matches = [
            order
            for order in (result.get("market") or [])
            if isinstance(order, list)
            and len(order) >= 3
            and order[0] == "BUY_ANIMAL"
            and order[1] == "COW"
            and _as_int(order[2]) == LATE_ANIMAL_QUANTITY
        ]
        if len(matches) != 1 or not _replace_order(
            matches[0], "COW", "SHEEP", LATE_ANIMAL_QUANTITY
        ):
            state["last_fallback_reason"] = "unexpected-late-purchase-action"
            state["decision_counts"]["mechanical-to-v110"] += 1
            return action
        state["conversion"] = {
            "purchase_step": step,
            "quantity": LATE_ANIMAL_QUANTITY,
            "picked": 0,
            "placed": 0,
            "carrier_slots": [],
        }
        state["decision_counts"]["cow-to-sheep-purchase"] += 1
        return result

    result = copy.deepcopy(action)
    actors = _actor_actions(result)
    changed = False
    remaining_pickup = int(conversion["quantity"]) - int(conversion["picked"])
    if remaining_pickup > 0 and _shed_count(obs, "SHEEP") >= remaining_pickup:
        for index, actor_action in enumerate(actors):
            if (
                isinstance(actor_action, list)
                and len(actor_action) >= 3
                and actor_action[0] == "PICKUP"
                and actor_action[1] == "COW"
                and 0 < _as_int(actor_action[2]) <= remaining_pickup
            ):
                quantity = _as_int(actor_action[2])
                actor_action[1] = "SHEEP"
                conversion["picked"] = int(conversion["picked"]) + quantity
                conversion["carrier_slots"].append(index)
                state["decision_counts"]["cow-to-sheep-pickup"] += quantity
                changed = True
                break

    inventories = _inventories(obs)
    remaining_place = int(conversion["quantity"]) - int(conversion["placed"])
    if remaining_place > 0:
        for index, actor_action in enumerate(actors):
            inventory = inventories[index] if index < len(inventories) else {}
            if (
                isinstance(actor_action, list)
                and len(actor_action) >= 2
                and actor_action[0] == "PLACE"
                and actor_action[1] == "COW"
                and _as_int(_get(inventory, "SHEEP", 0)) > 0
            ):
                actor_action[1] = "SHEEP"
                conversion["placed"] = int(conversion["placed"]) + 1
                state["decision_counts"]["cow-to-sheep-place"] += 1
                changed = True

    if changed:
        result["farmer"] = actors[0]
        result["hands"] = actors[1:]
        return result
    return action


_ROUTER_POLICY = base.base.public_v43._V43_POLICY
_ROUTER_GLOBALS = _ROUTER_POLICY.__globals__
_ORIGINAL_SELECTED_ROUTE = _ROUTER_GLOBALS["selected_route"]


def _selected_route(obs: Any, configuration: Any) -> str:
    original = str(_ORIGINAL_SELECTED_ROUTE(obs, configuration))
    state = _state_for(obs)
    if state.get("route_override") == "default" and original == "yarn_second":
        return "default"
    return original


def _install_route_gate() -> None:
    # The bundled router looks up selected_route in this retained module
    # dictionary.  Child planners are still called exactly once per turn.
    base.base.public_v43._V43_POLICY.__globals__["selected_route"] = _selected_route


_install_route_gate()


def reset_runtime_state() -> None:
    _RUNTIME.clear()
    base.reset_runtime_state()
    _install_route_gate()


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    state = _RUNTIME.get(_seat(obs), {})
    return {
        **base.policy_diagnostics(obs),
        "version": "v111",
        "strategic_policy": "v110-market-control-plus-heldout-72h-future-goal-gates",
        "strategy_model_protocol": MODEL.get("protocol"),
        "strategy_horizon": 72,
        "strategy_24h_enabled": False,
        "second_yarn_veto_enabled": ENABLE_SECOND_YARN_VETO,
        "strategy_ood_max_abs_z": OOD_MAX_ABS_Z,
        "last_strategy_model": copy.deepcopy(state.get("last_model")),
        "route_gate": copy.deepcopy(state.get("route_gate")),
        "late_goal": copy.deepcopy(state.get("late_goal")),
        "animal_conversion": copy.deepcopy(state.get("conversion")),
        "strategy_fallback_reason": state.get("last_fallback_reason"),
        "strategy_decision_counts": dict(state.get("decision_counts", {})),
    }


def agent(obs: Any, configuration: Any = None) -> dict[str, Any]:
    state = _state_for(obs)
    _update_strategy_goal(obs, state)
    action = base.agent(obs, configuration)
    return _rewrite_late_animals(obs, action, state)


def _kaggle_submission_entrypoint(obs: Any, configuration: Any = None) -> dict[str, Any]:
    return agent(obs, configuration)
