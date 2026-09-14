"""Kaggriculture V7: demand-responsive herd allocation on V6's safe core.

The unavailable external V7/V7-2 submissions showed that more frequent expert
imitation, higher utilization, and lower prediction error did not reliably
improve head-to-head strength.  This repository V7 therefore keeps every
validated V6 control unchanged and makes one supply-neutral correction: while
new animals can still repay their cost, move at most one not-yet-owned herd
slots toward the observable Town/price/opponent economic signal.

Total animals, crop targets, land, workforce, field assignment, market sales,
and liquidation remain V6.  The policy is deterministic and reconstructs all
state from the current observation.
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
        Path.cwd() / "agents" / "v7",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (
                (candidate / "v6_base.py").is_file()
                and (candidate / "v5_base.py").is_file()
                and (candidate / "v4_base.py").is_file()
                and (candidate / "v3_base.py").is_file()
                and (candidate / "v2_base.py").is_file()
                and (candidate / "feature_schema.py").is_file()
                and (candidate / "strategy_model.json").is_file()
            )
            or (
                (candidate / "main.py").is_file()
                and (candidate.parent / "v6" / "main.py").is_file()
            )
        ),
        Path.cwd(),
    )


def _load_v6_module():
    packaged = MODULE_DIR / "v6_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v6" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v7_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V6 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v6 = _load_v6_module()
v5 = v6.v5
v4 = v6.v4
v3 = v6.v3
base = v6.base
MODEL = v6.MODEL
OPENING_ACTIONS = v6.OPENING_ACTIONS


def _bounded_demand_herd(
    *,
    safe_animals: dict[str, int],
    economic_animals: dict[str, int],
    owned_cow: int,
    owned_sheep: int,
) -> dict[str, int]:
    """Move no more than one future slot while preserving total herd scale."""
    total = safe_animals["COW"] + safe_animals["SHEEP"]
    economic_total = economic_animals["COW"] + economic_animals["SHEEP"]
    if not total or not economic_total:
        return dict(safe_animals)

    safe_ratio = safe_animals["COW"] / total
    economic_ratio = economic_animals["COW"] / economic_total
    projected_cow = round(total * (0.55 * safe_ratio + 0.45 * economic_ratio))
    projected_cow = min(safe_animals["COW"] + 1, max(safe_animals["COW"] - 1, projected_cow))
    projected_cow = min(total - owned_sheep, max(owned_cow, projected_cow))
    return {"GOOSE": 0, "COW": projected_cow, "SHEEP": total - projected_cow}


def _strategy_targets(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
) -> tuple[dict[str, int], dict[str, int], int, int, dict[str, float], int]:
    """Keep V6 scale and shift only unowned Cow/Sheep allocation."""
    animals, crops, hands, target_land, weights, pasture_target = v6._strategy_targets(
        obs, farm, opponent_farm, private
    )
    day = base._as_int(base._get(obs, "day", 0))
    if 8 <= day < 21:
        summary = base._farm_summary(farm)
        opponent = base._farm_summary(opponent_farm)
        demand = base._demand_profile(obs)
        prices = base._get(base._get(obs, "market", {}) or {}, "prices", {}) or {}
        economic = base._desired_animals(day, summary["animals"], opponent, demand, prices)
        animals = _bounded_demand_herd(
            safe_animals=animals,
            economic_animals=economic,
            owned_cow=v4._owned_animals(farm, private, "COW"),
            owned_sheep=v4._owned_animals(farm, private, "SHEEP"),
        )
    return animals, crops, hands, target_land, weights, pasture_target


def agent(obs: Any) -> dict[str, Any]:
    """Return a demand-aware action through V6's validated executor."""
    safe = base._safe_observation(obs)
    if safe is None:
        return {"farmer": ["PASS"], "hands": [], "market": []}
    farm, opponent_farm, private = safe
    opening = v3._safe_opening(obs, farm)
    if opening is not None:
        return opening

    summary = base._farm_summary(farm)
    animal_targets, crop_targets, target_hands, target_land, weights, pasture_target = _strategy_targets(
        obs, farm, opponent_farm, private
    )
    positions = [tuple(base._get(farm, "farmer", [0, 0]))]
    positions.extend(tuple(position) for position in (base._get(farm, "hands", []) or []))
    raw_inventories = list(base._get(private, "inventories", []) or [])
    inventories = [
        raw_inventories[index] if index < len(raw_inventories) else {}
        for index in range(len(positions))
    ]
    tasks, reserved = v6._field_tasks(
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
    actions = v5._assign_tasks(positions, inventories, tasks)
    market = v6._market_plan(
        obs,
        farm,
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
    return {
        "farmer": actions[0] if actions else ["PASS"],
        "hands": actions[1:],
        "market": market,
    }
