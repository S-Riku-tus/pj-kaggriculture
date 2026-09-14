"""Kaggriculture V11: capacity-aware demand rotation on V10's safe core.

V11 fixes the production-mix residual found after V10's release audit.  V10's
fixed late Wheat floor could make the requested portfolio exceed 75 cells and
crowd out demand crops.  V11 protects the episode-split-supported Carrot
branch and the Rank-1 24-hour portfolio, then assigns only the remaining
productive-cell budget to Wheat.

Experimental turnover-priority and seed-order overrides were rejected: both
made the expiry wave path-dependent and degraded at least one lower-tail
metric.  V11 therefore leaves V10's deterministic field and market executors
unchanged.  The only policy change is the feasible future portfolio target.

Sales remain V10/V9-gated.  The paired diagnostic showed a production-mix
shortfall rather than unsold terminal inventory, so changing sale labels would
fit the old opponent without addressing the teacher-supported cause.
"""

from __future__ import annotations

import copy
import importlib.util
import math
import sys
from pathlib import Path
from typing import Any

if "__file__" in globals():
    MODULE_DIR = Path(__file__).resolve().parent
else:
    _runtime_candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd() / "agents" / "v11",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (
                (candidate / "v10_base.py").is_file()
                and (candidate / "v9_base.py").is_file()
            )
            or (
                (candidate / "main.py").is_file()
                and (candidate.parent / "v10" / "main.py").is_file()
            )
        ),
        Path.cwd(),
    )


def _load_v10_module():
    packaged = MODULE_DIR / "v10_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v10" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v11_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V10 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v10 = _load_v10_module()
v9 = v10.v9
v8 = v10.v8
v7 = v10.v7
v6 = v10.v6
v5 = v10.v5
v4 = v10.v4
v3 = v10.v3
base = v10.base

CROPS = v10.CROPS
ANIMALS = v10.ANIMALS

# Rank-1 Day-24 Carrot medians are stable across the untouched episode split:
# demand 4 -> train/validation/test 11/8.5/14 and demand 6 -> 21/23/18.
# Demand 6+ uses the split-wise lower envelope.  At demand 4 the executor
# ablation showed that eight one-time crops exceeded its stable turnover rate,
# so the feasible floor is six.  Rank 2 is more aggressive; Rank 3 often waits
# until demand 6, so V11 does not copy Rank 1's upper tail.
CARROT_FLOOR = (0, 0, 0, 2, 6, 7, 18, 20, 20, 32)


def _demand_floor(table: tuple[int, ...], demand: int) -> int:
    return table[min(max(0, demand), len(table) - 1)]


def _strategy_targets(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
) -> tuple[dict[str, int], dict[str, int], int, int, dict[str, float], int]:
    """Fit the late target vector inside a 72-cell future-state budget."""
    animals, crops, hands, land, weights, pastures = v10._strategy_targets(
        obs, farm, opponent_farm, private
    )
    day = base._as_int(base._get(obs, "day", 0))
    if not 24 <= day <= 26:
        return animals, crops, hands, land, weights, pastures
    prediction = v8._expert_prediction(obs, farm, opponent_farm, private)
    if prediction is None or prediction[2] < 0.35:
        return animals, crops, hands, land, weights, pastures

    short, _long, _confidence, _distance = prediction
    demand = base._demand_profile(obs)
    carrot_demand = int(demand.get("CARROT", 0))
    # The demand-conditioned branch is reproducible from demand 3 onward.
    # With demand 0--2, Rank 1 keeps Carrot at zero in every split and V10's
    # late-Wheat target is feasible, so preserve V10 bit-for-bit there.
    if carrot_demand < 3:
        return animals, crops, hands, land, weights, pastures
    carrot_floor = _demand_floor(CARROT_FLOOR, carrot_demand)
    crops["CARROT"] = max(crops["CARROT"], carrot_floor)

    # Strawberry and Tomato cannot be newly planted this late by the safe
    # executor.  Their 24-hour atlas predictions are therefore the relevant
    # future occupancies, rather than V9's change-limited current footprint.
    # This does not remove live crops; it only stops replacing cohorts that the
    # teacher trajectory expects to rotate out.
    crops["STRAWBERRY"] = min(
        crops["STRAWBERRY"],
        max(0, round(float(short["STRAWBERRY"]))),
    )
    crops["TOMATO"] = min(
        crops["TOMATO"],
        max(0, round(float(short["TOMATO"]))),
    )
    crops["MELON"] = min(crops["MELON"], max(0, round(float(short["MELON"]))))

    animal_total = animals["COW"] + animals["SHEEP"] + animals["GOOSE"]
    feed_floor = math.ceil((animals["COW"] + animals["SHEEP"]) * 1.2)
    crop_budget = max(feed_floor, 72 - animal_total)
    non_wheat = sum(crops[crop] for crop in CROPS if crop != "WHEAT")
    wheat_capacity = max(feed_floor, crop_budget - non_wheat)
    # Preserve V10's tested late-Wheat trajectory only while it fits.  As
    # Carrot demand rises, Wheat yields exactly the cells needed by the
    # held-out-supported Carrot floor.  This reproduces the teacher branch:
    # Rank 1's Day-24 Wheat median falls while Carrot rises at demand 4--6.
    crops["WHEAT"] = max(feed_floor, min(crops["WHEAT"], wheat_capacity))

    # A target below current occupancy never removes a live crop.  It only
    # prevents the market/executor from replenishing Wheat ahead of protected
    # demand crops when the current rotation wave frees cells.
    return animals, crops, hands, land, weights, pastures


def _field_tasks(
    obs: Any,
    farm: Any,
    private: Any,
    positions: list[tuple[int, int]],
    inventories: list[Any],
    summary: dict[str, Any],
    animal_targets: dict[str, int],
    crop_targets: dict[str, int],
    pasture_target: int,
    opponent_farm: Any = None,
) -> tuple[list[dict[str, Any]], set[tuple[int, int]]]:
    """Delegate unchanged to V10's safety-tested deterministic executor."""
    return v10._field_tasks(
        obs,
        farm,
        private,
        positions,
        inventories,
        summary,
        animal_targets,
        crop_targets,
        pasture_target,
    )


def _market_plan(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
    summary: dict[str, Any],
    animal_targets: dict[str, int],
    crop_targets: dict[str, int],
    target_hands: int,
    target_land: int,
    weights: dict[str, float],
    pasture_target: int,
    actions: list[list[Any]],
    reserved: set[tuple[int, int]],
) -> tuple[list[list[Any]], dict[str, Any]]:
    orders, recovery = v10._market_plan(
        obs,
        farm,
        opponent_farm,
        private,
        summary,
        animal_targets,
        crop_targets,
        target_hands,
        target_land,
        weights,
        pasture_target,
        actions,
        reserved,
    )
    return orders, recovery


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v10.policy_diagnostics(obs))
    safe = base._safe_observation(obs)
    if safe is None:
        return result
    farm, opponent_farm, private = safe
    targets = _strategy_targets(obs, farm, opponent_farm, private)
    day = base._as_int(base._get(obs, "day", 0))
    carrot_demand = int(base._demand_profile(obs).get("CARROT", 0))
    prediction = v8._expert_prediction(obs, farm, opponent_farm, private)
    confidence = float(prediction[2]) if prediction is not None else 0.0
    if not 24 <= day <= 26:
        reason = "outside-window"
    elif prediction is None:
        reason = "no-expert-anchor"
    elif confidence < 0.35:
        reason = "low-confidence"
    elif carrot_demand < 3:
        reason = "no-carrot-branch"
    else:
        reason = "active"
    result["v11_rotation"] = {
        "active": reason == "active",
        "reason": reason,
        "carrot_demand": carrot_demand,
        "confidence": confidence,
    }
    result["v11_future_targets"] = {
        "animals": targets[0],
        "crops": targets[1],
        "productive": sum(targets[0].values()) + sum(targets[1].values()),
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    """Return a capacity-aware teacher target through V10's safe executor."""
    safe = base._safe_observation(obs)
    if safe is None:
        return {"farmer": ["PASS"], "hands": [], "market": []}
    farm, opponent_farm, private = safe
    opening = v3._safe_opening(obs, farm)
    if opening is not None:
        return copy.deepcopy(opening)
    expert_opening = v8._safe_expert_opening(obs, farm)
    if expert_opening is not None and expert_opening[1]:
        return expert_opening[0]

    summary = base._farm_summary(farm)
    animal_targets, crop_targets, target_hands, target_land, weights, pasture_target = (
        _strategy_targets(obs, farm, opponent_farm, private)
    )
    positions = [tuple(base._get(farm, "farmer", [0, 0]))]
    positions.extend(tuple(position) for position in (base._get(farm, "hands", []) or []))
    raw_inventories = list(base._get(private, "inventories", []) or [])
    inventories = [
        raw_inventories[index] if index < len(raw_inventories) else {}
        for index in range(len(positions))
    ]
    tasks, reserved = _field_tasks(
        obs,
        farm,
        private,
        positions,
        inventories,
        summary,
        animal_targets,
        crop_targets,
        pasture_target,
        opponent_farm,
    )
    actions = v9._mission_assign(
        positions,
        inventories,
        tasks,
        base._as_int(
            base._get(
                obs,
                "step",
                base._as_int(base._get(obs, "day", 0)) * 24
                + base._as_int(base._get(obs, "hour", 0)),
            )
        ),
    )
    execution_prediction = v8._expert_prediction(obs, farm, opponent_farm, private)
    actions = v10._prefer_local_water(
        obs,
        farm,
        opponent_farm,
        private,
        positions,
        inventories,
        actions,
        execution_prediction,
    )
    actions = v10._preposition_idle_workers(
        obs,
        farm,
        opponent_farm,
        private,
        positions,
        inventories,
        tasks,
        actions,
        execution_prediction,
    )
    market, _recovery = _market_plan(
        obs,
        farm,
        opponent_farm,
        private,
        summary,
        animal_targets,
        crop_targets,
        target_hands,
        target_land,
        weights,
        pasture_target,
        actions,
        reserved,
    )
    result = {
        "farmer": actions[0] if actions else ["PASS"],
        "hands": actions[1:],
        "market": market,
    }
    if expert_opening is not None:
        scripted, _copy_market = expert_opening
        result["farmer"] = scripted["farmer"]
        result["hands"] = scripted["hands"]
    return result
