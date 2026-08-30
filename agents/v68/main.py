"""V68: uncertainty-calibrated relative-money gate on V67."""

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
        Path.cwd() / "agents" / "v68",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (candidate / "v67_base.py").is_file()
            or (
                (candidate / "main.py").is_file()
                and (candidate.parent / "v67" / "main.py").is_file()
            )
        ),
        Path.cwd(),
    )


def _load_v67_module():
    packaged = MODULE_DIR / "v67_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v67" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v68_relative_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V67 relative core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v67 = _load_v67_module()
v58 = v67.v58
v14 = v67.v14
base = v67.base

# max(validation, test) raw MAE was ~0.232; two MAE defines the uncertainty band.
MAX_PREDICTED_MONEY_GAP_DECLINE = 0.464
v67.MAX_PREDICTED_MONEY_GAP_DECLINE = MAX_PREDICTED_MONEY_GAP_DECLINE


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v67.policy_diagnostics(obs))
    result["v68_uncertainty_gate"] = {
        "maximum_predicted_money_gap_decline": MAX_PREDICTED_MONEY_GAP_DECLINE,
        "calibration": "2 * max(validation_MAE, test_MAE)",
        "rating_claim": "unverified",
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v67.agent(obs)
