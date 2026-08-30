"""Kaggriculture V21: bounded late-day preventive watering on V14.

The rule uses only worker turns that V14 leaves as PASS after normal task
assignment and future-work prepositioning.  Empty idle units may move toward
an observable, currently non-urgent plant that can still be reached and
watered before the day ends.  Mandatory work, carried inventory, and feed
emergencies remain owned by V14's deterministic executor.
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
        Path.cwd() / "agents" / "v21",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (candidate / "v14_base.py").is_file()
            or ((candidate / "main.py").is_file() and (candidate.parent / "v14" / "main.py").is_file())
        ),
        Path.cwd(),
    )


def _load_v14_module():
    packaged = MODULE_DIR / "v14_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v14" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v21_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V14 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v14 = _load_v14_module()
v10 = v14.v10
v4 = v14.v4
base = v14.base

ENABLE_PREVENTIVE_WATER = False
PREVENTIVE_DAYS = frozenset({11, 12})
PREVENTIVE_START_HOUR = 14
MAX_PREVENTIVE_ROUTE = 3
_SAFE_PREPOSITION = v10._preposition_idle_workers


def _feed_emergency(farm: Any, hour: int) -> bool:
    return any(
        base._get(tile, "animal") in base.ANIMAL_DATA
        and not bool(base._get(tile, "fed_today", False))
        and (base._as_int(base._get(tile, "consecutive_unfed", 0)) >= 1 or hour >= 18)
        for _x, _y, tile in base._iter_tiles(farm)
    )


def _preventive_positions(farm: Any, day: int) -> list[tuple[int, int]]:
    positions = []
    for x, y, tile in base._iter_tiles(farm):
        if base._tile_kind(tile) != "PLANT":
            continue
        if bool(base._get(tile, "watered_today", False)):
            continue
        if base._as_int(base._get(tile, "consecutive_unwatered", 0)) != 0:
            continue
        if v4._ongoing_finished(tile, day) or v4._water_is_useful(tile, day):
            continue
        positions.append((x, y))
    return positions


def _route_idle_preventive_water(
    obs: Any,
    farm: Any,
    positions: list[tuple[int, int]],
    inventories: list[Any],
    actions: list[list[Any]],
) -> list[list[Any]]:
    """Spend only residual same-day capacity on tomorrow's water deadline."""
    day = base._as_int(base._get(obs, "day", 0))
    hour = base._as_int(base._get(obs, "hour", 0))
    if (
        not ENABLE_PREVENTIVE_WATER
        or day not in PREVENTIVE_DAYS
        or hour < PREVENTIVE_START_HOUR
        or _feed_emergency(farm, hour)
    ):
        return actions

    candidates = _preventive_positions(farm, day)
    if not candidates:
        return actions

    turns_remaining = 24 - hour
    result = [list(action) for action in actions]
    claimed: set[tuple[int, int]] = set()
    for unit, action in enumerate(result):
        if action != ["PASS"] or unit >= len(positions) or unit >= len(inventories):
            continue
        if base._inventory_total(inventories[unit]) > 0:
            continue
        current = positions[unit]
        available = [
            target
            for target in candidates
            if target not in claimed
            and 0 < base._manhattan(current, target) <= MAX_PREVENTIVE_ROUTE
            and base._manhattan(current, target) + 1 <= turns_remaining
        ]
        if not available:
            continue
        target = min(
            available,
            key=lambda value: (base._manhattan(current, value), value[1], value[0]),
        )
        claimed.add(target)
        result[unit] = base._movement(current, target, unit)
    return result


def _preposition_idle_workers(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
    positions: list[tuple[int, int]],
    inventories: list[Any],
    tasks: list[dict[str, Any]],
    actions: list[list[Any]],
    expert_prediction: Any = None,
) -> list[list[Any]]:
    safe_actions = _SAFE_PREPOSITION(
        obs,
        farm,
        opponent_farm,
        private,
        positions,
        inventories,
        tasks,
        actions,
        expert_prediction,
    )
    return _route_idle_preventive_water(obs, farm, positions, inventories, safe_actions)


# V14 resolves this attribute dynamically on every decision.
v10._preposition_idle_workers = _preposition_idle_workers


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v14.policy_diagnostics(obs))
    day = base._as_int(base._get(obs, "day", 0))
    hour = base._as_int(base._get(obs, "hour", 0))
    result["v21_preventive_water"] = {
        "active": bool(
            ENABLE_PREVENTIVE_WATER
            and day in PREVENTIVE_DAYS
            and hour >= PREVENTIVE_START_HOUR
        ),
        "days": sorted(PREVENTIVE_DAYS),
        "start_hour": PREVENTIVE_START_HOUR,
        "max_route": MAX_PREVENTIVE_ROUTE,
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v14.agent(obs)
