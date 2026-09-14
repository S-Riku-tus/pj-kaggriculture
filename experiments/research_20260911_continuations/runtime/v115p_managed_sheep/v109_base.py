"""Kaggriculture V109: current-meta route with conservative OOD recovery.

The strategic layer is the public V43 sparse-shop policy distilled from recent
top trajectories.  It owns the coherent 719-step farm plan and its two YARN
continuations.  Its deterministic executor keeps hand counts aligned, repairs
weed collisions, and orders existing SELL slots by price impact.

V109 deliberately does not blend that route with the low-rated V108 lineage.
Only clearly broken trajectory states latch to a model-disabled rule policy:
malformed actions, a repeated animal-feeding miss, or a land purchase that is
still absent after a grace interval.  A land warning must persist for two
observations before the fallback is activated.
"""

from __future__ import annotations

import copy
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
        Path.cwd() / "agents" / "v109",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (candidate / "public_v43_base.py").is_file()
            and (
                (candidate / "v11_base.py").is_file()
                or (candidate.parent / "v11" / "main.py").is_file()
            )
        ),
        Path.cwd(),
    )


def _load_module(name: str, packaged_name: str, repository_source: Path):
    packaged = MODULE_DIR / packaged_name
    source = packaged if packaged.is_file() else repository_source
    spec = importlib.util.spec_from_file_location(name, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V109 dependency: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_public_v43_isolated():
    """Load the bundled policy without shadowing repository packages.

    The standalone artifact installs embedded modules under names such as
    ``scripts.*`` and ``v23.*``.  The policy closures retain those module
    objects after construction, so the temporary import registrations can be
    restored without changing runtime behaviour.
    """
    roots = ("scripts", "v19_terminal", "v23", "v24", "v43")
    before = {
        name: module
        for name, module in tuple(sys.modules.items())
        if any(name == root or name.startswith(root + ".") for root in roots)
    }
    parent_attributes = {
        name: dict(vars(module))
        for name, module in before.items()
        if name in roots and hasattr(module, "__dict__")
    }
    module = _load_module(
        "_kaggriculture_v109_public_v43",
        "public_v43_base.py",
        MODULE_DIR / "public_v43_base.py",
    )
    generated = set(getattr(module, "_V43_MODULE_ORDER", ())) | set(roots)
    for name in sorted(generated, key=lambda value: value.count("."), reverse=True):
        if name in before:
            sys.modules[name] = before[name]
        else:
            sys.modules.pop(name, None)
        parent, separator, child = name.rpartition(".")
        if not separator or parent not in before:
            continue
        parent_module = before[parent]
        old = parent_attributes.get(parent, {})
        if child in old:
            setattr(parent_module, child, old[child])
        elif getattr(parent_module, child, None) is not None:
            delattr(parent_module, child)
    return module


public_v43 = _load_public_v43_isolated()
safe_rule = _load_module(
    "_kaggriculture_v109_rule_fallback",
    "v11_base.py",
    MODULE_DIR.parent / "v11" / "main.py",
)


def _disable_fallback_models() -> None:
    """Keep only the mature deterministic executor in the fallback stack."""
    modules = (
        safe_rule,
        safe_rule.v10,
        safe_rule.v9,
        safe_rule.v8,
        safe_rule.v7,
        safe_rule.v6,
        safe_rule.v5,
        safe_rule.v4,
        safe_rule.v3,
    )
    for module in modules:
        if hasattr(module, "MODEL"):
            module.MODEL = None
        if hasattr(module, "POLICY_MODEL"):
            module.POLICY_MODEL = None
        if hasattr(module, "DECISION_MODEL"):
            module.DECISION_MODEL = None
        if hasattr(module, "EXPERT_OPENING"):
            module.EXPERT_OPENING = {}


_disable_fallback_models()

ENABLE_V109_OOD_FALLBACK = True
LAND_WARNING_CONFIRMATIONS = 2
SECOND_LAND_GRACE_STEP = 168
THIRD_LAND_GRACE_STEP = 264
TERMINAL_FEED_CUTOFF_STEP = 696
PUBLIC_SOURCE_SHA256 = "69f06a802b62aa08f28705dab5728eb924bb6a7c23ffe0164f65b104cc3dadf3"

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


def _derived_step(obs: Any) -> int:
    raw = _get(obs, "step", None)
    if raw is not None:
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            pass
    return max(0, 24 * _as_int(_get(obs, "day", 0)) + _as_int(_get(obs, "hour", 0)))


def _normalize_observation(obs: Any) -> Any:
    """Supply the route index when a local runner omits ``obs.step``."""
    raw = _get(obs, "step", None)
    try:
        if raw is not None and int(raw) >= 0:
            return obs
    except (TypeError, ValueError):
        pass
    if isinstance(obs, dict):
        normalized = dict(obs)
    else:
        try:
            normalized = dict(obs)
        except (TypeError, ValueError):
            normalized = copy.copy(obs)
            try:
                normalized.step = _derived_step(obs)
            except (AttributeError, TypeError):
                return obs
            return normalized
    normalized["step"] = _derived_step(obs)
    return normalized


def _seat(obs: Any) -> int:
    return 1 if _as_int(_get(obs, "player", 0)) == 1 else 0


def _farm(obs: Any) -> Any | None:
    farms = list(_get(obs, "farms", []) or [])
    seat = _seat(obs)
    return farms[seat] if seat < len(farms) else None


def _iter_tiles(farm: Any):
    for row in _get(farm, "tiles", []) or []:
        if isinstance(row, dict):
            yield row
            continue
        for tile in row or []:
            if tile is not None:
                yield tile


def _animal_risk(farm: Any, step: int) -> str | None:
    # There is no following day after step 696.  Strong routes intentionally
    # stop feeding here because the escape penalty can no longer reduce yield.
    if step >= TERMINAL_FEED_CUTOFF_STEP:
        return None
    for tile in _iter_tiles(farm):
        if not _get(tile, "animal"):
            continue
        missed = max(0, _as_int(_get(tile, "consecutive_unfed", 0)))
        if missed >= 2:
            return "animal-unfed-critical"
    return None


def _trajectory_warning(obs: Any, farm: Any) -> str | None:
    step = _derived_step(obs)
    unlocked = len(set(_get(farm, "unlocked_quadrants", []) or []))
    if step >= SECOND_LAND_GRACE_STEP and unlocked < 2:
        return "second-land-missing"
    return None


def _trajectory_observation(obs: Any, farm: Any) -> str | None:
    """Report soft route drift even when fallback evidence is negative."""
    warning = _trajectory_warning(obs, farm)
    if warning is not None:
        return warning
    step = _derived_step(obs)
    unlocked = len(set(_get(farm, "unlocked_quadrants", []) or []))
    if step >= THIRD_LAND_GRACE_STEP and unlocked < 3:
        return "third-land-missing-observe-only"
    return None


def _action_problem(action: Any, farm: Any) -> str | None:
    if not isinstance(action, dict):
        return "action-not-mapping"
    farmer = action.get("farmer")
    hands = action.get("hands")
    market = action.get("market")
    if not isinstance(farmer, list) or not farmer:
        return "farmer-action-shape"
    if not isinstance(hands, list):
        return "hands-action-shape"
    if len(hands) != len(_get(farm, "hands", []) or []):
        return "hands-action-count"
    if not isinstance(market, list):
        return "market-action-shape"
    return None


def _state_for(obs: Any) -> dict[str, Any]:
    seat = _seat(obs)
    step = _derived_step(obs)
    state = _RUNTIME.get(seat)
    if state is None or step == 0 or step < int(state.get("last_step", -1)):
        state = {
            "last_step": step,
            "warning_streak": 0,
            "latched": False,
            "reason": None,
            "fallback_step": None,
        }
        _RUNTIME[seat] = state
    state["last_step"] = step
    return state


def _update_fallback(obs: Any, farm: Any, action: Any, state: dict[str, Any]) -> None:
    if state["latched"] or not ENABLE_V109_OOD_FALLBACK:
        return
    step = _derived_step(obs)
    critical = _action_problem(action, farm) or _animal_risk(farm, step)
    if critical is not None:
        state.update(latched=True, reason=critical, fallback_step=_derived_step(obs))
        return
    warning = _trajectory_warning(obs, farm)
    if warning is None:
        state["warning_streak"] = 0
        return
    state["warning_streak"] = int(state["warning_streak"]) + 1
    state["reason"] = warning
    if state["warning_streak"] >= LAND_WARNING_CONFIRMATIONS:
        state.update(latched=True, fallback_step=_derived_step(obs))


def _pass_action(farm: Any) -> dict[str, Any]:
    return {
        "farmer": ["PASS"],
        "hands": [["PASS"] for _ in (_get(farm, "hands", []) or [])],
        "market": [],
    }


def reset_runtime_state() -> None:
    """Reset both the V109 latch and all child route state."""
    _RUNTIME.clear()
    builder = getattr(public_v43, "_v43_build", None)
    if callable(builder):
        public_v43._V43_POLICY = builder(public_v43._V43_ROUTES, public_v43._V43_CONFIG)


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    normalized = _normalize_observation(obs)
    farm = _farm(normalized)
    state = _RUNTIME.get(_seat(normalized), {})
    return {
        "step": _derived_step(normalized),
        "strategic_policy": "public-v43-sparse-shop-route",
        "deterministic_executor": "weed-repair/hand-alignment/sell-impact-ordering",
        "fallback_policy": "model-disabled-v11-rule-targets/deterministic-executor",
        "fallback_enabled": ENABLE_V109_OOD_FALLBACK,
        "fallback_latched": bool(state.get("latched", False)),
        "fallback_reason": state.get("reason"),
        "fallback_step": state.get("fallback_step"),
        "warning_streak": int(state.get("warning_streak", 0)),
        "current_warning": _trajectory_observation(normalized, farm) if farm is not None else "missing-farm",
    }


def agent(obs: Any, configuration: Any = None) -> dict[str, Any]:
    normalized = _normalize_observation(obs)
    farm = _farm(normalized)
    if farm is None:
        return {"farmer": ["PASS"], "hands": [], "market": []}
    state = _state_for(normalized)
    try:
        route_action = public_v43.agent(normalized, configuration)
    except Exception:
        route_action = None
    _update_fallback(normalized, farm, route_action, state)
    if state["latched"] and ENABLE_V109_OOD_FALLBACK:
        try:
            return safe_rule.agent(normalized)
        except Exception:
            return _pass_action(farm)
    if route_action is None:
        return _pass_action(farm)
    return route_action


def _kaggle_submission_entrypoint(obs: Any, configuration: Any = None) -> dict[str, Any]:
    return agent(obs, configuration)
