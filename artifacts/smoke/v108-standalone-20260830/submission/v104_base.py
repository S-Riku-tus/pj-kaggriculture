"""Kaggriculture V104: bounded, OOD-decaying recovery-goal latch.

V102 found a narrow episode-held-out region where V14's 72-hour crop goal is
closer to winning teacher futures than V11's goal.  A one-turn goal was
behaviorally neutral, so V104 latches only the admitted *crop-target delta*
for at most one day.  The latch is reprojected through current ownership,
feed, and productive-capacity constraints every turn.  V11 still owns all
actions, routing, assignment, purchases, sales, and survival invariants.

If the state leaves V14's supported manifold the learned delta is halved each
turn and then removed.  Catching up ends the latch immediately.  Repeated or
out-of-order steps reset episode state.
"""

from __future__ import annotations

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
        Path.cwd() / "agents" / "v104",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (
                (candidate / "v102_base.py").is_file()
                and (candidate / "v14_base.py").is_file()
                and (candidate / "winner_goal_model.json").is_file()
            )
            or ((candidate / "main.py").is_file() and (candidate.parent / "v102" / "main.py").is_file())
        ),
        Path.cwd(),
    )


def _load_v102_module():
    packaged = MODULE_DIR / "v102_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v102" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v104_entry_gate", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V102 entry gate: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v102 = _load_v102_module()
v14 = v102.v14
v11 = v102.v11
v10 = v102.v10
v9 = v102.v9
v8 = v102.v8
v7 = v102.v7
v6 = v102.v6
v5 = v102.v5
v4 = v102.v4
v3 = v102.v3
base = v102.base

ENABLE_LATCHED_RECOVERY = True
COMMITMENT_TURNS = 24
OOD_DECAY = 0.5
MIN_ACTIVE_WEIGHT = 0.20

_SAFE_STRATEGY_TARGETS = v102._SAFE_STRATEGY_TARGETS
_LATCH_DELTA: dict[str, int] | None = None
_LATCH_UNTIL_STEP = -1
_LATCH_PHASE = ""
_LATCH_USED_DAY = -1
_LATCH_WEIGHT = 0.0
_LATCH_LAST_STEP = -1
_LATCH_ACTIVATIONS = 0
_LATCH_SUPPORTED_STEPS = 0
_LATCH_DECAY_STEPS = 0


def _clear_active() -> None:
    global _LATCH_DELTA, _LATCH_PHASE, _LATCH_UNTIL_STEP, _LATCH_WEIGHT
    _LATCH_DELTA = None
    _LATCH_UNTIL_STEP = -1
    _LATCH_PHASE = ""
    _LATCH_WEIGHT = 0.0


def reset_runtime_state() -> None:
    global _LATCH_LAST_STEP, _LATCH_USED_DAY
    global _LATCH_ACTIVATIONS, _LATCH_SUPPORTED_STEPS, _LATCH_DECAY_STEPS
    _clear_active()
    _LATCH_USED_DAY = -1
    _LATCH_LAST_STEP = -1
    _LATCH_ACTIVATIONS = 0
    _LATCH_SUPPORTED_STEPS = 0
    _LATCH_DECAY_STEPS = 0


def _reproject_delta(
    obs: Any,
    farm: Any,
    baseline: tuple[dict[str, int], dict[str, int], int, int, dict[str, float], int],
    delta: dict[str, int],
    weight: float,
) -> tuple[dict[str, int], dict[str, int], int, int, dict[str, float], int]:
    animals = dict(baseline[0])
    crops = {
        crop: int(baseline[1][crop]) + round(weight * int(delta.get(crop, 0)))
        for crop in v14.CROPS
    }
    summary = base._farm_summary(farm)
    for crop in v14.CROPS:
        crops[crop] = max(int(summary["crops"].get(crop, 0)), crops[crop])
    feed_floor = math.ceil((animals["COW"] + animals["SHEEP"]) * 1.2)
    crops["WHEAT"] = max(crops["WHEAT"], feed_floor)

    baseline_mass = sum(baseline[0].values()) + sum(baseline[1].values())
    floors = {crop: int(summary["crops"].get(crop, 0)) for crop in v14.CROPS}
    floors["WHEAT"] = max(floors["WHEAT"], feed_floor)
    target = dict(crops)
    crop_budget = max(baseline_mass - sum(animals.values()), sum(floors.values()))
    demand = base._demand_profile(obs)
    while sum(target.values()) > crop_budget:
        reducible = [crop for crop in v14.CROPS if target[crop] > floors[crop]]
        if not reducible:
            break
        crop = min(
            reducible,
            key=lambda value: (
                int(demand.get(v14.ITEM_DEMAND[value], 0)),
                int(base.BASE_PRICE[v14.ITEM_DEMAND[value]]),
                -int(target[value] - floors[value]),
                v14.PORTFOLIO.index(value),
            ),
        )
        target[crop] -= 1
    if sum(target.values()) < crop_budget:
        target["WHEAT"] += crop_budget - sum(target.values())
    pastures = max(v8._pasture_count(farm), animals["COW"] + animals["SHEEP"])
    return animals, target, baseline[2], baseline[3], baseline[4], pastures


def _strategy_targets(
    obs: Any, farm: Any, opponent_farm: Any, private: Any
) -> tuple[dict[str, int], dict[str, int], int, int, dict[str, float], int]:
    global _LATCH_ACTIVATIONS, _LATCH_DECAY_STEPS, _LATCH_DELTA
    global _LATCH_LAST_STEP, _LATCH_PHASE, _LATCH_SUPPORTED_STEPS
    global _LATCH_UNTIL_STEP, _LATCH_USED_DAY, _LATCH_WEIGHT

    baseline = _SAFE_STRATEGY_TARGETS(obs, farm, opponent_farm, private)
    step = base._as_int(
        base._get(
            obs,
            "step",
            base._as_int(base._get(obs, "day", 0)) * 24
            + base._as_int(base._get(obs, "hour", 0)),
        )
    )
    day = base._as_int(base._get(obs, "day", 0))
    phase = v14._phase(day)
    if step <= _LATCH_LAST_STEP:
        reset_runtime_state()
    _LATCH_LAST_STEP = step
    if not ENABLE_LATCHED_RECOVERY:
        _clear_active()
        return baseline

    entry = v102._gate_decision(obs, farm, opponent_farm, private)
    if _LATCH_DELTA is None and entry.get("active") and day != _LATCH_USED_DAY:
        _LATCH_DELTA = {
            crop: int(entry["candidate_crops"][crop]) - int(baseline[1][crop])
            for crop in v14.CROPS
        }
        _LATCH_UNTIL_STEP = step + COMMITMENT_TURNS - 1
        _LATCH_PHASE = phase
        _LATCH_USED_DAY = day
        _LATCH_WEIGHT = 1.0
        _LATCH_ACTIVATIONS += 1

    if _LATCH_DELTA is None:
        return baseline
    if step > _LATCH_UNTIL_STEP or phase != _LATCH_PHASE:
        _clear_active()
        return baseline

    prediction = v14._winner_prediction(obs, farm, opponent_farm)
    reason = str(prediction.get("reason", "inactive"))
    if prediction.get("active"):
        _LATCH_WEIGHT = min(1.0, _LATCH_WEIGHT + 0.25)
        _LATCH_SUPPORTED_STEPS += 1
    elif reason == "not-behind":
        _clear_active()
        return baseline
    else:
        _LATCH_WEIGHT *= OOD_DECAY
        _LATCH_DECAY_STEPS += 1
        if _LATCH_WEIGHT < MIN_ACTIVE_WEIGHT:
            _clear_active()
            return baseline
    return _reproject_delta(obs, farm, baseline, _LATCH_DELTA, _LATCH_WEIGHT)


v14._strategy_targets = _strategy_targets


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v11.policy_diagnostics(obs))
    safe = base._safe_observation(obs)
    if safe is None:
        return result
    farm, opponent_farm, private = safe
    entry = v102._gate_decision(obs, farm, opponent_farm, private)
    entry.pop("baseline", None)
    result["v104_latched_recovery"] = {
        "enabled": ENABLE_LATCHED_RECOVERY,
        "entry": entry,
        "commitment_turns": COMMITMENT_TURNS,
        "state": {
            "active": _LATCH_DELTA is not None,
            "until_step": _LATCH_UNTIL_STEP,
            "phase": _LATCH_PHASE,
            "used_day": _LATCH_USED_DAY,
            "weight": _LATCH_WEIGHT,
            "delta": dict(_LATCH_DELTA or {}),
        },
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v14.agent(obs)
