"""V124: current-meta policy segments with a gated sale forecast experiment.

V124 keeps V123's executor and safety overlays, but replaces its broad farm
clone rule with a direct opponent-sale model experiment.  That intervention
is disabled in the promoted policy because cross-submission holdout did not
meet its precision/coverage gate.  A three-day state-compatible source latch
was also implemented, but is disabled after losing to library-only routing on
fresh paired seeds.  The promoted change is therefore the continuation library
rebuilt from V123's current live opponents.  Every runtime input is available
in the current or a past observation; identities, ratings, outcomes, and
future state are absent.
"""

from __future__ import annotations

import copy
import gzip
import importlib.util
import json
import math
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ENABLE_CURRENT_META_LIBRARY = True
ENABLE_SEGMENT_ROUTER = False
ENABLE_SELL_FORECAST = False

SEGMENT_GATES = (288, 360, 432, 504, 576, 648)
SEGMENT_MISMATCH_TOLERANCE = 1_000
SELL_MODEL_FORMAT = "v124-opponent-sell-v1"
PREEMPT_ITEMS = ("STRAWBERRY", "MILK", "WOOL")
BASE_PRICE = {"STRAWBERRY": 120.0, "MILK": 160.0, "WOOL": 200.0}
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


def _module_dir() -> Path:
    if "__file__" in globals():
        return Path(__file__).resolve().parent
    candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd() / "agents" / "v124",
        Path.cwd(),
    )
    return next(
        (
            candidate.resolve()
            for candidate in candidates
            if (candidate / "v123_base.py").is_file() or (candidate.parent / "v123" / "main.py").is_file()
        ),
        Path.cwd(),
    )


def _load(name: str, packaged_name: str, repository: Path) -> Any:
    packaged = _module_dir() / packaged_name
    source = packaged if packaged.is_file() else repository
    spec = importlib.util.spec_from_file_location(name, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[2] if "__file__" in globals() else Path.cwd()
base = _load("_v124_v123", "v123_base.py", ROOT / "agents/v123/main.py")
sparse = base.sparse
market = base.market
base.ENABLE_CLONE_PREEMPTION = False

_V123_CHOOSE_ROW = base._coherent_choose_row
_NEAREST_CHOOSE_ROW = base._ORIGINAL_CHOOSE_ROW
_FORECAST_STATE: dict[int, dict[str, Any]] = {0: {}, 1: {}}
_SELL_MODEL: dict[str, Any] | None = None


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _seat(observation: Mapping[str, Any]) -> int:
    return 1 if _integer(observation.get("player")) == 1 else 0


def _canonical_observation(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Use the game clock rather than the seat-dependent framework field."""
    result = dict(observation)
    result["step"] = 24 * _integer(observation.get("day")) + _integer(observation.get("hour"))
    return result


def _artifact_path(name: str) -> Path:
    packaged = _module_dir() / name
    repository = ROOT / "agents/v124" / name
    return packaged if packaged.is_file() else repository


def _install_policy_model() -> None:
    if not ENABLE_CURRENT_META_LIBRARY:
        return
    path = _artifact_path("policy_model.json.gz")
    if not path.is_file():
        return
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        model = json.load(stream)
    if model.get("format") != sparse.MODEL_FORMAT:
        raise RuntimeError("v124 continuation model format mismatch")
    if _integer(model.get("feature_length")) != sparse.FEATURE_LENGTH:
        raise RuntimeError("v124 continuation feature schema mismatch")
    sparse._MODEL = model


_install_policy_model()


def _segment_choose_row(
    observation: Mapping[str, Any],
    rows: Sequence[list[Any]],
    query: Sequence[int],
) -> list[Any]:
    if not ENABLE_SEGMENT_ROUTER:
        return _V123_CHOOSE_ROW(observation, rows, query)

    nearest = _NEAREST_CHOOSE_ROW(observation, rows, query)
    step = _integer(observation.get("step"))
    nearest_source = _integer(nearest[sparse.ROW_SOURCE], -1)
    state = sparse._STATE
    if step < sparse.OPENING_END:
        state["last_action_source"] = nearest_source
        return nearest

    if state.get("segment_source") is None or step in SEGMENT_GATES:
        state["segment_source"] = nearest_source
        state["segment_selected_at"] = step
        state["segment_switches"] = _integer(state.get("segment_switches")) + int(
            state.get("last_segment_source") not in {None, nearest_source}
        )
        state["last_segment_source"] = nearest_source

    source = _integer(state.get("segment_source"), nearest_source)
    pool = sparse._route_pool(sparse._compatible_units(rows, observation), step)
    active_rows = [row for row in pool if _integer(row[sparse.ROW_SOURCE], -1) == source]
    if not active_rows:
        state["segment_unavailable"] = _integer(state.get("segment_unavailable")) + 1
        state["last_action_source"] = nearest_source
        state["active_source"] = nearest_source
        return nearest

    active = min(active_rows, key=lambda row: sparse.base.feature_distance(query, row[sparse.ROW_FEATURES]))
    nearest_distance = sparse.base.feature_distance(query, nearest[sparse.ROW_FEATURES])
    active_distance = sparse.base.feature_distance(query, active[sparse.ROW_FEATURES])
    state["segment_distance"] = active_distance
    state["nearest_distance"] = nearest_distance
    if active_distance > nearest_distance + SEGMENT_MISMATCH_TOLERANCE:
        state["segment_emergency_fallbacks"] = _integer(state.get("segment_emergency_fallbacks")) + 1
        state["last_action_source"] = nearest_source
        state["active_source"] = source
        return nearest

    state["segment_holds"] = _integer(state.get("segment_holds")) + 1
    state["last_action_source"] = source
    state["active_source"] = source
    return active


sparse._choose_row = _segment_choose_row


def _load_sell_model() -> dict[str, Any]:
    global _SELL_MODEL
    if _SELL_MODEL is None:
        path = _artifact_path("opponent_sell_model.json")
        if not path.is_file():
            raise FileNotFoundError("v124 opponent_sell_model.json was not found")
        model = json.loads(path.read_text(encoding="utf-8"))
        if model.get("format") != SELL_MODEL_FORMAT:
            raise RuntimeError("v124 opponent sale model format mismatch")
        _SELL_MODEL = model
    return _SELL_MODEL


def _town_drain(observation: Mapping[str, Any], item: str, step: int) -> int:
    quantity = 0
    if step % 4 == 0:
        shops = list(_mapping(observation.get("town")).get("unlocked_shops") or [])
        for shop in shops:
            products = SHOP_PRODUCTS.get(str(shop), ())
            if item in products:
                quantity += 2 if len(products) == 1 else 1
    if step % 24 == 0:
        quantity += 1
    return quantity


def _sell_quantity(action: Mapping[str, Any], item: str) -> int:
    return sum(
        max(0, _integer(order[2]))
        for order in action.get("market") or []
        if isinstance(order, list | tuple) and len(order) >= 3 and order[0] == "SELL" and str(order[1]) == item
    )


def _forecast_state(observation: Mapping[str, Any]) -> dict[str, Any]:
    seat = _seat(observation)
    step = _integer(observation.get("step"))
    state = _FORECAST_STATE.setdefault(seat, {})
    if step == 0 or step < _integer(state.get("last_step"), -1):
        state.clear()
    state.setdefault("history", {item: [] for item in PREEMPT_ITEMS})
    state.setdefault("money_history", {})
    state.setdefault("shifted_targets", set())
    state.setdefault("preemptions", 0)
    state.setdefault("preemption_units", Counter())
    state["shifted_targets"] = {value for value in state["shifted_targets"] if _integer(value[0]) >= step}
    return state


def _observe_market(observation: Mapping[str, Any], state: dict[str, Any]) -> None:
    step = _integer(observation.get("step"))
    if state.get("observed_step") == step:
        return
    previous = state.get("previous_observation")
    previous_action = state.get("previous_action")
    if isinstance(previous, Mapping) and isinstance(previous_action, Mapping):
        previous_step = _integer(previous.get("step"), step - 1)
        previous_inventory = _mapping(_mapping(previous.get("market")).get("inventory"))
        current_inventory = _mapping(_mapping(observation.get("market")).get("inventory"))
        previous_prices = _mapping(_mapping(previous.get("market")).get("prices"))
        projected = market._projected_shed(previous, previous_action)
        for item in PREEMPT_ITEMS:
            delta = _integer(current_inventory.get(item), 10_000) - _integer(previous_inventory.get(item), 10_000)
            own_supply = 0
            if _integer(previous_prices.get(item)) > 1:
                own_supply = min(_integer(projected.get(item)), _sell_quantity(previous_action, item))
            inferred = max(0, delta - own_supply + _town_drain(previous, item, previous_step))
            if inferred:
                state["history"][item].append((step, inferred))
            state["history"][item] = [event for event in state["history"][item] if _integer(event[0]) >= step - 96]

    farms = list(observation.get("farms") or [])
    opponent = _mapping(farms[1 - _seat(observation)]) if len(farms) > 1 else {}
    state["money_history"][step] = _integer(opponent.get("money"))
    state["money_history"] = {
        event_step: money for event_step, money in state["money_history"].items() if _integer(event_step) >= step - 8
    }
    state["observed_step"] = step


def _farm_stats(farm: Mapping[str, Any], item: str) -> tuple[int, int, int, int]:
    asset = {"MILK": "COW", "WOOL": "SHEEP"}.get(item, item)
    count = total_yield = ready = serviced = 0
    for row in farm.get("tiles") or []:
        for raw in row or []:
            tile = _mapping(raw)
            if tile.get("crop") != asset and tile.get("animal") != asset:
                continue
            count += 1
            quantity = max(0, _integer(tile.get("yield_units")))
            total_yield += quantity
            ready += int(quantity > 0)
            serviced += int(bool(tile.get("watered_today") or tile.get("fed_today")))
    return count, total_yield, ready, serviced


def _sale_features(
    observation: Mapping[str, Any],
    state: Mapping[str, Any],
    item: str,
    planned: int,
    available: int,
) -> list[float]:
    step = _integer(observation.get("step"))
    seat = _seat(observation)
    farms = list(observation.get("farms") or [])
    own = _mapping(farms[seat]) if seat < len(farms) else {}
    opponent = _mapping(farms[1 - seat]) if len(farms) > 1 else {}
    opponent_asset, opponent_yield, opponent_ready, opponent_service = _farm_stats(opponent, item)
    own_asset, own_yield, own_ready, _own_service = _farm_stats(own, item)
    market_data = _mapping(observation.get("market"))
    market_inventory = _integer(_mapping(market_data.get("inventory")).get(item), 10_000)
    price = float(_mapping(market_data.get("prices")).get(item, 0) or 0)
    shops = list(_mapping(observation.get("town")).get("unlocked_shops") or [])
    demand = sum(item in SHOP_PRODUCTS.get(str(shop), ()) for shop in shops)
    events = list(_mapping(state.get("history")).get(item) or [])
    gaps = [
        step - _integer(event_step)
        for event_step, quantity in events
        if _integer(event_step) <= step and _integer(quantity) > 0
    ]
    gap = min(gaps) if gaps else 96
    recent = [
        sum(_integer(quantity) for event_step, quantity in events if step - window < _integer(event_step) <= step)
        for window in (1, 2, 4, 8, 12, 24, 48)
    ]
    money_history = _mapping(state.get("money_history"))
    opponent_money = _integer(opponent.get("money"))
    own_money = _integer(own.get("money"))
    previous_money = _integer(money_history.get(max(0, step - 1)), opponent_money)
    previous_four_money = _integer(money_history.get(max(0, step - 4)), opponent_money)
    features = [
        1.0,
        step / 720.0,
        (step // 24) / 30.0,
        opponent_asset / 20.0,
        opponent_yield / 50.0,
        opponent_ready / 20.0,
        opponent_service / 20.0,
        own_asset / 20.0,
        own_yield / 50.0,
        own_ready / 20.0,
        abs(opponent_asset - own_asset) / 20.0,
        (opponent_money - own_money) / 100_000.0,
        opponent_money / 100_000.0,
        (opponent_money - previous_money) / 10_000.0,
        (opponent_money - previous_four_money) / 20_000.0,
        (market_inventory - 10_000) / 1_000.0,
        price / BASE_PRICE[item],
        demand / 8.0,
        min(gap, 96) / 96.0,
        *(quantity / 50.0 for quantity in recent),
        min(planned, 100) / 50.0,
        min(available, 100) / 50.0,
    ]
    features.extend(float(step % 24 == hour) for hour in range(24))
    features.extend(float(step // 24 == day) for day in range(30))
    return features


def _sell_probability(features: Sequence[float], item: str) -> float:
    model = _load_sell_model()
    if len(features) != _integer(model.get("feature_length")):
        return 0.0
    head = _mapping(_mapping(model.get("models")).get(item))
    mean = list(head.get("mean") or [])
    scale = list(head.get("scale") or [])
    weights = list(head.get("weights") or [])
    if not (len(features) == len(mean) == len(scale) == len(weights)):
        return 0.0
    linear = sum(
        ((float(value) - float(center)) / max(1e-9, float(width))) * float(weight)
        for value, center, width, weight in zip(features, mean, scale, weights, strict=True)
    )
    linear = max(-30.0, min(30.0, linear))
    return 1.0 / (1.0 + math.exp(-linear))


def _forecast_market_overlay(
    observation: Mapping[str, Any], action: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    step = _integer(observation.get("step"))
    if not ENABLE_SELL_FORECAST or step < sparse.OPENING_END:
        return action
    source = _integer(sparse._STATE.get("active_source"), -1)
    if source < 0:
        return action

    result = copy.deepcopy(action)
    orders = [list(order) for order in result.get("market") or []]
    if len(orders) >= 10:
        return result
    existing = {str(order[1]) for order in orders if len(order) >= 3 and order[0] == "SELL"}
    available = market._projected_shed(observation, result)
    prices = _mapping(_mapping(observation.get("market")).get("prices"))
    threshold = float(_load_sell_model().get("threshold", 0.70))
    choices: list[tuple[float, float, str, int, int]] = []
    for item in PREEMPT_ITEMS:
        if item in existing or _integer(available.get(item)) < 2:
            continue
        plan = base._planned_next_turn_sale(item, step, source)
        if plan is None:
            continue
        target, planned = plan
        if (target, item) in state["shifted_targets"]:
            continue
        quantity = min(_integer(available.get(item)), _integer(planned))
        price = max(0.0, float(prices.get(item, 0) or 0))
        if quantity < 2 or price <= 1:
            continue
        if base._town_consumes_at(observation, item, step) or base._town_consumes_at(observation, item, target):
            continue
        probability = _sell_probability(_sale_features(observation, state, item, planned, quantity), item)
        if probability < threshold:
            continue
        choices.append((probability * price * quantity, probability, item, quantity, target))
    if not choices:
        return result

    _score, probability, item, quantity, target = max(choices)
    result["market"] = [["SELL", item, quantity], *orders][:10]
    state["shifted_targets"].add((target, item))
    state["preemptions"] = _integer(state.get("preemptions")) + 1
    state["preemption_units"][item] += quantity
    state["last_preemption"] = {
        "step": step,
        "target": target,
        "item": item,
        "quantity": quantity,
        "opponent_sell_probability": probability,
    }
    return result


def reset_runtime_state() -> None:
    base.reset_runtime_state()
    _FORECAST_STATE.clear()
    _FORECAST_STATE.update({0: {}, 1: {}})


def policy_diagnostics(observation: Mapping[str, Any]) -> dict[str, Any]:
    canonical = _canonical_observation(observation)
    state = _FORECAST_STATE.get(_seat(canonical), {})
    return {
        "version": "v124",
        "canonical_step": canonical["step"],
        "current_meta_library": ENABLE_CURRENT_META_LIBRARY,
        "segment_router": ENABLE_SEGMENT_ROUTER,
        "segment_source": sparse._STATE.get("segment_source"),
        "segment_selected_at": sparse._STATE.get("segment_selected_at"),
        "segment_holds": _integer(sparse._STATE.get("segment_holds")),
        "segment_emergency_fallbacks": _integer(sparse._STATE.get("segment_emergency_fallbacks")),
        "segment_unavailable": _integer(sparse._STATE.get("segment_unavailable")),
        "sell_forecast": ENABLE_SELL_FORECAST,
        "inferred_sale_events": {
            item: len(list(_mapping(state.get("history")).get(item) or [])) for item in PREEMPT_ITEMS
        },
        "preemptions": _integer(state.get("preemptions")),
        "preemption_units": dict(state.get("preemption_units", {})),
        "last_preemption": copy.deepcopy(state.get("last_preemption")),
        "market": market.policy_diagnostics(canonical),
    }


def agent(observation: Mapping[str, Any], configuration: Any = None) -> dict[str, Any]:
    canonical = _canonical_observation(observation)
    state = _forecast_state(canonical)
    try:
        _observe_market(canonical, state)
        action = market.agent(canonical, configuration)
        action = _forecast_market_overlay(canonical, action, state)
        action = sparse.base._normalize_output(action, canonical)
    except Exception:
        action = sparse.base._normalize_output({}, canonical)
    state["previous_observation"] = copy.deepcopy(canonical)
    state["previous_action"] = copy.deepcopy(action)
    state["last_step"] = _integer(canonical.get("step"))
    return action


def _kaggle_submission_entrypoint(observation: Mapping[str, Any], configuration: Any = None) -> dict[str, Any]:
    return agent(observation, configuration)


if __name__ == "__main__":
    for line in sys.stdin:
        if line.strip():
            request = json.loads(line)
            result = agent(request.get("observation", request), request.get("configuration"))
            print(json.dumps(result), flush=True)
