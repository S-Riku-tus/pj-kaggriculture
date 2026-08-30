"""V67: V63 late role continuity with a relative-money teacher gate."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

if "__file__" in globals():
    MODULE_DIR = Path(__file__).resolve().parent
else:
    _runtime_candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd() / "agents" / "v67",
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
    spec = importlib.util.spec_from_file_location("_kaggriculture_v67_role_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V58 role core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_relative_model() -> dict[str, Any] | None:
    packaged = MODULE_DIR / "relative_role_model.json"
    source = (
        packaged
        if packaged.is_file()
        else MODULE_DIR.parent / "v65" / "relative_role_model.json"
    )
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if payload.get("format") != "kaggriculture-v65-relative-role-knn-v1":
        return None
    return payload


v58 = _load_v58_module()
v14 = v58.v14
base = v58.base
RELATIVE_MODEL = _load_relative_model()
_ROLE_PREDICT = v58._predict
MAX_PREDICTED_MONEY_GAP_DECLINE = 0.0

v58.ENABLE_ROLE_CONTINUITY = True
v58.ACTIVE_DAYS = (11, 12)
v58.ROLE_TYPES = {"ANIMAL", "CROP"}
if RELATIVE_MODEL is not None:
    v58.MODEL = RELATIVE_MODEL
    v58.MODEL_FORMAT = str(RELATIVE_MODEL["format"])


def _relative_predict(obs: Any, farm: Any, opponent: Any) -> dict[str, Any]:
    result = dict(_ROLE_PREDICT(obs, farm, opponent))
    if not result.get("active"):
        return result
    labels = result.get("labels") or {}
    if "future72_money_gap_ratio" not in labels:
        return {**result, "active": False, "reason": "missing-relative-target"}
    context = v58._context(obs, farm, opponent)
    current = float(context["money_gap_ratio"])
    target = float(labels["future72_money_gap_ratio"])
    improvement = target - current
    if improvement < -MAX_PREDICTED_MONEY_GAP_DECLINE:
        return {
            **result,
            "active": False,
            "reason": "relative-money-decline",
            "current_money_gap_ratio": current,
            "future72_money_gap_ratio": target,
            "money_gap_improvement": improvement,
        }
    return {
        **result,
        "current_money_gap_ratio": current,
        "future72_money_gap_ratio": target,
        "money_gap_improvement": improvement,
    }


v58._predict = _relative_predict


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v58.policy_diagnostics(obs))
    result["v67_relative_money_gate"] = {
        "enabled": RELATIVE_MODEL is not None,
        "active_days": list(v58.ACTIVE_DAYS),
        "criterion": "future72_money_gap_ratio >= current_money_gap_ratio",
        "maximum_predicted_decline": MAX_PREDICTED_MONEY_GAP_DECLINE,
        "ood_fallback": "v14-exact",
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v58.agent(obs)
