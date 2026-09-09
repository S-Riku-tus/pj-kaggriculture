"""Kaggriculture V113: Development-predictive experimental continuation.

V111 remains the complete field trajectory, market-timing controller, future
goal model, and deterministic fallback.  V113 makes one active bounded change:

* the already-safe final two-Cow-to-Sheep transaction may be requested by a
  strong, in-support 72-turn animal tilt even when Yarn is not exactly shop 3;
An experimental price-sensitive SELL reordering overlay is retained only as
disabled diagnostic code after a same-seed ablation measured a small loss.

Neither overlay emits movement, maintenance, planting, or new sell quantity.
"""

from __future__ import annotations

import copy
import importlib.util
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if "__file__" in globals():
    MODULE_DIR = Path(__file__).resolve().parent
else:
    _runtime_candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd() / "agents" / "v113",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (candidate / "strategy_model.json").is_file()
            and (
                (candidate / "v111_base.py").is_file()
                or (candidate.parent / "v111" / "main.py").is_file()
            )
        ),
        Path.cwd(),
    )


def _load_module(name: str, packaged_name: str, repository_source: Path):
    packaged = MODULE_DIR / packaged_name
    source = packaged if packaged.is_file() else repository_source
    spec = importlib.util.spec_from_file_location(name, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V113 dependency: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load_module(
    "_kaggriculture_v113_base",
    "v111_base.py",
    MODULE_DIR.parent / "v111" / "main.py",
)

ENABLE_GENERALIZED_ANIMAL_GATE = True
ENABLE_PREMIUM_FIRST = False
GENERALIZED_ANIMAL_TILT = 1.5
PRICE_SENSITIVE_PRODUCTS = frozenset(
    {"TOMATO", "STRAWBERRY", "MELON", "MILK", "WOOL"}
)
ANIMAL_HORIZON_DAYS = 3.0
_RUNTIME: dict[int, dict[str, Any]] = {}


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    getter = getattr(obj, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except (AttributeError, TypeError):
            pass
    return getattr(obj, key, default)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _canonical_step(obs: Any) -> int:
    day = _get(obs, "day", None)
    hour = _get(obs, "hour", None)
    if day is not None and hour is not None:
        return max(0, 24 * _as_int(day) + _as_int(hour))
    return max(0, _as_int(_get(obs, "step", 0)))


def _normalize_observation(obs: Any) -> Any:
    step = _canonical_step(obs)
    if isinstance(obs, dict):
        if _as_int(obs.get("step", -1), -1) == step:
            return obs
        normalized = dict(obs)
        normalized["step"] = step
        return normalized
    try:
        normalized = dict(obs)
    except (TypeError, ValueError):
        normalized = copy.copy(obs)
        try:
            normalized.step = step
        except (AttributeError, TypeError):
            return obs
        return normalized
    normalized["step"] = step
    return normalized


def _seat(obs: Any) -> int:
    return 1 if _as_int(_get(obs, "player", 0)) == 1 else 0


def _new_state(step: int) -> dict[str, Any]:
    return {
        "last_step": step,
        "last_model": None,
        "generalized_goal": None,
        "model_rejections": Counter(),
        "premium_reorders": 0,
        "premium_orders_advanced": 0,
    }


def _state_for(obs: Any) -> dict[str, Any]:
    seat = _seat(obs)
    step = _canonical_step(obs)
    state = _RUNTIME.get(seat)
    if state is None or step == 0 or step < int(state.get("last_step", -1)):
        state = _new_state(step)
        _RUNTIME[seat] = state
    state["last_step"] = step
    return state


def _animal_residual_score(obs: Any) -> float | None:
    own, opponent = base._farms(obs)
    if own is None or opponent is None:
        return None
    own_assets = base._portfolio(own)
    opponent_assets = base._portfolio(opponent)
    shops = base._shops(obs)
    milk_demand = base._demand_per_day(shops, "MILK") * ANIMAL_HORIZON_DAYS
    wool_demand = base._demand_per_day(shops, "WOOL") * ANIMAL_HORIZON_DAYS
    milk_supply = (own_assets["COW"] + opponent_assets["COW"]) * ANIMAL_HORIZON_DAYS / 2.0
    wool_supply = (
        (own_assets["SHEEP"] + opponent_assets["SHEEP"])
        * ANIMAL_HORIZON_DAYS
        / 3.0
    )
    return (wool_demand - wool_supply) / base.MARKET_SCALE["WOOL"] - (
        milk_demand - milk_supply
    ) / base.MARKET_SCALE["MILK"]


def _prime_generalized_goal(obs: Any, state: dict[str, Any]) -> None:
    if _canonical_step(obs) != 216 or state.get("last_model") is not None:
        return
    prediction = base._predict_72(obs)
    if prediction is None:
        state["model_rejections"]["unavailable"] += 1
        return
    target, max_z = prediction
    tilt = float(target[-1] - target[-2])
    residual = _animal_residual_score(obs)
    state["last_model"] = {
        "step": 216,
        "animal_tilt": tilt,
        "max_abs_z": max_z,
        "in_support": max_z <= base.OOD_MAX_ABS_Z,
        "animal_residual_score": residual,
    }
    if not ENABLE_GENERALIZED_ANIMAL_GATE:
        state["model_rejections"]["disabled"] += 1
        return
    if max_z > base.OOD_MAX_ABS_Z:
        state["model_rejections"]["out-of-support"] += 1
        return
    if tilt < GENERALIZED_ANIMAL_TILT:
        state["model_rejections"]["below-tilt"] += 1
        return

    inherited_state = base._state_for(obs)
    goal = {
        "step": 216,
        "reason": "v113-development-predictive-animal-tilt",
        "animal_tilt": tilt,
        "max_abs_z": max_z,
        "animal_residual_score": residual,
    }
    inherited_state["late_goal"] = dict(goal)
    inherited_state["decision_counts"]["v113-generalized-animal-goal"] += 1
    state["generalized_goal"] = goal


def _is_price_sensitive_sell(order: Any) -> bool:
    return (
        isinstance(order, list | tuple)
        and len(order) >= 3
        and order[0] == "SELL"
        and order[1] in PRICE_SENSITIVE_PRODUCTS
    )


def _premium_first(action: Any, state: dict[str, Any]) -> Any:
    if not ENABLE_PREMIUM_FIRST or not isinstance(action, dict):
        return action
    market = list(action.get("market") or [])
    premium = [list(order) for order in market if _is_price_sensitive_sell(order)]
    if not premium:
        return action
    remainder = [list(order) for order in market if not _is_price_sensitive_sell(order)]
    reordered = [*premium, *remainder]
    if reordered == market:
        return action
    old_positions = [index for index, order in enumerate(market) if _is_price_sensitive_sell(order)]
    new_positions = list(range(len(premium)))
    state["premium_reorders"] += 1
    state["premium_orders_advanced"] += sum(
        max(0, old - new) for old, new in zip(old_positions, new_positions, strict=True)
    )
    result = copy.deepcopy(action)
    result["market"] = reordered
    return result


def reset_runtime_state() -> None:
    _RUNTIME.clear()
    base.reset_runtime_state()


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    normalized = _normalize_observation(obs)
    state = _RUNTIME.get(_seat(normalized), {})
    return {
        **base.policy_diagnostics(normalized),
        "version": "v113",
        "strategic_policy": "v111-plus-development-predictive-animal-gate",
        "canonical_step": _canonical_step(normalized),
        "generalized_animal_gate_enabled": ENABLE_GENERALIZED_ANIMAL_GATE,
        "generalized_animal_tilt": GENERALIZED_ANIMAL_TILT,
        "last_v113_model": copy.deepcopy(state.get("last_model")),
        "generalized_goal": copy.deepcopy(state.get("generalized_goal")),
        "model_rejections": dict(state.get("model_rejections", {})),
        "premium_first_enabled": ENABLE_PREMIUM_FIRST,
        "premium_reorders": int(state.get("premium_reorders", 0)),
        "premium_orders_advanced": int(state.get("premium_orders_advanced", 0)),
    }


def agent(obs: Any, configuration: Any = None) -> dict[str, Any]:
    normalized = _normalize_observation(obs)
    state = _state_for(normalized)
    _prime_generalized_goal(normalized, state)
    action = base.agent(normalized, configuration)
    return _premium_first(action, state)


def _kaggle_submission_entrypoint(obs: Any, configuration: Any = None) -> dict[str, Any]:
    return agent(obs, configuration)
