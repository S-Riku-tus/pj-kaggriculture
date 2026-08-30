"""Kaggriculture V18: intraday winner-trained recovery herd gate.

The model is trained at eight intraday checkpoints, then makes one bounded
macro choice while behind: keep V11's Cow/Sheep goal or stop buying at the
already-owned herd. Its own winner-state profile and tree-disagreement checks
fall back to V14. Crop strategy, feed, routing, legality, inventory, market
feasibility, and action execution remain deterministic V14/V11 behavior.
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
        Path.cwd() / "agents" / "v18",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (
                (candidate / "v14_base.py").is_file()
                and (candidate / "winner_goal_model.json").is_file()
                and (candidate / "intraday_herd_gate_model.json").is_file()
            )
            or ((candidate / "main.py").is_file() and (candidate.parent / "v14" / "main.py").is_file())
        ),
        Path.cwd(),
    )


def _load_v14_module():
    packaged = MODULE_DIR / "v14_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v14" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v18_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V14 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v14 = _load_v14_module()
v11 = v14.v11
v10 = v14.v10
v9 = v14.v9
v8 = v14.v8
v7 = v14.v7
v6 = v14.v6
v5 = v14.v5
v4 = v14.v4
v3 = v14.v3
base = v14.base

MODEL_FORMAT = "kaggriculture-v18-intraday-herd-gate-v1"
ENABLE_INTRADAY_HERD_GATE = False


def _load_model() -> dict[str, Any] | None:
    path = MODULE_DIR / "intraday_herd_gate_model.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    expected_features = (*v3.FEATURE_NAMES, "hour")
    if (
        payload.get("format") != MODEL_FORMAT
        or not payload.get("enabled")
        or tuple(payload.get("feature_names", ())) != expected_features
        or tuple(payload.get("animals", ())) != ("COW", "SHEEP")
        or not payload.get("forest")
        or not payload.get("profiles")
    ):
        return None
    return payload


HERD_MODEL = _load_model()


def _phase(day: int) -> str:
    for lower, upper in ((6, 9), (10, 11), (12, 13), (14, 17), (18, 19)):
        if lower <= day <= upper:
            return f"{lower}-{upper}"
    return "outside"


def _predict_tree(tree: list[Any], features: list[float]) -> float:
    node = tree
    while node[0] == "N":
        node = node[3] if features[int(node[1])] <= float(node[2]) else node[4]
    return float(node[1])


def _predict_forest(forest: list[list[Any]], features: list[float]) -> tuple[float, float]:
    values = [_predict_tree(tree, features) for tree in forest]
    mean = sum(values) / len(values)
    deviation = math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))
    return mean, deviation


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
    if not ENABLE_INTRADAY_HERD_GATE or HERD_MODEL is None:
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
    features = [*[float(value) for value in v3.encode_observation(obs)], hour / 23.0]
    profile_confidence, distance = _profile_confidence(features, day)
    minimum_confidence = float(HERD_MODEL["manifold_min_confidence"])
    if profile_confidence < minimum_confidence:
        return {
            "active": False,
            "reason": "ood",
            "money_gap_ratio": money_gap_ratio,
            "profile_confidence": profile_confidence,
            "distance": distance,
        }
    advantage, uncertainty = _predict_forest(HERD_MODEL["forest"], features)
    uncertainty_limit = float(HERD_MODEL["uncertainty_limit"])
    if uncertainty > uncertainty_limit:
        return {
            "active": False,
            "reason": "uncertain",
            "money_gap_ratio": money_gap_ratio,
            "advantage": advantage,
            "uncertainty": uncertainty,
            "uncertainty_limit": uncertainty_limit,
            "profile_confidence": profile_confidence,
            "distance": distance,
        }
    threshold = float(HERD_MODEL["threshold"])
    return {
        "active": True,
        "reason": "active",
        "decision": "freeze-owned" if advantage > threshold else "v11-herd",
        "money_gap_ratio": money_gap_ratio,
        "advantage": advantage,
        "threshold": threshold,
        "uncertainty": uncertainty,
        "uncertainty_limit": uncertainty_limit,
        "profile_confidence": profile_confidence,
        "distance": distance,
    }


_SAFE_STRATEGY_TARGETS = v14._strategy_targets


def _strategy_targets(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
) -> tuple[dict[str, int], dict[str, int], int, int, dict[str, float], int]:
    animals, crops, hands, land, weights, pastures = _SAFE_STRATEGY_TARGETS(obs, farm, opponent_farm, private)
    prediction = _herd_gate_prediction(obs, farm, opponent_farm)
    if not prediction.get("active") or prediction.get("decision") != "freeze-owned":
        return animals, crops, hands, land, weights, pastures
    animals = dict(animals)
    animals["COW"] = v4._owned_animals(farm, private, "COW")
    animals["SHEEP"] = v4._owned_animals(farm, private, "SHEEP")
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
    result["v18_intraday_herd_gate"] = prediction
    result["v18_herd_targets"] = {"animals": targets[0], "pastures": targets[5]}
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v14.agent(obs)
