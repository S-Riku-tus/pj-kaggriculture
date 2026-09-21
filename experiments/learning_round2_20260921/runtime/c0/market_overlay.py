"""V120 plus conservative market/correctness overlays.

This challenger intentionally leaves V120's macro route untouched.  It only
repairs certain weed collisions, removes market orders that are provably dead,
ranks existing SELL slots without crossing non-SELL cash dependencies, and
liquidates otherwise stranded final stock.
"""

from __future__ import annotations

import copy
import importlib.util
import math
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SELLABLE = (
    "WHEAT",
    "CARROT",
    "TOMATO",
    "STRAWBERRY",
    "MELON",
    "EGG",
    "MILK",
    "WOOL",
    "FERTILIZER",
)
LIQUIDATION_ORDER = (
    "MELON",
    "WOOL",
    "MILK",
    "STRAWBERRY",
    "TOMATO",
    "EGG",
    "CARROT",
    "WHEAT",
    "FERTILIZER",
)
MARKET_PARAMS = {
    "WHEAT": (25, 10000, 400, "sqrt", 0.8, "log", 0.2),
    "CARROT": (35, 10000, 450, "log", 0.2, "sqrt", 0.7),
    "TOMATO": (60, 10000, 200, "linear", 0.4, "sqrt", 0.6),
    "STRAWBERRY": (120, 10000, 100, "sqrt", 0.7, "linear", 1.6),
    "MELON": (250, 10000, 300, "log", 0.2, "sq", 3.6),
    "EGG": (50, 10000, 332, "linear", 0.4, "log", 0.2),
    "MILK": (160, 10000, 122, "sqrt", 0.6, "linear", 1.6),
    "WOOL": (200, 10000, 105, "log", 0.2, "sq", 3.2),
    "FERTILIZER": (100, 10000, 200, "linear", 0.4, "linear", 0.4),
}
PRICE_FLOOR = 1
WEED_REPLAY_STEPS = 8
ENABLE_WEED_REPAIR = True
ENABLE_DEAD_SELL_REMOVAL = True
ENABLE_SELL_RANKING = True
ENABLE_TERMINAL_LIQUIDATION = True
_STATE: dict[int, dict[str, Any]] = {0: {}, 1: {}}


def _module_dir() -> Path:
    if "__file__" in globals():
        return Path(__file__).resolve().parent
    candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd() / "agents" / "v121_market",
        Path.cwd(),
    )
    return next(
        (
            candidate.resolve()
            for candidate in candidates
            if (candidate / "v120_base.py").is_file()
            or (candidate.parent / "v120" / "main.py").is_file()
        ),
        Path.cwd(),
    )


def _load_base() -> Any:
    module_dir = _module_dir()
    packaged = module_dir / "v120_base.py"
    repository = module_dir.parent / "v120" / "main.py"
    source = packaged if packaged.is_file() else repository
    spec = importlib.util.spec_from_file_location("_v121_market_v120_base", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import V120 base: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load_base()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _copy_action(action: Any) -> dict[str, Any]:
    raw = _mapping(action)
    return {
        "farmer": list(raw.get("farmer") or ["PASS"]),
        "hands": [list(value or ["PASS"]) for value in raw.get("hands") or []],
        "market": [list(value) for value in raw.get("market") or [] if isinstance(value, list | tuple)],
    }


def _seat(observation: Mapping[str, Any]) -> int:
    return 1 if _integer(observation.get("player")) == 1 else 0


def _farm(observation: Mapping[str, Any]) -> Mapping[str, Any]:
    seat = _seat(observation)
    farms = list(observation.get("farms") or [])
    return _mapping(farms[seat]) if seat < len(farms) else {}


def reset_runtime_state() -> None:
    _STATE.clear()
    _STATE.update({0: {}, 1: {}})


def _state(observation: Mapping[str, Any], step: int) -> dict[str, Any]:
    seat = _seat(observation)
    state = _STATE.setdefault(seat, {})
    if step == 0 or step < _integer(state.get("last_step"), -1):
        state.clear()
    state.setdefault("weed", {})
    state.setdefault("history", {})
    state.setdefault("diagnostics", {})
    state["last_step"] = step
    return state


def _tile_at(farm: Mapping[str, Any], position: Any) -> Any:
    try:
        x, y = int(position[0]), int(position[1])
        return (farm.get("tiles") or [])[y][x]
    except (IndexError, TypeError, ValueError):
        return "LOCKED"


def _actor_action(action: Mapping[str, Any], actor: int) -> list[Any]:
    if actor == 0:
        return list(action.get("farmer") or ["PASS"])
    hands = list(action.get("hands") or [])
    return list(hands[actor - 1] if actor - 1 < len(hands) else ["PASS"])


def _weed_repair(
    observation: Mapping[str, Any], action: dict[str, Any], step: int, state: dict[str, Any]
) -> dict[str, Any]:
    result = _copy_action(action)
    state["history"][step] = _copy_action(action)
    state["history"] = {
        key: value for key, value in state["history"].items() if key >= step - WEED_REPLAY_STEPS - 2
    }
    farm = _farm(observation)
    positions = [farm.get("farmer"), *(farm.get("hands") or [])]
    unit_actions = [result["farmer"], *result["hands"]]
    active = state["weed"]

    for actor, transaction in list(active.items()):
        actor_index = int(actor)
        if actor_index >= len(unit_actions):
            active.pop(actor, None)
            continue
        age = step - _integer(transaction.get("start"))
        if age == 1:
            unit_actions[actor_index] = list(transaction["intended"])
        elif 2 <= age <= 1 + WEED_REPLAY_STEPS:
            previous = state["history"].get(step - 1, action)
            unit_actions[actor_index] = _actor_action(previous, actor_index)
        else:
            active.pop(actor, None)

    for actor_index, (position, intended) in enumerate(zip(positions, unit_actions, strict=False)):
        if actor_index in active or not intended or intended[0] not in {"BUILD_PASTURE", "PLANT"}:
            continue
        if _mapping(_tile_at(farm, position)).get("kind") != "WEED":
            continue
        active[actor_index] = {"start": step, "intended": list(intended)}
        unit_actions[actor_index] = ["DIG"]
        diagnostics = state["diagnostics"]
        diagnostics["weed_repairs"] = _integer(diagnostics.get("weed_repairs")) + 1

    result["farmer"] = unit_actions[0] if unit_actions else ["PASS"]
    result["hands"] = unit_actions[1:]
    return base._normalize_output(result, observation)


def _shed_access(board_size: int) -> set[tuple[int, int]]:
    middle = board_size // 2
    return {(middle - 1, middle - 1), (middle, middle - 1), (middle - 1, middle), (middle, middle)}


def _projected_shed(observation: Mapping[str, Any], action: Mapping[str, Any]) -> dict[str, int]:
    private = _mapping(observation.get("private"))
    projected = {key: max(0, _integer(value)) for key, value in _mapping(private.get("shed")).items()}
    inventories = list(private.get("inventories") or [])
    farm = _farm(observation)
    positions = [farm.get("farmer"), *(farm.get("hands") or [])]
    unit_actions = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
    access = _shed_access(len(farm.get("tiles") or []) or 10)
    for index, unit_action in enumerate(unit_actions):
        if index >= len(positions) or index >= len(inventories):
            continue
        position = positions[index]
        if not isinstance(position, list | tuple) or len(position) < 2:
            continue
        x, y = int(position[0]), int(position[1])
        if (x, y) not in access:
            continue
        inventory = {key: max(0, _integer(value)) for key, value in _mapping(inventories[index]).items()}
        if unit_action and unit_action[0] == "DROP":
            deposits = inventory.items()
        elif unit_action and unit_action[0] == "PLACE" and len(unit_action) >= 2:
            item = str(unit_action[1])
            tile = _tile_at(farm, position)
            structure = {"COW": "PASTURE", "SHEEP": "PASTURE", "GOOSE": "COOP"}.get(item)
            if structure and _mapping(tile).get("kind") == structure and not _mapping(tile).get("animal"):
                continue
            requested = _integer(unit_action[2], 1) if len(unit_action) >= 3 else 1
            deposits = ((item, min(max(0, requested), inventory.get(item, 0))),)
        else:
            continue
        for item, quantity in deposits:
            room = max(0, 100 - sum(projected.values()))
            amount = min(max(0, _integer(quantity)), room)
            if amount:
                projected[item] = projected.get(item, 0) + amount
    return projected


def _sanitize_market(
    observation: Mapping[str, Any], action: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    result = _copy_action(action)
    available = _projected_shed(observation, result)
    cleaned: list[list[Any]] = []
    removed = 0
    for order in result["market"]:
        if not order or order[0] != "SELL":
            cleaned.append(order)
            if len(order) >= 3 and order[0] == "BUY_PRODUCT" and str(order[1]) in {"WHEAT", "FERTILIZER"}:
                available[str(order[1])] = available.get(str(order[1]), 0) + max(0, _integer(order[2]))
            continue
        if len(order) < 3 or str(order[1]) not in SELLABLE or _integer(order[2]) <= 0:
            removed += 1
            continue
        item = str(order[1])
        if available.get(item, 0) <= 0:
            removed += 1
            continue
        cleaned.append(["SELL", item, _integer(order[2])])
        available[item] = max(0, available.get(item, 0) - _integer(order[2]))
    result["market"] = cleaned[:10]
    diagnostics = state["diagnostics"]
    diagnostics["dead_sells_removed"] = _integer(diagnostics.get("dead_sells_removed")) + removed
    return result


def _shape(name: str, value: float) -> float:
    value = max(0.0, float(value))
    if name == "linear":
        return value
    if name == "sq":
        return value * value
    if name == "sqrt":
        return math.sqrt(value)
    return math.log1p(value)


def _market_price(item: str, inventory: int) -> int:
    base_price, equilibrium, scale, below_func, below_target, above_func, above_target = MARKET_PARAMS[item]
    if inventory < equilibrium:
        amplitude = below_target * base_price / _shape(below_func, scale)
        price = base_price + amplitude * _shape(below_func, equilibrium - inventory)
    else:
        amplitude = above_target * base_price / _shape(above_func, scale)
        price = base_price - amplitude * _shape(above_func, inventory - equilibrium)
    return max(PRICE_FLOOR, int(round(price)))


def _sell_score(observation: Mapping[str, Any], order: list[Any]) -> float:
    item = str(order[1])
    quantity = max(0, _integer(order[2]))
    market = _mapping(observation.get("market"))
    inventory = _integer(_mapping(market.get("inventory")).get(item), 10000)
    current = float(_mapping(market.get("prices")).get(item, _market_price(item, inventory)))
    later = float(_market_price(item, inventory + quantity))
    return quantity * max(0.0, current - later)


def _rank_sell_slots(
    observation: Mapping[str, Any], action: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    result = _copy_action(action)
    market = result["market"]
    rows = [
        (_sell_score(observation, order), -index, order)
        for index, order in enumerate(market)
        if len(order) >= 3 and order[0] == "SELL" and str(order[1]) in SELLABLE
    ]
    if len(rows) < 2:
        return result
    rows.sort(reverse=True)
    ranked = iter(row[2] for row in rows)
    reordered = [next(ranked) if order and order[0] == "SELL" else order for order in market]
    if reordered != market:
        diagnostics = state["diagnostics"]
        diagnostics["sell_reorders"] = _integer(diagnostics.get("sell_reorders")) + 1
    result["market"] = reordered
    return result


def _terminal_liquidation(
    observation: Mapping[str, Any], action: dict[str, Any], step: int, state: dict[str, Any]
) -> dict[str, Any]:
    if step < 716:
        return action
    result = _copy_action(action)
    available = _projected_shed(observation, result)
    planned: dict[str, int] = {}
    for order in result["market"]:
        if len(order) >= 3 and order[0] == "SELL":
            item = str(order[1])
            planned[item] = planned.get(item, 0) + max(0, _integer(order[2]))
    appended = 0
    for item in LIQUIDATION_ORDER:
        extra = max(0, available.get(item, 0) - planned.get(item, 0))
        if extra and len(result["market"]) < 10:
            result["market"].append(["SELL", item, extra])
            appended += extra
    diagnostics = state["diagnostics"]
    diagnostics["terminal_units_appended"] = _integer(diagnostics.get("terminal_units_appended")) + appended
    return result


def policy_diagnostics(observation: Mapping[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(_STATE.get(_seat(observation), {}).get("diagnostics", {}))


def agent(observation: Mapping[str, Any], configuration: Any = None) -> dict[str, Any]:
    try:
        step = _integer(observation.get("step"))
        state = _state(observation, step)
        action = base.agent(observation, configuration)
        if ENABLE_WEED_REPAIR:
            action = _weed_repair(observation, action, step, state)
        if ENABLE_DEAD_SELL_REMOVAL:
            action = _sanitize_market(observation, action, state)
        if ENABLE_TERMINAL_LIQUIDATION:
            action = _terminal_liquidation(observation, action, step, state)
        if ENABLE_SELL_RANKING:
            action = _rank_sell_slots(observation, action, state)
        return base._normalize_output(action, observation)
    except Exception:
        return base._normalize_output({}, observation)


def _kaggle_submission_entrypoint(observation: Mapping[str, Any], configuration: Any = None) -> dict[str, Any]:
    return agent(observation, configuration)
