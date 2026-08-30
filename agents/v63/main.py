"""V63: late-phase, OOD-safe Top-3 role-continuity tie-break.

The winner-only model may influence deterministic worker assignment only on
days 11 and 12, when the observed state is inside the teacher manifold and its
predicted same-role target is high.  All task generation, legality, survival,
inventory, routing, market, and recovery constraints remain V14 behavior.
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
        Path.cwd() / "agents" / "v63",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (candidate / "v58_base.py").is_file()
            or (
                (candidate / "main.py").is_file()
                and (candidate.parent / "v58" / "main.py").is_file()
            )
        ),
        Path.cwd(),
    )


def _load_v58_module():
    packaged = MODULE_DIR / "v58_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v58" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v63_role_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V58 role core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v58 = _load_v58_module()
v14 = v58.v14
base = v58.base

v58.ENABLE_ROLE_CONTINUITY = True
v58.ACTIVE_DAYS = (11, 12)
v58.ROLE_TYPES = {"ANIMAL", "CROP"}


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v58.policy_diagnostics(obs))
    result["v63_late_role_gate"] = {
        "active_days": list(v58.ACTIVE_DAYS),
        "role_types": sorted(v58.ROLE_TYPES),
        "ood_fallback": "v14-exact",
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v58.agent(obs)
