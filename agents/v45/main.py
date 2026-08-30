"""V45: stage central animal capacity before the Day-7 crop catch-up.

Rank 1 does not immediately relocate every crop omitted from the newly
unlocked NE core.  It runs about three fewer crops on Day 6, prepares animal
capacity, and catches the crop count up on Day 7.  This wrapper mirrors that
ordering on two conservative, cross-teacher central cells: omit their plant
tasks through Day 6, then relocate any remaining plant tasks to outer empty
land on Days 7--8.  The V14 deterministic executor and all safety layers stay
in charge.  The experiment is disabled by default.
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
        Path.cwd() / "agents" / "v45",
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
    spec = importlib.util.spec_from_file_location("_kaggriculture_v45_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V14 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v14 = _load_v14_module()
v10 = v14.v10
base = v14.base

ENABLE_STAGED_EXPANSION = False
DELAY_DAYS = range(4, 7)
CATCHUP_DAYS = range(7, 9)
_SAFE_FIELD_TASKS = v10._field_tasks


def _protected_ne_positions(board_size: int) -> set[tuple[int, int]]:
    half = board_size // 2
    return {(half + 1, half - 1), (half + 1, half - 2)}


def _outer_replacements(
    farm: Any,
    tasks: list[dict[str, Any]],
    reserved: set[tuple[int, int]],
    protected: set[tuple[int, int]],
) -> list[tuple[int, int]]:
    claimed = {
        task.get("pos")
        for task in tasks
        if task.get("action", [None])[0] == "PLANT"
        and isinstance(task.get("pos"), tuple)
    }
    result = [
        (x, y)
        for x, y, tile in base._iter_tiles(farm)
        if tile is None
        and (x, y) not in reserved
        and (x, y) not in protected
        and (x, y) not in claimed
    ]
    size = len(base._get(farm, "tiles", []) or []) or 10
    sheds = base._shed_tiles(size)
    result.sort(
        key=lambda position: (
            min(base._manhattan(position, shed) for shed in sheds),
            position[1],
            position[0],
        )
    )
    return result


def _stage_core_plants(
    obs: Any,
    farm: Any,
    tasks: list[dict[str, Any]],
    reserved: set[tuple[int, int]],
) -> list[dict[str, Any]]:
    day = base._as_int(base._get(obs, "day", 0))
    unlocked = set(base._get(farm, "unlocked_quadrants", []) or [])
    size = len(base._get(farm, "tiles", []) or []) or 10
    protected = _protected_ne_positions(size)
    if (
        not ENABLE_STAGED_EXPANSION
        or "NE" not in unlocked
        or day not in (*DELAY_DAYS, *CATCHUP_DAYS)
    ):
        return tasks

    if day in DELAY_DAYS:
        return [
            task
            for task in tasks
            if not (
                task.get("action", [None])[0] == "PLANT"
                and task.get("pos") in protected
            )
        ]

    replacements = _outer_replacements(farm, tasks, reserved, protected)
    result = []
    replacement_index = 0
    for original in tasks:
        task = dict(original)
        task["action"] = list(original.get("action") or ["PASS"])
        if task["action"][0] == "PLANT" and task.get("pos") in protected:
            if replacement_index >= len(replacements):
                continue
            task["pos"] = replacements[replacement_index]
            replacement_index += 1
        result.append(task)
    return result


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
) -> tuple[list[dict[str, Any]], set[tuple[int, int]]]:
    tasks, reserved = _SAFE_FIELD_TASKS(
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
    return _stage_core_plants(obs, farm, tasks, reserved), reserved


v10._field_tasks = _field_tasks


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v14.policy_diagnostics(obs))
    safe = base._safe_observation(obs)
    if safe is None:
        return result
    farm = safe[0]
    day = base._as_int(base._get(obs, "day", 0))
    result["v45_staged_expansion"] = {
        "enabled": ENABLE_STAGED_EXPANSION,
        "phase": "delay" if day in DELAY_DAYS else ("catchup" if day in CATCHUP_DAYS else "off"),
        "positions": sorted(
            _protected_ne_positions(len(base._get(farm, "tiles", []) or []))
        ),
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v14.agent(obs)

