"""V53: persistent, uniquely owned Wheat-to-FEED missions on V14.

Top-1 and Top-3 use very different Wheat batch sizes, but both almost always
turn a successful pickup into FEED without PASS.  V53 therefore leaves market,
portfolio, pickup count, and pickup quantity untouched.  It assigns each
eligible Wheat carrier a unique currently-unfed animal and keeps that target
until FEED or invalidation.  Disabled by default pending closed-loop tests.
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
        Path.cwd() / "agents" / "v53",
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
    spec = importlib.util.spec_from_file_location("_kaggriculture_v53_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V14 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v14 = _load_v14_module()
v9 = v14.v9
base = v14.base

ENABLE_FEED_MISSIONS = False
ACTIVE_DAYS = range(6, 13)
_SAFE_MISSION_ASSIGN = v9._mission_assign
_LAST_STEP = -1
_LAST_UNIT_COUNT = -1
_FEED_MISSIONS: dict[int, tuple[int, int]] = {}


def _eligible_carrier(inventory: Any) -> bool:
    if base._inventory_count(inventory, "WHEAT") <= 0:
        return False
    if any(base._inventory_count(inventory, animal) for animal in base.ANIMAL_DATA):
        return False
    # A worker holding sale goods must remain available to the safe DROP logic.
    operational = {"WHEAT", "FERTILIZER"}
    return all(
        item in operational or base._inventory_count(inventory, item) <= 0
        for item in base.PRODUCTS
    )


def _assign_new_targets(
    positions: list[tuple[int, int]],
    inventories: list[Any],
    feed_tasks: dict[tuple[int, int], int],
) -> None:
    claimed = set(_FEED_MISSIONS.values())
    free_units = {
        unit
        for unit, inventory in enumerate(inventories)
        if unit < len(positions) and unit not in _FEED_MISSIONS and _eligible_carrier(inventory)
    }
    free_targets = set(feed_tasks) - claimed
    while free_units and free_targets:
        unit, target = min(
            (
                (unit, target)
                for unit in free_units
                for target in free_targets
            ),
            key=lambda pair: (
                base._manhattan(positions[pair[0]], pair[1]),
                -feed_tasks[pair[1]],
                pair[1][1],
                pair[1][0],
                pair[0],
            ),
        )
        _FEED_MISSIONS[unit] = target
        free_units.remove(unit)
        free_targets.remove(target)


def _feed_mission_assign(
    positions: list[tuple[int, int]],
    inventories: list[Any],
    tasks: list[dict[str, Any]],
    step: int = 0,
) -> list[list[Any]]:
    global _LAST_STEP, _LAST_UNIT_COUNT
    day = step // 24
    if not ENABLE_FEED_MISSIONS or day not in ACTIVE_DAYS:
        _FEED_MISSIONS.clear()
        _LAST_STEP = step
        _LAST_UNIT_COUNT = len(positions)
        return _SAFE_MISSION_ASSIGN(positions, inventories, tasks, step)
    if (
        step != _LAST_STEP + 1
        or step % 24 == 0
        or len(positions) != _LAST_UNIT_COUNT
    ):
        _FEED_MISSIONS.clear()

    feed_tasks = {
        tuple(task["pos"]): index
        for index, task in enumerate(tasks)
        if (task.get("action") or ["PASS"])[0] == "FEED"
        and isinstance(task.get("pos"), tuple)
    }
    for unit, target in list(_FEED_MISSIONS.items()):
        if (
            unit >= len(inventories)
            or not _eligible_carrier(inventories[unit])
            or target not in feed_tasks
        ):
            del _FEED_MISSIONS[unit]
    _assign_new_targets(positions, inventories, feed_tasks)

    actions: list[list[Any]] = [["PASS"] for _ in positions]
    pinned_units = set(_FEED_MISSIONS)
    pinned_tasks = {feed_tasks[target] for target in _FEED_MISSIONS.values()}
    for unit, target in _FEED_MISSIONS.items():
        actions[unit] = (
            ["FEED"]
            if positions[unit] == target
            else base._movement(positions[unit], target, unit)
        )

    remaining_units = [unit for unit in range(len(positions)) if unit not in pinned_units]
    if remaining_units:
        remap = {original: compact for compact, original in enumerate(remaining_units)}
        remaining_tasks: list[dict[str, Any]] = []
        for task_index, original in enumerate(tasks):
            if task_index in pinned_tasks:
                continue
            task = dict(original)
            task["action"] = list(original["action"])
            unit = task.get("unit")
            if isinstance(unit, int):
                if unit not in remap:
                    continue
                task["unit"] = remap[unit]
            remaining_tasks.append(task)
        compact_actions = _SAFE_MISSION_ASSIGN(
            [positions[unit] for unit in remaining_units],
            [inventories[unit] for unit in remaining_units],
            remaining_tasks,
            step,
        )
        for original, action in zip(remaining_units, compact_actions, strict=True):
            actions[original] = action

    _LAST_STEP = step
    _LAST_UNIT_COUNT = len(positions)
    return actions


v9._mission_assign = _feed_mission_assign


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v14.policy_diagnostics(obs))
    day = base._as_int(base._get(obs, "day", 0))
    result["v53_feed_missions"] = {
        "enabled": ENABLE_FEED_MISSIONS,
        "active": ENABLE_FEED_MISSIONS and day in ACTIVE_DAYS,
        "owned_targets": len(_FEED_MISSIONS),
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v14.agent(obs)
