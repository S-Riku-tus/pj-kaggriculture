"""Sequence-aware, quantity-conditional full-action behavioral-cloning agent."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

try:
    from .common import (
        ACTOR_TOKENS,
        MARKET_TOKENS,
        MarketHistory,
        SavedMLP,
        action_token,
        actor_context,
        actor_probe_succeeded,
        bc_actor_features,
        legal_actor_tokens,
        make_actor_probe,
        market_features,
        market_price,
        market_token,  # noqa: F401 - public helper used by the audit harness
        reserve_actor_token,
        shed_access,
        token_action,
        token_order,
    )
except ImportError:
    from common import (
        ACTOR_TOKENS,
        MARKET_TOKENS,
        MarketHistory,
        SavedMLP,
        action_token,
        actor_context,
        actor_probe_succeeded,
        bc_actor_features,
        legal_actor_tokens,
        make_actor_probe,
        market_features,
        market_price,
        market_token,  # noqa: F401 - public helper used by the audit harness
        reserve_actor_token,
        shed_access,
        token_action,
        token_order,
    )


def _module_dir() -> Path:
    return Path(__file__).resolve().parent


ACTOR_MODEL = SavedMLP(_module_dir() / "actor_token.npz")
MARKET_MODEL = SavedMLP(_module_dir() / "market_token.npz")
ACTOR_QUANTITY_MODEL = SavedMLP(_module_dir() / "actor_quantity.npz")
MARKET_QUANTITY_MODEL = SavedMLP(_module_dir() / "market_quantity.npz")
_history: dict[int, MarketHistory] = {}
_previous_market: dict[int, list[list[Any]]] = {}
_previous_actor: dict[int, list[str]] = {}
_probes: dict[int, list[dict[str, Any]]] = {}
_stats: dict[str, int] = {}


def reset_runtime_state() -> None:
    global _history, _previous_market, _previous_actor, _probes, _stats
    _history, _previous_market, _previous_actor, _probes = {}, {}, {}, {}
    _stats = {
        "model_loads": 4,
        "inference_calls": 0,
        "actor_decisions": 0,
        "market_decisions": 0,
        "quantity_decisions": 0,
        "legality_masks": 0,
        "resource_reservations": 0,
        "blocked_market_orders": 0,
        "model_action_checks": 0,
        "model_action_successes": 0,
    }


reset_runtime_state()


def _prefix_features(tokens: list[str]) -> np.ndarray:
    counts = np.zeros(len(ACTOR_TOKENS), dtype=np.float32)
    for token in tokens:
        if token in ACTOR_TOKENS:
            counts[ACTOR_TOKENS.index(token)] += 1.0
    if tokens:
        counts /= len(tokens)
    previous = np.zeros(len(ACTOR_TOKENS), dtype=np.float32)
    if tokens and tokens[-1] in ACTOR_TOKENS:
        previous[ACTOR_TOKENS.index(tokens[-1])] = 1.0
    return np.concatenate((counts, previous))


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


def _actor_quantity(features: np.ndarray, token: str) -> int:
    if not token.startswith(("PICKUP:", "PLACE:")):
        return 1
    return _predicted_quantity(
        ACTOR_QUANTITY_MODEL,
        np.concatenate((features, _token_one_hot(token, ACTOR_TOKENS))),
    )


def _market_quantity(features: np.ndarray, token: str) -> int:
    if token in {"EOS", "HIRE", "BUY_LAND"}:
        return 1
    return _predicted_quantity(
        MARKET_QUANTITY_MODEL,
        np.concatenate((features, _token_one_hot(token, MARKET_TOKENS))),
    )


def _actor_features(
    observation: Mapping[str, Any],
    index: int,
    previous_token: str,
    history: MarketHistory,
    current_tokens: list[str],
) -> np.ndarray:
    return np.concatenate(
        (bc_actor_features(observation, index, previous_token, history), _prefix_features(current_tokens))
    )


def _pick_actor(
    observation: Mapping[str, Any],
    index: int,
    previous_token: str,
    history: MarketHistory,
    reserved: dict[str, int],
    current_tokens: list[str],
    *,
    corrected: bool,
) -> list[Any]:
    features = _actor_features(observation, index, previous_token, history, current_tokens)
    probability = ACTOR_MODEL.probabilities(features)
    _stats["inference_calls"] += 1
    _stats["actor_decisions"] += 1
    ranking = sorted(zip(ACTOR_MODEL.classes, probability, strict=True), key=lambda pair: -float(pair[1]))
    if corrected:
        legal = legal_actor_tokens(observation, index, reserved)
        _stats["legality_masks"] += 1
        token = next((candidate for candidate, _score in ranking if candidate in legal), "PASS")
    else:
        token = str(ranking[0][0])
    quantity = _actor_quantity(features, token)
    if corrected:
        reserve_actor_token(reserved, token, quantity)
        if token == "DROP" or token.startswith("PLACE:"):
            _farm, position, inventory, tile = actor_context(observation, index)
            tile_map = tile if isinstance(tile, Mapping) else {}
            item = token.split(":", 1)[1] if ":" in token else None
            compatible = {"COOP": {"GOOSE"}, "PASTURE": {"COW", "SHEEP"}}
            animal_placement = bool(
                item and not tile_map.get("animal") and item in compatible.get(str(tile_map.get("kind")), set())
            )
            if shed_access(position) and not animal_placement:
                deposit = (
                    sum(max(0, int(value)) for value in inventory.values())
                    if token == "DROP"
                    else min(quantity, max(0, int(inventory.get(item, 0))))
                )
                reserved["shed:deposit"] = reserved.get("shed:deposit", 0) + deposit
    current_tokens.append(token)
    return token_action(token, quantity)


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


def _decode_market(
    observation: Mapping[str, Any], history: MarketHistory, *, corrected: bool
) -> list[list[Any]]:
    orders: list[list[Any]] = []
    previous = "EOS"
    sold: dict[str, int] = {}
    bought: dict[str, int] = {}
    spent = 0.0
    hired = 0
    lands = 0
    money = float(observation["farms"][int(observation.get("player", 0))].get("money", 0))
    shed_reserved = sum(int(value) for value in observation["private"]["shed"].values())
    for slot in range(10):
        features = market_features(observation, slot, previous, history)
        probability = MARKET_MODEL.probabilities(features)
        _stats["inference_calls"] += 1
        _stats["market_decisions"] += 1
        ranking = sorted(zip(MARKET_MODEL.classes, probability, strict=True), key=lambda pair: -float(pair[1]))
        if not corrected:
            token = str(ranking[0][0])
            if token == "EOS":
                break
            quantity = _market_quantity(features, token)
            orders.append(token_order(token, quantity))
            previous = token
            continue
        _stats["legality_masks"] += 1
        token = "EOS"
        quantity = 1
        cost = 0.0
        for candidate, _score in ranking:
            if candidate == "EOS":
                break
            candidate_quantity = _market_quantity(features, str(candidate))
            if candidate.startswith("SELL:"):
                item = candidate.split(":", 1)[1]
                available = int(observation["private"]["shed"].get(item, 0)) - sold.get(item, 0)
                if available <= 0:
                    _stats["blocked_market_orders"] += 1
                    continue
                candidate_quantity = min(candidate_quantity, available)
            elif candidate.startswith(("BUY_PRODUCT:", "BUY_ANIMAL:")):
                if shed_reserved + candidate_quantity > 100:
                    _stats["blocked_market_orders"] += 1
                    continue
            candidate_cost = _market_cost(
                observation, str(candidate), candidate_quantity, hired, lands, bought
            )
            if spent + candidate_cost > money:
                _stats["blocked_market_orders"] += 1
                continue
            token, quantity, cost = str(candidate), candidate_quantity, candidate_cost
            break
        if token == "EOS":
            break
        if token.startswith("SELL:"):
            item = token.split(":", 1)[1]
            sold[item] = sold.get(item, 0) + quantity
            shed_reserved -= quantity
        else:
            spent += cost
            _stats["resource_reservations"] += 1
            if token == "HIRE":
                hired += 1
            elif token == "BUY_LAND":
                lands += 1
            elif token.startswith("BUY_PRODUCT:"):
                item = token.split(":", 1)[1]
                bought[item] = bought.get(item, 0) + quantity
                shed_reserved += quantity
            elif token.startswith("BUY_ANIMAL:"):
                shed_reserved += quantity
        orders.append(token_order(token, quantity))
        previous = token
    return orders


def _policy(observation: Mapping[str, Any], *, corrected: bool) -> dict[str, Any]:
    seat = int(observation.get("player", 0))
    prior_probes = _probes.pop(seat, [])
    _stats["model_action_checks"] += len(prior_probes)
    _stats["model_action_successes"] += sum(actor_probe_succeeded(observation, probe) for probe in prior_probes)
    history = _history.setdefault(seat, MarketHistory())
    history.update(observation, _previous_market.get(seat))
    hand_count = len(observation["farms"][seat].get("hands", []))
    reserved: dict[str, int] = {}
    previous = _previous_actor.get(seat, [])
    current_tokens: list[str] = []
    units = [
        _pick_actor(
            observation,
            index,
            previous[index] if index < len(previous) else "PASS",
            history,
            reserved,
            current_tokens,
            corrected=corrected,
        )
        for index in range(hand_count + 1)
    ]
    market = _decode_market(observation, history, corrected=corrected)
    _probes[seat] = [
        make_actor_probe(observation, index, value)
        for index, value in enumerate(units)
        if value and value[0] != "PASS"
    ]
    _previous_actor[seat] = [action_token(value) for value in units]
    _previous_market[seat] = market
    return {"farmer": units[0], "hands": units[1:], "market": market}


def predict_raw_action(observation: Mapping[str, Any], configuration: Any = None) -> dict[str, Any]:
    return _policy(observation, corrected=False)


def agent(observation: Mapping[str, Any], configuration: Any = None) -> dict[str, Any]:
    return _policy(observation, corrected=True)


def policy_diagnostics(observation: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"arm": "round6_sequence_bc_v1", **_stats}
