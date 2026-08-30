"""V55: V54 redundant-pickup suppression with one safety carrier."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

if "__file__" in globals():
    MODULE_DIR = Path(__file__).resolve().parent
else:
    MODULE_DIR = Path.cwd() / "agents" / "v55"


def _load_v54_module():
    packaged = MODULE_DIR / "v54_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v54" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v55_v54", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V54 mechanism: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v54 = _load_v54_module()
v14 = v54.v14
base = v54.base

ENABLE_BUFFERED_SUPPRESSION = False
ACTIVE_DAYS = v54.ACTIVE_DAYS
SAFETY_CARRIER_BUFFER = 1
v54.REDUNDANT_CARRIER_BUFFER = SAFETY_CARRIER_BUFFER


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    v54.ENABLE_REDUNDANT_PICKUP_SUPPRESSION = ENABLE_BUFFERED_SUPPRESSION
    result = dict(v54.policy_diagnostics(obs))
    result["v55_buffered_suppression"] = {
        "enabled": ENABLE_BUFFERED_SUPPRESSION,
        "safety_carrier_buffer": SAFETY_CARRIER_BUFFER,
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    v54.ENABLE_REDUNDANT_PICKUP_SUPPRESSION = ENABLE_BUFFERED_SUPPRESSION
    v54.REDUNDANT_CARRIER_BUFFER = SAFETY_CARRIER_BUFFER
    return v54.agent(obs)
