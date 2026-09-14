"""Force the existing V111 two-Sheep transaction for route-value research only."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

if "__file__" in globals():
    MODULE_DIR = Path(__file__).resolve().parent
else:
    MODULE_DIR = next(p for p in (Path("/kaggle_simulations/agent"), *(Path(x) for x in reversed(sys.path) if x), Path.cwd()) if (p / "v111_base.py").is_file())
_spec = importlib.util.spec_from_file_location("_livestock_v111", MODULE_DIR / "v111_base.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)
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
        eligible = state.get("late_goal") is None and not base._fallback_latched(obs) and float(base._get(own, "money", 0)) >= 1500
        _DECISIONS[seat] = {"eligible": eligible, "committed": False, "first_action_step": None}
        if eligible:
            state["late_goal"] = {"research_forced_transaction": True}
    result = base.agent(obs, configuration)
    if step == 248 and _DECISIONS.get(seat, {}).get("eligible"):
        committed = state.get("conversion") is not None
        _DECISIONS[seat].update(committed=committed, first_action_step=248 if committed else None)
    return result


def policy_diagnostics(obs):
    return {**base.policy_diagnostics(obs), "version": "v115p_livestock",
            "research_decision": dict(_DECISIONS.get(base._seat(obs), {}))}


def _kaggle_submission_entrypoint(obs, configuration=None):
    return agent(obs, configuration)
