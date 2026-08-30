"""V74: core-late role continuity with V72 relative uncertainty gate."""

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
        Path.cwd() / "agents" / "v74",
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


def _load_module(name: str, packaged_name: str, local_relative: Path):
    packaged = MODULE_DIR / packaged_name
    source = packaged if packaged.is_file() else MODULE_DIR / local_relative
    spec = importlib.util.spec_from_file_location(name, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v67 = _load_module(
    "_kaggriculture_v74_relative_core",
    "v67_base.py",
    Path("../v67/main.py"),
)
v58 = v67.v58
v14 = v67.v14
base = v67.base


def _load_model() -> dict[str, Any] | None:
    packaged = MODULE_DIR / "core_late_relative_role_model.json"
    source = (
        packaged
        if packaged.is_file()
        else MODULE_DIR.parent / "v72" / "core_late_relative_role_model.json"
    )
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if payload.get("format") != "kaggriculture-v65-relative-role-knn-v1":
        return None
    return payload


CORE_LATE_MODEL = _load_model()
ACTIVE_DAYS = tuple(range(20, 25))
MAX_PREDICTED_MONEY_GAP_DECLINE = 0.089
if CORE_LATE_MODEL is not None:
    v58.MODEL = CORE_LATE_MODEL
    v58.MODEL_FORMAT = str(CORE_LATE_MODEL["format"])
v58.ENABLE_ROLE_CONTINUITY = True
v58.ACTIVE_DAYS = ACTIVE_DAYS
v58.ROLE_TYPES = {"ANIMAL", "CROP"}
v67.MAX_PREDICTED_MONEY_GAP_DECLINE = MAX_PREDICTED_MONEY_GAP_DECLINE


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v67.policy_diagnostics(obs))
    result["v74_core_late_gate"] = {
        "enabled": CORE_LATE_MODEL is not None,
        "active_days": list(v58.ACTIVE_DAYS),
        "maximum_predicted_money_gap_decline": MAX_PREDICTED_MONEY_GAP_DECLINE,
        "rating_claim": "unverified",
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v67.agent(obs)
