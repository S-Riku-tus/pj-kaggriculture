"""Kaggriculture V107: demand-aligned, path-safe recovery goals.

V106 demonstrated that a day-boundary goal can reach the deterministic V11
executor, but its broad recovery gate also admitted losing development
forks.  V107 keeps the same executor and safety boundary while restricting
admission to the path supported before implementation: days 10--11, at
least 500 cash, and a crop transfer toward strictly higher visible demand.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

if "__file__" in globals():
    MODULE_DIR = Path(__file__).resolve().parent
else:
    _runtime_candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd() / "agents" / "v107",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (candidate / "v106_base.py").is_file()
            or ((candidate / "main.py").is_file() and (candidate.parent / "v106" / "main.py").is_file())
        ),
        Path.cwd(),
    )


def _load_v106_module():
    packaged = MODULE_DIR / "v106_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v106" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v107_daily_goal", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V106 daily goal: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v106 = _load_v106_module()
v105 = v106.v105
v104 = v106.v104
v102 = v106.v102
v14 = v106.v14
v11 = v106.v11
v10 = v106.v10
v9 = v106.v9
v8 = v106.v8
v7 = v106.v7
v6 = v106.v6
v5 = v106.v5
v4 = v106.v4
v3 = v106.v3
base = v106.base

ENABLE_V107_RUNTIME_GATE = True
ELIGIBLE_PHASES = frozenset({"10-11"})
MIN_CURRENT_MONEY = 500.0
MIN_DEMAND_ALIGNMENT = 0.0

_SAFE_GATE_DECISION = v102._gate_decision


def _demand_alignment(
    obs: Any,
    baseline_crops: dict[str, int],
    candidate_crops: dict[str, int],
) -> float:
    """Weighted destination demand minus weighted source demand."""
    delta = {
        crop: float(candidate_crops[crop]) - float(baseline_crops[crop])
        for crop in v14.CROPS
    }
    positive_mass = sum(max(0.0, value) for value in delta.values())
    negative_mass = sum(max(0.0, -value) for value in delta.values())
    if positive_mass <= 0.0 or negative_mass <= 0.0:
        return 0.0
    demand = base._demand_profile(obs)
    destination = sum(
        max(0.0, delta[crop]) * float(demand.get(v14.ITEM_DEMAND[crop], 0))
        for crop in v14.CROPS
    ) / positive_mass
    source = sum(
        max(0.0, -delta[crop]) * float(demand.get(v14.ITEM_DEMAND[crop], 0))
        for crop in v14.CROPS
    ) / negative_mass
    return destination - source


def _gate_decision(obs: Any, farm: Any, opponent_farm: Any, private: Any) -> dict[str, Any]:
    decision = dict(_SAFE_GATE_DECISION(obs, farm, opponent_farm, private))
    if not ENABLE_V107_RUNTIME_GATE:
        decision.update(active=False, changed=False, reason="v107-disabled")
        return decision
    if not decision.get("active"):
        return decision

    phase = str(decision.get("phase", v14._phase(base._as_int(base._get(obs, "day", 0)))))
    money = float(base._get(farm, "money", 0) or 0)
    alignment = _demand_alignment(
        obs,
        decision["baseline"][1],
        decision["candidate_crops"],
    )
    decision.update(
        v107_current_money=money,
        v107_demand_alignment=alignment,
        v107_supported_phase=phase in ELIGIBLE_PHASES,
    )
    checks = (
        (phase in ELIGIBLE_PHASES, "v107-unsupported-phase"),
        (money >= MIN_CURRENT_MONEY, "v107-cash-floor"),
        (alignment > MIN_DEMAND_ALIGNMENT, "v107-demand-misaligned"),
    )
    for passed, reason in checks:
        if not passed:
            decision.update(active=False, changed=False, reason=reason)
            return decision
    decision["reason"] = "v107-active"
    return decision


# V105 asks this shared module only at a day boundary.  Replacing this one
# admission function leaves V11's action feasibility and resource rules intact.
v102._gate_decision = _gate_decision


def reset_runtime_state() -> None:
    v106.reset_runtime_state()


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v106.policy_diagnostics(obs))
    result["v107_runtime_gate"] = {
        "enabled": ENABLE_V107_RUNTIME_GATE,
        "eligible_phases": sorted(ELIGIBLE_PHASES),
        "minimum_current_money": MIN_CURRENT_MONEY,
        "minimum_demand_alignment": "strictly greater than zero",
        "executor": "v11-deterministic",
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    v106.ENABLE_SPEC_ACCURATE_DAILY_RECOVERY = ENABLE_V107_RUNTIME_GATE
    return v106.agent(obs)
