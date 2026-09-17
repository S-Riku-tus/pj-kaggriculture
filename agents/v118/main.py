"""Kaggriculture V118: state-safe recovery and late price-aware rotation.

V117 remains the complete parent policy.  V118 adds two bounded overlays:

* If a unit is standing on a weed and its inherited action is guaranteed to be
  ignored by the engine, DIG the weed.  DIG preserves the unit's route position.
* Late in the season, buy a bounded Carrot seed reserve and replace inherited
  Wheat plantings only when observable prices make the conservative four-Carrot
  yield worth materially more than the six-Wheat yield.

The policy uses only public observation and its own private inventory.  It does
not use seed, replay, opponent identity, score, future shops, or hidden state.
"""

from __future__ import annotations

import copy
import importlib.util
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
        Path.cwd() / "agents" / "v118",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (candidate / "v117_base.py").is_file()
            or (candidate.parent / "v117" / "main.py").is_file()
        ),
        Path.cwd(),
    )


def _load_parent():
    packaged = MODULE_DIR / "v117_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v117" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v118_parent", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V118 dependency: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load_parent()

CONTRACT_NAME = "state_safe_recovery_and_late_price_rotation"
CARROT_BUY_START = 590
CARROT_BUY_END = 600
CARROT_SWAP_START = 600
CARROT_SWAP_END = 700
CARROT_SEED_TARGET = 45
CARROT_SEED_COST = 20
MIN_CARROT_PRICE = 47.0
MIN_GROSS_EDGE = 20.0
MIN_CASH_RESERVE = 500.0
MAX_MARKET_ORDERS = 10
MOVES = {
    "NORTH": (0, -1),
    "SOUTH": (0, 1),
    "EAST": (1, 0),
    "WEST": (-1, 0),
}
ANIMAL_STRUCTURES = {"GOOSE": "COOP", "COW": "PASTURE", "SHEEP": "PASTURE"}

_RUNTIME: dict[int, dict[str, Any]] = {}


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _step(obs: Any) -> int:
    return int(_get(obs, "step", 0) or 0)


def _seat(obs: Any) -> int:
    return 1 if int(_get(obs, "player", 0) or 0) == 1 else 0


def _new_state(step: int) -> dict[str, Any]:
    return {
        "last_step": step,
        "weed_repairs": 0,
        "seed_orders": 0,
        "seeds_requested": 0,
        "wheat_to_carrot": 0,
        "safe_cancels": Counter(),
    }


def _state_for(obs: Any) -> dict[str, Any]:
    seat = _seat(obs)
    step = _step(obs)
    state = _RUNTIME.get(seat)
    if state is None or step == 0 or step <= int(state.get("last_step", -1)):
        state = _new_state(step)
        _RUNTIME[seat] = state
    state["last_step"] = step
    return state


def _shed_adjacent(x: int, y: int, board: int) -> bool:
    half = board // 2
    return (x, y) in {
        (half - 1, half - 1),
        (half, half - 1),
        (half - 1, half),
        (half, half),
    }


def _certain_noop(
    action: list[Any],
    tile: Any,
    inventory: dict[str, int],
    seeds: dict[str, int],
    x: int,
    y: int,
    board: int,
) -> bool:
    if not action:
        return True
    operation = action[0]
    if operation == "PASS":
        return True
    if operation in MOVES:
        dx, dy = MOVES[operation]
        return not (0 <= x + dx < board and 0 <= y + dy < board)
    if operation == "DROP":
        return not _shed_adjacent(x, y, board) or not inventory
    if operation == "PICKUP":
        return not _shed_adjacent(x, y, board)
    if operation == "PLACE":
        item = action[1] if len(action) > 1 else None
        if (
            item in ANIMAL_STRUCTURES
            and isinstance(tile, dict)
            and tile.get("kind") == ANIMAL_STRUCTURES[item]
            and tile.get("animal") is None
        ):
            return int(inventory.get(item, 0) or 0) <= 0
        if _shed_adjacent(x, y, board):
            return int(inventory.get(item, 0) or 0) <= 0
        return True
    if tile == "LOCKED":
        return True
    is_tile = isinstance(tile, dict)
    kind = tile.get("kind") if is_tile else None
    animal = bool(is_tile and tile.get("animal") is not None)
    if operation == "PLANT":
        crop = action[1] if len(action) > 1 else None
        return tile is not None or int(seeds.get(crop, 0) or 0) <= 0
    if operation == "WATER":
        return kind != "PLANT" or bool(tile.get("watered_today"))
    if operation == "HARVEST":
        return not is_tile or int(tile.get("yield_units", 0) or 0) <= 0
    if operation == "FERTILIZE":
        return kind != "PLANT" or int(inventory.get("FERTILIZER", 0) or 0) <= 0
    if operation == "DIG":
        return tile is None or animal
    if operation in {"BUILD_COOP", "BUILD_PASTURE"}:
        return tile is not None
    if operation == "FEED":
        return not animal or bool(tile.get("fed_today")) or int(inventory.get("WHEAT", 0) or 0) <= 0
    if operation == "CARE":
        return not animal or bool(tile.get("cared_today"))
    if operation == "COLLECT_FERTILIZER":
        return not animal or not bool(tile.get("fertilizer_available"))
    return False


def _repair_weeds(obs: Any, action: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    farms = list(_get(obs, "farms", []) or [])
    seat = _seat(obs)
    if seat >= len(farms):
        return action
    farm = farms[seat] or {}
    tiles = _get(farm, "tiles", []) or []
    if not tiles:
        return action
    board = len(tiles)
    positions = [tuple(_get(farm, "farmer", (-1, -1)))]
    positions.extend(tuple(position) for position in (_get(farm, "hands", []) or []))
    private = _get(obs, "private", {}) or {}
    inventories = list(_get(private, "inventories", []) or [])
    seeds = dict(_get(private, "seeds", {}) or {})
    actors = [list(action.get("farmer") or ["PASS"])]
    actors.extend(list(hand or ["PASS"]) for hand in (action.get("hands") or []))
    repaired = False
    for index in range(min(len(actors), len(positions))):
        x, y = positions[index]
        if not (0 <= x < board and 0 <= y < board):
            continue
        tile = tiles[y][x]
        inventory = inventories[index] if index < len(inventories) else {}
        if (
            isinstance(tile, dict)
            and tile.get("kind") == "WEED"
            and _certain_noop(actors[index], tile, inventory, seeds, x, y, board)
        ):
            actors[index] = ["DIG"]
            state["weed_repairs"] += 1
            repaired = True
    if repaired:
        action["farmer"] = actors[0]
        action["hands"] = actors[1:]
    return action


def _prices(obs: Any) -> dict[str, float]:
    market = _get(obs, "market", {}) or {}
    return {
        key: float(value or 0.0)
        for key, value in dict(_get(market, "prices", {}) or {}).items()
    }


def _rotation_has_edge(obs: Any) -> bool:
    prices = _prices(obs)
    carrot = prices.get("CARROT", 0.0)
    wheat = prices.get("WHEAT", 0.0)
    return carrot >= MIN_CARROT_PRICE and 4.0 * carrot >= 6.0 * wheat + MIN_GROSS_EDGE


def _buy_carrot_seeds(
    obs: Any,
    action: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    step = _step(obs)
    if not (CARROT_BUY_START <= step < CARROT_BUY_END) or not _rotation_has_edge(obs):
        return action
    private = _get(obs, "private", {}) or {}
    have = int((_get(private, "seeds", {}) or {}).get("CARROT", 0) or 0)
    need = CARROT_SEED_TARGET - have
    if need <= 0:
        return action
    market = [list(order) for order in (action.get("market") or [])]
    if len(market) >= MAX_MARKET_ORDERS:
        state["safe_cancels"]["market_full"] += 1
        return action
    if any(order and order[0] in {"HIRE", "BUY_LAND", "BUY_PRODUCT", "BUY_SEED", "BUY_ANIMAL"} for order in market):
        state["safe_cancels"]["inherited_spend"] += 1
        return action
    farms = list(_get(obs, "farms", []) or [])
    seat = _seat(obs)
    money = float(_get(farms[seat], "money", 0.0) or 0.0) if seat < len(farms) else 0.0
    affordable = int(max(0.0, money - MIN_CASH_RESERVE) // CARROT_SEED_COST)
    quantity = min(need, affordable)
    if quantity <= 0:
        state["safe_cancels"]["cash_reserve"] += 1
        return action
    market.append(["BUY_SEED", "CARROT", quantity])
    action["market"] = market
    state["seed_orders"] += 1
    state["seeds_requested"] += quantity
    return action


def _swap_late_wheat(
    obs: Any,
    action: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    step = _step(obs)
    if not (CARROT_SWAP_START <= step < CARROT_SWAP_END) or not _rotation_has_edge(obs):
        return action
    farmer = list(action.get("farmer") or ["PASS"])
    hands = [list(hand or ["PASS"]) for hand in (action.get("hands") or [])]
    actors = [farmer, *hands]
    swap_count = sum(
        1
        for actor in actors
        if len(actor) >= 2 and actor[0] == "PLANT" and actor[1] == "WHEAT"
    )
    if swap_count <= 0:
        return action
    private = _get(obs, "private", {}) or {}
    carrot_seeds = int((_get(private, "seeds", {}) or {}).get("CARROT", 0) or 0)
    if carrot_seeds < swap_count:
        state["safe_cancels"]["insufficient_carrot_seed"] += 1
        return action
    for actor in actors:
        if len(actor) >= 2 and actor[0] == "PLANT" and actor[1] == "WHEAT":
            actor[1] = "CARROT"
    action["farmer"] = actors[0]
    action["hands"] = actors[1:]
    state["wheat_to_carrot"] += swap_count
    return action


def reset_runtime_state() -> None:
    _RUNTIME.clear()
    base.reset_runtime_state()


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    state = _RUNTIME.get(_seat(obs), _new_state(_step(obs)))
    try:
        parent = base.policy_diagnostics(obs)
    except Exception:
        parent = {}
    decision = {
        key: copy.deepcopy(value)
        for key, value in state.items()
        if key != "last_step"
    }
    decision["safe_cancels"] = dict(state.get("safe_cancels", {}))
    decision["contract"] = CONTRACT_NAME
    return {
        **(parent if isinstance(parent, dict) else {}),
        "version": "v118",
        "strategic_policy": "v117-plus-state-safe-recovery-and-late-price-rotation",
        "v118_decision": decision,
    }


def agent(obs: Any, configuration: Any = None) -> dict[str, Any]:
    state = _state_for(obs)
    inherited = base.agent(obs, configuration)
    if not isinstance(inherited, dict):
        return inherited
    action = copy.deepcopy(inherited)
    action = _repair_weeds(obs, action, state)
    action = _buy_carrot_seeds(obs, action, state)
    return _swap_late_wheat(obs, action, state)


def _kaggle_submission_entrypoint(obs: Any, configuration: Any = None) -> dict[str, Any]:
    return agent(obs, configuration)
