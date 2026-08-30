"""V54: suppress only redundant new Wheat carriers on V14.

V52 showed that Top-1 and Top-3 differ in batch size but share near-zero
successful pickups that never FEED.  V54 preserves every existing carrier,
route, task priority, and pickup quantity.  It removes only new pickup tasks
already covered one-for-one by Wheat carriers that can reach distinct unfed
animals before day end.  Disabled by default pending closed-loop validation.
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
        Path.cwd() / "agents" / "v54",
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
    spec = importlib.util.spec_from_file_location("_kaggriculture_v54_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V14 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v14 = _load_v14_module()
v11 = v14.v11
base = v14.base

ENABLE_REDUNDANT_PICKUP_SUPPRESSION = False
ACTIVE_DAYS = range(6, 13)
REDUNDANT_CARRIER_BUFFER = 0
_SAFE_FIELD_TASKS = v11._field_tasks


def _eligible_carrier(inventory: Any) -> bool:
    if base._inventory_count(inventory, "WHEAT") <= 0:
        return False
    if any(base._inventory_count(inventory, animal) for animal in base.ANIMAL_DATA):
        return False
    operational = {"WHEAT", "FERTILIZER"}
    return all(
        item in operational or base._inventory_count(inventory, item) <= 0
        for item in base.PRODUCTS
    )


def _matched_animals(
    positions: list[tuple[int, int]],
    carriers: list[int],
    animals: list[tuple[int, int]],
    remaining_turns: int,
) -> set[tuple[int, int]]:
    animal_to_carrier: dict[tuple[int, int], int] = {}

    def augment(carrier: int, seen: set[tuple[int, int]]) -> bool:
        for animal in sorted(
            animals,
            key=lambda pos: (
                base._manhattan(positions[carrier], pos),
                pos[1],
                pos[0],
            ),
        ):
            cost = base._manhattan(positions[carrier], animal) + 1
            if animal in seen or cost > remaining_turns:
                continue
            seen.add(animal)
            previous = animal_to_carrier.get(animal)
            if previous is None or augment(previous, seen):
                animal_to_carrier[animal] = carrier
                return True
        return False

    for carrier in sorted(carriers):
        augment(carrier, set())
    return set(animal_to_carrier)


def _suppress_redundant_pickups(
    tasks: list[dict[str, Any]],
    obs: Any,
    farm: Any,
    positions: list[tuple[int, int]],
    inventories: list[Any],
) -> list[dict[str, Any]]:
    day = base._as_int(base._get(obs, "day", 0))
    if not ENABLE_REDUNDANT_PICKUP_SUPPRESSION or day not in ACTIVE_DAYS:
        return tasks
    pickup_indices = [
        index for index, task in enumerate(tasks) if task.get("label") == "pickup-wheat"
    ]
    if not pickup_indices:
        return tasks
    animals = [
        (x, y)
        for x, y, tile in base._iter_tiles(farm)
        if base._get(tile, "animal") in base.ANIMAL_DATA
        and not bool(base._get(tile, "fed_today", False))
    ]
    if not animals:
        return tasks
    carriers = [
        unit
        for unit, inventory in enumerate(inventories)
        if unit < len(positions) and _eligible_carrier(inventory)
    ]
    remaining_turns = 24 - base._as_int(base._get(obs, "hour", 0))
    covered = _matched_animals(positions, carriers, animals, remaining_turns)
    needed_new = max(
        0,
        len(animals) - len(covered) + REDUNDANT_CARRIER_BUFFER,
    )
    if needed_new >= len(pickup_indices):
        return tasks

    residual = set(animals) - covered
    ranked_pickups = sorted(
        pickup_indices,
        key=lambda index: (
            min(
                (
                    base._manhattan(positions[base._as_int(tasks[index].get("unit"), 0)], tasks[index]["pos"])
                    + base._manhattan(tasks[index]["pos"], animal)
                    for animal in residual
                ),
                default=0,
            ),
            base._as_int(tasks[index].get("unit"), 0),
        ),
    )
    kept_pickups = set(ranked_pickups[:needed_new])
    return [
        task
        for index, task in enumerate(tasks)
        if index not in pickup_indices or index in kept_pickups
    ]


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
    return _suppress_redundant_pickups(tasks, obs, farm, positions, inventories), reserved


v11._field_tasks = _field_tasks


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v14.policy_diagnostics(obs))
    day = base._as_int(base._get(obs, "day", 0))
    result["v54_redundant_pickup_suppression"] = {
        "enabled": ENABLE_REDUNDANT_PICKUP_SUPPRESSION,
        "active": ENABLE_REDUNDANT_PICKUP_SUPPRESSION and day in ACTIVE_DAYS,
        "preserves_existing_routes_and_batch_size": True,
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v14.agent(obs)
