"""Kaggriculture V110: observed-supply market adaptation over V109.

V109's coherent sparse-shop route remains responsible for the farm trajectory
and deterministic execution.  This module adds one bounded strategic expert:
it may move a route-planned premium sale at most four turns earlier when public
state transitions confirm a near-clone.  Opponent supply and sell phases are
still estimated for diagnosis, but phase-only intervention is disabled because
held-out playback did not show positive future quote support.

The controller has three confidence tiers.  Supported market states may use a
front-run, uncertain states execute the unchanged V109 route, and V109's own
critical-state latch retains the model-disabled deterministic rule fallback.
No opponent identity, private inventory, rating, or submission metadata is
used at runtime.
"""

from __future__ import annotations

import copy
import importlib.util
import sys
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

if "__file__" in globals():
    MODULE_DIR = Path(__file__).resolve().parent
else:
    _runtime_candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd() / "agents" / "v110",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (candidate / "v109_base.py").is_file()
            or (candidate.parent / "v109" / "main.py").is_file()
        ),
        Path.cwd(),
    )


def _load_module(name: str, packaged_name: str, repository_source: Path):
    packaged = MODULE_DIR / packaged_name
    source = packaged if packaged.is_file() else repository_source
    spec = importlib.util.spec_from_file_location(name, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V110 dependency: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load_module(
    "_kaggriculture_v110_base",
    "v109_base.py",
    MODULE_DIR.parent / "v109" / "main.py",
)


PREMIUM_ITEMS = ("STRAWBERRY", "MELON", "MILK", "WOOL")
BASE_PRICE = {"STRAWBERRY": 120, "MELON": 250, "MILK": 160, "WOOL": 200}
GLUT_WEIGHT = {"STRAWBERRY": 1.6, "MELON": 3.6, "MILK": 1.6, "WOOL": 3.2}
ITEM_ASSET = {"STRAWBERRY": "STRAWBERRY", "MELON": "MELON", "MILK": "COW", "WOOL": "SHEEP"}
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

FRONT_RUN_HORIZON = 4
CLONE_MIN_CONFIDENCE = 2
SECOND_ORDER_MIN_CONFIDENCE = 3
PHASE_MIN_EVENTS = 3
PHASE_AHEAD_MIN_EVENTS = 4
PHASE_MIN_SHARE = 2.0 / 3.0
PHASE_AHEAD_MIN_SHARE = 0.75
PHASE_HISTORY_LIMIT = 12
PHASE_HISTORY_MAX_AGE = 240
MIN_FRONT_RUN_UNITS = 2

ENABLE_MARKET_ADAPTATION = True
ENABLE_PHASE_FRONT_RUN = False
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


def _iter_tiles(farm: Any):
    for row in _get(farm, "tiles", []) or []:
        if isinstance(row, dict):
            yield row
            continue
        for tile in row or []:
            if isinstance(tile, dict):
                yield tile


def _farm_signature(farm: Any) -> tuple[Any, ...]:
    labels = (
        "COW",
        "SHEEP",
        "GOOSE",
        "WHEAT",
        "CARROT",
        "TOMATO",
        "STRAWBERRY",
        "MELON",
        "PASTURE",
        "COOP",
        "WEED",
    )
    counts: Counter[str] = Counter()
    for tile in _iter_tiles(farm):
        for key in ("animal", "crop", "kind"):
            value = _get(tile, key)
            if value in labels:
                counts[str(value)] += 1
                break
    positions = [_get(farm, "farmer", [0, 0]), *list(_get(farm, "hands", []) or [])]
    normalized_positions = tuple(sorted(tuple(_as_int(value) for value in position[:2]) for position in positions))
    return (
        len(_get(farm, "hands", []) or []),
        tuple(sorted(set(_get(farm, "unlocked_quadrants", []) or []))),
        normalized_positions,
        tuple(counts[label] for label in labels),
    )


def _signature_distance(left: tuple[Any, ...], right: tuple[Any, ...]) -> int:
    distance = abs(int(left[0]) - int(right[0]))
    distance += 3 * abs(len(left[1]) - len(right[1]))
    distance += sum(abs(int(a) - int(b)) for a, b in zip(left[3], right[3], strict=True))
    if left[2] != right[2]:
        distance += 2
    return distance


def _new_state(step: int) -> dict[str, Any]:
    return {
        "last_step": step,
        "clone_confidence": 0,
        "h4_meta_active": False,
        "opponent_sales": {item: [] for item in PREMIUM_ITEMS},
        "previous": None,
        "shifted_targets": set(),
        "last_overlay": None,
        "overlay_counts": Counter(),
        "observed_opponent_units": Counter(),
    }


def _state_for(obs: Any) -> dict[str, Any]:
    seat = _seat(obs)
    step = _step(obs)
    state = _RUNTIME.get(seat)
    if state is None or step == 0 or step < int(state.get("last_step", -1)):
        state = _new_state(step)
        _RUNTIME[seat] = state
    state["last_step"] = step
    state["shifted_targets"] = {
        value for value in state["shifted_targets"] if int(value[0]) >= step
    }
    state["last_overlay"] = None
    return state


def _update_clone_confidence(obs: Any, state: dict[str, Any], own: Any, opponent: Any) -> None:
    step = _step(obs)
    if step not in (4, 24) and not (step >= 48 and step % 24 == 0):
        return
    distance = _signature_distance(_farm_signature(own), _farm_signature(opponent))
    confidence = int(state["clone_confidence"])
    if distance <= 1:
        confidence = min(8, confidence + 1)
    elif distance <= 4:
        confidence = max(0, confidence - 1)
    else:
        confidence = max(0, confidence - 3)
    state["clone_confidence"] = confidence


def _town_demand(step: int, shops: tuple[str, ...], item: str, configuration: Any) -> int:
    shop_interval = max(1, _as_int(_get(configuration, "townShopSellInterval", 4), 4))
    center_interval = max(1, _as_int(_get(configuration, "townCenterSellInterval", 24), 24))
    demand = 0
    if step % shop_interval == 0:
        for shop in shops:
            products = SHOP_PRODUCTS.get(str(shop), ())
            if item in products:
                demand += 2 if len(products) == 1 else 1
    if item != "FERTILIZER" and step % center_interval == 0:
        demand += 1
    return demand


def _shed_access(board_size: int) -> set[tuple[int, int]]:
    half = max(1, int(board_size)) // 2
    return {(half - 1, half - 1), (half, half - 1), (half - 1, half), (half, half)}


def _take(inventory: dict[str, int], item: str, quantity: int) -> int:
    taken = min(max(0, int(quantity)), max(0, int(inventory.get(item, 0))))
    inventory[item] = max(0, int(inventory.get(item, 0)) - taken)
    return taken


def _project_shed(obs: Any, action: Any, configuration: Any) -> dict[str, int]:
    """Project actor transfers before market so inferred opponent supply is conservative."""
    private = _get(obs, "private", {}) or {}
    shed = {
        str(item): max(0, _as_int(quantity))
        for item, quantity in dict(_get(private, "shed", {}) or {}).items()
    }
    inventories = [
        {str(item): max(0, _as_int(quantity)) for item, quantity in dict(inventory or {}).items()}
        for inventory in list(_get(private, "inventories", []) or [])
    ]
    own, _opponent = _farms(obs)
    if own is None:
        return shed
    positions = [_get(own, "farmer", [0, 0]), *list(_get(own, "hands", []) or [])]
    actor_actions = [
        list(_get(action, "farmer", ["PASS"]) or ["PASS"]),
        *[list(value or ["PASS"]) for value in (_get(action, "hands", []) or [])],
    ]
    while len(inventories) < len(positions):
        inventories.append({})
    tiles = list(_get(own, "tiles", []) or [])
    access = _shed_access(len(tiles) or 10)
    capacity = max(1, _as_int(_get(configuration, "shedCapacity", 100), 100))
    for index, raw_action in enumerate(actor_actions):
        if index >= len(positions) or index >= len(inventories) or not raw_action:
            continue
        position = positions[index]
        if not isinstance(position, list | tuple) or len(position) < 2:
            continue
        x, y = _as_int(position[0]), _as_int(position[1])
        if (x, y) not in access:
            continue
        inventory = inventories[index]
        operation = str(raw_action[0])
        if operation == "DROP":
            for item, quantity in list(inventory.items()):
                room = max(0, capacity - sum(shed.values()))
                deposited = min(max(0, int(quantity)), room)
                shed[item] = shed.get(item, 0) + deposited
                inventory[item] = 0
        elif operation == "PICKUP" and len(raw_action) >= 2:
            item = str(raw_action[1])
            requested = _as_int(raw_action[2], 1) if len(raw_action) >= 3 else 1
            taken = _take(shed, item, requested)
            inventory[item] = inventory.get(item, 0) + taken
        elif operation == "PLACE" and len(raw_action) >= 2:
            item = str(raw_action[1])
            requested = _as_int(raw_action[2], 1) if len(raw_action) >= 3 else 1
            room = max(0, capacity - sum(shed.values()))
            deposited = _take(inventory, item, min(requested, room))
            shed[item] = shed.get(item, 0) + deposited
    return shed


def _effective_sell(action: Any, shed: dict[str, int], item: str) -> int:
    available = max(0, int(shed.get(item, 0)))
    sold = 0
    for order in (_get(action, "market", []) or [])[:10]:
        if not isinstance(order, list | tuple) or len(order) < 3:
            continue
        if order[0] == "SELL" and str(order[1]) == item:
            quantity = min(available, max(0, _as_int(order[2])))
            sold += quantity
            available -= quantity
    return sold


def _observe_opponent_sales(
    obs: Any,
    configuration: Any,
    state: dict[str, Any],
) -> dict[str, int]:
    previous = state.get("previous")
    if not isinstance(previous, dict) or int(previous.get("step", -2)) != _step(obs) - 1:
        return {}
    market = _get(obs, "market", {}) or {}
    current_inventory = _get(market, "inventory", {}) or {}
    current_prices = _get(market, "prices", {}) or {}
    supplies: dict[str, int] = {}
    for item in PREMIUM_ITEMS:
        # At the $1 floor, official sales stop increasing public inventory.
        if float(previous["prices"].get(item, 1) or 1) <= 1 or float(current_prices.get(item, 1) or 1) <= 1:
            continue
        own_supply = _effective_sell(previous["action"], previous["projected_shed"], item)
        demand = _town_demand(previous["step"], previous["shops"], item, previous["configuration"])
        delta = _as_int(current_inventory.get(item)) - _as_int(previous["inventory"].get(item))
        opponent_supply = max(0, delta + demand - own_supply)
        if opponent_supply <= 0:
            continue
        supplies[item] = opponent_supply
        events = list(state["opponent_sales"][item])
        events.append((int(previous["step"]), int(previous["step"]) % 4, opponent_supply))
        cutoff = _step(obs) - PHASE_HISTORY_MAX_AGE
        state["opponent_sales"][item] = [event for event in events if event[0] >= cutoff][
            -PHASE_HISTORY_LIMIT:
        ]
        state["observed_opponent_units"][item] += opponent_supply

    overlay = previous.get("overlay")
    if (
        isinstance(overlay, dict)
        and overlay.get("mode") == "clone-h4"
        and int(state["clone_confidence"]) >= SECOND_ORDER_MIN_CONFIDENCE
    ):
        item = str(overlay["item"])
        own_units = max(0, int(overlay["quantity"]))
        opponent_units = int(supplies.get(item, 0))
        if own_units >= MIN_FRONT_RUN_UNITS and opponent_units >= MIN_FRONT_RUN_UNITS:
            ratio = opponent_units / max(1, own_units)
            if 0.40 <= ratio <= 2.50:
                state["h4_meta_active"] = True
    return supplies


def _remember(obs: Any, action: dict[str, Any], configuration: Any, state: dict[str, Any]) -> None:
    market = _get(obs, "market", {}) or {}
    shops = tuple(str(value) for value in (_get(_get(obs, "town", {}) or {}, "unlocked_shops", []) or []))
    state["previous"] = {
        "step": _step(obs),
        "inventory": dict(_get(market, "inventory", {}) or {}),
        "prices": dict(_get(market, "prices", {}) or {}),
        "shops": shops,
        "action": copy.deepcopy(action),
        "projected_shed": _project_shed(obs, action, configuration),
        "configuration": configuration,
        "overlay": copy.deepcopy(state.get("last_overlay")),
    }


def _route_name(obs: Any) -> str:
    policy = getattr(base.public_v43, "_V43_POLICY", None)
    states = getattr(policy, "states", {})
    selected = states.get(_seat(obs), {}) if isinstance(states, dict) else {}
    route = selected.get("route") if isinstance(selected, dict) else None
    if route in {"default", "yarn_first", "yarn_second"}:
        return str(route)
    shops = list(_get(_get(obs, "town", {}) or {}, "unlocked_shops", []) or [])
    step = _step(obs)
    if shops and shops[0] == "YARN_STORE" and step >= 88:
        return "yarn_first"
    if len(shops) >= 2 and shops[0] != "YARN_STORE" and shops[1] == "YARN_STORE" and step >= 153:
        return "yarn_second"
    return "default"


def _trace_sell_quantity(route: str, step: int, item: str) -> int:
    routes = getattr(base.public_v43, "_V43_ROUTES", {})
    actions = routes.get(route, []) if isinstance(routes, dict) else []
    if not (0 <= step < len(actions)):
        return 0
    return sum(
        max(0, _as_int(order[2]))
        for order in ((actions[step] or {}).get("market", []) or [])
        if isinstance(order, list | tuple)
        and len(order) >= 3
        and order[0] == "SELL"
        and str(order[1]) == item
    )


def _planned_sales(route: str, step: int) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    routes = getattr(base.public_v43, "_V43_ROUTES", {})
    actions = routes.get(route, []) if isinstance(routes, dict) else []
    for distance in range(1, FRONT_RUN_HORIZON + 1):
        future = step + distance
        if future >= len(actions):
            break
        for order in ((actions[future] or {}).get("market", []) or []):
            if not (
                isinstance(order, list | tuple)
                and len(order) >= 3
                and order[0] == "SELL"
                and str(order[1]) in PREMIUM_ITEMS
            ):
                continue
            item = str(order[1])
            quantity = max(0, _as_int(order[2]))
            if item not in result:
                result[item] = {"distance": distance, "quantity": quantity, "target": future}
            else:
                result[item]["quantity"] += quantity
    return result


def _existing_sales(action: dict[str, Any]) -> Counter[str]:
    result: Counter[str] = Counter()
    for order in action.get("market", []) or []:
        if isinstance(order, list | tuple) and len(order) >= 3 and order[0] == "SELL":
            result[str(order[1])] += max(0, _as_int(order[2]))
    return result


def _asset_count(farm: Any, asset: str) -> int:
    return sum(
        _get(tile, "crop") == asset or _get(tile, "animal") == asset
        for tile in _iter_tiles(farm)
    )


def _phase_support(
    *,
    obs: Any,
    configuration: Any,
    state: dict[str, Any],
    opponent: Any,
    item: str,
    sale_distance: int,
) -> dict[str, Any] | None:
    events = list(state["opponent_sales"][item])
    own, _ = _farms(obs)
    farms = list(_get(obs, "farms", []) or [])
    opponent_money = float(_get(opponent, "money", 0) or 0)
    own_money = float(_get(own, "money", 0) or 0) if own is not None else 0.0
    ahead = own_money >= opponent_money + 5_000.0
    minimum_events = PHASE_AHEAD_MIN_EVENTS if ahead else PHASE_MIN_EVENTS
    minimum_share = PHASE_AHEAD_MIN_SHARE if ahead else PHASE_MIN_SHARE
    if len(events) < minimum_events or len(farms) < 2:
        return None
    phase_counts = Counter(int(event[1]) for event in events)
    dominant_phase, count = max(phase_counts.items(), key=lambda value: (value[1], -value[0]))
    share = count / len(events)
    if share < minimum_share:
        return None
    current_phase = _step(obs) % 4
    opponent_distance = (dominant_phase - current_phase) % 4
    # A phase preference alone does not establish that the opponent sells on
    # every four-turn cycle.  Only preempt a route sale on the next turn when
    # the opponent sold on this exact phase in both immediately prior cycles.
    if opponent_distance != 0 or sale_distance != 1:
        return None
    recent_by_step = {int(event[0]): int(event[2]) for event in events}
    required_steps = (_step(obs) - 4,)
    if any(required not in recent_by_step for required in required_steps):
        return None
    phase_units = [recent_by_step[required] for required in required_steps]
    predicted_units = float(median(phase_units)) if phase_units else 0.0
    shops = tuple(str(value) for value in (_get(_get(obs, "town", {}) or {}, "unlocked_shops", []) or []))
    visible_demand = sum(
        _town_demand(_step(obs) + offset, shops, item, configuration)
        for offset in range(max(0, sale_distance))
    )
    if predicted_units < visible_demand + MIN_FRONT_RUN_UNITS:
        return None
    if _asset_count(opponent, ITEM_ASSET[item]) < 2:
        return None
    return {
        "events": len(events),
        "phase": dominant_phase,
        "phase_share": share,
        "predicted_units": predicted_units,
        "visible_demand": visible_demand,
        "opponent_distance": opponent_distance,
        "ahead_mode": ahead,
    }


def _second_order_candidate(
    obs: Any,
    action: dict[str, Any],
    state: dict[str, Any],
    route: str,
    configuration: Any,
) -> dict[str, Any] | None:
    if not state["h4_meta_active"] or int(state["clone_confidence"]) < SECOND_ORDER_MIN_CONFIDENCE:
        return None
    target = _step(obs) + FRONT_RUN_HORIZON + 1
    shops = tuple(str(value) for value in (_get(_get(obs, "town", {}) or {}, "unlocked_shops", []) or []))
    existing = _existing_sales(action)
    shed = _get(_get(obs, "private", {}) or {}, "shed", {}) or {}
    prices = _get(_get(obs, "market", {}) or {}, "prices", {}) or {}
    rows = []
    for item in PREMIUM_ITEMS:
        planned = _trace_sell_quantity(route, target, item)
        if planned <= 0 or existing[item] > 0:
            continue
        if _town_demand(_step(obs), shops, item, configuration) > 0:
            continue
        quantity = min(max(0, _as_int(shed.get(item))), planned)
        price = float(prices.get(item, BASE_PRICE[item]) or 0)
        if quantity < MIN_FRONT_RUN_UNITS or price <= 1:
            continue
        rows.append((price * quantity * GLUT_WEIGHT[item], item, quantity))
    if not rows:
        return None
    _priority, item, quantity = max(rows)
    return {"mode": "clone-h5", "item": item, "quantity": quantity, "target": target}


def _front_run(
    obs: Any,
    action: dict[str, Any],
    configuration: Any,
    state: dict[str, Any],
    opponent: Any,
) -> dict[str, Any]:
    result = copy.deepcopy(action)
    market_orders = [list(order) for order in (result.get("market", []) or [])]
    max_orders = max(1, _as_int(_get(configuration, "maxMarketOrdersPerTurn", 10), 10))
    if not ENABLE_MARKET_ADAPTATION or len(market_orders) >= max_orders:
        return result
    route = _route_name(obs)
    candidate = _second_order_candidate(obs, result, state, route, configuration)
    planned = _planned_sales(route, _step(obs))
    existing = _existing_sales(result)
    shed = _get(_get(obs, "private", {}) or {}, "shed", {}) or {}
    prices = _get(_get(obs, "market", {}) or {}, "prices", {}) or {}
    choices: list[tuple[float, dict[str, Any]]] = []
    if candidate is None:
        for item, plan in planned.items():
            key = (int(plan["target"]), item)
            if key in state["shifted_targets"] or existing[item] > 0:
                continue
            available = max(0, _as_int(shed.get(item)))
            quantity = min(available, max(0, int(plan["quantity"])))
            price = float(prices.get(item, BASE_PRICE[item]) or 0)
            if quantity < MIN_FRONT_RUN_UNITS or price <= 1:
                continue
            mode = None
            evidence: dict[str, Any] = {}
            if int(state["clone_confidence"]) >= CLONE_MIN_CONFIDENCE:
                mode = "clone-h4"
                evidence = {"clone_confidence": int(state["clone_confidence"])}
            elif ENABLE_PHASE_FRONT_RUN:
                phase = _phase_support(
                    obs=obs,
                    configuration=configuration,
                    state=state,
                    opponent=opponent,
                    item=item,
                    sale_distance=int(plan["distance"]),
                )
                if phase is not None:
                    mode = "phase-front-run"
                    evidence = phase
            if mode is None:
                continue
            priority = (
                price * quantity * GLUT_WEIGHT[item]
                + (FRONT_RUN_HORIZON + 1 - int(plan["distance"])) * BASE_PRICE[item]
            )
            choices.append(
                (
                    priority,
                    {
                        "mode": mode,
                        "item": item,
                        "quantity": quantity,
                        "target": int(plan["target"]),
                        "distance": int(plan["distance"]),
                        "price": price,
                        "evidence": evidence,
                    },
                )
            )
        if choices:
            _priority, candidate = max(choices, key=lambda row: (row[0], row[1]["item"]))
    if candidate is None:
        return result
    # Put the strategic sale in slot zero.  SELL raises cash and cannot make a
    # later route purchase infeasible; the cap was checked above.
    result["market"] = [
        ["SELL", str(candidate["item"]), int(candidate["quantity"])],
        *market_orders,
    ][:max_orders]
    state["shifted_targets"].add((int(candidate["target"]), str(candidate["item"])))
    state["last_overlay"] = copy.deepcopy(candidate)
    state["overlay_counts"][str(candidate["mode"])] += 1
    return result


def reset_runtime_state() -> None:
    _RUNTIME.clear()
    base.reset_runtime_state()


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    seat = _seat(obs)
    state = _RUNTIME.get(seat, {})
    base_diagnostic = base.policy_diagnostics(obs)
    profiles = {}
    for item in PREMIUM_ITEMS:
        events = list((state.get("opponent_sales") or {}).get(item, []))
        phase_counts = Counter(int(event[1]) for event in events)
        profiles[item] = {
            "events": len(events),
            "units": sum(int(event[2]) for event in events),
            "phase_counts": dict(sorted(phase_counts.items())),
        }
    return {
        **base_diagnostic,
        "version": "v110",
        "strategic_policy": "v109-route-plus-observed-supply-market-controller",
        "market_confidence_tiers": "front-run / coherent-v109 / deterministic-critical-fallback",
        "market_adaptation_enabled": ENABLE_MARKET_ADAPTATION,
        "phase_front_run_enabled": ENABLE_PHASE_FRONT_RUN,
        "clone_confidence": int(state.get("clone_confidence", 0)),
        "second_order_active": bool(state.get("h4_meta_active", False)),
        "last_overlay": copy.deepcopy(state.get("last_overlay")),
        "overlay_counts": dict(state.get("overlay_counts", {})),
        "opponent_sale_profiles": profiles,
    }


def agent(obs: Any, configuration: Any = None) -> dict[str, Any]:
    action = base.agent(obs, configuration)
    own, opponent = _farms(obs)
    if own is None or opponent is None or not isinstance(action, dict):
        return action
    state = _state_for(obs)
    _update_clone_confidence(obs, state, own, opponent)
    _observe_opponent_sales(obs, configuration, state)
    base_diagnostic = base.policy_diagnostics(obs)
    if bool(base_diagnostic.get("fallback_latched", False)):
        result = action
    else:
        result = _front_run(obs, action, configuration, state, opponent)
    _remember(obs, result, configuration, state)
    return result


def _kaggle_submission_entrypoint(obs: Any, configuration: Any = None) -> dict[str, Any]:
    return agent(obs, configuration)
