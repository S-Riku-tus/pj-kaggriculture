"""V51: capacity-matched Wheat pickup sizing on V14's safe policy.

V50 found that V11 moves roughly twice the Wheat needed for feeding while the
Rank-1 teacher moves close to one unit per FEED.  Earlier V12/V15 caps failed:
one removed carriers and missed feed, while the other forced extra refill
trips.  V51 changes a pickup to one unit only when a one-carrier-per-animal
matching proves that every currently unfed animal remains reachable today.
All other states retain V14 byte-for-byte behavior.  Disabled by default.
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
        Path.cwd() / "agents" / "v51",
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
    spec = importlib.util.spec_from_file_location("_kaggriculture_v51_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V14 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v14 = _load_v14_module()
v11 = v14.v11
base = v14.base

ENABLE_CAPACITY_MATCHED_WHEAT = False
ACTIVE_DAYS = range(6, 13)
_SAFE_FIELD_TASKS = v11._field_tasks


def _unfed_positions(farm: Any) -> list[tuple[int, int]]:
    return [
        (x, y)
        for x, y, tile in base._iter_tiles(farm)
        if base._get(tile, "animal") in base.ANIMAL_DATA
        and not bool(base._get(tile, "fed_today", False))
    ]


def _maximum_reachable_matching(
    carrier_routes: dict[int, dict[tuple[int, int], int]],
    animals: list[tuple[int, int]],
    remaining_turns: int,
) -> int:
    """Return maximum one-carrier/one-animal matching within today's budget."""

    animal_to_carrier: dict[tuple[int, int], int] = {}

    def augment(carrier: int, seen: set[tuple[int, int]]) -> bool:
        routes = carrier_routes[carrier]
        for animal in sorted(animals, key=lambda pos: (routes.get(pos, 10**9), pos[1], pos[0])):
            if animal in seen or routes.get(animal, 10**9) > remaining_turns:
                continue
            seen.add(animal)
            previous = animal_to_carrier.get(animal)
            if previous is None or augment(previous, seen):
                animal_to_carrier[animal] = carrier
                return True
        return False

    for carrier in sorted(carrier_routes):
        augment(carrier, set())
    return len(animal_to_carrier)


def _capacity_matched_pickups(
    tasks: list[dict[str, Any]],
    obs: Any,
    farm: Any,
    positions: list[tuple[int, int]],
    inventories: list[Any],
) -> list[dict[str, Any]]:
    day = base._as_int(base._get(obs, "day", 0))
    if not ENABLE_CAPACITY_MATCHED_WHEAT or day not in ACTIVE_DAYS:
        return tasks
    pickup_tasks = [task for task in tasks if task.get("label") == "pickup-wheat"]
    if not pickup_tasks or all(base._as_int(task["action"][2], 1) <= 1 for task in pickup_tasks):
        return tasks
    animals = _unfed_positions(farm)
    if not animals:
        return tasks

    hour = base._as_int(base._get(obs, "hour", 0))
    remaining_turns = 24 - hour
    pickup_by_unit = {
        base._as_int(task.get("unit"), -1): task
        for task in pickup_tasks
        if task.get("unit") is not None
    }
    carrier_routes: dict[int, dict[tuple[int, int], int]] = {}
    for unit, (position, inventory) in enumerate(zip(positions, inventories, strict=True)):
        if any(base._inventory_count(inventory, animal) for animal in base.ANIMAL_DATA):
            continue
        if base._inventory_count(inventory, "WHEAT") > 0:
            carrier_routes[unit] = {
                animal: base._manhattan(position, animal) + 1 for animal in animals
            }
            continue
        pickup = pickup_by_unit.get(unit)
        if pickup is None:
            continue
        shed = tuple(pickup["pos"])
        carrier_routes[unit] = {
            animal: (
                base._manhattan(position, shed)
                + 1  # PICKUP
                + base._manhattan(shed, animal)
                + 1  # FEED
            )
            for animal in animals
        }

    if _maximum_reachable_matching(carrier_routes, animals, remaining_turns) < len(animals):
        return tasks

    result = []
    for original in tasks:
        task = dict(original)
        task["action"] = list(original["action"])
        if task.get("label") == "pickup-wheat" and len(task["action"]) >= 3:
            task["action"][2] = 1
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
    return _capacity_matched_pickups(tasks, obs, farm, positions, inventories), reserved


v11._field_tasks = _field_tasks


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v14.policy_diagnostics(obs))
    day = base._as_int(base._get(obs, "day", 0))
    result["v51_capacity_matched_wheat"] = {
        "enabled": ENABLE_CAPACITY_MATCHED_WHEAT,
        "active": ENABLE_CAPACITY_MATCHED_WHEAT and day in ACTIVE_DAYS,
        "fallback": "v14-safe-load-unless-complete-reachable-matching",
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v14.agent(obs)
