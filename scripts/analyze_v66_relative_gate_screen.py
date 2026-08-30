"""Screen principled relative-state gates before a new closed-loop run."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v58 import main as v58  # noqa: E402
from scripts.train_v12_relative_policy import _observation  # noqa: E402

MODEL = ROOT / "agents/v65/relative_role_model.json"
OUTPUT = ROOT / "data/analysis/v66_relative_gate_screen.json"
COMPARISONS = {
    "v14_calibration": (
        ROOT / "data/runs/v58_interaction_safe_v14_20265821.json",
        ROOT / "data/runs/v62_phase_late_v14_20265821.json",
    ),
    "v14_holdout": (
        ROOT / "data/runs/v58_interaction_safe_v14_holdout_20265831.json",
        ROOT / "data/runs/v63_phase_late_v14_holdout_20265831.json",
    ),
    "v18_diagnostic": (
        ROOT / "data/runs/v58_interaction_safe_v18_20265841.json",
        ROOT / "data/runs/v63_phase_late_v18_20265841.json",
    ),
    "v18_holdout": (
        ROOT / "data/runs/v63_safe_v18_holdout_20265851.json",
        ROOT / "data/runs/v63_phase_late_v18_holdout_20265851.json",
    ),
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _replay(game: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(game["replay"]))
    if not path.is_absolute():
        path = ROOT / path
    return _load(path)


def _prediction(replay: dict[str, Any], game: dict[str, Any], day: int) -> dict[str, Any]:
    obs = _observation(replay, day * 24, int(game["seat"]))
    if obs is None:
        return {"day": day, "active": False, "reason": "missing-observation"}
    safe = v58.base._safe_observation(obs)
    if safe is None:
        return {"day": day, "active": False, "reason": "invalid-observation"}
    result = dict(v58._predict(obs, safe[0], safe[1]))
    result["day"] = day
    if not result.get("active"):
        return result
    context = v58._context(obs, safe[0], safe[1])
    labels = result["labels"]
    current_productive_gap = (
        context["own_productive"] - context["opponent_productive"]
    )
    money_improvement = (
        float(labels["future72_money_gap_ratio"]) - context["money_gap_ratio"]
    )
    productive_improvement = (
        float(labels["future72_productive_gap"]) - current_productive_gap
    )
    result.update(
        {
            "current_money_gap_ratio": context["money_gap_ratio"],
            "future72_money_gap_ratio": float(labels["future72_money_gap_ratio"]),
            "money_gap_improvement": money_improvement,
            "current_productive_gap": current_productive_gap,
            "future72_productive_gap": float(labels["future72_productive_gap"]),
            "productive_gap_improvement": productive_improvement,
            "gates": {
                "money_nondecline": money_improvement >= 0.0,
                "productive_nondecline": productive_improvement >= 0.0,
                "both_nondecline": money_improvement >= 0.0
                and productive_improvement >= 0.0,
                "future_money_lead": float(labels["future72_money_gap_ratio"]) >= 0.0,
            },
        }
    )
    return result


def _comparison(safe_path: Path, candidate_path: Path) -> dict[str, Any]:
    safe = _load(safe_path)
    candidate = _load(candidate_path)
    safe_games = {(int(g["seed"]), int(g["seat"])): g for g in safe["games"]}
    candidate_games = {
        (int(g["seed"]), int(g["seat"])): g for g in candidate["games"]
    }
    if set(safe_games) != set(candidate_games):
        raise ValueError("paired games do not match")
    rows = []
    for key in sorted(safe_games):
        safe_game = safe_games[key]
        candidate_game = candidate_games[key]
        replay = _replay(safe_game)
        predictions = [_prediction(replay, safe_game, day) for day in (11, 12)]
        gate_names = (
            "money_nondecline",
            "productive_nondecline",
            "both_nondecline",
            "future_money_lead",
        )
        rows.append(
            {
                "seed": key[0],
                "seat": key[1],
                "reward_delta": float(candidate_game["ours"])
                - float(safe_game["ours"]),
                "opponent_reward_delta": float(candidate_game["theirs"])
                - float(safe_game["theirs"]),
                "margin_delta": float(candidate_game["margin"])
                - float(safe_game["margin"]),
                "predictions": predictions,
                "game_gate_eligible": {
                    gate: any(
                        prediction.get("active")
                        and prediction.get("gates", {}).get(gate, False)
                        for prediction in predictions
                    )
                    for gate in gate_names
                },
            }
        )
    gates = tuple(rows[0]["game_gate_eligible"])
    gate_summary = {}
    for gate in gates:
        eligible = [row for row in rows if row["game_gate_eligible"][gate]]
        gate_summary[gate] = {
            "eligible_games": len(eligible),
            "observed_v63_reward_delta_mean": mean(
                row["reward_delta"] for row in eligible
            )
            if eligible
            else 0.0,
            "observed_v63_margin_delta_mean": mean(
                row["margin_delta"] for row in eligible
            )
            if eligible
            else 0.0,
            "warning": "descriptive screen only; a gated rerun has different trajectories",
        }
    return {"games": len(rows), "gate_summary": gate_summary, "rows": rows}


def main() -> None:
    old_model = v58.MODEL
    old_format = v58.MODEL_FORMAT
    old_enabled = v58.ENABLE_ROLE_CONTINUITY
    old_days = v58.ACTIVE_DAYS
    try:
        v58.MODEL = _load(MODEL)
        v58.MODEL_FORMAT = str(v58.MODEL["format"])
        v58.ENABLE_ROLE_CONTINUITY = True
        v58.ACTIVE_DAYS = (11, 12)
        comparisons = {
            name: _comparison(*paths) for name, paths in COMPARISONS.items()
        }
    finally:
        v58.MODEL = old_model
        v58.MODEL_FORMAT = old_format
        v58.ENABLE_ROLE_CONTINUITY = old_enabled
        v58.ACTIVE_DAYS = old_days
    payload = {
        "format": "kaggriculture-v66-relative-gate-screen-v1",
        "runtime_policy_enabled": False,
        "objective": "screen relative 72h teacher goals before closed-loop gating",
        "model": str(MODEL.relative_to(ROOT)),
        "comparisons": comparisons,
        "limits": [
            "eligibility is computed on safe-core trajectories",
            "observed V63 deltas are not counterfactual gated-policy estimates",
            "gates were defined from the relative-score objective before inspecting this output",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                name: comparison["gate_summary"]
                for name, comparison in comparisons.items()
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"result: {OUTPUT}")


if __name__ == "__main__":
    main()
