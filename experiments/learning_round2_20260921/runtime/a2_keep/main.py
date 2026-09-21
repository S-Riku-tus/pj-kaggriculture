"""A2: bounded coherent-job overlay with KEEP_C0 as an explicit choice."""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

try:
    from .common import (
        A2ValueModel,
        MarketHistory,
        a2_candidates,
        a2_features,
        actor_context,
        actor_probe_succeeded,
        legal_actor_tokens,
        make_actor_probe,
        observation_fingerprint,
        safe_action_shape,
    )
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from common import (  # type: ignore[no-redef]
        A2ValueModel,
        MarketHistory,
        a2_candidates,
        a2_features,
        actor_context,
        actor_probe_succeeded,
        legal_actor_tokens,
        make_actor_probe,
        observation_fingerprint,
        safe_action_shape,
    )


def _module_dir() -> Path:
    return Path(__file__).resolve().parent


def _load_c0() -> Any:
    local = _module_dir() / "c0_main.py"
    repository = _module_dir().parent / "v125_exec" / "main.py"
    source = local if local.is_file() else repository
    if not source.is_file():
        raise FileNotFoundError(f"C0 is required and missing: {source}")
    spec = importlib.util.spec_from_file_location(f"_round2_a2_c0_{id(source)}", source)
    if spec is None or spec.loader is None:
        raise ImportError(source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_config() -> dict[str, Any]:
    path = _module_dir() / "arm_config.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"mode": "learned"}


base = _load_c0()
CONFIG = _load_config()
MODE = str(CONFIG.get("mode", "learned"))
T_MIN = int(CONFIG.get("t_min", 240))
MAX_JOBS = int(CONFIG.get("max_jobs", 1))
VALUE_GATE = float(CONFIG.get("value_gate", 0.0))
RISK_GATE = float(CONFIG.get("risk_gate", 0.35))
MODEL = A2ValueModel(_module_dir() / "a2_model.npz") if MODE == "learned" else None

_history: dict[int, MarketHistory] = {}
_previous_market: dict[int, list[list[Any]]] = {}
_pending: dict[int, dict[str, Any]] = {}
_jobs_used: dict[int, int] = {}
_trace: list[dict[str, Any]] = []
_stats: dict[str, int | float] = {}


def reset_runtime_state() -> None:
    global _history, _previous_market, _pending, _jobs_used, _trace, _stats
    _history, _previous_market, _pending, _jobs_used, _trace = {}, {}, {}, {}, []
    _stats = {
        "model_loads": int(MODE == "learned"),
        "base_calls": 0,
        "shadow_candidate_sets": 0,
        "candidate_sets": 0,
        "inference_calls": 0,
        "keep_choices": 0,
        "jobs_started": 0,
        "jobs_completed": 0,
        "jobs_aborted": 0,
        "primitive_successes": 0,
        "action_changes": 0,
        "fallbacks": 0,
    }
    if hasattr(base, "reset_runtime_state"):
        base.reset_runtime_state()


reset_runtime_state()


def _call_base(observation: Mapping[str, Any], configuration: Any) -> Any:
    try:
        parameters = inspect.signature(base.agent).parameters.values()
        accepts_configuration = any(
            parameter.kind in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD} for parameter in parameters
        ) or len(list(parameters)) >= 2
    except (TypeError, ValueError):
        accepts_configuration = True
    _stats["base_calls"] = int(_stats["base_calls"]) + 1
    return base.agent(observation, configuration) if accepts_configuration else base.agent(observation)


def _token(action: list[Any]) -> str:
    if not action:
        return "PASS"
    if action[0] in {"PLANT", "PICKUP", "PLACE"} and len(action) >= 2:
        return f"{action[0]}:{action[1]}"
    return str(action[0])


def _record(payload: dict[str, Any]) -> None:
    _trace.append(payload)
    if len(_trace) > 4000:
        del _trace[:1000]


def _advance_pending(
    observation: Mapping[str, Any], control: dict[str, Any], seat: int
) -> dict[str, Any] | None:
    job = _pending.get(seat)
    if job is None:
        return None
    step = int(observation.get("step", 0))
    actor = int(job["actor_index"])
    prior_ok = actor_probe_succeeded(observation, job["probe"])
    _stats["primitive_successes"] = int(_stats["primitive_successes"]) + int(prior_ok)
    if not prior_ok:
        _stats["jobs_aborted"] = int(_stats["jobs_aborted"]) + 1
        _record({"step": step, "event": "job_aborted", "reason": "previous primitive failed", **job["identity"]})
        _pending.pop(seat, None)
        return control
    if int(job["next_index"]) >= len(job["sequence"]):
        _farm, position, _inventory, _tile = actor_context(observation, actor)
        rejoined = list(position) == list(job["target"])
        if rejoined:
            _stats["jobs_completed"] = int(_stats["jobs_completed"]) + 1
        else:
            _stats["jobs_aborted"] = int(_stats["jobs_aborted"]) + 1
        _record(
            {
                "step": step,
                "event": "job_completed" if rejoined else "job_aborted",
                "rejoined": rejoined,
                "actual_position": list(position),
                **job["identity"],
            }
        )
        _pending.pop(seat, None)
        return control
    if step > int(job["deadline_step"]):
        _stats["jobs_aborted"] = int(_stats["jobs_aborted"]) + 1
        _record({"step": step, "event": "job_aborted", "reason": "deadline", **job["identity"]})
        _pending.pop(seat, None)
        return control
    _farm, position, _inventory, _tile = actor_context(observation, actor)
    action = list(job["sequence"][int(job["next_index"])])
    if list(position) != list(job["target"]) or _token(action) not in legal_actor_tokens(observation, actor):
        _stats["jobs_aborted"] = int(_stats["jobs_aborted"]) + 1
        _record({"step": step, "event": "job_aborted", "reason": "precondition", **job["identity"]})
        _pending.pop(seat, None)
        return control
    units = [list(control["farmer"]), *[list(value) for value in control["hands"]]]
    prior = list(units[actor])
    units[actor] = action
    job["next_index"] = int(job["next_index"]) + 1
    job["probe"] = make_actor_probe(observation, actor, action)
    _stats["action_changes"] = int(_stats["action_changes"]) + int(action != prior)
    _record(
        {
            "step": step,
            "event": "job_primitive",
            "proposed": action,
            "control": prior,
            "output": action,
            **job["identity"],
        }
    )
    return {"farmer": units[0], "hands": units[1:], "market": control["market"]}


def agent(observation: Mapping[str, Any], configuration: Any = None) -> dict[str, Any]:
    seat = int(observation.get("player", 0))
    history = _history.setdefault(seat, MarketHistory())
    history.update(observation, _previous_market.get(seat))
    before = observation_fingerprint(observation)
    raw = _call_base(observation, configuration)
    hand_count = len(observation["farms"][seat].get("hands", []))
    control = safe_action_shape(raw, hand_count)
    after_base = observation_fingerprint(observation)
    if before != after_base:
        raise RuntimeError("C0 modified the observation in place")

    active = _advance_pending(observation, control, seat)
    if active is not None:
        _previous_market[seat] = [list(value) for value in active["market"]]
        return active

    shadow = deepcopy(observation)
    candidates = a2_candidates(shadow, deepcopy(control), t_min=T_MIN)
    if observation_fingerprint(shadow) != before:
        raise RuntimeError("A2 encoder/candidate generation modified the observation")
    _stats["shadow_candidate_sets"] = int(_stats["shadow_candidate_sets"]) + int(bool(candidates))
    if MODE == "keep" or not candidates or _jobs_used.get(seat, 0) >= MAX_JOBS:
        _stats["keep_choices"] = int(_stats["keep_choices"]) + 1
        _previous_market[seat] = [list(value) for value in control["market"]]
        return control

    _stats["candidate_sets"] = int(_stats["candidate_sets"]) + 1
    chosen: dict[str, Any] | None = None
    scores: list[dict[str, Any]] = [{"candidate_id": "KEEP_C0", "value": 0.0, "risk": 0.0}]
    if MODE == "nonlearned":
        chosen = candidates[int(observation.get("step", 0)) % len(candidates)]
        scores.extend({"candidate_id": row["candidate_id"], "value": 0.0, "risk": 0.0} for row in candidates)
    elif MODE == "learned":
        if MODEL is None:
            raise RuntimeError("learned mode requires a2_model.npz")
        ranked = []
        for row in candidates:
            value, risk = MODEL.predict(a2_features(observation, row, history))
            _stats["inference_calls"] = int(_stats["inference_calls"]) + 1
            scores.append({"candidate_id": row["candidate_id"], "value": value, "risk": risk})
            ranked.append((value, -risk, row))
        value, negative_risk, proposed = max(ranked, key=lambda value: (value[0], value[1], value[2]["candidate_id"]))
        if value > VALUE_GATE and -negative_risk < RISK_GATE:
            chosen = proposed
    else:
        raise ValueError(f"unknown A2 mode: {MODE}")

    step = int(observation.get("step", 0))
    if chosen is None:
        _stats["keep_choices"] = int(_stats["keep_choices"]) + 1
        _record({"step": step, "event": "selection", "selected": "KEEP_C0", "scores": scores})
        _previous_market[seat] = [list(value) for value in control["market"]]
        return control

    actor = int(chosen["actor_index"])
    action = list(chosen["sequence"][0])
    if _token(action) not in legal_actor_tokens(observation, actor):
        raise RuntimeError(f"selected candidate is not executable: {chosen['candidate_id']}")
    units = [list(control["farmer"]), *[list(value) for value in control["hands"]]]
    prior = list(units[actor])
    units[actor] = action
    identity = {"job_type": chosen["job_type"], "candidate_id": chosen["candidate_id"], "actor_index": actor}
    _pending[seat] = {
        "identity": identity,
        "actor_index": actor,
        "target": list(chosen["target"]),
        "deadline_step": int(chosen["deadline_step"]),
        "sequence": deepcopy(chosen["sequence"]),
        "next_index": 1,
        "probe": make_actor_probe(observation, actor, action),
    }
    _jobs_used[seat] = _jobs_used.get(seat, 0) + 1
    _stats["jobs_started"] = int(_stats["jobs_started"]) + 1
    _stats["action_changes"] = int(_stats["action_changes"]) + int(action != prior)
    _record(
        {
            "step": step,
            "event": "selection",
            "selected": chosen["candidate_id"],
            "scores": scores,
            "proposed": action,
            "control": prior,
            "output": action,
            "reservations": chosen["reservations"],
            **identity,
        }
    )
    result = {"farmer": units[0], "hands": units[1:], "market": control["market"]}
    _previous_market[seat] = [list(value) for value in result["market"]]
    return result


def policy_diagnostics(observation: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"arm": f"A2_{MODE}", **_stats, "pending_jobs": len(_pending)}


def policy_trace() -> list[dict[str, Any]]:
    return deepcopy(_trace)
