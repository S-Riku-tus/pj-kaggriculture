"""Kaggriculture V101: bounded early Strawberry optionality on V14.

V101 retains V14's complete deterministic executor, herd target, market
controller, OOD fallback, and winner-recovery crop model.  During a narrow
Day-8..15 regime it may stop increasing the future Strawberry target when
Town demand is weak, the opponent already has public Strawberry capacity, and
V3's existing expert gate does not identify a Rank-3-like regime.  Existing
crops are never removed and the branch expires automatically on Day 16.
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
        Path.cwd() / "agents" / "v101",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (
                (candidate / "v14_base.py").is_file()
                and (candidate / "winner_goal_model.json").is_file()
                and (candidate / "strategy_model.json").is_file()
            )
            or ((candidate / "main.py").is_file() and (candidate.parent / "v14" / "main.py").is_file())
        ),
        Path.cwd(),
    )


def _load_v14_module():
    packaged = MODULE_DIR / "v14_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v14" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v101_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V14 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v14 = _load_v14_module()
v11 = v14.v11
v10 = v14.v10
v9 = v14.v9
v8 = v14.v8
v7 = v14.v7
v6 = v14.v6
v5 = v14.v5
v4 = v14.v4
v3 = v14.v3
base = v14.base

ENABLE_EARLY_OPTIONALITY = False
DAY_START = 8
DAY_END = 15
MAX_BERRY_DEMAND = 1
OPPONENT_BERRY_THRESHOLD = 16.0
MAX_RANK3_WEIGHT = 0.25
BERRY_INTERCEPT = 16.0
BERRY_DEMAND_SLOPE = 6.0
OPPONENT_EXCESS_SLOPE = 0.2
MIN_EXPERT_CONFIDENCE = 0.35

_SAFE_STRATEGY_TARGETS = v14._strategy_targets


def _branch_decision(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
    baseline_crops: dict[str, int],
) -> dict[str, Any]:
    day = base._as_int(base._get(obs, "day", 0))
    result: dict[str, Any] = {
        "active": False,
        "changed": False,
        "reason": "disabled" if not ENABLE_EARLY_OPTIONALITY else "outside-window",
        "day": day,
        "baseline_strawberry": int(baseline_crops["STRAWBERRY"]),
        "selected_strawberry": int(baseline_crops["STRAWBERRY"]),
    }
    if not ENABLE_EARLY_OPTIONALITY or not DAY_START <= day <= DAY_END:
        return result

    expert_prediction = v8._expert_prediction(obs, farm, opponent_farm, private)
    if expert_prediction is None:
        result["reason"] = "no-expert-anchor"
        return result
    confidence = float(expert_prediction[2])
    result["expert_confidence"] = confidence
    if confidence < MIN_EXPERT_CONFIDENCE:
        result["reason"] = "ood-or-low-confidence"
        return result

    demand = base._demand_profile(obs)
    berry_demand = int(demand.get("STRAWBERRY", 0))
    opponent_summary = base._farm_summary(opponent_farm)
    opponent_berry = float(opponent_summary["crops"].get("STRAWBERRY", 0))
    weights = v3._expert_weights(obs, day)
    rank3_weight = float(weights.get("rank3", 1.0))
    result.update(
        {
            "berry_demand": berry_demand,
            "opponent_strawberry": opponent_berry,
            "expert_weights": {name: float(value) for name, value in weights.items()},
        }
    )
    if berry_demand > MAX_BERRY_DEMAND:
        result["reason"] = "demand-strong"
        return result
    if opponent_berry < OPPONENT_BERRY_THRESHOLD:
        result["reason"] = "opponent-supply-low"
        return result
    if rank3_weight > MAX_RANK3_WEIGHT:
        result["reason"] = "rank3-regime"
        return result

    cap = round(
        BERRY_INTERCEPT
        + BERRY_DEMAND_SLOPE * berry_demand
        - OPPONENT_EXCESS_SLOPE * max(0.0, opponent_berry - OPPONENT_BERRY_THRESHOLD)
    )
    current = int(base._farm_summary(farm)["crops"].get("STRAWBERRY", 0))
    selected = max(current, min(int(baseline_crops["STRAWBERRY"]), cap))
    result.update(
        {
            "active": True,
            "changed": selected < int(baseline_crops["STRAWBERRY"]),
            "reason": "bounded-wait" if selected < int(baseline_crops["STRAWBERRY"]) else "already-committed",
            "cap": cap,
            "current_strawberry": current,
            "selected_strawberry": selected,
            "withheld_target": int(baseline_crops["STRAWBERRY"]) - selected,
        }
    )
    return result


def _strategy_targets(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
) -> tuple[dict[str, int], dict[str, int], int, int, dict[str, float], int]:
    animals, crops, hands, land, weights, pastures = _SAFE_STRATEGY_TARGETS(
        obs, farm, opponent_farm, private
    )
    decision = _branch_decision(obs, farm, opponent_farm, private, crops)
    if not decision.get("changed"):
        return animals, crops, hands, land, weights, pastures
    selected_crops = dict(crops)
    selected_crops["STRAWBERRY"] = int(decision["selected_strawberry"])
    return animals, selected_crops, hands, land, weights, pastures


v14._strategy_targets = _strategy_targets


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v14.policy_diagnostics(obs))
    safe = base._safe_observation(obs)
    if safe is None:
        return result
    farm, opponent_farm, private = safe
    baseline = _SAFE_STRATEGY_TARGETS(obs, farm, opponent_farm, private)
    selected = _strategy_targets(obs, farm, opponent_farm, private)
    decision = _branch_decision(obs, farm, opponent_farm, private, baseline[1])
    decision["animals_unchanged"] = selected[0] == baseline[0]
    decision["non_strawberry_crops_unchanged"] = all(
        selected[1][crop] == baseline[1][crop]
        for crop in v14.CROPS
        if crop != "STRAWBERRY"
    )
    result["v101_early_optionality"] = decision
    result["v101_future_targets"] = {"animals": selected[0], "crops": selected[1]}
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v14.agent(obs)
