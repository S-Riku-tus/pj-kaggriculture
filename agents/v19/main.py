"""Kaggriculture V19: seat-aware, animal-specific recovery gates.

V19 separates Cow and Sheep decisions and includes market-order seat in the
intraday feature vector. Only animal branches with material validation gains
are enabled. Each enabled branch can choose only between V11's target and the
already-owned count. Intraday OOD and tree-disagreement checks fall back to
V14's deterministic strategy and execution.
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
        Path.cwd() / "agents" / "v19",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if ((candidate / "v18_base.py").is_file() and (candidate / "seat_animal_gate_model.json").is_file())
            or ((candidate / "main.py").is_file() and (candidate.parent / "v18" / "main.py").is_file())
        ),
        Path.cwd(),
    )


def _load_v18_module():
    packaged = MODULE_DIR / "v18_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v18" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v19_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V18 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v18 = _load_v18_module()
v14 = v18.v14
v11 = v18.v11
v10 = v18.v10
v9 = v18.v9
v8 = v18.v8
v7 = v18.v7
v6 = v18.v6
v5 = v18.v5
v4 = v18.v4
v3 = v18.v3
base = v18.base

MODEL_FORMAT = "kaggriculture-v19-seat-animal-gates-v1"
ENABLE_SEAT_ANIMAL_GATES = False


def _load_model() -> dict[str, Any] | None:
    path = MODULE_DIR / "seat_animal_gate_model.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    expected_features = (*v3.FEATURE_NAMES, "hour", "seat")
    if (
        payload.get("format") != MODEL_FORMAT
        or not payload.get("enabled")
        or tuple(payload.get("feature_names", ())) != expected_features
        or tuple(payload.get("animals", ())) != ("COW", "SHEEP")
        or not payload.get("forests")
        or not payload.get("profiles")
    ):
        return None
    return payload


HERD_MODEL = _load_model()


def _phase(day: int) -> str:
    return v18._phase(day)


def _predict_forest(forest: list[list[Any]], features: list[float]) -> tuple[float, float]:
    return v18._predict_forest(forest, features)


def _profile_confidence(features: list[float], day: int) -> tuple[float, float]:
    if HERD_MODEL is None:
        return 0.0, math.inf
    profile = HERD_MODEL["profiles"].get(_phase(day))
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


def _herd_gate_prediction(obs: Any, farm: Any, opponent_farm: Any) -> dict[str, Any]:
    if not ENABLE_SEAT_ANIMAL_GATES or HERD_MODEL is None:
        return {"active": False, "reason": "disabled-or-missing"}
    day = base._as_int(base._get(obs, "day", 0))
    lower, upper = [int(value) for value in HERD_MODEL["day_window"]]
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
    if profile_confidence < float(HERD_MODEL["profile_min_confidence"]):
        return {
            "active": False,
            "reason": "ood",
            "money_gap_ratio": money_gap_ratio,
            "profile_confidence": profile_confidence,
            "distance": distance,
        }
    decisions: dict[str, str] = {}
    details: dict[str, Any] = {}
    for animal in HERD_MODEL["animals"]:
        if not HERD_MODEL["animal_enabled"].get(animal):
            decisions[animal] = "v11-herd"
            details[animal] = {"reason": "validation-disabled"}
            continue
        advantage, uncertainty = _predict_forest(HERD_MODEL["forests"][animal], features)
        uncertainty_limit = float(HERD_MODEL["uncertainty_limits"][animal])
        threshold = float(HERD_MODEL["thresholds"][animal])
        if uncertainty > uncertainty_limit:
            decisions[animal] = "v11-herd"
            reason = "uncertain"
        elif advantage > threshold:
            decisions[animal] = "freeze-owned"
            reason = "active"
        else:
            decisions[animal] = "v11-herd"
            reason = "active"
        details[animal] = {
            "reason": reason,
            "advantage": advantage,
            "threshold": threshold,
            "uncertainty": uncertainty,
            "uncertainty_limit": uncertainty_limit,
        }
    return {
        "active": True,
        "reason": "active",
        "decisions": decisions,
        "animals": details,
        "money_gap_ratio": money_gap_ratio,
        "profile_confidence": profile_confidence,
        "distance": distance,
        "seat": seat,
    }


_SAFE_STRATEGY_TARGETS = v18._SAFE_STRATEGY_TARGETS


def _strategy_targets(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
) -> tuple[dict[str, int], dict[str, int], int, int, dict[str, float], int]:
    animals, crops, hands, land, weights, pastures = _SAFE_STRATEGY_TARGETS(obs, farm, opponent_farm, private)
    prediction = _herd_gate_prediction(obs, farm, opponent_farm)
    if not prediction.get("active"):
        return animals, crops, hands, land, weights, pastures
    animals = dict(animals)
    for animal, decision in prediction["decisions"].items():
        if decision == "freeze-owned":
            animals[animal] = v4._owned_animals(farm, private, animal)
    pastures = max(v8._pasture_count(farm), animals["COW"] + animals["SHEEP"])
    return animals, crops, hands, land, weights, pastures


v14._strategy_targets = _strategy_targets


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v14.policy_diagnostics(obs))
    safe = base._safe_observation(obs)
    if safe is None:
        return result
    farm, opponent_farm, private = safe
    prediction = dict(_herd_gate_prediction(obs, farm, opponent_farm))
    baseline_targets = _SAFE_STRATEGY_TARGETS(obs, farm, opponent_farm, private)
    targets = _strategy_targets(obs, farm, opponent_farm, private)
    prediction["changed"] = targets[0] != baseline_targets[0]
    prediction["baseline_animals"] = baseline_targets[0]
    prediction["selected_animals"] = targets[0]
    result["v19_seat_animal_gates"] = prediction
    result["v19_herd_targets"] = {"animals": targets[0], "pastures": targets[5]}
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v14.agent(obs)
