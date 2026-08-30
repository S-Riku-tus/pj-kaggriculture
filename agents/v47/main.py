"""V47: conservative continuity bonus for active movement missions.

V46 found a cross-split executor gap: V11 immediately reverses 1.5--2.6% of
movement orders while Top-3 agents are near zero.  This wrapper preserves the
V14 strategy and task set.  Only when the safe assignment would immediately
reverse the previous move, the exact still-feasible prior task receives a
bounded two-tile-equivalent assignment bonus.  Emergency tasks disable the
guard.  Irregular calls, day boundaries, and disabled mode fall back to V14.
"""

from __future__ import annotations

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
        Path.cwd() / "agents" / "v47",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (candidate / "v14_base.py").is_file()
            or (
                (candidate / "main.py").is_file()
                and (candidate.parent / "v14" / "main.py").is_file()
            )
        ),
        Path.cwd(),
    )


def _load_v14_module():
    packaged = MODULE_DIR / "v14_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v14" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v47_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V14 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v14 = _load_v14_module()
v9 = v14.v9
v5 = v9.v5
base = v14.base

ENABLE_ANTI_REVERSAL = False
ACTIVE_DAYS = range(5, 15)
CONTINUITY_BONUS = 900
CONTINUITY_TASK_ACTIONS: frozenset[str] | None = None
EMERGENCY_PRIORITY = 15000
MOVES = {"NORTH", "SOUTH", "EAST", "WEST"}
OPPOSITE = {"NORTH": "SOUTH", "SOUTH": "NORTH", "EAST": "WEST", "WEST": "EAST"}
_SAFE_MISSION_ASSIGN = v9._mission_assign
_LAST_STEP = -1
_PREVIOUS_ACTIONS: list[list[Any]] = []
_MISSIONS: dict[int, tuple[Any, ...]] = {}


def _signature(task: dict[str, Any]) -> tuple[Any, ...]:
    return (
        task.get("pos"),
        tuple(task.get("action") or ()),
        task.get("required"),
        task.get("unit"),
        str(task.get("label", "")),
    )


def _assigned_actions(
    positions: list[tuple[int, int]],
    inventories: list[Any],
    tasks: list[dict[str, Any]],
    guarded_units: set[int],
) -> tuple[list[list[Any]], dict[int, dict[str, Any]]]:
    actions: list[list[Any]] = [["PASS"] for _ in positions]
    assigned: dict[int, dict[str, Any]] = {}
    if not positions or not tasks:
        return actions, assigned
    density: Counter[tuple[int, int]] = Counter(task["pos"] for task in tasks)
    impossible = 10**8
    dummy = 0

    def cost(unit: int, task: dict[str, Any]) -> int:
        value = v5._assignment_cost(unit, task, positions, inventories, density)
        if unit in guarded_units and _signature(task) == _MISSIONS.get(unit):
            value -= CONTINUITY_BONUS * 100
        return value

    if len(positions) <= len(tasks):
        columns: list[dict[str, Any] | None] = [*tasks, *([None] * len(positions))]
        matrix = [
            [dummy if task is None else cost(unit, task) for task in columns]
            for unit in range(len(positions))
        ]
        for unit, column in enumerate(v5.v3._hungarian(matrix)):
            if 0 <= column < len(tasks) and matrix[unit][column] < min(dummy, impossible):
                assigned[unit] = tasks[column]
    else:
        columns: list[int | None] = [*range(len(positions)), *([None] * len(tasks))]
        matrix = [
            [dummy if unit is None else cost(unit, task) for unit in columns]
            for task in tasks
        ]
        for task_index, column in enumerate(v5.v3._hungarian(matrix)):
            if 0 <= column < len(positions) and matrix[task_index][column] < min(
                dummy, impossible
            ):
                unit = columns[column]
                if unit is not None:
                    assigned[unit] = tasks[task_index]
    for unit, task in assigned.items():
        actions[unit] = (
            list(task["action"])
            if positions[unit] == task["pos"]
            else base._movement(positions[unit], task["pos"], unit)
        )
    return actions, assigned


def _reset(step: int) -> None:
    global _LAST_STEP, _PREVIOUS_ACTIONS, _MISSIONS
    _LAST_STEP = step
    _PREVIOUS_ACTIONS = []
    _MISSIONS = {}


def _mission_assign(
    positions: list[tuple[int, int]],
    inventories: list[Any],
    tasks: list[dict[str, Any]],
    step: int = 0,
) -> list[list[Any]]:
    global _LAST_STEP, _PREVIOUS_ACTIONS, _MISSIONS
    day = step // 24
    if not ENABLE_ANTI_REVERSAL or day not in ACTIVE_DAYS:
        if step <= _LAST_STEP or step // 24 != _LAST_STEP // 24:
            _reset(step)
        return _SAFE_MISSION_ASSIGN(positions, inventories, tasks, step)
    if step != _LAST_STEP + 1 or day != _LAST_STEP // 24:
        _reset(step - 1)

    safe_actions, safe_assigned = _assigned_actions(positions, inventories, tasks, set())
    emergency = any(int(task.get("priority", 0)) >= EMERGENCY_PRIORITY for task in tasks)
    guarded: set[int] = set()
    if not emergency:
        for unit, (previous, current) in enumerate(
            zip(_PREVIOUS_ACTIONS, safe_actions, strict=False)
        ):
            previous_op = str(previous[0]) if previous else "PASS"
            current_op = str(current[0]) if current else "PASS"
            mission = _MISSIONS.get(unit)
            mission_action = (
                str(mission[1][0])
                if mission is not None and len(mission) > 1 and mission[1]
                else ""
            )
            allowed = (
                CONTINUITY_TASK_ACTIONS is None
                or mission_action in CONTINUITY_TASK_ACTIONS
            )
            if (
                current_op == OPPOSITE.get(previous_op)
                and mission is not None
                and allowed
            ):
                guarded.add(unit)
    actions, assigned = (
        _assigned_actions(positions, inventories, tasks, guarded)
        if guarded
        else (safe_actions, safe_assigned)
    )
    _LAST_STEP = step
    _PREVIOUS_ACTIONS = [list(action) for action in actions]
    _MISSIONS = {
        unit: _signature(task)
        for unit, task in assigned.items()
        if actions[unit] and str(actions[unit][0]) in MOVES
    }
    return actions


v9._mission_assign = _mission_assign


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v14.policy_diagnostics(obs))
    step = base._as_int(
        base._get(
            obs,
            "step",
            base._as_int(base._get(obs, "day", 0)) * 24
            + base._as_int(base._get(obs, "hour", 0)),
        )
    )
    result["v47_anti_reversal"] = {
        "enabled": ENABLE_ANTI_REVERSAL,
        "active": ENABLE_ANTI_REVERSAL and step // 24 in ACTIVE_DAYS,
        "bonus": CONTINUITY_BONUS,
        "task_actions": (
            sorted(CONTINUITY_TASK_ACTIONS)
            if CONTINUITY_TASK_ACTIONS is not None
            else ["ALL"]
        ),
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v14.agent(obs)
