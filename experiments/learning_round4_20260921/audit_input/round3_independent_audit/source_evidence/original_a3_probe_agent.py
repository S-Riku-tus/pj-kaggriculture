# ruff: noqa: E501
"""Bounded Round3 worker-plan probe; never a promotion candidate by itself."""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

try:
    from .contracts import actor_identity, validate_joint_action
except (ImportError, KeyError):
    sys.path.insert(0, str(Path.cwd()))
    from contracts import actor_identity, validate_joint_action


def _module_dir() -> Path:
    if "__file__" in globals():
        return Path(__file__).resolve().parent
    candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd(),
    )
    return next((path.resolve() for path in candidates if (path / "c0_main.py").is_file()), Path.cwd())


def _load_c0() -> Any:
    source = _module_dir() / "c0_main.py"
    spec = importlib.util.spec_from_file_location(f"_round3_probe_c0_{id(source)}", source)
    if spec is None or spec.loader is None:
        raise ImportError(source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_config() -> dict[str, Any]:
    path = _module_dir() / "arm_config.json"
    return json.loads(path.read_text(encoding="utf-8"))


base = _load_c0()
CONFIG = _load_config()
MODE = str(CONFIG["mode"])
MAX_JOBS = int(CONFIG.get("max_jobs", 1))
_pending: dict[int, dict[str, Any]] = {}
_jobs: dict[int, int] = {}
_trace: list[dict[str, Any]] = []
_stats: dict[str, int] = {}


def reset_runtime_state() -> None:
    global _pending, _jobs, _trace, _stats
    _pending, _jobs, _trace = {}, {}, []
    _stats = {
        "model_loads": 0,
        "inference_calls": 0,
        "base_calls": 0,
        "candidate_sets": 0,
        "supported_candidates": 0,
        "jobs_started": 0,
        "jobs_completed": 0,
        "jobs_aborted": 0,
        "action_changes": 0,
        "fallbacks": 0,
    }
    if hasattr(base, "reset_runtime_state"):
        base.reset_runtime_state()


reset_runtime_state()


def _call_base(observation: Mapping[str, Any], configuration: Any) -> Any:
    _stats["base_calls"] += 1
    try:
        parameters = inspect.signature(base.agent).parameters.values()
        accepts = any(value.kind in {value.VAR_POSITIONAL, value.VAR_KEYWORD} for value in parameters) or len(list(parameters)) >= 2
    except (TypeError, ValueError):
        accepts = True
    return base.agent(observation, configuration) if accepts else base.agent(observation)


def _shape(action: Mapping[str, Any], hands: int) -> dict[str, Any]:
    result = {
        "farmer": list(action.get("farmer") or ["PASS"]),
        "hands": [list(value or ["PASS"]) for value in action.get("hands") or []],
        "market": [list(value) for value in action.get("market") or []],
    }
    result["hands"].extend([["PASS"] for _ in range(max(0, hands - len(result["hands"])))])
    result["hands"] = result["hands"][:hands]
    return result


def _positions(farm: Mapping[str, Any]) -> list[list[int]]:
    return [list(farm.get("farmer") or [0, 0]), *[list(value) for value in farm.get("hands") or []]]


def _move(left: Sequence[int], right: Sequence[int]) -> list[str]:
    if int(left[0]) < int(right[0]):
        return ["EAST"]
    if int(left[0]) > int(right[0]):
        return ["WEST"]
    if int(left[1]) < int(right[1]):
        return ["SOUTH"]
    if int(left[1]) > int(right[1]):
        return ["NORTH"]
    return ["PASS"]


def _distance(left: Sequence[int], right: Sequence[int]) -> int:
    return abs(int(left[0]) - int(right[0])) + abs(int(left[1]) - int(right[1]))


def _route(left: Sequence[int], right: Sequence[int]) -> list[list[str]]:
    current = [int(left[0]), int(left[1])]
    result = []
    while current != list(right):
        action = _move(current, right)
        result.append(action)
        if action[0] == "EAST":
            current[0] += 1
        elif action[0] == "WEST":
            current[0] -= 1
        elif action[0] == "SOUTH":
            current[1] += 1
        elif action[0] == "NORTH":
            current[1] -= 1
    return result


def _tile(farm: Mapping[str, Any], position: Sequence[int]) -> Any:
    return farm["tiles"][int(position[1])][int(position[0])]


def _contract(observation: Mapping[str, Any], actor: int, kind: str, reserve: int) -> dict[str, Any]:
    step, day = int(observation.get("step", 0)), int(observation.get("day", 0))
    return {
        "candidate_id": f"{kind}:a{actor}:s{step}",
        "preconditions": {"same_day_completion": True},
        "actor_identity": actor_identity(observation, actor),
        "reserved_materials": {"shed:WHEAT": reserve} if reserve else {},
        "reserved_cash": 0,
        "reserved_shed_capacity": reserve if kind == "HARVEST_DELIVER_DAY_BOUNDARY" else 0,
        "deadline_step": day * 24 + 23,
        "continuation": [["PICKUP", "WHEAT", reserve], ["FEED"]] if reserve else [["HARVEST"], ["DROP"]],
        "safe_rejoin_boundary": {"kind": "HAND_DAY_END_DISAPPEARANCE", "day": day},
        "expected_rejoin": {"actor_absent_next_day": True, "remaining_obligations": 0},
        "primitive_postconditions": ["material transition observed"],
        "economic_postconditions": ["paired terminal margin measured"],
        "abort_policy": "SAFE_REPLAN",
        "replanning_policy": "STATE_BASED_ACTOR_REPLAN",
    }


def _unfed(farm: Mapping[str, Any]) -> list[list[int]]:
    result = []
    for y, row in enumerate(farm.get("tiles") or []):
        for x, tile in enumerate(row):
            if isinstance(tile, Mapping) and tile.get("animal") and not tile.get("fed_today"):
                result.append([x, y])
    return result


def _candidate(observation: Mapping[str, Any], control: Mapping[str, Any]) -> dict[str, Any] | None:
    seat = int(observation["player"])
    farm = observation["farms"][seat]
    positions = _positions(farm)
    shed = observation["private"].get("shed") or {}
    hour, step = int(observation.get("hour", 0)), int(observation.get("step", 0))
    if not 192 <= step <= 600 or hour > 20 or _jobs.get(seat, 0) >= MAX_JOBS:
        return None
    shed_tiles = ([4, 4], [5, 4], [4, 5], [5, 5])
    animals = _unfed(farm)
    for actor in range(1, len(positions)):
        if control["hands"][actor - 1] != ["PASS"]:
            continue
        position = positions[actor]
        if MODE in {"feed_refill", "feed_once_replan"} and position in shed_tiles and int(shed.get("WHEAT", 0)) > 0 and animals:
            target = min(animals, key=lambda value: (_distance(position, value), value))
            quantity = 1 if MODE == "feed_once_replan" else min(int(shed.get("WHEAT", 0)), max(1, len(animals)), 5)
            if hour + 1 + _distance(position, target) + 1 <= 23:
                kind = "FEED_ONCE_STATE_REPLAN" if MODE == "feed_once_replan" else "FEED_REFILL_DAY_BOUNDARY"
                contract = _contract(observation, actor, kind, quantity)
                if MODE == "feed_once_replan":
                    contract["safe_rejoin_boundary"] = {"kind": "FEED_POSTCONDITION_OBSERVED"}
                    contract["expected_rejoin"] = {
                        "position": target,
                        "minimum_inventory": {},
                        "remaining_obligations": 0,
                    }
                    contract["continuation"] = [["PICKUP", "WHEAT", 1], *_route(position, target), ["FEED"]]
                contract.update({"phase": "pickup", "origin": position, "target": target, "remaining": quantity})
                return contract
        if MODE == "harvest_deliver":
            tile = _tile(farm, position)
            if isinstance(tile, Mapping) and tile.get("kind") == "PLANT" and int(tile.get("yield_units", 0)) > 0:
                target = min(shed_tiles, key=lambda value: (_distance(position, value), value))
                if hour + 1 + _distance(position, target) + 1 <= 23:
                    contract = _contract(observation, actor, "HARVEST_DELIVER_DAY_BOUNDARY", int(tile.get("yield_units", 0)))
                    contract.update({"phase": "harvest", "origin": position, "target": target, "remaining": 1})
                    return contract
    return None


def _pending_action(observation: Mapping[str, Any], job: dict[str, Any]) -> list[Any]:
    seat, actor = int(observation["player"]), int(job["actor_identity"]["actor_index"])
    farm = observation["farms"][seat]
    positions = _positions(farm)
    if int(observation.get("day", 0)) != int(job["actor_identity"]["day_epoch"]) or actor >= len(positions):
        job["phase"] = "complete"
        return ["PASS"]
    position = positions[actor]
    inventory = (observation["private"].get("inventories") or [])[actor]
    if job["candidate_id"].startswith(("FEED_REFILL", "FEED_ONCE")):
        if job["phase"] == "pickup":
            job["phase"] = "feed_route"
            return ["PICKUP", "WHEAT", int(job["remaining"])]
        if int(inventory.get("WHEAT", 0)) >= int(job["remaining"]):
            job["reserved_materials"] = {f"actor:{actor}:WHEAT": int(job["remaining"])}
        if job["candidate_id"].startswith("FEED_ONCE") and job["phase"] == "verify_feed":
            target = list(job["target"])
            tile = _tile(farm, target)
            if position == target and isinstance(tile, Mapping) and bool(tile.get("fed_today")):
                job["phase"] = "complete"
                return ["PASS"]
            job["phase"] = "aborted"
            return ["PASS"]
        animals = _unfed(farm)
        if not animals or int(inventory.get("WHEAT", 0)) <= 0 or int(observation.get("hour", 0)) >= 23:
            return ["PASS"]
        target = min(animals, key=lambda value: (_distance(position, value), value))
        if position != target:
            return _move(position, target)
        if job["candidate_id"].startswith("FEED_ONCE"):
            job["phase"] = "verify_feed"
        return ["FEED"]
    if job["phase"] == "harvest":
        job["phase"] = "deposit_route"
        return ["HARVEST"]
    if position != list(job["target"]):
        return _move(position, job["target"])
    if sum(int(value) for value in inventory.values()) > 0:
        job["phase"] = "wait_boundary"
        return ["DROP"]
    return ["PASS"]


def _record(row: dict[str, Any]) -> None:
    _trace.append(row)
    if len(_trace) > 4000:
        del _trace[:1000]


def _agent_impl(observation: Mapping[str, Any], configuration: Any = None) -> dict[str, Any]:
    seat = int(observation["player"])
    raw = _call_base(observation, configuration)
    hands = len(observation["farms"][seat].get("hands") or [])
    control = _shape(raw, hands)
    job = _pending.get(seat)
    if job is not None and int(observation.get("day", 0)) != int(job["actor_identity"]["day_epoch"]):
        _stats["jobs_completed"] += 1
        _record({"step": int(observation.get("step", 0)), "event": "safe_day_boundary", "candidate_id": job["candidate_id"]})
        _pending.pop(seat, None)
        job = None
    if job is None:
        _stats["candidate_sets"] += 1
        job = _candidate(observation, control)
        if job is None:
            return control
        _stats["supported_candidates"] += 1
        actor = int(job["actor_identity"]["actor_index"])
        proposal = deepcopy(control)
        proposal["hands"][actor - 1] = _pending_action(observation, job)
        reasons = validate_joint_action(observation, proposal, [job])
        if reasons:
            _stats["fallbacks"] += 1
            _record({"step": int(observation.get("step", 0)), "event": "candidate_rejected", "reasons": reasons, "candidate_id": job["candidate_id"]})
            return control
        _pending[seat] = job
        _jobs[seat] = _jobs.get(seat, 0) + 1
        _stats["jobs_started"] += 1
        _stats["action_changes"] += int(proposal != control)
        _record({"step": int(observation.get("step", 0)), "event": "candidate_started", "contract": deepcopy(job)})
        return proposal
    actor = int(job["actor_identity"]["actor_index"])
    if actor > hands:
        _stats["jobs_aborted"] += 1
        _pending.pop(seat, None)
        return control
    proposal = deepcopy(control)
    proposal["hands"][actor - 1] = _pending_action(observation, job)
    if job.get("phase") == "complete":
        _stats["jobs_completed"] += 1
        _record({"step": int(observation.get("step", 0)), "event": "state_replan_boundary", "candidate_id": job["candidate_id"]})
        _pending.pop(seat, None)
        return control
    if job.get("phase") == "aborted":
        _stats["jobs_aborted"] += 1
        _record({"step": int(observation.get("step", 0)), "event": "postcondition_failed", "candidate_id": job["candidate_id"]})
        _pending.pop(seat, None)
        return control
    reasons = validate_joint_action(observation, proposal, [job])
    if reasons:
        proposal["hands"][actor - 1] = ["PASS"]
        _stats["fallbacks"] += 1
        _record({"step": int(observation.get("step", 0)), "event": "state_replan_pass", "reasons": reasons, "candidate_id": job["candidate_id"]})
    _stats["action_changes"] += int(proposal != control)
    return proposal


def policy_diagnostics(_observation: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"arm": f"A3_probe_{MODE}", **_stats, "active_jobs": len(_pending)}


def policy_trace() -> list[dict[str, Any]]:
    return deepcopy(_trace)


# Kaggle selects the final callable in the exec namespace.  Keep agent last.
def agent(observation: Mapping[str, Any], configuration: Any = None) -> dict[str, Any]:
    return _agent_impl(observation, configuration)
