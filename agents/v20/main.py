"""Kaggriculture V20: seat-aware multi-horizon Cow purchase gate.

V20 freezes Cow growth only when independent 24-hour and 72-hour winner
models agree that the already-owned count is closer than V11's target. The
state must also pass intraday OOD and both uncertainty gates. Sheep and every
other strategy/execution decision remain deterministic V14/V11 behavior.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

if "__file__" in globals():
    MODULE_DIR = Path(__file__).resolve().parent
else:
    _runtime_candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd() / "agents" / "v20",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if ((candidate / "v19_base.py").is_file() and (candidate / "multihorizon_cow_gate_model.json").is_file())
            or ((candidate / "main.py").is_file() and (candidate.parent / "v19" / "main.py").is_file())
        ),
        Path.cwd(),
    )


def _load_v19_module():
    packaged = MODULE_DIR / "v19_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v19" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v20_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V19 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v19 = _load_v19_module()
v18 = v19.v18
v14 = v19.v14
v11 = v19.v11
v10 = v19.v10
v9 = v19.v9
v8 = v19.v8
v7 = v19.v7
v6 = v19.v6
v5 = v19.v5
v4 = v19.v4
v3 = v19.v3
base = v19.base

MODEL_FORMAT = "kaggriculture-v20-multihorizon-cow-gate-v1"
ENABLE_MULTIHORIZON_COW_GATE = False


def _load_model() -> dict[str, Any] | None:
    path = MODULE_DIR / "multihorizon_cow_gate_model.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    expected_features = (*v3.FEATURE_NAMES, "hour", "seat")
    if (
        payload.get("format") != MODEL_FORMAT
        or not payload.get("enabled")
        or tuple(payload.get("feature_names", ())) != expected_features
        or payload.get("animal") != "COW"
        or tuple(payload.get("horizons", ())) != ("h24", "h72")
        or not payload.get("forests")
        or not payload.get("profiles")
    ):
        return None
    return payload


COW_MODEL = _load_model()


def _phase(day: int) -> str:
    return v18._phase(day)


def _predict_forest(forest: list[list[Any]], features: list[float]) -> tuple[float, float]:
    return v18._predict_forest(forest, features)


def _profile_confidence(features: list[float], day: int) -> tuple[float, float]:
    if COW_MODEL is None:
        return 0.0, math.inf
    profile = COW_MODEL["profiles"].get(_phase(day))
    if not isinstance(profile, dict):
        return 0.0, math.inf
    indices = [int(value) for value in profile.get("feature_indices", [])]
    centers = [float(value) for value in profile.get("center", [])]
    scales = [max(1e-6, float(value)) for value in profile.get("scale", [])]
    if not indices or not (len(indices) == len(centers) == len(scales)):
        return 0.0, math.inf
    z = [
        min(8.0, abs(features[index] - center) / scale)
        for index, center, scale in zip(indices, centers, scales, strict=True)
    ]
    distance = math.sqrt(sum(value * value for value in z) / len(z))
    p50 = float(profile["distance_p50"])
    p90 = max(p50 + 1e-6, float(profile["distance_p90"]))
    p99 = max(p90 + 1e-6, float(profile["distance_p99"]))
    if distance <= p50:
        confidence = 1.0
    elif distance <= p90:
        confidence = 1.0 - 0.35 * (distance - p50) / (p90 - p50)
    elif distance <= p99:
        confidence = 0.65 - 0.50 * (distance - p90) / (p99 - p90)
    else:
        confidence = max(0.0, 0.15 * math.exp(-(distance - p99)))
    return confidence, distance


def _cow_gate_prediction(obs: Any, farm: Any, opponent_farm: Any) -> dict[str, Any]:
    if not ENABLE_MULTIHORIZON_COW_GATE or COW_MODEL is None:
        return {"active": False, "reason": "disabled-or-missing"}
    day = base._as_int(base._get(obs, "day", 0))
    lower, upper = [int(value) for value in COW_MODEL["day_window"]]
    if not lower <= day <= upper:
        return {"active": False, "reason": "outside-window"}
    own_money = float(base._get(farm, "money", 0) or 0)
    opponent_money = float(base._get(opponent_farm, "money", 0) or 0)
    money_gap_ratio = (own_money - opponent_money) / max(1.0, own_money + opponent_money)
    if money_gap_ratio >= 0:
        return {
            "active": False,
            "reason": "not-behind",
            "money_gap_ratio": money_gap_ratio,
        }
    hour = base._as_int(base._get(obs, "hour", 0))
    seat = base._as_int(base._get(obs, "player", 0))
    features = [
        *[float(value) for value in v3.encode_observation(obs)],
        hour / 23.0,
        float(seat),
    ]
    profile_confidence, distance = _profile_confidence(features, day)
    if profile_confidence < float(COW_MODEL["profile_min_confidence"]):
        return {
            "active": False,
            "reason": "ood",
            "money_gap_ratio": money_gap_ratio,
            "profile_confidence": profile_confidence,
            "distance": distance,
        }
    predictions: dict[str, Any] = {}
    freeze = True
    for horizon in COW_MODEL["horizons"]:
        advantage, uncertainty = _predict_forest(COW_MODEL["forests"][horizon], features)
        threshold = float(COW_MODEL["thresholds"][horizon])
        uncertainty_limit = float(COW_MODEL["uncertainty_limits"][horizon])
        supported = advantage > threshold and uncertainty <= uncertainty_limit
        freeze &= supported
        predictions[horizon] = {
            "supported": supported,
            "advantage": advantage,
            "threshold": threshold,
            "uncertainty": uncertainty,
            "uncertainty_limit": uncertainty_limit,
        }
    return {
        "active": True,
        "reason": "active",
        "decision": "freeze-owned" if freeze else "v11-herd",
        "horizons": predictions,
        "money_gap_ratio": money_gap_ratio,
        "profile_confidence": profile_confidence,
        "distance": distance,
        "seat": seat,
    }


_SAFE_STRATEGY_TARGETS = v19._SAFE_STRATEGY_TARGETS


def _strategy_targets(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
) -> tuple[dict[str, int], dict[str, int], int, int, dict[str, float], int]:
    animals, crops, hands, land, weights, pastures = _SAFE_STRATEGY_TARGETS(obs, farm, opponent_farm, private)
    prediction = _cow_gate_prediction(obs, farm, opponent_farm)
    if prediction.get("active") and prediction.get("decision") == "freeze-owned":
        animals = dict(animals)
        animals["COW"] = v4._owned_animals(farm, private, "COW")
        pastures = max(v8._pasture_count(farm), animals["COW"] + animals["SHEEP"])
    return animals, crops, hands, land, weights, pastures


v14._strategy_targets = _strategy_targets


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v14.policy_diagnostics(obs))
    safe = base._safe_observation(obs)
    if safe is None:
        return result
    farm, opponent_farm, private = safe
    prediction = dict(_cow_gate_prediction(obs, farm, opponent_farm))
    baseline_targets = _SAFE_STRATEGY_TARGETS(obs, farm, opponent_farm, private)
    targets = _strategy_targets(obs, farm, opponent_farm, private)
    prediction["changed"] = targets[0] != baseline_targets[0]
    prediction["baseline_animals"] = baseline_targets[0]
    prediction["selected_animals"] = targets[0]
    result["v20_multihorizon_cow_gate"] = prediction
    result["v20_herd_targets"] = {"animals": targets[0], "pastures": targets[5]}
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v14.agent(obs)
