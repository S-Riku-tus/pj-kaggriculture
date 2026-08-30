"""Extend V57 teacher goals with opponent and relative 24h/72h states."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import train_v57_role_portfolio as trainer  # noqa: E402

FORMAT = "kaggriculture-v65-relative-role-validation-v1"
MODEL_FORMAT = "kaggriculture-v65-relative-role-knn-v1"
RELATIVE_LABELS = (
    "future24_opponent_productive",
    "future72_opponent_productive",
    "future24_productive_gap",
    "future72_productive_gap",
    "future24_opponent_animals",
    "future72_opponent_animals",
    "future24_money_gap_ratio",
    "future72_money_gap_ratio",
)
LABELS = (*trainer.LABELS, *RELATIVE_LABELS)


def _future_summary(
    replay: dict[str, Any], seat: int, day: int
) -> dict[str, float]:
    obs = trainer._observation(replay, min(719, day * 24), seat)
    if obs is None:
        return {
            "own_productive": 0.0,
            "own_animals": 0.0,
            "opponent_productive": 0.0,
            "opponent_animals": 0.0,
            "productive_gap": 0.0,
            "money_gap_ratio": 0.0,
        }
    farms = obs.get("farms") or []
    if len(farms) < 2:
        return {
            "own_productive": 0.0,
            "own_animals": 0.0,
            "opponent_productive": 0.0,
            "opponent_animals": 0.0,
            "productive_gap": 0.0,
            "money_gap_ratio": 0.0,
        }
    own = trainer.v14.base._farm_summary(farms[seat])
    opponent = trainer.v14.base._farm_summary(farms[1 - seat])
    own_money = float(farms[seat].get("money", 0) or 0)
    opponent_money = float(farms[1 - seat].get("money", 0) or 0)
    return {
        "own_productive": float(own["productive"]),
        "own_animals": float(own["animal_total"]),
        "opponent_productive": float(opponent["productive"]),
        "opponent_animals": float(opponent["animal_total"]),
        "productive_gap": float(own["productive"] - opponent["productive"]),
        "money_gap_ratio": (own_money - opponent_money)
        / max(1.0, own_money + opponent_money),
    }


def _row(
    replay: dict[str, Any], manifest: dict[str, str], source: str, day: int
) -> dict[str, Any] | None:
    seat = int(manifest["submission_seat"])
    obs = trainer._observation(replay, day * 24, seat)
    role = trainer._day_row(replay, manifest, source, day)
    if obs is None or role is None:
        return None
    hands = max(1.0, role["metrics"]["hands_peak"])
    future24 = _future_summary(replay, seat, day + 1)
    future72 = _future_summary(replay, seat, day + 3)
    labels = {
        "animal_worker_fraction": role["metrics"]["animal_workers"] / hands,
        "crop_worker_fraction": role["metrics"]["crop_workers"] / hands,
        "logistics_worker_fraction": role["metrics"]["logistics_workers"] / hands,
        "productive_per_hand": role["metrics"]["productive_per_hand"],
        "move_per_productive": role["metrics"]["move_per_productive"],
        "pass_per_hand": role["metrics"]["pass_per_hand"],
        "same_role_transition_rate": role["metrics"]["same_role_transition_rate"],
        "future24_productive": future24["own_productive"],
        "future72_productive": future72["own_productive"],
        "future24_animals": future24["own_animals"],
        "future72_animals": future72["own_animals"],
        "future24_opponent_productive": future24["opponent_productive"],
        "future72_opponent_productive": future72["opponent_productive"],
        "future24_productive_gap": future24["productive_gap"],
        "future72_productive_gap": future72["productive_gap"],
        "future24_opponent_animals": future24["opponent_animals"],
        "future72_opponent_animals": future72["opponent_animals"],
        "future24_money_gap_ratio": future24["money_gap_ratio"],
        "future72_money_gap_ratio": future72["money_gap_ratio"],
    }
    return {
        "source": source,
        "episode_id": str(manifest["episode_id"]),
        "split": trainer._split(str(manifest["episode_id"])),
        "day": day,
        "features": trainer._context(obs, seat),
        "labels": labels,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--neighbors", type=int, default=15)
    parser.add_argument(
        "--days",
        default="6,7,8,9,10,11,12",
        help="comma-separated days included in training and evaluation",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v65_relative_role_validation.json"),
    )
    parser.add_argument(
        "--model-output",
        type=Path,
        default=Path("agents/v65/relative_role_model.json"),
    )
    args = parser.parse_args()

    days = tuple(sorted({int(value) for value in args.days.split(",") if value.strip()}))
    if not days or any(day < 0 or day > 29 for day in days):
        parser.error("--days must contain game days in [0, 29]")

    trainer.FORMAT = FORMAT
    trainer.MODEL_FORMAT = MODEL_FORMAT
    trainer.LABELS = LABELS
    trainer.DAYS = days
    trainer._row = _row
    old_argv = sys.argv
    sys.argv = [
        old_argv[0],
        "--neighbors",
        str(args.neighbors),
        "--output",
        str(args.output),
        "--model-output",
        str(args.model_output),
    ]
    try:
        trainer.main()
    finally:
        sys.argv = old_argv


if __name__ == "__main__":
    main()
