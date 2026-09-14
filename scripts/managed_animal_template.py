"""Research-only two-animal purchase, transport, placement, service, sale contract."""

# ruff: noqa: E501

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

if "__file__" in globals():
    MODULE_DIR = Path(__file__).resolve().parent
else:
    MODULE_DIR = next(p for p in (Path("/kaggle_simulations/agent"), *(Path(x) for x in reversed(sys.path) if x), Path.cwd()) if (p / "animal_option.json").is_file())
_spec = importlib.util.spec_from_file_location("_managed_v111", MODULE_DIR / "v111_base.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)
SETTINGS = json.loads((MODULE_DIR / "animal_option.json").read_text(encoding="utf-8"))
SPECIES = SETTINGS["species"]
PRODUCT = {"SHEEP": "WOOL", "GOOSE": "EGG"}[SPECIES]
_RUNTIME = {}


def reset_runtime_state():
    _RUNTIME.clear()
    base.reset_runtime_state()


def _count(obs):
    own, _ = base._farms(obs)
    private = base._private(obs)
    return (
        sum(tile.get("animal") == SPECIES for row in own["tiles"] for tile in row if isinstance(tile, dict))
        + int(private["shed"].get(SPECIES, 0))
        + sum(int(inv.get(SPECIES, 0)) for inv in private["inventories"])
    )


def _state(obs):
    seat, step = base._seat(obs), base._step(obs)
    state = _RUNTIME.get(seat)
    if state is None or step == 0 or step < state["step"]:
        state = {"step": step, "eligible": False, "committed": False, "carriers": [], "targets": [],
                 "picked": 0, "placed_requested": 0, "purchase_confirmed": False,
                 "empty_harvest_skips": 0, "extra_sale_orders": 0}
        _RUNTIME[seat] = state
    state["step"] = step
    return state


def agent(obs, configuration=None):
    original = base.agent(obs, configuration)
    state = _state(obs)
    step = base._step(obs)
    own, _ = base._farms(obs)
    private = base._private(obs)
    result = copy.deepcopy(original)
    if step == 248:
        purchases = [i for i, o in enumerate(result.get("market", [])) if o == ["BUY_ANIMAL", "COW", 2]]
        shed = base.base._project_shed(obs, original, configuration)
        standard = all(base._get(configuration, k, v) == v for k, v in {"boardSize": 10, "turnsPerDay": 24, "shedCapacity": 100, "maxMarketOrdersPerTurn": 10}.items())
        state["eligible"] = len(purchases) == 1 and purchases[0] < 10 and own["money"] >= 1500 and sum(shed.values()) <= 98 and not base._fallback_latched(obs) and standard
        if state["eligible"]:
            state["initial_owned"] = _count(obs)
            state["committed"] = True
            result["market"][purchases[0]][1] = SPECIES
    if not state["committed"]:
        return original
    if step == 249:
        state["purchase_confirmed"] = _count(obs) >= state["initial_owned"] + 2
    positions = [own["farmer"], *own["hands"]]
    actors = [result.get("farmer", ["PASS"]), *result.get("hands", [])]
    if step > 248:
        for index, raw in enumerate(actors):
            if index >= len(positions):
                continue
            inv = private["inventories"][index]
            xy = positions[index]
            tile = own["tiles"][xy[1]][xy[0]]
            if len(raw) >= 3 and raw[:2] == ["PICKUP", "COW"] and 0 < int(raw[2]) <= 2 - state["picked"] and private["shed"].get(SPECIES, 0) >= int(raw[2]):
                raw[1] = SPECIES
                state["picked"] += int(raw[2])
                state["carriers"].append(index)
            elif index in state["carriers"] and inv.get(SPECIES, 0) > 0:
                if raw[0] == "BUILD_PASTURE" and SPECIES == "GOOSE":
                    raw[0] = "BUILD_COOP"
                elif raw[:2] == ["PLACE", "COW"] and state["placed_requested"] < 2:
                    raw[1] = SPECIES
                    state["placed_requested"] += 1
                    state["targets"].append(list(xy))
            if xy in state["targets"] and raw[0] == "HARVEST" and isinstance(tile, dict) and tile.get("animal") == SPECIES and tile.get("yield_units", 0) <= 0:
                actors[index] = ["PASS"]
                state["empty_harvest_skips"] += 1
        result["farmer"], result["hands"] = actors[0], actors[1:]
    # Exact stock of non-input products; no purchase/worker/seed order removed.
    shed = base.base._project_shed(obs, result, configuration)
    available = dict(shed)
    orders = []
    for order in result.get("market", []):
        row = list(order)
        if len(row) >= 3 and row[0] == "SELL" and row[1] in {PRODUCT, "MILK"}:
            row[2] = min(max(0, int(row[2])), max(0, available.get(row[1], 0)))
            available[row[1]] = available.get(row[1], 0) - row[2]
            if not row[2]:
                continue
        orders.append(row)
    if len(orders) < 10 and available.get(PRODUCT, 0) > 0:
        orders.insert(0, ["SELL", PRODUCT, int(available[PRODUCT])])
        state["extra_sale_orders"] += 1
    result["market"] = orders
    base.base._remember(obs, result, configuration, base.base._state_for(obs))
    return result


def policy_diagnostics(obs):
    state = _RUNTIME.get(base._seat(obs), {})
    own, _ = base._farms(obs)
    placed = sum(isinstance(own["tiles"][xy[1]][xy[0]], dict) and own["tiles"][xy[1]][xy[0]].get("animal") == SPECIES for xy in state.get("targets", [])) if own else 0
    return {**base.policy_diagnostics(obs), "version": SETTINGS["version"], "research_decision": {
        **copy.deepcopy(state), "first_action_step": 248 if state.get("committed") else None,
        "species": SPECIES, "placement_confirmed": placed,
    }}


def _kaggle_submission_entrypoint(obs, configuration=None):
    return agent(obs, configuration)
