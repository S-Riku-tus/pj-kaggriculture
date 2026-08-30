"""Kaggriculture V16: repair the Day 6-10 routine-WATER priority gap.

V10's documented policy places routine WATER above routine FEED and below
emergency FEED, but its implementation applies that ordering only after Day
10. A broad repair displaced Strawberry expansion, so V16 applies the missing
Day 6-10 ordering only to the fixed-opening Melons whose delayed sale creates
the measured capital gap. All legality, inventory, market, and fallback rules
remain in their deterministic layers.
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
        Path.cwd() / "agents" / "v16",
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
    spec = importlib.util.spec_from_file_location("_kaggriculture_v16_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V14 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v14 = _load_v14_module()
v11 = v14.v11
base = v14.base
ENABLE_CAPITAL_WATER = False
CAPITAL_WATER_PRIORITY = 12_000
CAPITAL_WATER_CROPS = frozenset({"MELON"})
_SAFE_FIELD_TASKS = v11._field_tasks


def _raise_capital_water(tasks: list[dict[str, Any]], day: int, farm: Any) -> list[dict[str, Any]]:
    if not ENABLE_CAPITAL_WATER or not 6 <= day <= 10:
        return tasks
    result: list[dict[str, Any]] = []
    for task in tasks:
        updated = dict(task)
        action = updated.get("action")
        position = updated.get("pos")
        tile = None
        if isinstance(position, list | tuple) and len(position) >= 2:
            x, y = base._as_int(position[0], -1), base._as_int(position[1], -1)
            tiles = base._get(farm, "tiles", []) or []
            if 0 <= y < len(tiles) and 0 <= x < len(tiles[y]):
                tile = tiles[y][x]
        if (
            isinstance(action, list | tuple)
            and action
            and action[0] == "WATER"
            and base._get(tile, "crop") in CAPITAL_WATER_CROPS
        ):
            updated["priority"] = max(CAPITAL_WATER_PRIORITY, int(updated.get("priority", 0)))
        result.append(updated)
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
    day = base._as_int(base._get(obs, "day", 0))
    return _raise_capital_water(tasks, day, farm), reserved


# V14 resolves this module attribute on every call. Installing a stable wrapper
# keeps the implementation small without introducing cross-turn learned state.
v11._field_tasks = _field_tasks


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v14.policy_diagnostics(obs))
    day = base._as_int(base._get(obs, "day", 0))
    result["v16_capital_water"] = {
        "active": bool(ENABLE_CAPITAL_WATER and 6 <= day <= 10),
        "priority": CAPITAL_WATER_PRIORITY,
        "crops": sorted(CAPITAL_WATER_CROPS),
        "window": [6, 10],
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v14.agent(obs)
