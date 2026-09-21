"""Learning-B overlay: opponent SELL prediction changes only C0 market ordering."""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

try:
    from .common import (
        MARKET_PARAMS,
        PRODUCTS,
        MarketHistory,
        SavedMLP,
        market_price,
        safe_action_shape,
        state_features,
    )
except ImportError:  # standalone archive
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from common import MARKET_PARAMS, PRODUCTS, MarketHistory, SavedMLP, market_price, safe_action_shape, state_features

HORIZONS = (1, 4, 24)


def _module_dir() -> Path:
    return Path(__file__).resolve().parent


def _load_c0() -> Any:
    local = _module_dir() / "c0_main.py"
    repository = _module_dir().parent / "v125_exec" / "main.py"
    source = local if local.is_file() else repository
    spec = importlib.util.spec_from_file_location(f"_learning_b_c0_{id(source)}", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"C0 could not be loaded: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_config() -> dict[str, Any]:
    path = _module_dir() / "arm_config.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"mode": "learned"}


base = _load_c0()
CONFIG = _load_config()
MODE = str(CONFIG.get("mode", "learned"))
MODEL = SavedMLP(_module_dir() / "b_model.npz") if MODE == "learned" else None
SIMPLE = json.loads((_module_dir() / "b_simple_model.json").read_text(encoding="utf-8"))
_history: dict[int, MarketHistory] = {}
_previous_market: dict[int, list[list[Any]]] = {}
_previous_probe: dict[int, dict[str, Any] | None] = {}
_stats: dict[str, int] = {}


def reset_runtime_state() -> None:
    global _history, _previous_market, _previous_probe, _stats
    _history = {}
    _previous_market = {}
    _previous_probe = {}
    _stats = {
        "model_loads": int(MODE == "learned"),
        "inference_calls": 0,
        "candidate_sets": 0,
        "action_changes": 0,
        "changed_action_checks": 0,
        "changed_action_successes": 0,
        "fallbacks": 0,
    }
    if hasattr(base, "reset_runtime_state"):
        base.reset_runtime_state()


reset_runtime_state()


def _call_base(observation: Mapping[str, Any], configuration: Any) -> Any:
    try:
        parameters = inspect.signature(base.agent).parameters.values()
        accepts_configuration = (
            any(parameter.kind in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD} for parameter in parameters)
            or len(list(parameters)) >= 2
        )
    except (TypeError, ValueError):
        accepts_configuration = True
    return base.agent(observation, configuration) if accepts_configuration else base.agent(observation)


def _predict(observation: Mapping[str, Any], history: MarketHistory) -> dict[tuple[str, int], tuple[float, float]]:
    result: dict[tuple[str, int], tuple[float, float]] = {}
    if MODE == "simple":
        hour = str(int(observation.get("hour", 0)))
        for item in PRODUCTS:
            for horizon in HORIZONS:
                row = SIMPLE["by_hour"].get(hour, SIMPLE["global"])[item][str(horizon)]
                result[(item, horizon)] = (float(row["probability"]), float(row["expected_quantity"]))
        return result
    if MODEL is None:
        raise RuntimeError("learned B mode has no loaded model")
    outputs = MODEL.logits(state_features(observation, history))
    width = len(PRODUCTS) * len(HORIZONS)
    probability = 1.0 / (1.0 + np.exp(-np.clip(outputs[:width], -30.0, 30.0)))
    quantity = np.maximum(0.0, np.expm1(np.clip(outputs[width:], 0.0, 8.0)))
    offset = 0
    for item in PRODUCTS:
        for horizon in HORIZONS:
            result[(item, horizon)] = (float(probability[offset]), float(quantity[offset]))
            offset += 1
    _stats["inference_calls"] += 1
    return result


def _sell_blocks(orders: Sequence[Sequence[Any]], risk: Mapping[str, float]) -> list[list[list[Any]]]:
    original = [list(order) for order in orders]
    candidates = [original]
    reordered = [list(order) for order in original]
    start = 0
    changed = False
    while start < len(reordered):
        if not reordered[start] or reordered[start][0] != "SELL":
            start += 1
            continue
        end = start
        while end < len(reordered) and reordered[end] and reordered[end][0] == "SELL":
            end += 1
        block = reordered[start:end]
        ranked = sorted(block, key=lambda order: (-risk.get(str(order[1]), 0.0), str(order[1])))
        changed |= ranked != block
        reordered[start:end] = ranked
        start = end
    if changed:
        candidates.append(reordered)
    return candidates


def _score_sell_candidate(
    observation: Mapping[str, Any],
    own_orders: Sequence[Sequence[Any]],
    prediction: Mapping[tuple[str, int], tuple[float, float]],
) -> float:
    inventory = {
        item: int(observation["market"]["inventory"].get(item, MARKET_PARAMS[item]["I0"])) for item in PRODUCTS
    }
    shed = {item: int(observation["private"]["shed"].get(item, 0)) for item in PRODUCTS}
    opponent = [
        ["SELL", item, max(1, int(round(prediction[(item, 1)][1])))]
        for item in PRODUCTS
        if prediction[(item, 1)][0] >= 0.25 and prediction[(item, 1)][1] >= 0.5
    ]
    revenue = 0.0
    for slot in range(max(len(own_orders), len(opponent))):
        pair = [own_orders[slot] if slot < len(own_orders) else None, opponent[slot] if slot < len(opponent) else None]
        quantities = []
        for order in pair:
            quantities.append(int(order[2]) if order and len(order) >= 3 and order[0] == "SELL" else 0)
        for unit in range(max(quantities, default=0)):
            quoted: list[tuple[str, int] | None] = []
            for player, order in enumerate(pair):
                if order and unit < quantities[player]:
                    item = str(order[1])
                    quoted.append((item, market_price(item, inventory[item])))
                else:
                    quoted.append(None)
            if quoted[0] is not None:
                item, price = quoted[0]
                if shed.get(item, 0) > 0:
                    shed[item] -= 1
                    revenue += price
                    if price > 1:
                        inventory[item] += 1
            if quoted[1] is not None:
                item, price = quoted[1]
                if price > 1:
                    inventory[item] += 1
    return revenue


def agent(observation: Mapping[str, Any], configuration: Any = None) -> dict[str, Any]:
    seat = int(observation.get("player", 0))
    history = _history.setdefault(seat, MarketHistory())
    history.update(observation, _previous_market.get(seat))
    previous = _previous_probe.get(seat)
    if previous is not None:
        money = float(observation["farms"][seat]["money"])
        shed = observation["private"]["shed"]
        _stats["changed_action_checks"] += 1
        if money > float(previous["money"]) or any(
            int(shed.get(item, 0)) < int(previous["shed"].get(item, 0)) for item in previous["sold_items"]
        ):
            _stats["changed_action_successes"] += 1
        _previous_probe[seat] = None
    try:
        raw = _call_base(observation, configuration)
        hand_count = len(observation["farms"][seat].get("hands", []))
        control = safe_action_shape(raw, hand_count)
        prediction = _predict(observation, history)
        risk = {
            item: sum(prediction[(item, horizon)][0] * prediction[(item, horizon)][1] / horizon for horizon in HORIZONS)
            for item in PRODUCTS
        }
        candidates = _sell_blocks(control["market"], risk)
        _stats["candidate_sets"] += 1
        scores = [_score_sell_candidate(observation, candidate, prediction) for candidate in candidates]
        chosen = candidates[max(range(len(candidates)), key=lambda index: (scores[index], -index))]
        result = dict(control)
        result["market"] = chosen
        if chosen != control["market"]:
            _stats["action_changes"] += 1
            sold_items = [str(order[1]) for order in chosen if len(order) >= 2 and order[0] == "SELL"]
            _previous_probe[seat] = {
                "money": float(observation["farms"][seat]["money"]),
                "shed": {item: int(observation["private"]["shed"].get(item, 0)) for item in sold_items},
                "sold_items": sold_items,
            }
        _previous_market[seat] = [list(order) for order in chosen]
        return result
    except Exception:
        _stats["fallbacks"] += 1
        raise


def policy_diagnostics(observation: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"arm": f"B_{MODE}", **_stats}
