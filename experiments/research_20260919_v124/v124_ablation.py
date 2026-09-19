"""Local-only V124 ablation entrypoint selected by V124_ABLATION."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("_v124_ablation_base", ROOT / "agents/v124/main.py")
if SPEC is None or SPEC.loader is None:
    raise ImportError("cannot load V124")
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)

variant = os.environ.get("V124_ABLATION", "full")
if variant == "library_only":
    policy.ENABLE_SEGMENT_ROUTER = False
    policy.ENABLE_SELL_FORECAST = False
elif variant == "library_segment":
    policy.ENABLE_SEGMENT_ROUTER = True
    policy.ENABLE_SELL_FORECAST = False
elif variant == "library_forecast":
    policy.ENABLE_SEGMENT_ROUTER = False
    policy.ENABLE_SELL_FORECAST = True
elif variant != "full":
    raise ValueError(f"unknown V124_ABLATION={variant!r}")

agent = policy.agent
reset_runtime_state = policy.reset_runtime_state
policy_diagnostics = policy.policy_diagnostics
