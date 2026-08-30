"""V43: preserve two central NE cells for imminent compact pastures.

V11 fills the newly unlocked NE core with crops while Rank 1 and Rank 2 keep
several central cells empty and convert them to animals by Day 9.  This wrapper
relocates only PLANT tasks targeting two shared top-team animal-core cells to
the nearest legal outer cell.  Crop quantity, market orders, and all V14 safety
layers remain unchanged.
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
        Path.cwd() / "agents" / "v43",
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
    spec = importlib.util.spec_from_file_location("_kaggriculture_v43_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V14 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v14 = _load_v14_module()
v10 = v14.v10
base = v14.base

ENABLE_NE_CORE_RESERVATION = False
RESERVATION_DAYS = range(4, 9)
_SAFE_FIELD_TASKS = v10._field_tasks


def _protected_ne_positions(board_size: int) -> set[tuple[int, int]]:
    half = board_size // 2
    # The first two NE cells are already selected by V14's current pasture
    # target. These next two form the compact 2x2 service block shared most
    # strongly by Rank 1 and Rank 2.
    return {(half + 1, half - 1), (half + 1, half - 2)}


def _relocate_core_plants(
    obs: Any,
    farm: Any,
    tasks: list[dict[str, Any]],
    reserved: set[tuple[int, int]],
) -> list[dict[str, Any]]:
    day = base._as_int(base._get(obs, "day", 0))
    unlocked = set(base._get(farm, "unlocked_quadrants", []) or [])
    tiles = base._get(farm, "tiles", []) or []
    board_size = len(tiles) or 10
    protected = _protected_ne_positions(board_size)
    if (
        not ENABLE_NE_CORE_RESERVATION
        or day not in RESERVATION_DAYS
        or "NE" not in unlocked
        or not any(
            task.get("action", [None])[0] == "PLANT" and task.get("pos") in protected
            for task in tasks
        )
    ):
        return tasks

    claimed = {
        task.get("pos")
        for task in tasks
        if task.get("action", [None])[0] == "PLANT"
        and isinstance(task.get("pos"), tuple)
    }
    replacements = [
        (x, y)
        for x, y, tile in base._iter_tiles(farm)
        if tile is None
        and (x, y) not in reserved
        and (x, y) not in protected
        and (x, y) not in claimed
    ]
    shed_tiles = base._shed_tiles(board_size)
    replacements.sort(
        key=lambda position: (
            min(base._manhattan(position, shed) for shed in shed_tiles),
            position[1],
            position[0],
        )
    )
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
    return _relocate_core_plants(obs, farm, tasks, reserved), reserved


v10._field_tasks = _field_tasks


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v14.policy_diagnostics(obs))
    safe = base._safe_observation(obs)
    if safe is None:
        return result
    farm = safe[0]
    day = base._as_int(base._get(obs, "day", 0))
    result["v43_ne_core_reservation"] = {
        "active": bool(
            ENABLE_NE_CORE_RESERVATION
            and day in RESERVATION_DAYS
            and "NE" in set(base._get(farm, "unlocked_quadrants", []) or [])
        ),
        "positions": sorted(_protected_ne_positions(len(base._get(farm, "tiles", []) or []))),
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v14.agent(obs)
