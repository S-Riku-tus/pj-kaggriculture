"""Screen V72 day-20/24 role and relative-money gates on safe trajectories."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v58 import main as v58  # noqa: E402
from scripts.train_v12_relative_policy import _observation  # noqa: E402

MODEL = ROOT / "agents/v72/core_late_relative_role_model.json"
OUTPUT = ROOT / "data/analysis/v73_core_late_gate_screen.json"
ACTIVE_DAYS = tuple(range(20, 25))
MAX_PREDICTED_MONEY_GAP_DECLINE = 0.089
GROUPS = {
    "v14_calibration": ROOT / "data/runs/v58_interaction_safe_v14_20265821.json",
    "v14_holdout": ROOT / "data/runs/v58_interaction_safe_v14_holdout_20265831.json",
    "v18_diagnostic": ROOT / "data/runs/v58_interaction_safe_v18_20265841.json",
    "v18_holdout": ROOT / "data/runs/v63_safe_v18_holdout_20265851.json",
    "v11_diagnostic": ROOT / "data/runs/v68_safe_v11_diagnostic_20266801.json",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _replay(game: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(game["replay"]))
    if not path.is_absolute():
        path = ROOT / path
    return _load(path)


def _group(path: Path) -> dict[str, Any]:
    payload = _load(path)
    rows = []
    for game in payload["games"]:
        replay = _replay(game)
        for day in ACTIVE_DAYS:
            obs = _observation(replay, day * 24, int(game["seat"]))
            if obs is None:
                continue
            safe = v58.base._safe_observation(obs)
            if safe is None:
                continue
            prediction = v58._predict(obs, safe[0], safe[1])
            context = v58._context(obs, safe[0], safe[1])
            labels = prediction.get("labels") or {}
            improvement = (
                float(labels["future72_money_gap_ratio"])
                - float(context["money_gap_ratio"])
                if prediction.get("active")
                else None
            )
            relative_allowed = (
                improvement is not None
                and improvement >= -MAX_PREDICTED_MONEY_GAP_DECLINE
            )
            rows.append(
                {
                    "seed": int(game["seed"]),
                    "seat": int(game["seat"]),
                    "day": day,
                    "role_active": bool(prediction.get("active")),
                    "reason": str(prediction.get("reason")),
                    "nearest_distance": prediction.get("nearest_distance"),
                    "same_role_target": labels.get("same_role_transition_rate"),
                    "money_gap_improvement": improvement,
                    "relative_allowed": relative_allowed,
                    "final_active": bool(prediction.get("active"))
                    and relative_allowed,
                }
            )
    by_game: Counter[tuple[int, int]] = Counter()
    for row in rows:
        if row["final_active"]:
            by_game[(row["seed"], row["seat"])] += 1
    active_rows = [row for row in rows if row["final_active"]]
    return {
        "games": len(payload["games"]),
        "episode_days": len(rows),
        "reason_counts": dict(Counter(row["reason"] for row in rows)),
        "role_active_days": sum(row["role_active"] for row in rows),
        "relative_allowed_days": len(active_rows),
        "games_with_intervention": len(by_game),
        "mean_active_days_per_affected_game": mean(by_game.values()) if by_game else 0.0,
        "money_gap_improvement_on_active": {
            "minimum": min(
                (float(row["money_gap_improvement"]) for row in active_rows),
                default=0.0,
            ),
            "mean": mean(
                float(row["money_gap_improvement"]) for row in active_rows
            )
            if active_rows
            else 0.0,
        },
        "rows": rows,
    }


def main() -> None:
    old_model = v58.MODEL
    old_format = v58.MODEL_FORMAT
    old_enabled = v58.ENABLE_ROLE_CONTINUITY
    old_days = v58.ACTIVE_DAYS
    try:
        v58.MODEL = _load(MODEL)
        v58.MODEL_FORMAT = str(v58.MODEL["format"])
        v58.ENABLE_ROLE_CONTINUITY = True
        v58.ACTIVE_DAYS = ACTIVE_DAYS
        groups = {name: _group(path) for name, path in GROUPS.items()}
    finally:
        v58.MODEL = old_model
        v58.MODEL_FORMAT = old_format
        v58.ENABLE_ROLE_CONTINUITY = old_enabled
        v58.ACTIVE_DAYS = old_days
    payload = {
        "format": "kaggriculture-v73-core-late-gate-screen-v1",
        "runtime_policy_enabled": False,
        "model": str(MODEL.relative_to(ROOT)),
        "active_days": list(ACTIVE_DAYS),
        "maximum_predicted_money_gap_decline": MAX_PREDICTED_MONEY_GAP_DECLINE,
        "groups": groups,
        "limits": [
            "screen uses safe-core trajectories and does not estimate closed-loop reward",
            "the tolerance is two times the worse held-out raw MAE, rounded upward",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                name: {
                    key: value[key]
                    for key in (
                        "games",
                        "episode_days",
                        "reason_counts",
                        "role_active_days",
                        "relative_allowed_days",
                        "games_with_intervention",
                        "mean_active_days_per_affected_game",
                        "money_gap_improvement_on_active",
                    )
                }
                for name, value in groups.items()
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"result: {OUTPUT}")


if __name__ == "__main__":
    main()
