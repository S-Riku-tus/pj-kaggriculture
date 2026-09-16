"""Kaggriculture V117: bounded late land-order resequencing over V111.

V111 remains the complete policy and production Champion.  V117 changes only
one V111-owned late market transaction.  When the current action already sells
Melon and buys exactly two Cows, the current farm owns exactly two quadrants,
and a conservative sequential-order preflight leaves the inherited 500-coin
reserve, V117 appends BUY_LAND to that transaction.  Once the third quadrant is
observably unlocked, the later duplicate V111 BUY_LAND order is removed.

No step, seed, source, opponent identity, replay signature, future state, or
opponent-private value is used.  All field and hand actions, the Cow purchase,
pickup/place/feed continuation, and every unrelated market order remain V111.
"""

from __future__ import annotations

import copy
import importlib.util
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
        Path.cwd() / "agents" / "v117",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (candidate / "v111_base.py").is_file()
            or (candidate.parent / "v111" / "main.py").is_file()
        ),
        Path.cwd(),
    )


def _load_module(name: str, packaged_name: str, repository_source: Path):
    packaged = MODULE_DIR / packaged_name
    source = packaged if packaged.is_file() else repository_source
    spec = importlib.util.spec_from_file_location(name, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V117 dependency: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load_module(
    "_kaggriculture_v117_base",
    "v111_base.py",
    MODULE_DIR.parent / "v111" / "main.py",
)

CONTRACT_NAME = "midgame_land_cash_reserve_live_trial"
IMPLEMENTATION = "late_land_order_resequence"
LAND_COST = 2_000
COW_QUANTITY = 2
COW_UNIT_COST = 400
# This is inherited from V111's frozen late-transaction mechanical reserve.
MINIMUM_CASH_AFTER_TRANSACTION = 500
STANDARD_CONFIGURATION = {
    "episodeSteps": 720,
    "boardSize": 10,
    "startingMoney": 3_000,
    "maxMarketOrdersPerTurn": 10,
    "turnsPerDay": 24,
    "shedCapacity": 100,
}
MELON_PARAMS = {
    "base": 250.0,
    "I0": 10_000.0,
    "T": 300.0,
    "below_func": "log",
    "below_target": 0.2,
    "above_func": "sq",
    "above_target": 3.6,
}
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


def _farm(obs: Any) -> Any | None:
    farms = list(_get(obs, "farms", []) or [])
    seat = _seat(obs)
    return farms[seat] if seat < len(farms) else None


def _private(obs: Any) -> Any:
    return _get(obs, "private", {}) or {}


def _new_state(step: int) -> dict[str, Any]:
    return {
        "last_step": step,
        "phase": "BASELINE",
        "trigger_requests": 0,
        "safe_cancels": Counter(),
        "commits": 0,
        "commit_step": None,
        "preflight": None,
        "pre_unlocked": [],
        "pre_cows": 0,
        "land_confirmed_step": None,
        "cow_confirmed_step": None,
        "new_quadrant": None,
        "duplicate_land_removed": 0,
        "duplicate_land_removed_step": None,
        "first_productive_action": None,
        "cow_pickups": 0,
        "cow_places": 0,
        "feed_actions_after_commit": 0,
        "rejoined": False,
        "rejoin_step": None,
        "hard_failure": None,
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


def _standard_configuration(configuration: Any) -> bool:
    return all(
        _as_int(_get(configuration, key, expected), expected) == expected
        for key, expected in STANDARD_CONFIGURATION.items()
    )


def _iter_tiles(farm: Any):
    for row in _get(farm, "tiles", []) or []:
        yield from row or []


def _owned_cows(obs: Any) -> int:
    farm = _farm(obs) or {}
    count = sum(
        isinstance(tile, dict) and _get(tile, "animal") == "COW"
        for tile in _iter_tiles(farm)
    )
    private = _private(obs)
    shed = _get(private, "shed", {}) or {}
    count += max(0, _as_int(_get(shed, "COW", 0)))
    for inventory in _get(private, "inventories", []) or []:
        count += max(0, _as_int(_get(inventory, "COW", 0)))
    return count


def _total_private_item(obs: Any, item: str) -> int:
    private = _private(obs)
    shed = _get(private, "shed", {}) or {}
    inventories = list(_get(private, "inventories", []) or [])
    return max(0, _as_int(_get(shed, item, 0))) + sum(
        max(0, _as_int(_get(inventory, item, 0))) for inventory in inventories
    )


def _actor_actions(action: dict[str, Any]) -> list[list[Any]]:
    farmer = action.get("farmer")
    hands = list(action.get("hands") or [])
    return [farmer if isinstance(farmer, list) else ["PASS"], *hands]


def _positions(farm: Any) -> list[list[int]]:
    return [list(_get(farm, "farmer", []) or []), *list(_get(farm, "hands", []) or [])]


def _shed_access(board_size: int) -> set[tuple[int, int]]:
    half = max(1, board_size) // 2
    return {(half - 1, half - 1), (half, half - 1), (half - 1, half), (half, half)}


def _project_shed(obs: Any, action: dict[str, Any], configuration: Any) -> dict[str, int]:
    """Project only deterministic same-turn transfers into/out of the shed."""
    farm = _farm(obs) or {}
    private = _private(obs)
    shed = {
        str(item): max(0, _as_int(quantity))
        for item, quantity in dict(_get(private, "shed", {}) or {}).items()
    }
    inventories = [
        {
            str(item): max(0, _as_int(quantity))
            for item, quantity in dict(inventory or {}).items()
        }
        for inventory in list(_get(private, "inventories", []) or [])
    ]
    positions = _positions(farm)
    actions = _actor_actions(action)
    while len(inventories) < len(positions):
        inventories.append({})
    access = _shed_access(_as_int(_get(configuration, "boardSize", 10), 10))
    capacity = _as_int(_get(configuration, "shedCapacity", 100), 100)
    for index, actor_action in enumerate(actions):
        if index >= len(positions) or index >= len(inventories) or not actor_action:
            continue
        position = positions[index]
        if len(position) < 2 or (_as_int(position[0]), _as_int(position[1])) not in access:
            continue
        inventory = inventories[index]
        operation = str(actor_action[0])
        if operation == "DROP":
            for item, quantity in list(inventory.items()):
                room = max(0, capacity - sum(shed.values()))
                moved = min(max(0, quantity), room)
                shed[item] = shed.get(item, 0) + moved
                inventory[item] = max(0, quantity - moved)
        elif operation == "PLACE" and len(actor_action) >= 2:
            item = str(actor_action[1])
            requested = _as_int(actor_action[2], 1) if len(actor_action) >= 3 else 1
            room = max(0, capacity - sum(shed.values()))
            moved = min(max(0, requested), max(0, inventory.get(item, 0)), room)
            shed[item] = shed.get(item, 0) + moved
            inventory[item] = max(0, inventory.get(item, 0) - moved)
    return shed


def _shape(name: str, value: float, anchor: float) -> float:
    value = max(0.0, value)
    if name == "linear":
        return value
    if name == "sq":
        return value * value
    if name == "sqrt":
        return math.sqrt(value)
    if name == "log":
        return math.log1p(value)
    if name == "log10":
        return math.log10(1.0 + value)
    if name == "hinge":
        ratio = value / max(1.0, anchor)
        return ratio + 8.0 * max(0.0, ratio - 1.0) ** 2
    raise ValueError(name)


def _melon_price(inventory: int) -> int:
    params = MELON_PARAMS
    base = params["base"]
    equilibrium = params["I0"]
    anchor = params["T"]
    if inventory < equilibrium:
        function = str(params["below_func"])
        amplitude = params["below_target"] * base / _shape(function, anchor, anchor)
        price = base + amplitude * _shape(function, equilibrium - inventory, anchor)
    else:
        function = str(params["above_func"])
        amplitude = params["above_target"] * base / _shape(function, anchor, anchor)
        price = base - amplitude * _shape(function, inventory - equilibrium, anchor)
    return max(1, int(round(price)))


def _maintenance_reserve(obs: Any) -> dict[str, int]:
    farm = _farm(obs) or {}
    urgent_unfed = sum(
        isinstance(tile, dict)
        and bool(_get(tile, "animal"))
        and not bool(_get(tile, "fed_today", False))
        for tile in _iter_tiles(farm)
    )
    wheat = _total_private_item(obs, "WHEAT")
    shortfall = max(0, urgent_unfed - wheat)
    market = _get(obs, "market", {}) or {}
    prices = _get(market, "prices", {}) or {}
    wheat_price = max(1, _as_int(_get(prices, "WHEAT", 25), 25))
    return {
        "urgent_unfed_animals": urgent_unfed,
        "owned_wheat": wheat,
        "wheat_shortfall": shortfall,
        "coin": shortfall * wheat_price,
    }


def _find_transaction(action: dict[str, Any]) -> tuple[int, int, int] | None:
    orders = list(action.get("market") or [])
    cow_indices = [
        index
        for index, order in enumerate(orders)
        if isinstance(order, list)
        and len(order) >= 3
        and order[0] == "BUY_ANIMAL"
        and order[1] == "COW"
        and _as_int(order[2]) == COW_QUANTITY
    ]
    melon_indices = [
        index
        for index, order in enumerate(orders)
        if isinstance(order, list)
        and len(order) >= 3
        and order[0] == "SELL"
        and order[1] == "MELON"
        and _as_int(order[2]) > 0
    ]
    if len(cow_indices) != 1 or not melon_indices or any(
        isinstance(order, list) and order and order[0] == "BUY_LAND" for order in orders
    ):
        return None
    cow_index = cow_indices[0]
    preceding = [index for index in melon_indices if index < cow_index]
    if not preceding:
        return None
    melon_index = preceding[-1]
    return melon_index, cow_index, _as_int(orders[melon_index][2])


def _preflight(
    obs: Any,
    action: dict[str, Any],
    configuration: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    farm = _farm(obs)
    if farm is None:
        return None, "missing-farm"
    if not _standard_configuration(configuration):
        return None, "non-standard-configuration"
    unlocked = sorted(set(_get(farm, "unlocked_quadrants", []) or []))
    if len(unlocked) != 2:
        return None, "not-exactly-two-quadrants"
    if len(action.get("hands") or []) != len(_get(farm, "hands", []) or []):
        return None, "hands-shape-mismatch"
    transaction = _find_transaction(action)
    if transaction is None:
        return None, "late-transaction-signature-absent"
    melon_index, cow_index, melon_quantity = transaction
    orders = list(action.get("market") or [])
    max_orders = _as_int(_get(configuration, "maxMarketOrdersPerTurn", 10), 10)
    if len(orders) + 1 > max_orders:
        return None, "market-slot-capacity"
    if any(
        not isinstance(order, list)
        or not order
        or order[0] not in {"SELL", "BUY_ANIMAL"}
        for order in orders
    ):
        return None, "unexpected-market-family"
    shed = _project_shed(obs, action, configuration)
    melon_available = max(0, int(shed.get("MELON", 0)))
    if melon_available < melon_quantity:
        return None, "projected-melon-unavailable"
    market = _get(obs, "market", {}) or {}
    inventory = _get(market, "inventory", {}) or {}
    melon_inventory = _as_int(_get(inventory, "MELON", 10_000), 10_000)
    sale_income = 0
    simulated_inventory = melon_inventory
    for _ in range(melon_quantity):
        price = _melon_price(simulated_inventory)
        sale_income += price
        if price > 1:
            simulated_inventory += 1
    maintenance = _maintenance_reserve(obs)
    cash_before = float(_get(farm, "money", 0.0) or 0.0)
    cash_after = cash_before + sale_income - COW_QUANTITY * COW_UNIT_COST - LAND_COST
    required_reserve = MINIMUM_CASH_AFTER_TRANSACTION + maintenance["coin"]
    if cash_after < required_reserve:
        return None, "sequential-cash-reserve"
    shed_total_after = sum(max(0, int(value)) for value in shed.values())
    shed_total_after = shed_total_after - melon_quantity + COW_QUANTITY
    shed_capacity = _as_int(_get(configuration, "shedCapacity", 100), 100)
    if shed_total_after > shed_capacity:
        return None, "shed-capacity"
    return {
        "melon_order_index": melon_index,
        "cow_order_index": cow_index,
        "melon_quantity": melon_quantity,
        "cash_before": cash_before,
        "projected_sale_income": sale_income,
        "projected_cash_after_land_and_cows": cash_after,
        "maintenance_reserve": maintenance,
        "activation_reserve": 0,
        "inherited_cash_reserve": MINIMUM_CASH_AFTER_TRANSACTION,
        "market_orders_before": len(orders),
        "market_orders_after": len(orders) + 1,
        "projected_shed_after": shed_total_after,
        "shed_capacity": shed_capacity,
        "unlocked_before": unlocked,
    }, None


def _quadrant(position: list[int], board_size: int = 10) -> str | None:
    if len(position) < 2:
        return None
    half = board_size // 2
    x, y = _as_int(position[0]), _as_int(position[1])
    if not (0 <= x < board_size and 0 <= y < board_size):
        return None
    return ("N" if y < half else "S") + ("W" if x < half else "E")


def _track_post_commit(obs: Any, action: dict[str, Any], state: dict[str, Any]) -> None:
    if state.get("commit_step") is None:
        return
    step = _step(obs)
    farm = _farm(obs) or {}
    unlocked = sorted(set(_get(farm, "unlocked_quadrants", []) or []))
    if step > int(state["commit_step"]) and state.get("land_confirmed_step") is None:
        if len(unlocked) >= 3:
            state["land_confirmed_step"] = step
            added = sorted(set(unlocked) - set(state.get("pre_unlocked") or []))
            state["new_quadrant"] = added[0] if len(added) == 1 else None
        else:
            state["hard_failure"] = state.get("hard_failure") or "land-not-committed"
    if step > int(state["commit_step"]) and state.get("cow_confirmed_step") is None:
        if _owned_cows(obs) >= int(state.get("pre_cows", 0)) + COW_QUANTITY:
            state["cow_confirmed_step"] = step
        else:
            state["hard_failure"] = state.get("hard_failure") or "cow-order-not-committed"
    actor_actions = _actor_actions(action)
    for actor_action in actor_actions:
        if not actor_action:
            continue
        if actor_action[:2] == ["PICKUP", "COW"]:
            state["cow_pickups"] += max(1, _as_int(actor_action[2], 1) if len(actor_action) >= 3 else 1)
        elif actor_action[:2] == ["PLACE", "COW"]:
            state["cow_places"] += 1
        elif actor_action[0] == "FEED":
            state["feed_actions_after_commit"] += 1
    if state.get("new_quadrant") and state.get("first_productive_action") is None:
        positions = _positions(farm)
        productive = {
            "PLANT",
            "WATER",
            "HARVEST",
            "BUILD_COOP",
            "BUILD_PASTURE",
            "FEED",
            "CARE",
            "COLLECT_FERTILIZER",
        }
        for index, actor_action in enumerate(actor_actions):
            if (
                index < len(positions)
                and actor_action
                and actor_action[0] in productive
                and _quadrant(positions[index]) == state["new_quadrant"]
            ):
                state["first_productive_action"] = {
                    "step": step,
                    "unit_index": index,
                    "action": copy.deepcopy(actor_action),
                    "quadrant": state["new_quadrant"],
                }
                break


def _apply_contract(
    obs: Any,
    baseline_action: Any,
    configuration: Any,
    state: dict[str, Any],
) -> Any:
    if not isinstance(baseline_action, dict):
        return baseline_action
    _track_post_commit(obs, baseline_action, state)
    orders = list(baseline_action.get("market") or [])
    if state.get("land_confirmed_step") is not None and any(
        isinstance(order, list) and order and order[0] == "BUY_LAND" for order in orders
    ):
        result = copy.deepcopy(baseline_action)
        removed = False
        retained = []
        for order in result.get("market") or []:
            if not removed and isinstance(order, list) and order and order[0] == "BUY_LAND":
                removed = True
                continue
            retained.append(order)
        result["market"] = retained
        if removed:
            state["duplicate_land_removed"] += 1
            state["duplicate_land_removed_step"] = _step(obs)
            if state.get("cow_confirmed_step") is not None:
                state["rejoined"] = True
                state["rejoin_step"] = _step(obs)
                state["phase"] = "REJOINED_V111"
        return result
    if state.get("commit_step") is not None:
        return baseline_action
    transaction = _find_transaction(baseline_action)
    if transaction is None:
        return baseline_action
    state["trigger_requests"] += 1
    preflight, reason = _preflight(obs, baseline_action, configuration)
    if preflight is None:
        state["safe_cancels"][str(reason)] += 1
        return baseline_action
    result = copy.deepcopy(baseline_action)
    cow_index = int(preflight["cow_order_index"])
    result["market"] = [
        *result.get("market", [])[: cow_index + 1],
        ["BUY_LAND"],
        *result.get("market", [])[cow_index + 1 :],
    ]
    state.update(
        phase="COMMITTED_AWAIT_CONFIRMATION",
        commits=1,
        commit_step=_step(obs),
        preflight=preflight,
        pre_unlocked=list(preflight["unlocked_before"]),
        pre_cows=_owned_cows(obs),
    )
    return result


def reset_runtime_state() -> None:
    _RUNTIME.clear()
    base.reset_runtime_state()


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    state = _RUNTIME.get(_seat(obs), _new_state(_step(obs)))
    decision = {
        key: copy.deepcopy(value)
        for key, value in state.items()
        if key != "last_step"
    }
    decision["safe_cancels"] = dict(state.get("safe_cancels", {}))
    decision["contract"] = CONTRACT_NAME
    decision["implementation"] = IMPLEMENTATION
    decision["first_action_step"] = state.get("commit_step")
    decision["committed"] = bool(state.get("commits"))
    try:
        parent = base.policy_diagnostics(obs)
    except Exception:
        parent = {}
    return {
        **(parent if isinstance(parent, dict) else {}),
        "version": "v117",
        "strategic_policy": "v111-plus-bounded-late-land-order-resequence",
        "research_decision": decision,
    }


def agent(obs: Any, configuration: Any = None) -> dict[str, Any]:
    state = _state_for(obs)
    baseline_action = base.agent(obs, configuration)
    return _apply_contract(obs, baseline_action, configuration, state)


def _kaggle_submission_entrypoint(obs: Any, configuration: Any = None) -> dict[str, Any]:
    return agent(obs, configuration)
