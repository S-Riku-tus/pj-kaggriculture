"""Kaggriculture V102: narrow V14 recovery goals above V11's safe core.

V11 is the default policy.  V14's bounded 72-hour crop projection is admitted
only in episode-held-out-supported recovery phases with a material target
change, a visible cash deficit, high manifold confidence, and low forest
disagreement.  V11/V14 retain deterministic feasibility and execution.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from statistics import mean
from typing import Any

if "__file__" in globals():
    MODULE_DIR = Path(__file__).resolve().parent
else:
    _runtime_candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd() / "agents" / "v102",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (
                (candidate / "v14_base.py").is_file()
                and (candidate / "winner_goal_model.json").is_file()
                and (candidate / "strategy_model.json").is_file()
            )
            or ((candidate / "main.py").is_file() and (candidate.parent / "v14" / "main.py").is_file())
        ),
        Path.cwd(),
    )


def _load_v14_module():
    packaged = MODULE_DIR / "v14_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v14" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v102_v14_candidate", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V14 candidate: {source}")
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

ENABLE_RECOVERY_META_GATE = True
ELIGIBLE_PHASES = frozenset({"10-11", "14-17"})
MIN_CONFIDENCE = 0.65
MAX_UNCERTAINTY_RATIO = 0.80
MIN_NORMALIZED_CHANGE = 0.02
MAX_MONEY_GAP_RATIO = -0.05

_SAFE_STRATEGY_TARGETS = v14.v11._strategy_targets


def _target_change(
    baseline_animals: dict[str, int],
    baseline_crops: dict[str, int],
    candidate_animals: dict[str, int],
    candidate_crops: dict[str, int],
) -> float:
    baseline = {**baseline_crops, "COW": baseline_animals["COW"], "SHEEP": baseline_animals["SHEEP"]}
    candidate = {
        **candidate_crops,
        "COW": candidate_animals["COW"],
        "SHEEP": candidate_animals["SHEEP"],
    }
    scales = [float(value) for value in v14.WINNER_MODEL["target_scales"]]
    return mean(
        abs(float(candidate[item]) - float(baseline[item])) / scales[index]
        for index, item in enumerate(v14.PORTFOLIO)
    )


def _gate_decision(obs: Any, farm: Any, opponent_farm: Any, private: Any) -> dict[str, Any]:
    baseline = _SAFE_STRATEGY_TARGETS(obs, farm, opponent_farm, private)
    result: dict[str, Any] = {
        "active": False,
        "changed": False,
        "reason": "disabled" if not ENABLE_RECOVERY_META_GATE else "v14-inactive",
        "baseline": baseline,
    }
    if not ENABLE_RECOVERY_META_GATE:
        return result
    prediction = v14._winner_prediction(obs, farm, opponent_farm)
    result["prediction"] = prediction
    if not prediction.get("active"):
        result["reason"] = f"v14-{prediction.get('reason', 'inactive')}"
        return result

    candidate_animals, candidate_crops = v14._project_targets(
        obs, farm, private, baseline[0], baseline[1], prediction
    )
    change = _target_change(baseline[0], baseline[1], candidate_animals, candidate_crops)
    uncertainty_reference = max(
        0.05, float(v14.WINNER_MODEL["uncertainty_p90"]["h72"])
    )
    uncertainty_ratio = float(prediction["uncertainty"]) / uncertainty_reference
    phase = v14._phase(base._as_int(base._get(obs, "day", 0)))
    result.update(
        {
            "phase": phase,
            "confidence": float(prediction["confidence"]),
            "uncertainty_ratio": uncertainty_ratio,
            "normalized_change": change,
            "candidate_animals": candidate_animals,
            "candidate_crops": candidate_crops,
        }
    )
    checks = (
        (phase in ELIGIBLE_PHASES, "unsupported-phase"),
        (float(prediction["confidence"]) >= MIN_CONFIDENCE, "confidence-low"),
        (uncertainty_ratio <= MAX_UNCERTAINTY_RATIO, "uncertainty-high"),
        (change >= MIN_NORMALIZED_CHANGE, "change-too-small"),
        (
            float(prediction["money_gap_ratio"]) <= MAX_MONEY_GAP_RATIO,
            "deficit-too-small",
        ),
    )
    for passed, reason in checks:
        if not passed:
            result["reason"] = reason
            return result
    result.update({"active": True, "changed": candidate_crops != baseline[1], "reason": "active"})
    return result


def _strategy_targets(
    obs: Any, farm: Any, opponent_farm: Any, private: Any
) -> tuple[dict[str, int], dict[str, int], int, int, dict[str, float], int]:
    decision = _gate_decision(obs, farm, opponent_farm, private)
    baseline = decision["baseline"]
    if not decision.get("active"):
        return baseline
    animals = dict(decision["candidate_animals"])
    crops = dict(decision["candidate_crops"])
    pastures = max(v8._pasture_count(farm), animals["COW"] + animals["SHEEP"])
    return animals, crops, baseline[2], baseline[3], baseline[4], pastures


v14._strategy_targets = _strategy_targets


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v11.policy_diagnostics(obs))
    safe = base._safe_observation(obs)
    if safe is None:
        return result
    farm, opponent_farm, private = safe
    decision = _gate_decision(obs, farm, opponent_farm, private)
    baseline = decision.pop("baseline")
    result["v102_recovery_meta_gate"] = decision
    selected = _strategy_targets(obs, farm, opponent_farm, private)
    result["v102_future_targets"] = {
        "safe_animals": baseline[0],
        "safe_crops": baseline[1],
        "selected_animals": selected[0],
        "selected_crops": selected[1],
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v14.agent(obs)
