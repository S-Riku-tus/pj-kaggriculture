"""V125 execution-only arm.

This arm deliberately leaves V124's economic policy unchanged.  It repairs two
atomic execution hazards which are visible in the real engine:

* PLANT requests for a crop are capped by seeds available at the beginning of
  the turn.  The engine otherwise cancels every request for that crop.
* DROP at the shed is replaced by a quantity-bounded PLACE when the whole
  carried inventory would overflow the shed.  Items which do not fit stay with
  the worker instead of being destroyed.

Market orders are not used to increase either allowance because they execute
after unit actions.  This file is a separate evaluation arm; it does not alter
the frozen V124 source or archive.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SHED_CAPACITY = 100
ANIMAL_VALUE = {"GOOSE": 300, "COW": 400, "SHEEP": 500}


def _module_dir() -> Path:
    if "__file__" in globals():
        return Path(__file__).resolve().parent
    candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd() / "agents" / "v125_exec",
        Path.cwd(),
    )
    return next(
        (
            candidate.resolve()
            for candidate in candidates
            if (candidate / "v124_base.py").is_file()
            or (candidate.parent / "v124" / "main.py").is_file()
        ),
        Path.cwd(),
    )


def _load_v124() -> Any:
    module_dir = _module_dir()
    packaged = module_dir / "v124_base.py"
    repository = module_dir.parent / "v124" / "main.py"
    source = packaged if packaged.is_file() else repository
    spec = importlib.util.spec_from_file_location("_kaggriculture_v125_exec_v124", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import frozen V124 policy: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load_v124()


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _unit_actions(action: dict[str, Any]) -> list[list[Any]]:
    farmer = action.get("farmer")
    units = [list(farmer) if isinstance(farmer, list | tuple) and farmer else ["PASS"]]
    units.extend(
        list(candidate) if isinstance(candidate, list | tuple) and candidate else ["PASS"]
        for candidate in action.get("hands") or []
    )
    return units


def _unit_positions(farm: Mapping[str, Any]) -> list[tuple[int, int]]:
    positions = [tuple(farm.get("farmer") or (0, 0))]
    positions.extend(tuple(pos) for pos in farm.get("hands") or [])
    return [(int(pos[0]), int(pos[1])) for pos in positions]


def _is_shed_access(position: tuple[int, int], board_size: int) -> bool:
    half = board_size // 2
    return position in {
        (half - 1, half - 1),
        (half, half - 1),
        (half - 1, half),
        (half, half),
    }


def _item_value(observation: Mapping[str, Any], item: str) -> int:
    prices = _mapping(_mapping(observation.get("market")).get("prices"))
    return max(_integer(prices.get(item)), ANIMAL_VALUE.get(item, 0))


def repair_action(
    observation: Mapping[str, Any], action: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a legal, execution-safer copy plus auditable intervention counts."""
    farms = list(observation.get("farms") or [])
    seat = 1 if _integer(observation.get("player")) == 1 else 0
    farm = _mapping(farms[seat]) if seat < len(farms) else {}
    private = _mapping(observation.get("private"))
    inventories = list(private.get("inventories") or [])
    positions = _unit_positions(farm)
    units = _unit_actions(dict(action))
    while len(units) < len(positions):
        units.append(["PASS"])
    units = units[: len(positions)]

    diagnostics = {
        "plant_requests_removed": 0,
        "drop_actions_bounded": 0,
        "drop_units_preserved": 0,
    }

    seeds = _mapping(private.get("seeds"))
    remaining = {str(crop): max(0, _integer(quantity)) for crop, quantity in seeds.items()}
    for index, unit_action in enumerate(units):
        if unit_action and unit_action[0] == "PLANT" and len(unit_action) >= 2:
            crop = str(unit_action[1])
            if remaining.get(crop, 0) <= 0:
                units[index] = ["PASS"]
                diagnostics["plant_requests_removed"] += 1
            else:
                remaining[crop] -= 1

    shed = _mapping(private.get("shed"))
    room = max(0, SHED_CAPACITY - sum(max(0, _integer(value)) for value in shed.values()))
    board_size = len(farm.get("tiles") or []) or 10
    for index, unit_action in enumerate(units):
        if not unit_action or unit_action[0] != "DROP":
            continue
        inventory = _mapping(inventories[index] if index < len(inventories) else {})
        carried = sum(max(0, _integer(value)) for value in inventory.values())
        if index >= len(positions) or not _is_shed_access(positions[index], board_size):
            continue
        if carried <= room:
            room -= carried
            continue
        choices = [
            (item, max(0, _integer(quantity)))
            for item, quantity in inventory.items()
            if _integer(quantity) > 0
        ]
        choices.sort(key=lambda pair: (-_item_value(observation, str(pair[0])), str(pair[0])))
        if room > 0 and choices:
            item, quantity = choices[0]
            placed = min(room, quantity)
            units[index] = ["PLACE", str(item), placed]
            room -= placed
            diagnostics["drop_units_preserved"] += carried - placed
        else:
            units[index] = ["PASS"]
            diagnostics["drop_units_preserved"] += carried
        diagnostics["drop_actions_bounded"] += 1

    market = [list(order) for order in action.get("market") or [] if isinstance(order, list | tuple)]
    repaired = {
        "farmer": units[0] if units else ["PASS"],
        "hands": units[1:],
        "market": market[:10],
    }
    return repaired, diagnostics


def agent(observation: Mapping[str, Any]) -> dict[str, Any]:
    action = base.agent(observation)
    repaired, _diagnostics = repair_action(observation, action)
    return repaired
