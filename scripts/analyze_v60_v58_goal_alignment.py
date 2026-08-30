"""Measure whether V58 runtime changes move toward all learned daily goals.

V58 currently gates on the predicted same-role transition rate, but the same
winner-only model also predicts animal/crop worker fractions and future state.
This analysis checks those targets together on paired local replays before a
new runtime policy is attempted.
"""

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
from scripts.analyze_v33_asset_labor import _farm  # noqa: E402
from scripts.analyze_v56_daily_roles import _day_row  # noqa: E402
from scripts.train_v12_relative_policy import _observation  # noqa: E402

OUTPUT = ROOT / "data/analysis/v60_v58_goal_alignment.json"
COMPARISONS = {
    "v14_calibration": (
        ROOT / "data/runs/v58_interaction_safe_v14_20265821.json",
        ROOT / "data/runs/v58_interaction_roles_v14_20265821.json",
    ),
    "v14_holdout": (
        ROOT / "data/runs/v58_interaction_safe_v14_holdout_20265831.json",
        ROOT / "data/runs/v58_interaction_roles_v14_holdout_20265831.json",
    ),
    "v18_diagnostic": (
        ROOT / "data/runs/v58_interaction_safe_v18_20265841.json",
        ROOT / "data/runs/v58_interaction_roles_v18_20265841.json",
    ),
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _replay(game: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(game["replay"]))
    if not path.is_absolute():
        path = ROOT / path
    return _load(path)


def _farm_summary(replay: dict[str, Any], step: int, seat: int) -> dict[str, float] | None:
    obs = _observation(replay, step, seat)
    if obs is None:
        return None
    farm = _farm(obs, seat)
    summary = v58.base._farm_summary(farm)
    return {
        "animals": float(summary["animal_total"]),
        "crops": float(sum(summary["crops"].values())),
        "productive": float(summary["productive"]),
    }


def _day_metrics(
    replay: dict[str, Any], game: dict[str, Any], source: str, day: int
) -> dict[str, Any] | None:
    seat = int(game["seat"])
    obs = _observation(replay, day * 24, seat)
    if obs is None:
        return None
    safe = v58.base._safe_observation(obs)
    if safe is None:
        return None
    prediction = v58._predict(obs, safe[0], safe[1])
    if prediction.get("reason") != "active":
        return None
    role = _day_row(
        replay,
        {
            "submission_seat": str(seat),
            "episode_id": f"local-{game['seed']}-{seat}",
            "result": "unknown",
        },
        source,
        day,
    )
    future24 = _farm_summary(replay, (day + 1) * 24, seat)
    future72 = _farm_summary(replay, (day + 3) * 24, seat)
    if role is None or future24 is None:
        return None
    labels = prediction["labels"]
    hands = max(1.0, role["metrics"]["hands_peak"])
    actual = {
        "animal_worker_fraction": role["metrics"]["animal_workers"] / hands,
        "crop_worker_fraction": role["metrics"]["crop_workers"] / hands,
        "productive_per_hand": role["metrics"]["productive_per_hand"],
        "move_per_productive": role["metrics"]["move_per_productive"],
        "pass_per_hand": role["metrics"]["pass_per_hand"],
        "same_role_transition_rate": role["metrics"]["same_role_transition_rate"],
        "future24_productive": future24["productive"],
        "future24_animals": future24["animals"],
    }
    if future72 is not None:
        actual["future72_productive"] = future72["productive"]
        actual["future72_animals"] = future72["animals"]
    metrics: dict[str, Any] = {
        "seed": int(game["seed"]),
        "seat": seat,
        "day": day,
        "nearest_distance": float(prediction["nearest_distance"]),
    }
    for name, value in actual.items():
        target = float(labels[name])
        metrics[f"actual_{name}"] = float(value)
        metrics[f"target_{name}"] = target
        metrics[f"absolute_error_{name}"] = abs(float(value) - target)
    return metrics


def _rows(payload: dict[str, Any], source: str) -> dict[tuple[int, int, int], dict[str, Any]]:
    rows: dict[tuple[int, int, int], dict[str, Any]] = {}
    for game in payload["games"]:
        replay = _replay(game)
        for day in v58.ACTIVE_DAYS:
            metrics = _day_metrics(replay, game, source, day)
            if metrics is not None:
                rows[(int(game["seed"]), int(game["seat"]), day)] = metrics
    return rows


def _mean_metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    keys = sorted(
        {
            key
            for row in rows
            for key, value in row.items()
            if isinstance(value, float)
        }
    )
    return {
        key: mean(row[key] for row in rows if key in row)
        for key in keys
    }


def _comparison(safe_path: Path, candidate_path: Path) -> dict[str, Any]:
    old_enabled = v58.ENABLE_ROLE_CONTINUITY
    v58.ENABLE_ROLE_CONTINUITY = True
    try:
        safe_payload = _load(safe_path)
        candidate_payload = _load(candidate_path)
        safe_rows = _rows(safe_payload, "safe")
        candidate_rows = _rows(candidate_payload, "candidate")
    finally:
        v58.ENABLE_ROLE_CONTINUITY = old_enabled
    common_days = sorted(set(safe_rows) & set(candidate_rows))
    safe_common = [safe_rows[key] for key in common_days]
    candidate_common = [candidate_rows[key] for key in common_days]
    safe_mean = _mean_metrics(safe_common)
    candidate_mean = _mean_metrics(candidate_common)
    common = sorted(set(safe_mean) & set(candidate_mean))
    label_names = [
        name
        for name in v58.MODEL["labels"]
        if all(
            f"actual_{name}" in safe_rows[key]
            and f"actual_{name}" in candidate_rows[key]
            for key in common_days
        )
    ]
    safe_reference_error_delta = {
        name: mean(
            abs(
                float(candidate_rows[key][f"actual_{name}"])
                - float(safe_rows[key][f"target_{name}"])
            )
            - float(safe_rows[key][f"absolute_error_{name}"])
            for key in common_days
        )
        for name in label_names
    }
    return {
        "games": len(safe_payload["games"]),
        "active_episode_days": {
            "safe": len(safe_rows),
            "candidate": len(candidate_rows),
            "matched": len(common_days),
        },
        "safe_mean": safe_mean,
        "candidate_mean": candidate_mean,
        "mean_delta_candidate_minus_safe": {
            key: candidate_mean[key] - safe_mean[key] for key in common
        },
        "safe_reference_absolute_error_delta": safe_reference_error_delta,
        "reward_delta": (
            float(candidate_payload["summary"]["reward"]["mean"])
            - float(safe_payload["summary"]["reward"]["mean"])
        ),
        "margin_delta": (
            float(candidate_payload["summary"]["margin"]["mean"])
            - float(safe_payload["summary"]["margin"]["mean"])
        ),
    }


def main() -> None:
    comparisons = {
        name: _comparison(*paths) for name, paths in COMPARISONS.items()
    }
    payload = {
        "format": "kaggriculture-v60-v58-goal-alignment-v1",
        "runtime_policy_enabled": False,
        "objective": (
            "test whether the V58 continuity tie-break approaches the model's "
            "other held-out-validated role and future-state goals"
        ),
        "comparisons": comparisons,
        "limits": [
            "local opponents are V14 and V18, not hidden leaderboard opponents",
            "each replay is evaluated against the prediction from its own day-start state",
            "observational goal alignment is not a causal rating estimate",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {
        name: {
            "games": value["games"],
            "active_days": value["active_episode_days"],
            "reward_delta": value["reward_delta"],
            "margin_delta": value["margin_delta"],
            "error_delta": {
                key.removeprefix("absolute_error_"): delta
                for key, delta in value["mean_delta_candidate_minus_safe"].items()
                if key.startswith("absolute_error_")
            },
            "safe_reference_error_delta": value[
                "safe_reference_absolute_error_delta"
            ],
        }
        for name, value in comparisons.items()
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))
    print(f"result: {OUTPUT}")


if __name__ == "__main__":
    main()
