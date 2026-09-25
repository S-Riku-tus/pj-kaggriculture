"""Learned policy interface for Round9 A2 prefix-state BC checkpoints."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

try:
    from . import common as _common
    from . import spatial as _spatial
except ImportError:
    import common as _common
    import spatial as _spatial

ACTOR_TOKENS = _common.ACTOR_TOKENS
MARKET_TOKENS = _common.MARKET_TOKENS
MarketHistory = _common.MarketHistory
SavedMLP = _common.SavedMLP
action_token = _common.action_token
actor_context = _common.actor_context
bc_actor_features = _common.bc_actor_features
legal_actor_tokens = _common.legal_actor_tokens
base_market_features = _common.market_features
market_price = _common.market_price
reserve_actor_token = _common.reserve_actor_token
shed_access = _common.shed_access
token_action = _common.token_action
token_order = _common.token_order
make_prefix_entry = _spatial.make_prefix_entry
prefix_extra_features = _spatial.prefix_extra_features
prefix_token_features = _spatial.prefix_token_features
shared_spatial_features = _spatial.shared_spatial_features


def _module_dir() -> Path:
    return Path(__file__).resolve().parent


ACTOR_MODEL = SavedMLP(_module_dir() / "actor_token.npz")
MARKET_MODEL = SavedMLP(_module_dir() / "market_token.npz")
ACTOR_QUANTITY_MODEL = SavedMLP(_module_dir() / "actor_quantity.npz")
MARKET_QUANTITY_MODEL = SavedMLP(_module_dir() / "market_quantity.npz")
_history: dict[int, MarketHistory] = {}
_previous_market: dict[int, list[list[Any]]] = {}
_previous_actor: dict[int, list[str]] = {}
_shared_cache: dict[int, tuple[int, np.ndarray]] = {}
_stats: dict[str, int] = {}


def reset_runtime_state() -> None:
    global _history, _previous_market, _previous_actor, _shared_cache, _stats
    _history, _previous_market, _previous_actor = {}, {}, {}
    _shared_cache = {}
    _stats = {
        "model_loads": 4,
        "inference_calls": 0,
        "actor_decisions": 0,
        "market_decisions": 0,
        "quantity_decisions": 0,
        "legality_masks": 0,
        "resource_reservations": 0,
        "blocked_market_orders": 0,
    }


reset_runtime_state()


def _shared_features(observation: Mapping[str, Any]) -> np.ndarray:
    # Multiple accepted actor/order prefixes exist at the same environment
    # step.  A seat+step cache would return a stale physical state here.
    return shared_spatial_features(observation)


def _token_one_hot(token: str, tokens: tuple[str, ...]) -> np.ndarray:
    values = np.zeros(len(tokens), dtype=np.float32)
    if token in tokens:
        values[tokens.index(token)] = 1.0
    return values


def _predicted_quantity(model: SavedMLP, features: np.ndarray) -> int:
    probability = model.probabilities(features)
    _stats["inference_calls"] += 1
    _stats["quantity_decisions"] += 1
    return max(1, int(float(model.classes[int(probability.argmax())])))


def _actor_features(
    observation: Mapping[str, Any],
    index: int,
    previous_token: str,
    history: MarketHistory,
    current_entries: list[Any],
) -> np.ndarray:
    return np.concatenate(
        (
            bc_actor_features(observation, index, previous_token, history),
            prefix_token_features(current_entries),
            prefix_extra_features(current_entries),
            _shared_features(observation),
        )
    )


def market_features(
    observation: Mapping[str, Any], slot: int, previous_token: str, history: MarketHistory
) -> np.ndarray:
    return np.concatenate(
        (base_market_features(observation, slot, previous_token, history), _shared_features(observation))
    )


SEED_COST = {"WHEAT": 10, "CARROT": 20, "TOMATO": 50, "STRAWBERRY": 100, "MELON": 80}
ANIMAL_COST = {"GOOSE": 300, "COW": 400, "SHEEP": 500}
LAND_COST = (1000, 2000, 4000)


def _fib(index: int) -> int:
    left, right = 1, 1
    for _ in range(index):
        left, right = right, left + right
    return left


def _market_cost(
    observation: Mapping[str, Any],
    token: str,
    quantity: int,
    hired: int,
    lands: int,
    bought: Mapping[str, int],
) -> float:
    seat = int(observation.get("player", 0))
    farm = observation["farms"][seat]
    if token == "HIRE":
        return float(_fib(int(farm.get("hires_today", 0)) + hired))
    if token == "BUY_LAND":
        index = len(farm.get("unlocked_quadrants", [])) - 1 + lands
        return float(LAND_COST[index]) if 0 <= index < len(LAND_COST) else float("inf")
    operation, item = token.split(":", 1)
    if operation == "BUY_SEED":
        return float(SEED_COST[item] * quantity)
    if operation == "BUY_ANIMAL":
        return float(ANIMAL_COST[item] * quantity)
    if operation == "BUY_PRODUCT":
        inventory = int(observation["market"]["inventory"].get(item, 0)) - int(bought.get(item, 0))
        return float(sum(market_price(item, inventory - unit) for unit in range(1, quantity + 1)))
    return 0.0


def policy_diagnostics(observation: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "policy": "round9_a2_prefix_state_bc",
        "input_contract": "public observation plus self private state and causal own-history only",
        **_stats,
    }
