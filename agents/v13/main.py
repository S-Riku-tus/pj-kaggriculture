"""Kaggriculture V13: residual relative-value routing on V11's safe executor.

V13 compares V11's macro target with separately retained expert candidates.
An episode-held-out residual critic scores only the value attributable to each
candidate's 24h/72h public portfolio trajectory.  The learned layer cannot
issue worker or market actions.  Low-confidence, uncertain, unsupported, or
weak-improvement states fall back exactly to V11.
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
        Path.cwd() / "agents" / "v13",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (candidate / "v12_base.py").is_file()
            and (candidate / "relative_critic_model.json").is_file()
            or ((candidate / "main.py").is_file() and (candidate.parent / "v12" / "main.py").is_file())
        ),
        Path.cwd(),
    )


def _load_v12_module():
    packaged = MODULE_DIR / "v12_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v12" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v13_safe_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V12/V11 safe core: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v12 = _load_v12_module()
v11 = v12.v11
v10 = v12.v10
v9 = v12.v9
v8 = v12.v8
v4 = v12.v4
v3 = v12.v3
base = v12.base

CROPS = v12.CROPS
ANIMALS = v12.ANIMALS
PORTFOLIO = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "COW", "SHEEP")
ITEM_SCALE = {item: (16.0 if item in {"COW", "SHEEP"} else 50.0) for item in PORTFOLIO}
ACTION_FEATURE_NAMES = (
    *(f"h24_delta_{item}" for item in PORTFOLIO),
    *(f"h72_delta_{item}" for item in PORTFOLIO),
    *(f"h24_target_{item}" for item in PORTFOLIO),
    *(f"h72_target_{item}" for item in PORTFOLIO),
)
CRITIC_FORMAT = "kaggriculture-v13-relative-critic-v1"
TARGET_NAMES = ("relative_delta_24", "relative_delta_72", "final_margin")
UTILITY_WEIGHTS = (0.25, 0.45, 0.30)
MIN_UTILITY_IMPROVEMENT = 0.15
MIN_HORIZON_IMPROVEMENT = (0.0, 0.05, 0.05)

# Rejected by paired closed-loop diagnostics. Keep the artifact and routing
# code reproducible, but release behavior falls back exactly to V11.
ENABLE_RELATIVE_CRITIC = False


def _load_critic() -> dict[str, Any] | None:
    path = MODULE_DIR / "relative_critic_model.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if (
        payload.get("format") != CRITIC_FORMAT
        or not payload.get("enabled")
        or tuple(payload.get("state_feature_names", ())) != tuple(v3.schema.FEATURE_NAMES)
        or tuple(payload.get("action_feature_names", ())) != ACTION_FEATURE_NAMES
        or tuple(payload.get("target_names", ())) != TARGET_NAMES
        or not (payload.get("forests") or {}).get("residual")
    ):
        return None
    return payload


CRITIC = _load_critic()


def _action_features(current: dict[str, float], h24: dict[str, float], h72: dict[str, float]) -> list[float]:
    values: list[float] = []
    values.extend((float(h24[item]) - float(current[item])) / ITEM_SCALE[item] for item in PORTFOLIO)
    values.extend((float(h72[item]) - float(current[item])) / ITEM_SCALE[item] for item in PORTFOLIO)
    values.extend(float(h24[item]) / ITEM_SCALE[item] for item in PORTFOLIO)
    values.extend(float(h72[item]) / ITEM_SCALE[item] for item in PORTFOLIO)
    return values


def _predict_tree(tree: list[Any], features: list[float]) -> list[float]:
    node = tree
    while node[0] == "N":
        node = node[3] if features[int(node[1])] <= float(node[2]) else node[4]
    return [float(value) for value in node[1:]]


def _critic_prediction(features: list[float]) -> tuple[list[float], float]:
    trees = [_predict_tree(tree, features) for tree in CRITIC["forests"]["residual"]]
    means = [sum(values[index] for values in trees) / len(trees) for index in range(len(TARGET_NAMES))]
    deviations = [
        math.sqrt(sum((values[index] - means[index]) ** 2 for values in trees) / len(trees))
        for index in range(len(TARGET_NAMES))
    ]
    return means, sum(deviations) / len(deviations)


def _baseline_profile(animals: dict[str, int], crops: dict[str, int]) -> dict[str, dict[str, float]]:
    target = {
        **{crop: float(crops[crop]) for crop in CROPS},
        "COW": float(animals["COW"]),
        "SHEEP": float(animals["SHEEP"]),
    }
    return {"h24": dict(target), "h72": dict(target)}


def _utility(values: list[float]) -> float:
    return sum(weight * value for weight, value in zip(UTILITY_WEIGHTS, values, strict=True))


def _candidate_decision(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
    baseline: dict[str, dict[str, float]],
) -> dict[str, Any]:
    if not ENABLE_RELATIVE_CRITIC or CRITIC is None:
        return {"active": False, "reason": "disabled-or-missing"}
    anchor = v8._expert_prediction(obs, farm, opponent_farm, private)
    if anchor is None or float(anchor[2]) < 0.35:
        return {"active": False, "reason": "low-atlas-confidence"}
    context = v12._relative_context(obs, farm, opponent_farm)
    candidates = (CRITIC.get("profiles") or {}).get(context["key"])
    if not isinstance(candidates, dict):
        return {"active": False, "reason": "unsupported-branch", "context": context}

    current = v12._public_portfolio(farm)
    uncertainty_limit = float(CRITIC["uncertainty_p90"])
    baseline_values, baseline_uncertainty = _critic_prediction(
        _action_features(current, baseline["h24"], baseline["h72"])
    )
    if baseline_uncertainty > uncertainty_limit:
        return {
            "active": False,
            "reason": "uncertain-baseline",
            "context": context,
            "uncertainty": baseline_uncertainty,
        }

    scored: list[dict[str, Any]] = []
    for expert, candidate in candidates.items():
        profile = candidate["profile"]
        values, uncertainty = _critic_prediction(_action_features(current, profile["h24"], profile["h72"]))
        improvements = [value - baseline_values[index] for index, value in enumerate(values)]
        scored.append(
            {
                "expert": expert,
                "profile": profile,
                "values": values,
                "uncertainty": uncertainty,
                "improvements": improvements,
                "utility_improvement": _utility(values) - _utility(baseline_values),
                "eligible": uncertainty <= uncertainty_limit
                and all(
                    improvement >= required
                    for improvement, required in zip(improvements, MIN_HORIZON_IMPROVEMENT, strict=True)
                ),
            }
        )
    eligible = [row for row in scored if row["eligible"] and row["utility_improvement"] >= MIN_UTILITY_IMPROVEMENT]
    if not eligible:
        return {
            "active": False,
            "reason": "no-value-improvement",
            "context": context,
            "baseline_values": baseline_values,
            "candidates": scored,
        }
    selected = max(eligible, key=lambda row: (row["utility_improvement"], row["expert"]))
    return {
        "active": True,
        "reason": "active",
        "context": context,
        "atlas_confidence": float(anchor[2]),
        "baseline_values": baseline_values,
        "selected": selected,
        "candidates": scored,
    }


def _strategy_targets(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
) -> tuple[dict[str, int], dict[str, int], int, int, dict[str, float], int]:
    animals, crops, hands, land, weights, pastures = v11._strategy_targets(obs, farm, opponent_farm, private)
    baseline_mass = sum(animals.values()) + sum(crops.values())
    decision = _candidate_decision(obs, farm, opponent_farm, private, _baseline_profile(animals, crops))
    if not decision["active"]:
        return animals, crops, hands, land, weights, pastures

    profile = decision["selected"]["profile"]
    desired = {
        item: round(0.70 * float(profile["h24"][item]) + 0.30 * float(profile["h72"][item])) for item in PORTFOLIO
    }
    summary = base._farm_summary(farm)
    owned = {animal: v4._owned_animals(farm, private, animal) for animal in ("COW", "SHEEP")}
    animals["GOOSE"] = 0
    animals["COW"] = max(owned["COW"], desired["COW"])
    animals["SHEEP"] = max(owned["SHEEP"], desired["SHEEP"])
    for crop in CROPS:
        if crop != "WHEAT":
            crops[crop] = max(summary["crops"].get(crop, 0), desired[crop])
    non_wheat = sum(animals.values()) + sum(crops[crop] for crop in CROPS if crop != "WHEAT")
    feed_floor = math.ceil((animals["COW"] + animals["SHEEP"]) * 1.2)
    crops["WHEAT"] = max(feed_floor, baseline_mass - non_wheat)
    pastures = max(v8._pasture_count(farm), animals["COW"] + animals["SHEEP"])
    return animals, crops, hands, land, weights, pastures


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v11.policy_diagnostics(obs))
    safe = base._safe_observation(obs)
    if safe is None:
        return result
    farm, opponent_farm, private = safe
    animals, crops, *_rest = v11._strategy_targets(obs, farm, opponent_farm, private)
    result["v13_relative_critic"] = _candidate_decision(
        obs,
        farm,
        opponent_farm,
        private,
        _baseline_profile(animals, crops),
    )
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
        obs, farm, opponent_farm, private, positions, inventories, actions, execution_prediction
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
    result = {"farmer": actions[0] if actions else ["PASS"], "hands": actions[1:], "market": market}
    if expert_opening is not None:
        scripted, _copy_market = expert_opening
        result["farmer"] = scripted["farmer"]
        result["hands"] = scripted["hands"]
    return result
