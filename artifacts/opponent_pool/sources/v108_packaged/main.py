"""Kaggriculture V108: liquidity-bounded demand recovery.

V107's first untouched confirmation exposed a high-cash false positive: the
agent was behind in relative money but already held 14,249 cash.  V108 treats
the learned branch as a liquidity-recovery tool and admits it only below a
round 5,000 cash ceiling.  All V107, V106, and V11 safety checks remain.
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
        Path.cwd() / "agents" / "v108",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (candidate / "v107_base.py").is_file()
            or ((candidate / "main.py").is_file() and (candidate.parent / "v107" / "main.py").is_file())
        ),
        Path.cwd(),
    )


def _load_v107_module():
    packaged = MODULE_DIR / "v107_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v107" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v108_path_gate", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V107 path gate: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v107 = _load_v107_module()
v106 = v107.v106
v105 = v107.v105
v104 = v107.v104
v102 = v107.v102
v14 = v107.v14
v11 = v107.v11
v10 = v107.v10
v9 = v107.v9
v8 = v107.v8
v7 = v107.v7
v6 = v107.v6
v5 = v107.v5
v4 = v107.v4
v3 = v107.v3
base = v107.base

ENABLE_V108_LIQUIDITY_GATE = True
MAX_CURRENT_MONEY = 5_000.0

_SAFE_V107_GATE_DECISION = v107._gate_decision


def _gate_decision(obs: Any, farm: Any, opponent_farm: Any, private: Any) -> dict[str, Any]:
    decision = dict(_SAFE_V107_GATE_DECISION(obs, farm, opponent_farm, private))
    if not ENABLE_V108_LIQUIDITY_GATE:
        decision.update(active=False, changed=False, reason="v108-disabled")
        return decision
    if not decision.get("active"):
        return decision
    money = float(decision.get("v107_current_money", base._get(farm, "money", 0)) or 0)
    decision["v108_maximum_current_money"] = MAX_CURRENT_MONEY
    if money >= MAX_CURRENT_MONEY:
        decision.update(active=False, changed=False, reason="v108-high-cash-fallback")
        return decision
    decision["reason"] = "v108-active"
    return decision


v102._gate_decision = _gate_decision


def reset_runtime_state() -> None:
    v107.reset_runtime_state()


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v107.policy_diagnostics(obs))
    result["v108_liquidity_gate"] = {
        "enabled": ENABLE_V108_LIQUIDITY_GATE,
        "minimum_current_money": v107.MIN_CURRENT_MONEY,
        "maximum_current_money_exclusive": MAX_CURRENT_MONEY,
        "fallback": "v11-safe-core",
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    v107.ENABLE_V107_RUNTIME_GATE = ENABLE_V108_LIQUIDITY_GATE
    return v107.agent(obs)
