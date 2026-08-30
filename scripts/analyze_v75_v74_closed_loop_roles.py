"""Recompute V74 and safe role metrics on the same day-20/24 interval."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_v56_daily_roles import _day_row  # noqa: E402

DAYS = tuple(range(20, 25))
OUTPUT = ROOT / "data/analysis/v75_v74_closed_loop_roles.json"
COMPARISONS = {
    "calibration": (
        ROOT / "data/runs/v58_interaction_safe_v14_20265821.json",
        ROOT / "data/runs/v74_core_late_v14_calibration_20265821.json",
    ),
    "holdout": (
        ROOT / "data/runs/v58_interaction_safe_v14_holdout_20265831.json",
        ROOT / "data/runs/v74_core_late_v14_holdout_20265831.json",
    ),
}
METRICS = (
    "productive_per_hand",
    "productive_p10_hand",
    "move_per_productive",
    "pass_per_hand",
    "same_role_transition_rate",
    "productive_transition_distance",
    "animal_workers",
    "crop_workers",
    "logistics_workers",
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(payload: dict[str, Any], source: str) -> list[dict[str, Any]]:
    rows = []
    for game in payload["games"]:
        path = Path(str(game["replay"]))
        if not path.is_absolute():
            path = ROOT / path
        replay = _load(path)
        for day in DAYS:
            row = _day_row(
                replay,
                {
                    "submission_seat": str(game["seat"]),
                    "episode_id": f"local-{game['seed']}-{game['seat']}",
                    "result": "unknown",
                },
                source,
                day,
            )
            if row is not None:
                rows.append(row)
    return rows


def _means(rows: list[dict[str, Any]]) -> dict[str, float]:
    return {
        metric: mean(float(row["metrics"][metric]) for row in rows)
        for metric in METRICS
    }


def _comparison(safe_path: Path, candidate_path: Path) -> dict[str, Any]:
    safe_payload = _load(safe_path)
    candidate_payload = _load(candidate_path)
    safe_rows = _rows(safe_payload, "safe")
    candidate_rows = _rows(candidate_payload, "candidate")
    safe_mean = _means(safe_rows)
    candidate_mean = _means(candidate_rows)
    return {
        "games": len(safe_payload["games"]),
        "episode_days": {"safe": len(safe_rows), "candidate": len(candidate_rows)},
        "safe_mean": safe_mean,
        "candidate_mean": candidate_mean,
        "delta": {
            metric: candidate_mean[metric] - safe_mean[metric]
            for metric in METRICS
        },
        "reward_delta": float(candidate_payload["summary"]["reward"]["mean"])
        - float(safe_payload["summary"]["reward"]["mean"]),
        "margin_delta": float(candidate_payload["summary"]["margin"]["mean"])
        - float(safe_payload["summary"]["margin"]["mean"]),
    }


def main() -> None:
    comparisons = {
        name: _comparison(*paths) for name, paths in COMPARISONS.items()
    }
    payload = {
        "format": "kaggriculture-v75-v74-closed-loop-roles-v1",
        "runtime_policy_enabled": False,
        "days": list(DAYS),
        "comparisons": comparisons,
        "interpretation_limit": (
            "role metrics are downstream closed-loop outcomes, not isolated mediator effects"
        ),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(comparisons, ensure_ascii=False, indent=2))
    print(f"result: {OUTPUT}")


if __name__ == "__main__":
    main()
