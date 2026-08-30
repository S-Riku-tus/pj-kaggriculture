"""Kaggriculture V105: day-granularity recovery-goal commitment.

V14's 72-hour goal model is trained and validated on day-boundary states.
V104 incorrectly treated intraday states as if they shared that manifold and
therefore cancelled every goal before a replacement cycle.  V105 evaluates
the learned/OOD gate only at hour zero, then keeps the admitted crop-target
delta for that day.  Current-state ownership, feed, and capacity constraints
are re-applied every turn, while V11 remains the sole concrete executor.
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
        Path.cwd() / "agents" / "v105",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (
                (candidate / "v104_base.py").is_file()
                and (candidate / "v102_base.py").is_file()
                and (candidate / "winner_goal_model.json").is_file()
            )
            or ((candidate / "main.py").is_file() and (candidate.parent / "v104" / "main.py").is_file())
        ),
        Path.cwd(),
    )


def _load_v104_module():
    packaged = MODULE_DIR / "v104_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v104" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v105_projection", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V104 projection: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v104 = _load_v104_module()
v102 = v104.v102
v14 = v104.v14
v11 = v104.v11
v10 = v104.v10
v9 = v104.v9
v8 = v104.v8
v7 = v104.v7
v6 = v104.v6
v5 = v104.v5
v4 = v104.v4
v3 = v104.v3
base = v104.base

ENABLE_DAILY_RECOVERY = True
COMMITMENT_TURNS = 24

_SAFE_STRATEGY_TARGETS = v102._SAFE_STRATEGY_TARGETS
_DAILY_DELTA: dict[str, int] | None = None
_DAILY_UNTIL_STEP = -1
_DAILY_USED_DAY = -1
_DAILY_LAST_STEP = -1
_DAILY_ACTIVATIONS = 0
_DAILY_ACTIVE_STEPS = 0
_DAILY_EMERGENCY_FALLBACKS = 0


def _clear_active() -> None:
    global _DAILY_DELTA, _DAILY_UNTIL_STEP
    _DAILY_DELTA = None
    _DAILY_UNTIL_STEP = -1


def reset_runtime_state() -> None:
    global _DAILY_ACTIVATIONS, _DAILY_ACTIVE_STEPS, _DAILY_EMERGENCY_FALLBACKS
    global _DAILY_LAST_STEP, _DAILY_USED_DAY
    v104.reset_runtime_state()
    _clear_active()
    _DAILY_USED_DAY = -1
    _DAILY_LAST_STEP = -1
    _DAILY_ACTIVATIONS = 0
    _DAILY_ACTIVE_STEPS = 0
    _DAILY_EMERGENCY_FALLBACKS = 0


def _resource_emergency(farm: Any) -> bool:
    return any(
        base._get(tile, "animal") in base.ANIMAL_DATA
        and not bool(base._get(tile, "fed_today", False))
        and base._as_int(base._get(tile, "consecutive_unfed", 0)) >= 1
        for _x, _y, tile in base._iter_tiles(farm)
    )


def _strategy_targets(
    obs: Any, farm: Any, opponent_farm: Any, private: Any
) -> tuple[dict[str, int], dict[str, int], int, int, dict[str, float], int]:
    global _DAILY_ACTIVATIONS, _DAILY_ACTIVE_STEPS, _DAILY_DELTA
    global _DAILY_EMERGENCY_FALLBACKS, _DAILY_LAST_STEP
    global _DAILY_UNTIL_STEP, _DAILY_USED_DAY

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
    hour = base._as_int(base._get(obs, "hour", 0))
    if step <= _DAILY_LAST_STEP:
        reset_runtime_state()
    _DAILY_LAST_STEP = step
    if not ENABLE_DAILY_RECOVERY:
        _clear_active()
        return baseline
    if _DAILY_DELTA is not None and step > _DAILY_UNTIL_STEP:
        _clear_active()

    # The forest and its OOD profile are day-boundary models.  Never use an
    # intraday observation to accept or reject their manifold.
    if _DAILY_DELTA is None and hour == 0 and day != _DAILY_USED_DAY:
        entry = v102._gate_decision(obs, farm, opponent_farm, private)
        _DAILY_USED_DAY = day
        if entry.get("active"):
            _DAILY_DELTA = {
                crop: int(entry["candidate_crops"][crop]) - int(baseline[1][crop])
                for crop in v14.CROPS
            }
            _DAILY_UNTIL_STEP = step + COMMITMENT_TURNS - 1
            _DAILY_ACTIVATIONS += 1

    if _DAILY_DELTA is None:
        return baseline
    if _resource_emergency(farm):
        _DAILY_EMERGENCY_FALLBACKS += 1
        _clear_active()
        return baseline
    _DAILY_ACTIVE_STEPS += 1
    return v104._reproject_delta(obs, farm, baseline, _DAILY_DELTA, 1.0)


v14._strategy_targets = _strategy_targets


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v11.policy_diagnostics(obs))
    safe = base._safe_observation(obs)
    if safe is None:
        return result
    result["v105_daily_recovery"] = {
        "enabled": ENABLE_DAILY_RECOVERY,
        "model_time_granularity": "day-boundary-only",
        "state": {
            "active": _DAILY_DELTA is not None,
            "until_step": _DAILY_UNTIL_STEP,
            "used_day": _DAILY_USED_DAY,
            "delta": dict(_DAILY_DELTA or {}),
        },
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v14.agent(obs)
