"""V114 research candidate: one residual-demand choice between V111 suffixes."""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

HERE = (
    Path(__file__).resolve().parent
    if "__file__" in globals()
    else next(
        (
            path
            for path in [Path("/kaggle_simulations/agent"), *(Path(x) for x in reversed(sys.path) if x), Path.cwd()]
            if (path / "v111_base.py").is_file()
        ),
        Path.cwd(),
    )
)
SOURCE = HERE / "v111_base.py"
if not SOURCE.exists():
    SOURCE = HERE.parent / "v111/main.py"
_spec = importlib.util.spec_from_file_location("_v114_v111", SOURCE)
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

DECISION_STEP = 153
MIN_ROBUST_MARGIN_ADVANTAGE = 2000.0
OPPONENT_SUPPLY_SCALES = (0.75, 1.0, 1.25)
ROUTES = base.base.base.public_v43._V43_ROUTES
PREFIX_COMPATIBLE = ROUTES["default"][:DECISION_STEP] == ROUTES["yarn_second"][:DECISION_STEP]
_ORIGINAL_ROUTE = base._selected_route
_STATE = {}
PARAMS = {
    "WHEAT": (25, 400, "sqrt", 0.8, "log", 0.2),
    "CARROT": (35, 450, "hinge", 1.0, "sqrt", 0.7),
    "TOMATO": (60, 200, "hinge", 0.4, "sqrt", 0.6),
    "STRAWBERRY": (120, 100, "sqrt", 0.7, "linear", 1.6),
    "MELON": (250, 300, "log", 0.2, "sq", 3.6),
    "MILK": (160, 122, "sqrt", 0.6, "linear", 1.6),
    "WOOL": (200, 105, "log", 0.2, "sq", 3.2),
    "EGG": (50, 332, "hinge", 0.4, "log", 0.2),
    "FERTILIZER": (100, 200, "linear", 0.4, "linear", 0.4),
}
SEED_COST = {"WHEAT": 10, "CARROT": 20, "TOMATO": 50, "STRAWBERRY": 100, "MELON": 80}
ANIMAL_COST = {"COW": 400, "SHEEP": 500, "GOOSE": 300}
ANIMAL_PRODUCT = {"COW": "MILK", "SHEEP": "WOOL", "GOOSE": "EGG"}


def _shape(name, x, scale):
    if name == "sqrt":
        return math.sqrt(x)
    if name == "log":
        return math.log1p(x)
    if name == "sq":
        return x * x
    if name == "hinge":
        return x / scale + 8 * max(0, x / scale - 1) ** 2
    return x


def _price(item, inventory):
    value, scale, below, below_amp, above, above_amp = PARAMS[item]
    scarcity = inventory < 10000
    shape = below if scarcity else above
    amplitude = below_amp if scarcity else above_amp
    change = amplitude * value * _shape(shape, abs(inventory - 10000), scale) / _shape(shape, scale, scale)
    return max(1, int(round(value + (change if scarcity else -change))))


def _state(obs):
    seat, step = int(obs.get("player", 0)), base._step(obs)
    if seat not in _STATE or step == 0 or step < _STATE[seat]["step"]:
        _STATE[seat] = {"step": step, "choice": None, "decision": None}
    _STATE[seat]["step"] = step
    return _STATE[seat]


def _opponent_flow(obs):
    """Public inventory-free forecast; existing portfolio, maintained-service scenario."""
    opponent = obs["farms"][1 - int(obs.get("player", 0))]
    flow = {item: 0.0 for item in PARAMS}
    for row in opponent["tiles"]:
        for tile in row:
            if not isinstance(tile, dict):
                continue
            animal, crop = tile.get("animal"), tile.get("crop")
            if animal in ANIMAL_PRODUCT:
                item = ANIMAL_PRODUCT[animal]
                interval = {"COW": 2, "SHEEP": 3, "GOOSE": 1}[animal]
                flow[item] += (1 + interval) / interval / 24
                flow["FERTILIZER"] += 1 / 24
            elif crop in flow:
                flow[crop] += {"WHEAT": 1.25, "CARROT": 1.0, "TOMATO": 0.65, "STRAWBERRY": 0.5, "MELON": 0.4}[crop] / 24
    return flow


def _route_relative_value(obs, route, supply_scale):
    """Approximate relative cash, with explicit costs and shared-price externality."""
    inventory = {item: float(obs["market"]["inventory"][item]) for item in PARAMS}
    shops = list(obs.get("town", {}).get("unlocked_shops", []))
    flow = _opponent_flow(obs)
    current_day = int(obs.get("day", 0))
    own_money = float(obs["farms"][int(obs.get("player", 0))]["money"])
    delta = 0.0
    hires, day = int(obs["farms"][int(obs.get("player", 0))].get("hires_today", 0)), current_day
    lands = len(obs["farms"][int(obs.get("player", 0))].get("unlocked_quadrants", []))
    for step in range(DECISION_STEP, 719):
        if step // 24 != day:
            day, hires = step // 24, 0
        # Unrevealed shop draws are integrated uniformly, never read from a seed.
        expected_new = max(0, min(8, day // 3) - len(shops))
        for item in PARAMS:
            demand = 0.0 if item == "FERTILIZER" else 1 / 24
            for shop in shops:
                products = base.SHOP_PRODUCTS[shop]
                if item in products:
                    demand += (2 if len(products) == 1 else 1) / 4
            demand += (
                expected_new
                * sum(
                    (2 if len(products) == 1 else 1) / 4 for products in base.SHOP_PRODUCTS.values() if item in products
                )
                / 8
            )
            inventory[item] = max(0, inventory[item] - demand)
            units = flow[item] * supply_scale
            price = _price(item, inventory[item])
            delta -= price * units
            if price > 1:
                inventory[item] += units
        for order in ROUTES[route][step].get("market", []):
            op = order[0]
            if op == "SELL" and order[1] in PARAMS:
                for _ in range(max(0, int(order[2]))):
                    price = _price(order[1], inventory[order[1]])
                    delta += price
                    own_money += price
                    if price > 1:
                        inventory[order[1]] += 1
            elif op == "HIRE":
                a, b = 1, 1
                for _ in range(hires):
                    a, b = b, a + b
                delta -= a
                own_money -= a
                hires += 1
            elif op == "BUY_LAND":
                cost = (1000, 2000, 4000)[min(2, max(0, lands - 1))]
                delta -= cost
                own_money -= cost
                lands += 1
            elif len(order) >= 3 and op in ("BUY_SEED", "BUY_ANIMAL", "BUY_PRODUCT"):
                cost = (
                    SEED_COST
                    if op == "BUY_SEED"
                    else ANIMAL_COST
                    if op == "BUY_ANIMAL"
                    else {"WHEAT": 25, "FERTILIZER": 100}
                ).get(order[1], 0) * int(order[2])
                delta -= cost
                own_money -= cost
            if own_money < 0:
                return None
    return delta


def _selected_route(obs, configuration):
    original = _ORIGINAL_ROUTE(obs, configuration)
    state = _state(obs)
    if base._step(obs) >= DECISION_STEP and state["choice"] == "yarn_second":
        return "yarn_second"
    return original


def _install():
    base._ROUTER_GLOBALS["selected_route"] = _selected_route


def reset_runtime_state():
    _STATE.clear()
    base.reset_runtime_state()
    _install()


def policy_diagnostics(obs):
    return {**base.policy_diagnostics(obs), "version": "v114", "research_decision": _state(obs)["decision"]}


def agent(obs, configuration=None):
    state = _state(obs)
    if base._step(obs) == DECISION_STEP and state["decision"] is None:
        original = str(_ORIGINAL_ROUTE(obs, configuration))
        differences = []
        if original == "default" and PREFIX_COMPATIBLE and not base._fallback_latched(obs):
            for scale in OPPONENT_SUPPLY_SCALES:
                left = _route_relative_value(obs, "default", scale)
                right = _route_relative_value(obs, "yarn_second", scale)
                if left is None or right is None:
                    differences = []
                    break
                differences.append(right - left)
            if differences and min(differences) > MIN_ROBUST_MARGIN_ADVANTAGE:
                state["choice"] = "yarn_second"
        state["decision"] = {
            "step": DECISION_STEP,
            "kind": "route_choice",
            "original": original,
            "selected": state["choice"] or original,
            "relative_value_deltas": differences,
            "committed": state["choice"] is not None,
            "threshold": MIN_ROBUST_MARGIN_ADVANTAGE,
        }
    return base.agent(obs, configuration)


_install()


def _kaggle_submission_entrypoint(obs, configuration=None):
    return agent(obs, configuration)
