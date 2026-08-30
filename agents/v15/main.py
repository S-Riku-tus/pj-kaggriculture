"""Kaggriculture V15: distributed low-surplus feed logistics on V14.

V12 showed that reducing both Wheat load and carrier count misses feed. V15
keeps every independently assigned carrier but reduces each pickup from the
V11 average of 2.38 toward the Rank-1 sample's 1.40. The deterministic rule
keeps at least one unit per carrier and 20% observable demand slack.
"""

from __future__ import annotations

import copy
import importlib.util
import math
import sys
from pathlib import Path
from typing import Any

if "__file__" in globals():
    MODULE_DIR = Path(__file__).resolve().parent
else:
    _runtime_candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd() / "agents" / "v15",
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
    spec = importlib.util.spec_from_file_location("_kaggriculture_v15_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V14 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v14 = _load_v14_module()
v11 = v14.v11
v10 = v14.v10
v9 = v14.v9
v8 = v14.v8
v4 = v14.v4
v3 = v14.v3
base = v14.base

CROPS = v14.CROPS
ANIMALS = v14.ANIMALS
ENABLE_DISTRIBUTED_WHEAT = False
FEED_SLACK = 1.20


def _pickup_amount(task: dict[str, Any]) -> int:
    action = task.get("action")
    if not isinstance(action, list | tuple) or len(action) < 3:
        return 1
    return max(1, base._as_int(action[2], 1))


def _distribute_wheat_pickups(
    tasks: list[dict[str, Any]],
    farm: Any,
    private: Any,
    inventories: list[Any],
) -> list[dict[str, Any]]:
    if not ENABLE_DISTRIBUTED_WHEAT:
        return tasks
    pickup_indices = [index for index, task in enumerate(tasks) if task.get("label") == "pickup-wheat"]
    if not pickup_indices:
        return tasks
    unfed = sum(
        base._get(tile, "animal") in base.ANIMAL_DATA and not bool(base._get(tile, "fed_today", False))
        for _x, _y, tile in base._iter_tiles(farm)
    )
    carried = sum(base._inventory_count(inventory, "WHEAT") for inventory in inventories)
    stock = base._inventory_count(base._get(private, "shed", {}) or {}, "WHEAT")
    original_total = sum(_pickup_amount(tasks[index]) for index in pickup_indices)
    carrier_count = len(pickup_indices)
    observable_need = max(0, unfed - carried)
    target_total = min(
        original_total,
        stock,
        max(carrier_count, math.ceil(FEED_SLACK * observable_need)),
    )
    # Base generation already guarantees stock >= carrier count. If a malformed
    # external task list violates that invariant, leave it untouched.
    if target_total < carrier_count:
        return tasks
    result = [dict(task) for task in tasks]
    extras = target_total - carrier_count
    for order, task_index in enumerate(pickup_indices):
        carriers_left = carrier_count - order
        extra = min(2, math.ceil(extras / max(1, carriers_left))) if extras else 0
        extras -= extra
        action = list(result[task_index].get("action") or ["PICKUP", "WHEAT", 1])
        if len(action) < 3:
            action = ["PICKUP", "WHEAT", 1]
        action[2] = 1 + extra
        result[task_index]["action"] = action
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
    tasks, reserved = v11._field_tasks(
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
    return _distribute_wheat_pickups(tasks, farm, private, inventories), reserved


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v14.policy_diagnostics(obs))
    result["v15_distributed_wheat"] = {
        "active": ENABLE_DISTRIBUTED_WHEAT,
        "feed_slack": FEED_SLACK,
        "carrier_policy": "preserve-all",
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    safe = base._safe_observation(obs)
    if safe is None:
        return {"farmer": ["PASS"], "hands": [], "market": []}
    farm, opponent_farm, private = safe
    opening = v3._safe_opening(obs, farm)
    if opening is not None:
        return copy.deepcopy(opening)
    expert_opening = v8._safe_expert_opening(obs, farm)
    if expert_opening is not None and expert_opening[1]:
        return expert_opening[0]

    summary = base._farm_summary(farm)
    animal_targets, crop_targets, target_hands, target_land, weights, pasture_target = v14._strategy_targets(
        obs, farm, opponent_farm, private
    )
    positions = [tuple(base._get(farm, "farmer", [0, 0]))]
    positions.extend(tuple(position) for position in (base._get(farm, "hands", []) or []))
    raw_inventories = list(base._get(private, "inventories", []) or [])
    inventories = [raw_inventories[index] if index < len(raw_inventories) else {} for index in range(len(positions))]
    tasks, reserved = _field_tasks(
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
    actions = v9._mission_assign(
        positions,
        inventories,
        tasks,
        base._as_int(
            base._get(
                obs,
                "step",
                base._as_int(base._get(obs, "day", 0)) * 24 + base._as_int(base._get(obs, "hour", 0)),
            )
        ),
    )
    execution_prediction = v8._expert_prediction(obs, farm, opponent_farm, private)
    actions = v10._prefer_local_water(
        obs,
        farm,
        opponent_farm,
        private,
        positions,
        inventories,
        actions,
        execution_prediction,
    )
    actions = v10._preposition_idle_workers(
        obs,
        farm,
        opponent_farm,
        private,
        positions,
        inventories,
        tasks,
        actions,
        execution_prediction,
    )
    market, _recovery = v11._market_plan(
        obs,
        farm,
        opponent_farm,
        private,
        summary,
        animal_targets,
        crop_targets,
        target_hands,
        target_land,
        weights,
        pasture_target,
        actions,
        reserved,
    )
    result = {
        "farmer": actions[0] if actions else ["PASS"],
        "hands": actions[1:],
        "market": market,
    }
    if expert_opening is not None:
        scripted, _copy_market = expert_opening
        result["farmer"] = scripted["farmer"]
        result["hands"] = scripted["hands"]
    return result
