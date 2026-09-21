"""Pure-Python lockstep market evaluator matching kaggriculture 1.32.7."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER")
CROPS = {"WHEAT": 10, "CARROT": 20, "TOMATO": 50, "STRAWBERRY": 80, "MELON": 100}
ANIMALS = {"GOOSE": 100, "COW": 500, "SHEEP": 300}
LAND_PRICES = (1000, 2000, 4000)
MARKET_PARAMS = {
    "WHEAT": {"base": 25, "I0": 10000, "T": 400, "below_func": "sqrt", "below_target": .8, "above_func": "log", "above_target": .2},
    "CARROT": {"base": 35, "I0": 10000, "T": 450, "below_func": "hinge", "below_target": 1., "above_func": "sqrt", "above_target": .7},
    "TOMATO": {"base": 60, "I0": 10000, "T": 200, "below_func": "hinge", "below_target": .4, "above_func": "sqrt", "above_target": .6},
    "STRAWBERRY": {"base": 120, "I0": 10000, "T": 100, "below_func": "sqrt", "below_target": .7, "above_func": "linear", "above_target": 1.6},
    "MELON": {"base": 250, "I0": 10000, "T": 300, "below_func": "log", "below_target": .2, "above_func": "sq", "above_target": 3.6},
    "EGG": {"base": 50, "I0": 10000, "T": 332, "below_func": "hinge", "below_target": .4, "above_func": "log", "above_target": .2},
    "MILK": {"base": 160, "I0": 10000, "T": 122, "below_func": "sqrt", "below_target": .6, "above_func": "linear", "above_target": 1.6},
    "WOOL": {"base": 200, "I0": 10000, "T": 105, "below_func": "log", "below_target": .2, "above_func": "sq", "above_target": 3.2},
    "FERTILIZER": {"base": 100, "I0": 10000, "T": 200, "below_func": "linear", "below_target": .4, "above_func": "linear", "above_target": .4},
}


def _shape(kind: str, x: float, threshold: float) -> float:
    x = max(0.0, x)
    if kind == "linear": return x
    if kind == "sq": return x * x
    if kind == "sqrt": return math.sqrt(x)
    if kind == "log": return math.log(1.0 + x)
    if kind == "log10": return math.log10(1.0 + x)
    if kind == "hinge":
        u = x / threshold if threshold > 0 else x
        return u + 8.0 * max(0.0, u - 1.0) ** 2
    return x


def market_price(item: str, inventory: int, params: Mapping[str, Mapping[str, Any]] = MARKET_PARAMS) -> int:
    row = params[item]
    base, initial, threshold = float(row["base"]), int(row["I0"]), float(row["T"])
    if inventory < initial:
        kind = str(row["below_func"])
        amplitude = float(row["below_target"]) * base / _shape(kind, threshold, threshold)
        price = base + amplitude * _shape(kind, initial - inventory, threshold)
    else:
        kind = str(row["above_func"])
        amplitude = float(row["above_target"]) * base / _shape(kind, threshold, threshold)
        price = base - amplitude * _shape(kind, inventory - initial, threshold)
    return max(1, int(round(price)))


def _parse(order: Sequence[Any]) -> dict[str, Any] | None:
    if not isinstance(order, Sequence) or not order:
        return None
    op = str(order[0])
    if op in {"HIRE", "BUY_LAND"}:
        return {"type": op, "remaining": 1, "item": None}
    if len(order) < 3:
        return None
    try:
        quantity = max(0, int(order[2]))
    except (TypeError, ValueError):
        return None
    return {"type": op, "item": str(order[1]), "remaining": quantity}


def simulate_market(
    inventory: Mapping[str, int],
    players: Sequence[Mapping[str, Any]],
    orders: Sequence[Sequence[Sequence[Any]]],
    *,
    max_orders: int = 10,
    shed_capacity: int = 100,
    hire_multiplier: int = 1,
    params: Mapping[str, Mapping[str, Any]] = MARKET_PARAMS,
) -> dict[str, Any]:
    """Simulate both ordered queues with unit quotes before each lockstep commit."""

    market = {item: int(inventory.get(item, params[item]["I0"])) for item in PRODUCTS}
    state = [
        {
            "money": int(row.get("money", 0)),
            "shed": {str(k): int(v) for k, v in row.get("shed", {}).items()},
            "seeds": {str(k): int(v) for k, v in row.get("seeds", {}).items()},
            "hires_today": int(row.get("hires_today", 0)),
            "hands": int(row.get("hands", 0)),
            "unlocked_land": int(row.get("unlocked_land", 1)),
        }
        for row in players
    ]
    queues = [[_parse(order) for order in list(queue)[:max_orders]] for queue in orders]
    revenue = [0, 0]
    executed: list[list[dict[str, Any]]] = [[], []]
    for slot in range(max((len(queue) for queue in queues), default=0)):
        current = [queue[slot] if slot < len(queue) else None for queue in queues]
        for player, parsed in enumerate(current):
            if parsed is None:
                continue
            if parsed["type"] == "HIRE":
                n = state[player]["hires_today"]
                a, b = 0, 1
                for _ in range(n): a, b = b, a + b
                cost = max(1, b) * hire_multiplier
                if state[player]["money"] >= cost:
                    state[player]["money"] -= cost
                    state[player]["hires_today"] += 1
                    state[player]["hands"] += 1
                    executed[player].append({"slot": slot, "type": "HIRE", "price": cost})
                current[player] = None
            elif parsed["type"] == "BUY_LAND":
                extra = state[player]["unlocked_land"] - 1
                if 0 <= extra < len(LAND_PRICES) and state[player]["money"] >= LAND_PRICES[extra]:
                    price = LAND_PRICES[extra]
                    state[player]["money"] -= price
                    state[player]["unlocked_land"] += 1
                    executed[player].append({"slot": slot, "type": "BUY_LAND", "price": price})
                current[player] = None
        for _ in range(100000):
            quotes: list[tuple[str, str, int, dict[str, Any]] | None] = [None, None]
            for player, parsed in enumerate(current):
                if parsed is None or parsed["remaining"] <= 0:
                    continue
                op, item = parsed["type"], parsed["item"]
                if op == "SELL" and item in PRODUCTS:
                    quotes[player] = (op, item, market_price(item, market[item], params), parsed)
                elif op == "BUY_PRODUCT" and item in {"WHEAT", "FERTILIZER"}:
                    quotes[player] = (op, item, market_price(item, market[item] - 1, params), parsed)
                elif op == "BUY_SEED" and item in CROPS:
                    quotes[player] = (op, item, CROPS[item], parsed)
                elif op == "BUY_ANIMAL" and item in ANIMALS:
                    quotes[player] = (op, item, ANIMALS[item], parsed)
                else:
                    current[player] = None
            if all(quote is None for quote in quotes):
                break
            committed = False
            for player, quote in enumerate(quotes):
                if quote is None:
                    continue
                op, item, price, parsed = quote
                row = state[player]
                ok = False
                if op == "SELL" and row["shed"].get(item, 0) > 0:
                    row["shed"][item] -= 1
                    row["money"] += price
                    revenue[player] += price
                    if price > 1: market[item] += 1
                    ok = True
                elif op == "BUY_PRODUCT" and row["money"] >= price and sum(row["shed"].values()) < shed_capacity:
                    row["money"] -= price
                    row["shed"][item] = row["shed"].get(item, 0) + 1
                    market[item] -= 1
                    ok = True
                elif op == "BUY_SEED" and row["money"] >= price:
                    row["money"] -= price
                    row["seeds"][item] = row["seeds"].get(item, 0) + 1
                    ok = True
                elif op == "BUY_ANIMAL" and row["money"] >= price and sum(row["shed"].values()) < shed_capacity:
                    row["money"] -= price
                    row["shed"][item] = row["shed"].get(item, 0) + 1
                    ok = True
                if ok:
                    parsed["remaining"] -= 1
                    executed[player].append({"slot": slot, "type": op, "item": item, "price": price})
                    committed = True
                else:
                    current[player] = None
            if not committed:
                break
        else:
            raise RuntimeError("market loop exceeded 100000 iterations")
    return {"market_inventory": market, "players": deepcopy(state), "revenue": revenue, "executed": executed}


def expected_scenario_score(
    inventory: Mapping[str, int],
    players: Sequence[Mapping[str, Any]],
    own_orders: Sequence[Sequence[Any]],
    scenarios: Sequence[Mapping[str, Any]],
) -> tuple[float, float]:
    """Expected own cash and relative cash over complete ordered scenarios."""

    total_weight = sum(float(row.get("weight", 0.0)) for row in scenarios)
    if total_weight <= 0:
        raise ValueError("scenario weights must be positive")
    expected_own = expected_margin = 0.0
    for scenario in scenarios:
        weight = float(scenario.get("weight", 0.0)) / total_weight
        result = simulate_market(inventory, players, [own_orders, scenario.get("orders") or []])
        cash = [row["money"] for row in result["players"]]
        expected_own += weight * cash[0]
        expected_margin += weight * (cash[0] - cash[1])
    return expected_own, expected_margin


__all__ = ["MARKET_PARAMS", "PRODUCTS", "expected_scenario_score", "market_price", "simulate_market"]
