"""Learning-A task selector with explicit, observation-checked FEED jobs."""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

try:
    from .common import (
        WORK_OPS,
        MarketHistory,
        SavedMLP,
        action_token,
        actor_context,
        actor_features,
        actor_probe_succeeded,
        legal_actor_tokens,
        make_actor_probe,
        safe_action_shape,
        shed_access,
        work_legal_ops,
    )
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from common import (
        WORK_OPS,
        MarketHistory,
        SavedMLP,
        action_token,
        actor_context,
        actor_features,
        actor_probe_succeeded,
        legal_actor_tokens,
        make_actor_probe,
        safe_action_shape,
        shed_access,
        work_legal_ops,
    )


def _module_dir() -> Path:
    return Path(__file__).resolve().parent


def _load_c0() -> Any:
    source = _module_dir() / "c0_main.py"
    if not source.is_file():
        source = _module_dir().parent / "v125_exec" / "main.py"
    spec = importlib.util.spec_from_file_location(f"_learning_a_c0_{id(source)}", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"C0 could not be loaded: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load_c0()
config_path = _module_dir() / "arm_config.json"
CONFIG = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {"mode": "learned"}
MODE = str(CONFIG.get("mode", "learned"))
MODEL = SavedMLP(_module_dir() / "a_model.npz") if MODE == "learned" else None
_history: dict[int, MarketHistory] = {}
_jobs: dict[tuple[int, int], dict[str, Any]] = {}
_last_hour: dict[int, int] = {}
_probes: dict[int, list[dict[str, Any]]] = {}
_stats: dict[str, int] = {}


def reset_runtime_state() -> None:
    global _history, _jobs, _last_hour, _probes, _stats
    _history, _jobs, _last_hour, _probes = {}, {}, {}, {}
    _stats = {
        "model_loads": int(MODE == "learned"),
        "inference_calls": 0,
        "task_boundaries": 0,
        "action_changes": 0,
        "jobs_started": 0,
        "jobs_completed": 0,
        "jobs_aborted": 0,
        "fallbacks": 0,
        "changed_action_checks": 0,
        "changed_action_successes": 0,
    }
    if hasattr(base, "reset_runtime_state"):
        base.reset_runtime_state()


reset_runtime_state()


def _call_base(observation: Mapping[str, Any], configuration: Any) -> Any:
    try:
        parameters = inspect.signature(base.agent).parameters.values()
        accepts_configuration = (
            any(parameter.kind in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD} for parameter in parameters)
            or len(list(parameters)) >= 2
        )
    except (TypeError, ValueError):
        accepts_configuration = True
    return base.agent(observation, configuration) if accepts_configuration else base.agent(observation)


def _move(position: tuple[int, int], target: tuple[int, int]) -> list[str]:
    x, y = position
    tx, ty = target
    if x < tx:
        return ["EAST"]
    if x > tx:
        return ["WEST"]
    if y < ty:
        return ["SOUTH"]
    if y > ty:
        return ["NORTH"]
    return ["PASS"]


def _nearest_shed(position: tuple[int, int]) -> tuple[int, int]:
    return min(
        ((4, 4), (5, 4), (4, 5), (5, 5)), key=lambda target: abs(target[0] - position[0]) + abs(target[1] - position[1])
    )


def _job_action(observation: Mapping[str, Any], seat: int, actor_index: int) -> list[Any] | None:
    key = (seat, actor_index)
    job = _jobs.get(key)
    if job is None:
        return None
    _farm, position, inventory, tile = actor_context(observation, actor_index)
    tile_map = tile if isinstance(tile, Mapping) else {}
    target = tuple(job["target"])
    if job["phase"] == "to_shed":
        if int(inventory.get("WHEAT", 0)) > 0:
            job["phase"] = "return"
        elif shed_access(position):
            if int(observation["private"]["shed"].get("WHEAT", 0)) <= 0:
                _jobs.pop(key, None)
                _stats["jobs_aborted"] += 1
                return ["PASS"]
            return ["PICKUP", "WHEAT", 1]
        else:
            return _move(position, tuple(job["shed"]))
    if job.get("phase") == "return":
        if int(inventory.get("WHEAT", 0)) <= 0:
            _jobs.pop(key, None)
            _stats["jobs_aborted"] += 1
            return ["PASS"]
        if position != target:
            return _move(position, target)
        if tile_map.get("kind") not in {"COOP", "PASTURE"} or not tile_map.get("animal") or tile_map.get("fed_today"):
            _jobs.pop(key, None)
            _stats["jobs_aborted"] += 1
            return ["PASS"]
        _jobs.pop(key, None)
        _stats["jobs_completed"] += 1
        return ["FEED"]
    _jobs.pop(key, None)
    _stats["jobs_aborted"] += 1
    return ["PASS"]


def _choose_work(observation: Mapping[str, Any], actor_index: int, history: MarketHistory) -> str | None:
    legal = work_legal_ops(observation, actor_index)
    _farm, position, inventory, tile = actor_context(observation, actor_index)
    tile_map = tile if isinstance(tile, Mapping) else {}
    feed_job = (
        tile_map.get("kind") in {"COOP", "PASTURE"}
        and tile_map.get("animal")
        and not tile_map.get("fed_today")
        and int(inventory.get("WHEAT", 0)) <= 0
        and int(observation["private"]["shed"].get("WHEAT", 0)) > 0
    )
    if feed_job:
        legal.add("FEED")
    if not legal:
        return None
    if MODE == "baseline":
        priority = (
            "FEED",
            "HARVEST",
            "WATER",
            "CARE",
            "COLLECT_FERTILIZER",
            "FERTILIZE",
            "DROP",
            "PICKUP",
            "PLACE",
            "PLANT",
            "DIG",
        )
        return next((op for op in priority if op in legal), None)
    if MODEL is None:
        raise RuntimeError("learned A mode has no model")
    probability = MODEL.probabilities(actor_features(observation, actor_index, history))
    _stats["inference_calls"] += 1
    ranked = sorted(zip(MODEL.classes, probability, strict=True), key=lambda pair: -float(pair[1]))
    return next((op for op, _score in ranked if op in legal), None)


def _materialize_work(
    observation: Mapping[str, Any], actor_index: int, chosen: str, control_action: list[Any]
) -> list[Any] | None:
    legal = legal_actor_tokens(observation, actor_index)
    if control_action and str(control_action[0]) == chosen and action_token(control_action) in legal:
        return list(control_action)
    matching = sorted(token for token in legal if token.split(":", 1)[0] == chosen)
    if not matching:
        return None
    token = matching[0]
    if ":" not in token:
        return [token]
    op, item = token.split(":", 1)
    if op in {"PICKUP", "PLACE"}:
        return [op, item, 1]
    return [op, item]


def agent(observation: Mapping[str, Any], configuration: Any = None) -> dict[str, Any]:
    seat = int(observation.get("player", 0))
    prior_probes = _probes.pop(seat, [])
    _stats["changed_action_checks"] += len(prior_probes)
    _stats["changed_action_successes"] += sum(
        actor_probe_succeeded(observation, probe) for probe in prior_probes
    )
    hour = int(observation.get("hour", 0))
    if hour == 0 and _last_hour.get(seat) not in {None, 0}:
        for key in [key for key in _jobs if key[0] == seat]:
            _jobs.pop(key, None)
            _stats["jobs_aborted"] += 1
    _last_hour[seat] = hour
    history = _history.setdefault(seat, MarketHistory())
    history.update(observation)
    raw = _call_base(observation, configuration)
    hand_count = len(observation["farms"][seat].get("hands", []))
    control = safe_action_shape(raw, hand_count)
    units = [list(control["farmer"]), *[list(action) for action in control["hands"]]]
    for index, control_action in enumerate(list(units)):
        active = _job_action(observation, seat, index)
        if active is not None:
            units[index] = active
            _stats["action_changes"] += int(active != control_action)
            continue
        op = str(control_action[0]) if control_action else "PASS"
        if op not in WORK_OPS:
            continue
        _stats["task_boundaries"] += 1
        chosen = _choose_work(observation, index, history)
        if chosen is None:
            continue
        _farm, position, inventory, tile = actor_context(observation, index)
        tile_map = tile if isinstance(tile, Mapping) else {}
        if chosen == "FEED" and int(inventory.get("WHEAT", 0)) <= 0 and tile_map.get("animal"):
            _jobs[(seat, index)] = {"phase": "to_shed", "target": list(position), "shed": list(_nearest_shed(position))}
            _stats["jobs_started"] += 1
            selected = _job_action(observation, seat, index) or ["PASS"]
        elif chosen in work_legal_ops(observation, index):
            selected = _materialize_work(observation, index, chosen, control_action) or ["PASS"]
        else:
            _stats["fallbacks"] += 1
            selected = ["PASS"]
        if selected != control_action:
            units[index] = selected
            _stats["action_changes"] += 1
    _probes[seat] = [
        make_actor_probe(observation, index, action)
        for index, (action, control_action) in enumerate(
            zip(units, [control["farmer"], *control["hands"]], strict=True)
        )
        if action != control_action and action and action[0] != "PASS"
    ]
    return {"farmer": units[0], "hands": units[1:], "market": control["market"]}


def policy_diagnostics(observation: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"arm": f"A_{MODE}", **_stats}
