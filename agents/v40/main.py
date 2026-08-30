"""V40: finish feasible late Day-6/8 Cow deliveries before refresh.

V11 buys many Cows late on Days 6 and 8 from same-turn Milk/Wool sales.  The
safe executor then leaves part of that stock in the shed across the daily
refresh.  This wrapper raises only Cow PICKUP/PLACE tasks whose shortest route
can still complete before the boundary.  Emergency FEED and WATER remain
higher priority, and every legality/resource constraint remains in V14.
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
        Path.cwd() / "agents" / "v40",
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
    spec = importlib.util.spec_from_file_location("_kaggriculture_v40_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V14 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v14 = _load_v14_module()
v10 = v14.v10
base = v14.base

ENABLE_LATE_COW_COMPLETION = False
COMPLETION_DAYS = frozenset({6, 8})
COMPLETION_START_HOUR = 18
PICKUP_PRIORITY = 14800
PLACE_PRIORITY = 14900
_SAFE_FIELD_TASKS = v10._field_tasks


def _empty_pastures(farm: Any) -> list[tuple[int, int]]:
    return [
        (x, y)
        for x, y, tile in base._iter_tiles(farm)
        if base._tile_kind(tile) == "PASTURE" and base._get(tile, "animal") is None
    ]


def _can_finish_pickup(
    task: dict[str, Any],
    positions: list[tuple[int, int]],
    pastures: list[tuple[int, int]],
    remaining: int,
) -> bool:
    unit = task.get("unit")
    pickup = task.get("pos")
    if (
        not isinstance(unit, int)
        or not 0 <= unit < len(positions)
        or not isinstance(pickup, tuple)
        or len(pickup) != 2
        or not pastures
    ):
        return False
    shortest = min(
        base._manhattan(positions[unit], pickup)
        + 1
        + base._manhattan(pickup, pasture)
        + 1
        for pasture in pastures
    )
    return shortest <= remaining


def _can_finish_place(
    task: dict[str, Any], positions: list[tuple[int, int]], remaining: int
) -> bool:
    unit = task.get("unit")
    target = task.get("pos")
    return bool(
        isinstance(unit, int)
        and 0 <= unit < len(positions)
        and isinstance(target, tuple)
        and len(target) == 2
        and base._manhattan(positions[unit], target) + 1 <= remaining
    )


def _prioritize_finishable_cows(
    obs: Any,
    farm: Any,
    positions: list[tuple[int, int]],
    tasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    day = base._as_int(base._get(obs, "day", 0))
    hour = base._as_int(base._get(obs, "hour", 0))
    if (
        not ENABLE_LATE_COW_COMPLETION
        or day not in COMPLETION_DAYS
        or hour < COMPLETION_START_HOUR
    ):
        return tasks
    remaining = 24 - hour
    pastures = _empty_pastures(farm)
    result = []
    for original in tasks:
        task = dict(original)
        task["action"] = list(original.get("action") or ["PASS"])
        action = str(task["action"][0])
        label = str(task.get("label", ""))
        if (
            action == "PICKUP"
            and label == "pickup-COW"
            and _can_finish_pickup(task, positions, pastures, remaining)
        ):
            task["priority"] = max(PICKUP_PRIORITY, int(task.get("priority", 0)))
        elif (
            action == "PLACE"
            and label == "place-COW"
            and _can_finish_place(task, positions, remaining)
        ):
            task["priority"] = max(PLACE_PRIORITY, int(task.get("priority", 0)))
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
    return _prioritize_finishable_cows(obs, farm, positions, tasks), reserved


# V14 -> V11 resolves this attribute dynamically on every decision.
v10._field_tasks = _field_tasks


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v14.policy_diagnostics(obs))
    day = base._as_int(base._get(obs, "day", 0))
    hour = base._as_int(base._get(obs, "hour", 0))
    result["v40_late_cow_completion"] = {
        "active": bool(
            ENABLE_LATE_COW_COMPLETION
            and day in COMPLETION_DAYS
            and hour >= COMPLETION_START_HOUR
        ),
        "days": sorted(COMPLETION_DAYS),
        "start_hour": COMPLETION_START_HOUR,
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v14.agent(obs)
