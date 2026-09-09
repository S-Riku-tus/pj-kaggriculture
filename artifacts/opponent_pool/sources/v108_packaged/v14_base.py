"""Kaggriculture V14: selective winner-recovery goals on V11's safe core.

The learned layer is active only while observably behind and inside the
winning-teacher manifold.  It supplies a conservative 72-hour portfolio goal;
V11 still owns the short horizon, hiring, land, market feasibility, worker
assignment, survival, and liquidation.  All learned goals are projected
through current ownership, feed, herd, and productive-capacity constraints.
"""

from __future__ import annotations

import copy
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
        Path.cwd() / "agents" / "v14",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if ((candidate / "v11_base.py").is_file() and (candidate / "winner_goal_model.json").is_file())
            or ((candidate / "main.py").is_file() and (candidate.parent / "v11" / "main.py").is_file())
        ),
        Path.cwd(),
    )


def _load_v11_module():
    packaged = MODULE_DIR / "v11_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v11" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v14_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V11 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v11 = _load_v11_module()
v10 = v11.v10
v9 = v11.v9
v8 = v11.v8
v7 = v11.v7
v6 = v11.v6
v5 = v11.v5
v4 = v11.v4
v3 = v11.v3
base = v11.base

CROPS = v11.CROPS
ANIMALS = v11.ANIMALS
PORTFOLIO = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "COW", "SHEEP")
MODEL_FORMAT = "kaggriculture-v14-winner-goals-v1"
PHASES = ((6, 9), (10, 11), (12, 13), (14, 17), (18, 21), (22, 24), (25, 27))
CROP_CHANGE_LIMIT = {"WHEAT": 8, "CARROT": 6, "TOMATO": 3, "STRAWBERRY": 6, "MELON": 3}
ITEM_DEMAND = {
    "WHEAT": "WHEAT",
    "CARROT": "CARROT",
    "TOMATO": "TOMATO",
    "STRAWBERRY": "STRAWBERRY",
    "MELON": "MELON",
    "COW": "MILK",
    "SHEEP": "WOOL",
}

ENABLE_WINNER_RECOVERY = True
MIN_RECOVERY_GAP_RATIO = 0.0
MIN_CONFIDENCE = 0.35
MAX_BLEND = 0.35


def _load_model() -> dict[str, Any] | None:
    path = MODULE_DIR / "winner_goal_model.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if (
        payload.get("format") != MODEL_FORMAT
        or not payload.get("enabled")
        or not (payload.get("selection") or {}).get("h72_recovery")
        or tuple(payload.get("feature_names", ())) != tuple(v3.FEATURE_NAMES)
        or tuple(payload.get("target_names", ())) != PORTFOLIO
        or not (payload.get("forests") or {}).get("h72")
    ):
        return None
    return payload


WINNER_MODEL = _load_model()


def _phase(day: int) -> str:
    for lower, upper in PHASES:
        if lower <= day <= upper:
            return f"{lower}-{upper}"
    return "outside"


def _predict_tree(tree: list[Any], features: list[float]) -> list[float]:
    node = tree
    while node[0] == "N":
        node = node[3] if features[int(node[1])] <= float(node[2]) else node[4]
    return [float(value) for value in node[1:]]


def _predict_forest(forest: list[list[Any]], features: list[float]) -> tuple[list[float], list[float]]:
    rows = [_predict_tree(tree, features) for tree in forest]
    means = [sum(row[index] for row in rows) / len(rows) for index in range(len(PORTFOLIO))]
    deviations = [
        math.sqrt(sum((row[index] - means[index]) ** 2 for row in rows) / len(rows)) for index in range(len(PORTFOLIO))
    ]
    return means, deviations


def _distance_confidence(features: list[float], day: int) -> tuple[float, float]:
    if WINNER_MODEL is None:
        return 0.0, math.inf
    profile = (WINNER_MODEL.get("profiles") or {}).get(_phase(day))
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
    p50 = float(profile.get("distance_p50", 1.0))
    p90 = max(p50 + 1e-6, float(profile.get("distance_p90", p50 + 1.0)))
    p99 = max(p90 + 1e-6, float(profile.get("distance_p99", p90 + 1.0)))
    if distance <= p50:
        confidence = 1.0
    elif distance <= p90:
        confidence = 1.0 - 0.35 * (distance - p50) / (p90 - p50)
    elif distance <= p99:
        confidence = 0.65 - 0.50 * (distance - p90) / (p99 - p90)
    else:
        confidence = max(0.0, 0.15 * math.exp(-(distance - p99)))
    return confidence, distance


def _winner_prediction(obs: Any, farm: Any, opponent_farm: Any) -> dict[str, Any]:
    if not ENABLE_WINNER_RECOVERY or WINNER_MODEL is None:
        return {"active": False, "reason": "disabled-or-missing"}
    day = base._as_int(base._get(obs, "day", 0))
    if not 6 <= day <= 27:
        return {"active": False, "reason": "outside-window"}
    own_money = float(base._get(farm, "money", 0) or 0)
    opponent_money = float(base._get(opponent_farm, "money", 0) or 0)
    gap_ratio = (own_money - opponent_money) / max(1.0, own_money + opponent_money)
    if gap_ratio >= -MIN_RECOVERY_GAP_RATIO:
        return {"active": False, "reason": "not-behind", "money_gap_ratio": gap_ratio}
    features = [float(value) for value in v3.encode_observation(obs)]
    manifold_confidence, distance = _distance_confidence(features, day)
    if manifold_confidence <= 0.0:
        return {"active": False, "reason": "ood", "distance": distance}
    means, deviations = _predict_forest(WINNER_MODEL["forests"]["h72"], features)
    scales = [max(1.0, float(value)) for value in WINNER_MODEL["target_scales"]]
    uncertainty = sum(deviation / scale for deviation, scale in zip(deviations, scales, strict=True)) / len(scales)
    reference = max(0.05, float(WINNER_MODEL["uncertainty_p90"]["h72"]))
    model_confidence = min(1.0, max(0.0, 1.15 - 0.50 * uncertainty / reference))
    confidence = manifold_confidence * model_confidence
    if uncertainty > reference:
        return {
            "active": False,
            "reason": "uncertain",
            "money_gap_ratio": gap_ratio,
            "confidence": confidence,
            "uncertainty": uncertainty,
            "distance": distance,
        }
    if confidence < MIN_CONFIDENCE:
        return {
            "active": False,
            "reason": "low-confidence",
            "money_gap_ratio": gap_ratio,
            "confidence": confidence,
            "uncertainty": uncertainty,
            "distance": distance,
        }
    return {
        "active": True,
        "reason": "active",
        "money_gap_ratio": gap_ratio,
        "confidence": confidence,
        "uncertainty": uncertainty,
        "distance": distance,
        "h72": dict(zip(PORTFOLIO, means, strict=True)),
    }


def _project_targets(
    obs: Any,
    farm: Any,
    private: Any,
    baseline_animals: dict[str, int],
    baseline_crops: dict[str, int],
    prediction: dict[str, Any],
) -> tuple[dict[str, int], dict[str, int]]:
    confidence = float(prediction["confidence"])
    blend = min(MAX_BLEND, 0.15 + 0.20 * confidence)
    goal = prediction["h72"]
    animals = dict(baseline_animals)
    crops = dict(baseline_crops)
    summary = base._farm_summary(farm)
    owned = {animal: v4._owned_animals(farm, private, animal) for animal in ("COW", "SHEEP")}
    # A logged future herd count omits the coupled purchase, pasture, feed, and
    # routing cost. Preserve V11's demand/capital-aware herd controller exactly.

    for crop in CROPS:
        mixed = round((1.0 - blend) * crops[crop] + blend * float(goal[crop]))
        limit = CROP_CHANGE_LIMIT[crop]
        limited = min(crops[crop] + limit, max(crops[crop] - limit, mixed))
        crops[crop] = max(summary["crops"].get(crop, 0), limited)
    feed_floor = math.ceil((animals["COW"] + animals["SHEEP"]) * 1.2)
    crops["WHEAT"] = max(crops["WHEAT"], feed_floor)

    baseline_mass = sum(baseline_animals.values()) + sum(baseline_crops.values())
    floors = {
        **{crop: int(summary["crops"].get(crop, 0)) for crop in CROPS},
        **owned,
    }
    floors["WHEAT"] = max(floors["WHEAT"], feed_floor)
    target = {**crops, "COW": animals["COW"], "SHEEP": animals["SHEEP"]}
    budget = max(baseline_mass, sum(floors.values()))
    demand = base._demand_profile(obs)
    while sum(target.values()) > budget:
        reducible = [item for item in CROPS if target[item] > floors[item]]
        if not reducible:
            break
        item = min(
            reducible,
            key=lambda value: (
                int(demand.get(ITEM_DEMAND[value], 0)),
                int(base.BASE_PRICE[ITEM_DEMAND[value]]),
                -int(target[value] - floors[value]),
                PORTFOLIO.index(value),
            ),
        )
        target[item] -= 1
    if sum(target.values()) < budget:
        target["WHEAT"] += budget - sum(target.values())
    for crop in CROPS:
        crops[crop] = target[crop]
    animals["COW"], animals["SHEEP"] = target["COW"], target["SHEEP"]
    return animals, crops


def _strategy_targets(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
) -> tuple[dict[str, int], dict[str, int], int, int, dict[str, float], int]:
    animals, crops, hands, land, weights, pastures = v11._strategy_targets(obs, farm, opponent_farm, private)
    prediction = _winner_prediction(obs, farm, opponent_farm)
    if not prediction["active"]:
        return animals, crops, hands, land, weights, pastures
    animals, crops = _project_targets(obs, farm, private, animals, crops, prediction)
    pastures = max(v8._pasture_count(farm), animals["COW"] + animals["SHEEP"])
    return animals, crops, hands, land, weights, pastures


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v11.policy_diagnostics(obs))
    safe = base._safe_observation(obs)
    if safe is None:
        return result
    farm, opponent_farm, private = safe
    prediction = _winner_prediction(obs, farm, opponent_farm)
    result["v14_winner_recovery"] = prediction
    targets = _strategy_targets(obs, farm, opponent_farm, private)
    result["v14_future_targets"] = {
        "animals": targets[0],
        "crops": targets[1],
        "productive": sum(targets[0].values()) + sum(targets[1].values()),
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    safe = base._safe_observation(obs)
    if safe is None:
        return {"farmer": ["PASS"], "hands": [], "market": []}
    farm, opponent_farm, private = safe
    opening = v3._safe_opening(obs, farm)
    if opening is not None:
        return copy.deepcopy(opening)
    expert_opening = v8._safe_expert_opening(obs, farm)
    if expert_opening is not None and expert_opening[1]:
        return expert_opening[0]

    summary = base._farm_summary(farm)
    animal_targets, crop_targets, target_hands, target_land, weights, pasture_target = _strategy_targets(
        obs, farm, opponent_farm, private
    )
    positions = [tuple(base._get(farm, "farmer", [0, 0]))]
    positions.extend(tuple(position) for position in (base._get(farm, "hands", []) or []))
    raw_inventories = list(base._get(private, "inventories", []) or [])
    inventories = [raw_inventories[index] if index < len(raw_inventories) else {} for index in range(len(positions))]
    tasks, reserved = v11._field_tasks(
        obs,
        farm,
        private,
        positions,
        inventories,
        summary,
        animal_targets,
        crop_targets,
        pasture_target,
        opponent_farm,
    )
    actions = v9._mission_assign(
        positions,
        inventories,
        tasks,
        base._as_int(
            base._get(
                obs,
                "step",
                base._as_int(base._get(obs, "day", 0)) * 24 + base._as_int(base._get(obs, "hour", 0)),
            )
        ),
    )
    execution_prediction = v8._expert_prediction(obs, farm, opponent_farm, private)
    actions = v10._prefer_local_water(
        obs,
        farm,
        opponent_farm,
        private,
        positions,
        inventories,
        actions,
        execution_prediction,
    )
    actions = v10._preposition_idle_workers(
        obs,
        farm,
        opponent_farm,
        private,
        positions,
        inventories,
        tasks,
        actions,
        execution_prediction,
    )
    market, _recovery = v11._market_plan(
        obs,
        farm,
        opponent_farm,
        private,
        summary,
        animal_targets,
        crop_targets,
        target_hands,
        target_land,
        weights,
        pasture_target,
        actions,
        reserved,
    )
    result = {
        "farmer": actions[0] if actions else ["PASS"],
        "hands": actions[1:],
        "market": market,
    }
    if expert_opening is not None:
        scripted, _copy_market = expert_opening
        result["farmer"] = scripted["farmer"]
        result["hands"] = scripted["hands"]
    return result
