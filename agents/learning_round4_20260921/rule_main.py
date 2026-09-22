"""Explicit-rule comparison policy using the identical Round4 executor."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def _module_dir() -> Path:
    if "__file__" in globals():
        return Path(__file__).resolve().parent
    candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(value) for value in reversed(sys.path) if value),
        Path.cwd(),
    )
    return next((value.resolve() for value in candidates if (value / "executor.py").is_file()), Path.cwd())


MODULE_DIR = _module_dir()
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

try:
    from .contracts import crop_harvestability, tile_at
    from .executor import ExecutionCoordinator
except ImportError:
    from contracts import crop_harvestability, tile_at  # type: ignore
    from executor import ExecutionCoordinator  # type: ignore


coordinator = ExecutionCoordinator("explicit-rule")
_stats: dict[str, int] = {}


def reset_runtime_state() -> None:
    global _stats
    coordinator.reset()
    _stats = {"model_loads": 0, "inference_calls": 0, "rule_decisions": 0}


def _proposal(observation: Mapping[str, Any]) -> dict[str, Any]:
    seat = int(observation.get("player", 0))
    farm = observation["farms"][seat]
    private = observation.get("private") or {}
    inventories = list(private.get("inventories") or [])
    positions = [farm.get("farmer") or [0, 0], *(farm.get("hands") or [])]
    units: list[list[Any]] = []
    for actor, position in enumerate(positions):
        tile = tile_at(observation, position)
        inventory = inventories[actor] if actor < len(inventories) else {}
        action: list[Any] = ["PASS"]
        if isinstance(tile, Mapping) and tile.get("animal"):
            if not bool(tile.get("fed_today")) and int(inventory.get("WHEAT", 0)) > 0:
                action = ["FEED"]
            elif bool(tile.get("fed_today")) and not bool(tile.get("cared_today")):
                action = ["CARE"]
        elif crop_harvestability(observation, actor).applicable:
            action = ["HARVEST"]
        elif isinstance(tile, Mapping) and tile.get("kind") == "PLANT" and not bool(tile.get("watered_today")):
            action = ["WATER"]
        elif tile is None and int((private.get("seeds") or {}).get("CARROT", 0)) > 0:
            action = ["PLANT", "CARROT"]
        units.append(action)
    market: list[list[Any]] = []
    shed = private.get("shed") or {}
    if int(shed.get("CARROT", 0)) > 0:
        market.append(["SELL", "CARROT", int(shed["CARROT"])])
    if int((private.get("seeds") or {}).get("CARROT", 0)) == 0 and float(farm.get("money", 0)) >= 20:
        market.append(["BUY_SEED", "CARROT", 1])
    return {"farmer": units[0], "hands": units[1:], "market": market}


def _rule_scores(observation: Mapping[str, Any]) -> dict[str, float]:
    seat = int(observation.get("player", 0))
    farm = observation["farms"][seat]
    animal = any(
        isinstance(tile, Mapping) and tile.get("animal") and not bool(tile.get("fed_today"))
        for row in farm.get("tiles") or []
        for tile in row
    )
    harvest = any(
        crop_harvestability(observation, actor).applicable for actor in range(1 + len(farm.get("hands") or []))
    )
    return {
        "ANIMAL_SERVICE_WITH_CONTINUATION": float(animal),
        "HARVEST_AND_LAND_CONVERSION": float(harvest),
        "SELL_AND_REINVEST": float(bool((observation.get("private") or {}).get("shed"))),
    }


def agent(observation: Mapping[str, Any], configuration: Any = None) -> dict[str, Any]:
    del configuration
    if int(observation.get("step", 24 * int(observation.get("day", 0)) + int(observation.get("hour", 0)))) == 0:
        reset_runtime_state()
    _stats["rule_decisions"] += 1
    return coordinator.repair(observation, _proposal(observation), _rule_scores(observation))


def policy_diagnostics(_observation: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"arm": "round4_rule", **_stats, "executor": coordinator.diagnostics()}


def policy_trace() -> list[dict[str, Any]]:
    return coordinator.policy_trace()


reset_runtime_state()
