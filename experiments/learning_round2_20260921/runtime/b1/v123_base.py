"""V123: V122 continuation routing with clone-aware sale preemption.

V122's opening, route library, and safety overlays remain the backbone.  The
only strategic changes are:

* an opponent that reproduced the public opening through day four is treated
  as an opening clone, and one route-planned sale may be moved one turn early
  when the opponent visibly owns the corresponding production asset.

The measured coherent-source experiment remains available for diagnostics but
is disabled in the promoted policy: its direct average margin was positive,
but its paired win/loss stability failed the no-regression gate.

Both controls use public current-state information only.  No opponent identity,
rating, replay id, outcome, or future observation is available at runtime.
"""

from __future__ import annotations

import copy
import importlib.util
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

COHERENCE_DISTANCE_TOLERANCE = 250
ENABLE_COHERENCE = False
ENABLE_CLONE_PREEMPTION = True
CLONE_CHECKPOINTS = (24, 48, 72, 96)
CLONE_MIN_CONFIRMATIONS = 3
PREEMPT_ITEMS = ("STRAWBERRY", "MELON", "MILK", "WOOL")
ITEM_ASSET = {
    "STRAWBERRY": "STRAWBERRY",
    "MELON": "MELON",
    "MILK": "COW",
    "WOOL": "SHEEP",
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


def _module_dir() -> Path:
    if "__file__" in globals():
        return Path(__file__).resolve().parent
    candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd() / "agents" / "v123",
        Path.cwd(),
    )
    return next(
        (
            candidate.resolve()
            for candidate in candidates
            if (candidate / "v121_sparse.py").is_file() or (candidate.parent / "v121" / "main.py").is_file()
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
sparse = _load("_v123_sparse", "v121_sparse.py", ROOT / "agents/v121/main.py")
market = _load("_v123_market", "market_overlay.py", ROOT / "agents/v121_market/main.py")

sparse._normalize_output = sparse.base._normalize_output
market.base = sparse
market.ENABLE_WEED_REPAIR = True
market.ENABLE_DEAD_SELL_REMOVAL = True
market.ENABLE_TERMINAL_LIQUIDATION = True
market.ENABLE_SELL_RANKING = False

_ORIGINAL_CHOOSE_ROW = sparse._choose_row
_CLONE_STATE: dict[int, dict[str, Any]] = {0: {}, 1: {}}


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _seat(observation: Mapping[str, Any]) -> int:
    return 1 if _integer(observation.get("player")) == 1 else 0


def _coherent_choose_row(
    observation: Mapping[str, Any],
    rows: Sequence[list[Any]],
    query: Sequence[int],
) -> list[Any]:
    """Prefer the gate-selected source unless current-state drift is material."""
    nearest = _ORIGINAL_CHOOSE_ROW(observation, rows, query)
    step = _integer(observation.get("step"))
    nearest_source = _integer(nearest[sparse.ROW_SOURCE], -1)
    state = sparse._STATE

    if step < sparse.OPENING_END or state.get("last_gate") == step:
        state["active_source"] = nearest_source
        state["source_selected_at"] = step

    if not ENABLE_COHERENCE:
        state["last_action_source"] = nearest_source
        return nearest

    active_source = _integer(state.get("active_source"), nearest_source)
    if active_source < 0 or active_source == nearest_source:
        state["last_action_source"] = nearest_source
        return nearest

    pool = sparse._route_pool(sparse._compatible_units(rows, observation), step)
    beam = set(state.get("beam") or ())
    if step >= sparse.OPENING_END and beam:
        beamed = [row for row in pool if _integer(row[sparse.ROW_SOURCE], -1) in beam]
        if beamed:
            pool = beamed
    active_rows = [row for row in pool if _integer(row[sparse.ROW_SOURCE], -1) == active_source]
    if not active_rows:
        state["coherence_unavailable"] = _integer(state.get("coherence_unavailable")) + 1
        state["last_action_source"] = nearest_source
        return nearest

    active = min(
        active_rows,
        key=lambda row: sparse.base.feature_distance(query, row[sparse.ROW_FEATURES]),
    )
    nearest_distance = sparse.base.feature_distance(query, nearest[sparse.ROW_FEATURES])
    active_distance = sparse.base.feature_distance(query, active[sparse.ROW_FEATURES])
    if active_distance <= nearest_distance + COHERENCE_DISTANCE_TOLERANCE:
        state["coherence_holds"] = _integer(state.get("coherence_holds")) + 1
        state["last_action_source"] = active_source
        return active

    state["coherence_fallbacks"] = _integer(state.get("coherence_fallbacks")) + 1
    state["last_action_source"] = nearest_source
    return nearest


sparse._choose_row = _coherent_choose_row


def _farm_signature(farm: Mapping[str, Any]) -> tuple[Any, ...]:
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
    for raw in sparse.base._board(farm):
        tile = _mapping(raw)
        for field in ("animal", "crop", "kind"):
            value = str(tile.get(field, ""))
            if value in labels:
                counts[value] += 1
                break
    positions = [farm.get("farmer"), *(farm.get("hands") or [])]
    normalized_positions = tuple(
        sorted(tuple(_integer(value, -1) for value in list(position or [])[:2]) for position in positions)
    )
    return (
        len(farm.get("hands") or []),
        tuple(sorted(set(farm.get("unlocked_quadrants") or []))),
        normalized_positions,
        tuple(counts[label] for label in labels),
    )


def _signature_distance(left: tuple[Any, ...], right: tuple[Any, ...]) -> int:
    distance = abs(_integer(left[0]) - _integer(right[0]))
    distance += 3 * abs(len(left[1]) - len(right[1]))
    distance += sum(abs(_integer(a) - _integer(b)) for a, b in zip(left[3], right[3], strict=True))
    if left[2] != right[2]:
        distance += 2
    return distance


def _clone_state(observation: Mapping[str, Any]) -> dict[str, Any]:
    seat = _seat(observation)
    step = _integer(observation.get("step"))
    state = _CLONE_STATE.setdefault(seat, {})
    if step == 0 or step < _integer(state.get("last_step"), -1):
        state.clear()
    state.setdefault("confirmations", 0)
    state.setdefault("opening_clone", False)
    state.setdefault("shifted_targets", set())
    state.setdefault("preemptions", 0)
    state.setdefault("preemption_units", Counter())
    state["shifted_targets"] = {value for value in state["shifted_targets"] if _integer(value[0]) >= step}
    state["last_step"] = step
    return state


def _update_opening_clone(observation: Mapping[str, Any], state: dict[str, Any]) -> None:
    step = _integer(observation.get("step"))
    if step not in CLONE_CHECKPOINTS:
        return
    farms = list(observation.get("farms") or [])
    if len(farms) < 2:
        return
    distance = _signature_distance(
        _farm_signature(_mapping(farms[0])),
        _farm_signature(_mapping(farms[1])),
    )
    state["last_opening_distance"] = distance
    if distance <= 1:
        state["confirmations"] = _integer(state.get("confirmations")) + 1
    elif distance <= 4:
        state["confirmations"] = max(0, _integer(state.get("confirmations")) - 1)
    else:
        state["confirmations"] = 0
    if _integer(state.get("confirmations")) >= CLONE_MIN_CONFIRMATIONS:
        state["opening_clone"] = True


def _opponent_asset_count(observation: Mapping[str, Any], item: str) -> int:
    farms = list(observation.get("farms") or [])
    opponent_index = 1 - _seat(observation)
    opponent = _mapping(farms[opponent_index]) if opponent_index < len(farms) else {}
    asset = ITEM_ASSET[item]
    return sum(
        str(_mapping(tile).get("crop")) == asset
        or str(_mapping(tile).get("animal")) == asset
        or str(_mapping(tile).get("kind")) == asset
        for tile in sparse.base._board(opponent)
    )


def _town_consumes_at(observation: Mapping[str, Any], item: str, step: int) -> bool:
    if step % 4:
        return False
    shops = list(_mapping(observation.get("town")).get("unlocked_shops") or [])
    return any(item in SHOP_PRODUCTS.get(str(shop), ()) for shop in shops)


def _planned_next_turn_sale(item: str, step: int, source: int) -> tuple[int, int] | None:
    model = sparse._load_model()
    target = step + 1
    steps = model.get("steps") or []
    if not (0 <= target < len(steps)):
        return None
    for row in steps[target] or []:
        if _integer(row[sparse.ROW_SOURCE], -1) != source:
            continue
        quantity = sum(
            max(0, _integer(order[2]))
            for order in _mapping(row[sparse.ROW_ACTION]).get("market") or []
            if isinstance(order, list | tuple) and len(order) >= 3 and order[0] == "SELL" and str(order[1]) == item
        )
        if quantity:
            return target, quantity
    return None


def _clone_market_overlay(observation: Mapping[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    state = _clone_state(observation)
    _update_opening_clone(observation, state)
    step = _integer(observation.get("step"))
    if not ENABLE_CLONE_PREEMPTION or step < sparse.OPENING_END or not state.get("opening_clone"):
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
    choices: list[tuple[float, str, int, int]] = []
    for item in PREEMPT_ITEMS:
        if item in existing or available.get(item, 0) <= 0:
            continue
        plan = _planned_next_turn_sale(item, step, source)
        if plan is None or plan in state["shifted_targets"]:
            continue
        target, planned = plan
        quantity = min(max(0, _integer(available.get(item))), planned)
        price = max(0.0, float(prices.get(item, 0) or 0))
        if quantity < 2 or price <= 1:
            continue
        if _town_consumes_at(observation, item, step) or _town_consumes_at(observation, item, target):
            continue
        if _opponent_asset_count(observation, item) <= 0:
            continue
        score = price * quantity
        choices.append((score, item, quantity, target))
    if not choices:
        return result

    _score, item, quantity, target = max(choices)
    result["market"] = [["SELL", item, quantity], *orders][:10]
    state["shifted_targets"].add((target, item))
    state["preemptions"] = _integer(state.get("preemptions")) + 1
    state["preemption_units"][item] += quantity
    state["last_preemption"] = {
        "step": step,
        "target": target,
        "item": item,
        "quantity": quantity,
    }
    return result


def reset_runtime_state() -> None:
    sparse.reset_runtime_state()
    market.reset_runtime_state()
    _CLONE_STATE.clear()
    _CLONE_STATE.update({0: {}, 1: {}})


def policy_diagnostics(observation: Mapping[str, Any]) -> dict[str, Any]:
    sparse_diagnostic = sparse.policy_diagnostics()
    sparse_diagnostic.update(
        {
            "active_source": sparse._STATE.get("active_source"),
            "last_action_source": sparse._STATE.get("last_action_source"),
            "coherence_holds": _integer(sparse._STATE.get("coherence_holds")),
            "coherence_fallbacks": _integer(sparse._STATE.get("coherence_fallbacks")),
            "coherence_unavailable": _integer(sparse._STATE.get("coherence_unavailable")),
        }
    )
    clone = _CLONE_STATE.get(_seat(observation), {})
    return {
        "version": "v123",
        "sparse": sparse_diagnostic,
        "market": market.policy_diagnostics(observation),
        "opening_clone": bool(clone.get("opening_clone", False)),
        "clone_confirmations": _integer(clone.get("confirmations")),
        "preemptions": _integer(clone.get("preemptions")),
        "preemption_units": dict(clone.get("preemption_units", {})),
        "last_preemption": copy.deepcopy(clone.get("last_preemption")),
        "sell_ranking": False,
        "coherence_enabled": ENABLE_COHERENCE,
        "clone_preemption_enabled": ENABLE_CLONE_PREEMPTION,
    }


def agent(observation: Mapping[str, Any], configuration: Any = None) -> dict[str, Any]:
    action = market.agent(observation, configuration)
    try:
        action = _clone_market_overlay(observation, action)
        return sparse.base._normalize_output(action, observation)
    except Exception:
        return sparse.base._normalize_output(action, observation)


def _kaggle_submission_entrypoint(observation: Mapping[str, Any], configuration: Any = None) -> dict[str, Any]:
    return agent(observation, configuration)


if __name__ == "__main__":
    import json

    for line in sys.stdin:
        if line.strip():
            request = json.loads(line)
            result = agent(request.get("observation", request), request.get("configuration"))
            print(json.dumps(result), flush=True)
