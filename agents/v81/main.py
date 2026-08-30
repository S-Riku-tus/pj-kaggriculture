"""Kaggriculture V81: bounded late crop-decay harvest protection.

Stored V11 and Top-3 replays show a reproducible Day 23--24 crop-output
backlog.  The safe executor normally waits for two units before harvesting an
ongoing crop; after the last production event, however, the engine may start
removing held units every two turns.  V81 exposes a HARVEST task for every
already-decaying plant with held output and raises that task above routine
work, while keeping emergency FEED above it.  All portfolio, market, routing,
inventory, legality, and OOD behavior remain V14.
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
        Path.cwd() / "agents" / "v81",
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
    spec = importlib.util.spec_from_file_location("_kaggriculture_v81_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V14 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v14 = _load_v14_module()
v11 = v14.v11
base = v14.base

ENABLE_DECAY_HARVEST = False
ACTIVE_DAYS = frozenset(range(23, 27))
DECAY_HARVEST_PRIORITY = 14_900
RAISE_EXISTING_DECAY_HARVEST = True
_SAFE_FIELD_TASKS = v11._field_tasks


def _decaying_positions(obs: Any, farm: Any) -> set[tuple[int, int]]:
    if not ENABLE_DECAY_HARVEST:
        return set()
    day = base._as_int(base._get(obs, "day", 0))
    if day not in ACTIVE_DAYS:
        return set()
    step = base._as_int(base._get(obs, "step", day * 24))
    return {
        (x, y)
        for x, y, tile in base._iter_tiles(farm)
        if base._tile_kind(tile) == "PLANT"
        and base._as_int(base._get(tile, "yield_units", 0)) > 0
        and base._as_int(base._get(tile, "max_lifespan_step", -1), -1) >= 0
        and step >= base._as_int(base._get(tile, "max_lifespan_step", -1), -1)
    }


def _protect_decaying_harvest(
    tasks: list[dict[str, Any]], obs: Any, farm: Any
) -> list[dict[str, Any]]:
    positions = _decaying_positions(obs, farm)
    if not positions:
        return tasks
    result: list[dict[str, Any]] = []
    exposed: set[tuple[int, int]] = set()
    for original in tasks:
        task = dict(original)
        task["action"] = list(original.get("action") or ["PASS"])
        position = task.get("pos")
        if (
            isinstance(position, tuple)
            and position in positions
            and task["action"][0] == "HARVEST"
        ):
            exposed.add(position)
            if RAISE_EXISTING_DECAY_HARVEST:
                task["priority"] = max(
                    DECAY_HARVEST_PRIORITY, int(task.get("priority", 0))
                )
                task["label"] = "decaying-crop-harvest"
        result.append(task)
    for position in sorted(positions - exposed, key=lambda value: (value[1], value[0])):
        result.append(
            base._task(
                position,
                ["HARVEST"],
                DECAY_HARVEST_PRIORITY,
                label="decaying-crop-harvest",
            )
        )
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
    opponent_farm: Any = None,
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
        opponent_farm,
    )
    return _protect_decaying_harvest(tasks, obs, farm), reserved


# V14 resolves the V11 executor dynamically at every decision.
v11._field_tasks = _field_tasks


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v14.policy_diagnostics(obs))
    safe = base._safe_observation(obs)
    day = base._as_int(base._get(obs, "day", 0))
    positions = _decaying_positions(obs, safe[0]) if safe is not None else set()
    result["v81_decay_harvest"] = {
        "active": bool(ENABLE_DECAY_HARVEST and day in ACTIVE_DAYS),
        "decaying_tiles": len(positions),
        "priority": DECAY_HARVEST_PRIORITY,
        "raise_existing": RAISE_EXISTING_DECAY_HARVEST,
        "days": sorted(ACTIVE_DAYS),
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v14.agent(obs)
