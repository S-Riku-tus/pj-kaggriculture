"""Research-only option retaining V111's completed Cow continuation."""

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
        p
        for p in (
            Path("/kaggle_simulations/agent"),
            *(Path(x) for x in reversed(sys.path) if x),
            Path.cwd(),
        )
        if (p / "v111_base.py").is_file()
    )

_spec = importlib.util.spec_from_file_location("_retain_cow_v111", MODULE_DIR / "v111_base.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)
VERSION = "v115p_retain_cow"
if (MODULE_DIR / "option.json").is_file():
    VERSION = json.loads((MODULE_DIR / "option.json").read_text(encoding="utf-8"))["version"]
_DECISIONS = {}


def reset_runtime_state():
    _DECISIONS.clear()
    base.reset_runtime_state()


def agent(obs, configuration=None):
    step, seat = base._step(obs), base._seat(obs)
    if step == 0:
        _DECISIONS.pop(seat, None)
    state = base._state_for(obs)
    if step == 248:
        own, _ = base._farms(obs)
        standard = all(
            base._get(configuration, key, default) == default
            for key, default in {
                "boardSize": 10,
                "turnsPerDay": 24,
                "shedCapacity": 100,
                "maxMarketOrdersPerTurn": 10,
            }.items()
        )
        eligible = (
            state.get("late_goal") is not None
            and not base._fallback_latched(obs)
            and float(base._get(own, "money", 0) or 0) >= 1500
            and standard
        )
        _DECISIONS[seat] = {
            "eligible": eligible,
            "committed": False,
            "first_action_step": None,
            "saved_late_goal": copy.deepcopy(state.get("late_goal")),
        }
        if eligible:
            state["late_goal"] = None
    result = base.agent(obs, configuration)
    if step == 248 and _DECISIONS.get(seat, {}).get("eligible"):
        cow_orders = [
            order
            for order in result.get("market", [])
            if isinstance(order, list)
            and len(order) >= 3
            and order[0] == "BUY_ANIMAL"
            and order[1] == "COW"
            and int(order[2]) == 2
        ]
        committed = len(cow_orders) == 1
        _DECISIONS[seat].update(
            committed=committed,
            first_action_step=248 if committed else None,
            expected_cow_order_count=len(cow_orders),
        )
    return result


def policy_diagnostics(obs):
    return {
        **base.policy_diagnostics(obs),
        "version": VERSION,
        "research_decision": copy.deepcopy(_DECISIONS.get(base._seat(obs), {})),
    }


def _kaggle_submission_entrypoint(obs, configuration=None):
    return agent(obs, configuration)
