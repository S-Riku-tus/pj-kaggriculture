"""V49: preposition otherwise-idle loaded workers toward feasible work.

V48 found that most remaining V11 PASS workers carry Wheat/Fertilizer and
still have positive-score legal tasks, while V10's safe preposition layer
categorically excludes every non-empty inventory.  This wrapper preserves the
safe result first, then routes only loaded PASS workers toward observable,
currently feasible tasks.  Animal carriers and low-confidence/OOD states fall
back unchanged.  The experiment is disabled by default.
"""

from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if "__file__" in globals():
    MODULE_DIR = Path(__file__).resolve().parent
else:
    _runtime_candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd() / "agents" / "v49",
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
    spec = importlib.util.spec_from_file_location("_kaggriculture_v49_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V14 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v14 = _load_v14_module()
v10 = v14.v10
v8 = v14.v8
v5 = v14.v5
base = v14.base

ENABLE_LOADED_PREPOSITION = False
ACTIVE_DAYS = range(6, 13)
MIN_CONFIDENCE = 0.35
_SAFE_PREPOSITION = v10._preposition_idle_workers


def _loaded_preposition(
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
    safe = _SAFE_PREPOSITION(
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
    day = base._as_int(base._get(obs, "day", 0))
    if not ENABLE_LOADED_PREPOSITION or day not in ACTIVE_DAYS:
        return safe
    prediction = expert_prediction or v8._expert_prediction(
        obs, farm, opponent_farm, private
    )
    if prediction is None or prediction[2] < MIN_CONFIDENCE:
        return safe

    density: Counter[tuple[int, int]] = Counter(task["pos"] for task in tasks)
    result = [list(action) for action in safe]
    claimed: set[tuple[int, int]] = set()
    for unit, action in enumerate(result):
        if action != ["PASS"] or unit >= len(positions) or unit >= len(inventories):
            continue
        inventory = inventories[unit]
        if base._inventory_total(inventory) <= 0:
            continue
        if any(base._inventory_count(inventory, animal) > 0 for animal in ("COW", "SHEEP", "GOOSE")):
            continue
        candidates = []
        for task in tasks:
            position = task.get("pos")
            if (
                not isinstance(position, tuple)
                or position == positions[unit]
                or position in claimed
            ):
                continue
            cost = v5._assignment_cost(unit, task, positions, inventories, density)
            if cost < 0:
                candidates.append((cost, task))
        if not candidates:
            continue
        _cost, target_task = min(
            candidates,
            key=lambda value: (
                value[0],
                base._manhattan(positions[unit], value[1]["pos"]),
                value[1]["pos"][1],
                value[1]["pos"][0],
            ),
        )
        claimed.add(target_task["pos"])
        result[unit] = base._movement(positions[unit], target_task["pos"], unit)
    return result


v10._preposition_idle_workers = _loaded_preposition


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v14.policy_diagnostics(obs))
    day = base._as_int(base._get(obs, "day", 0))
    result["v49_loaded_preposition"] = {
        "enabled": ENABLE_LOADED_PREPOSITION,
        "active": ENABLE_LOADED_PREPOSITION and day in ACTIVE_DAYS,
        "minimum_confidence": MIN_CONFIDENCE,
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v14.agent(obs)

