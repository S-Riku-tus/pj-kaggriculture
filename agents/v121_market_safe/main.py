"""V120 with conservative correctness overlays but no SELL reordering."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2] if "__file__" in globals() else Path.cwd()
SOURCE = ROOT / "agents/v121_market/main.py"
SPEC = importlib.util.spec_from_file_location("_v121_market_safe_base", SOURCE)
if SPEC is None or SPEC.loader is None:
    raise ImportError(f"cannot import market overlay: {SOURCE}")
overlay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(overlay)
overlay.ENABLE_SELL_RANKING = False


def reset_runtime_state() -> None:
    overlay.reset_runtime_state()


def policy_diagnostics(observation: dict[str, Any]) -> dict[str, Any]:
    return overlay.policy_diagnostics(observation)


def agent(observation: dict[str, Any], configuration: Any = None) -> dict[str, Any]:
    return overlay.agent(observation, configuration)


def _kaggle_submission_entrypoint(observation: dict[str, Any], configuration: Any = None) -> dict[str, Any]:
    return agent(observation, configuration)
