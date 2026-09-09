"""Kaggriculture V106: spec-accurate day-goal safety boundary.

V105 incorrectly cancelled a day goal at consecutive_unfed == 1 even though
the game removes animals only at 2+ and V11 already assigns those FEED tasks
its maximum emergency priority.  V106 preserves V105's day-granularity goal
and falls back only at the actual escape boundary.
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
        Path.cwd() / "agents" / "v106",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (candidate / "v105_base.py").is_file()
            or ((candidate / "main.py").is_file() and (candidate.parent / "v105" / "main.py").is_file())
        ),
        Path.cwd(),
    )


def _load_v105_module():
    packaged = MODULE_DIR / "v105_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v105" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v106_daily_goal", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V105 daily goal: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v105 = _load_v105_module()
v104 = v105.v104
v102 = v105.v102
v14 = v105.v14
v11 = v105.v11
v10 = v105.v10
v9 = v105.v9
v8 = v105.v8
v7 = v105.v7
v6 = v105.v6
v5 = v105.v5
v4 = v105.v4
v3 = v105.v3
base = v105.base

ENABLE_SPEC_ACCURATE_DAILY_RECOVERY = True


def _resource_emergency(farm: Any) -> bool:
    """Return true only at the documented animal-escape boundary."""
    return any(
        base._get(tile, "animal") in base.ANIMAL_DATA
        and not bool(base._get(tile, "fed_today", False))
        and base._as_int(base._get(tile, "consecutive_unfed", 0)) >= 2
        for _x, _y, tile in base._iter_tiles(farm)
    )


v105._resource_emergency = _resource_emergency


def reset_runtime_state() -> None:
    v105.reset_runtime_state()


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v105.policy_diagnostics(obs))
    result["v106_safety_boundary"] = {
        "enabled": ENABLE_SPEC_ACCURATE_DAILY_RECOVERY,
        "animal_escape_consecutive_unfed": 2,
        "emergency_feed_owner": "v11-deterministic-executor",
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    v105.ENABLE_DAILY_RECOVERY = ENABLE_SPEC_ACCURATE_DAILY_RECOVERY
    return v105.agent(obs)
