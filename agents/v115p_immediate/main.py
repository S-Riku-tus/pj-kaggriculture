"""Research-only sale option over the exact frozen V111; settings in option.json."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

if "__file__" in globals():
    MODULE_DIR = Path(__file__).resolve().parent
else:
    MODULE_DIR = next(
        p for p in (Path("/kaggle_simulations/agent"), *(Path(x) for x in reversed(sys.path) if x), Path.cwd())
        if (p / "option.json").is_file()
    )
_spec = importlib.util.spec_from_file_location("_continuation_v111", MODULE_DIR / "v111_base.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)
SETTINGS = json.loads((MODULE_DIR / "option.json").read_text(encoding="utf-8"))
PRODUCTS = ("STRAWBERRY", "MELON", "MILK", "WOOL", "CARROT", "TOMATO", "EGG")
_RUNTIME = {}


def reset_runtime_state():
    _RUNTIME.clear()
    base.reset_runtime_state()


def _state(obs):
    seat, step = base._seat(obs), base._step(obs)
    state = _RUNTIME.get(seat)
    if state is None or step == 0 or step < state["step"]:
        state = {"step": step, "eligible": False, "managed": [], "first_action_step": None, "extra_orders": 0}
        _RUNTIME[seat] = state
    state["step"] = step
    return state


def _eligible(obs, config):
    own, _ = base._farms(obs)
    return (
        own is not None and float(base._get(own, "money", 0)) >= SETTINGS["minimum_cash"]
        and not base._fallback_latched(obs)
        and all(base._get(config, k, v) == v for k, v in {
            "boardSize": 10, "turnsPerDay": 24, "shedCapacity": 100, "maxMarketOrdersPerTurn": 10,
        }.items())
    )


def _cap_orders(orders, shed, managed):
    available = dict(shed)
    result = []
    for order in orders:
        row = list(order)
        if len(row) >= 3 and row[0] == "SELL" and row[1] in managed:
            quantity = min(max(0, int(row[2])), max(0, int(available.get(row[1], 0))))
            available[row[1]] = available.get(row[1], 0) - quantity
            if not quantity:
                continue
            row[2] = quantity
        result.append(row)
    return result


def agent(obs, configuration=None):
    original = base.agent(obs, configuration)
    state = _state(obs)
    step = base._step(obs)
    if step == SETTINGS["start"]:
        state["eligible"] = _eligible(obs, configuration)
    if not state["eligible"]:
        return original
    shed = base.base._project_shed(obs, original, configuration)
    orders = _cap_orders(original.get("market", []), shed, state["managed"])
    own, _ = base._farms(obs)
    active = (
        SETTINGS["start"] <= step < SETTINGS["end"]
        and float(base._get(own, "money", 0)) >= SETTINGS["minimum_cash"]
        and not base._fallback_latched(obs)
        and (SETTINGS["mode"] == "immediate" or step % 4 == 1)
    )
    extra = []
    if active:
        remaining = dict(shed)
        for row in orders:
            if len(row) >= 3 and row[0] == "SELL":
                remaining[row[1]] = max(0, remaining.get(row[1], 0) - int(row[2]))
        prices = base._get(base._get(obs, "market", {}), "prices", {})
        choices = sorted(
            (item for item in PRODUCTS if remaining.get(item, 0) > 0),
            key=lambda item: (-float(prices.get(item, 0)) * remaining[item], item),
        )
        for item in choices[:max(0, 10 - len(orders))]:
            extra.append(["SELL", item, int(remaining[item])])
            if item not in state["managed"]:
                state["managed"].append(item)
        state["extra_orders"] += len(extra)
    result = copy.deepcopy(original)
    result["market"] = extra + orders
    if result != original and state["first_action_step"] is None:
        state["first_action_step"] = step
    # V110 infers opponent supply from our previous emitted sale, so keep its
    # remembered action consistent with the actual market contract.
    base.base._remember(obs, result, configuration, base.base._state_for(obs))
    return result


def policy_diagnostics(obs):
    state = _RUNTIME.get(base._seat(obs), {})
    return {
        **base.policy_diagnostics(obs), "version": SETTINGS["version"],
        "research_decision": {
            "eligible": bool(state.get("eligible")),
            "committed": state.get("first_action_step") is not None,
            "first_action_step": state.get("first_action_step"),
            "extra_sale_orders": state.get("extra_orders", 0),
            "managed_products": list(state.get("managed", [])),
            "settings": SETTINGS,
        },
    }


def _kaggle_submission_entrypoint(obs, configuration=None):
    return agent(obs, configuration)
