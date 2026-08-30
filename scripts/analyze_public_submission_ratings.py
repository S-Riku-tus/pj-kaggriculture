"""Compare public submission rating trajectories and score tails."""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Iterable
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/submissions"
OUTPUT = ROOT / "data/analysis/v10_v11_v14_public_rating.json"
SUBMISSIONS = (
    ("v10", 55786256),
    ("v11", 55787906),
    ("v14", 55815097),
)


def _quantile(values: Iterable[float], probability: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * probability
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    fraction = position - low
    return ordered[low] * (1.0 - fraction) + ordered[high] * fraction


def _summary(values: list[float]) -> dict[str, float | None]:
    return {
        "mean": round(mean(values), 3) if values else None,
        "median": round(median(values), 3) if values else None,
        "p10": round(float(_quantile(values, 0.10)), 3) if values else None,
        "p25": round(float(_quantile(values, 0.25)), 3) if values else None,
        "p75": round(float(_quantile(values, 0.75)), 3) if values else None,
        "p90": round(float(_quantile(values, 0.90)), 3) if values else None,
        "minimum": round(min(values), 3) if values else None,
        "maximum": round(max(values), 3) if values else None,
    }


def _optional_float(value: str) -> float | None:
    return float(value) if value != "" else None


def _result_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    results = [str(row["result"]) for row in rows]
    margins = [float(row["margin"]) for row in rows]
    own_rewards = [float(row["own_reward"]) for row in rows]
    return {
        "episodes": len(rows),
        "wins": results.count("win"),
        "losses": results.count("loss"),
        "draws": results.count("draw"),
        "win_rate": round(results.count("win") / len(rows), 5) if rows else None,
        "own_reward": _summary(own_rewards),
        "margin": _summary(margins),
    }


def _load(version: str, submission_id: int) -> dict[str, Any]:
    directory = DATA / f"{version}_submission_{submission_id}"
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    with (directory / "episodes.csv").open(encoding="utf-8-sig", newline="") as handle:
        episode_rows = list(csv.DictReader(handle))
    with (directory / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        manifest = {row["episode_id"]: row for row in csv.DictReader(handle)}

    rows: list[dict[str, Any]] = []
    for episode in episode_rows:
        episode_id = episode["episode_id"]
        local = manifest[episode_id]
        own_seat = 0 if int(episode["agent_0_submission_id"]) == submission_id else 1
        opponent_seat = 1 - own_seat
        own_initial = _optional_float(episode[f"agent_{own_seat}_initial_score"])
        own_updated = _optional_float(episode[f"agent_{own_seat}_updated_score"])
        opponent_initial = _optional_float(episode[f"agent_{opponent_seat}_initial_score"])
        own_reward = float(local["own_reward"])
        opponent_reward = float(local["opponent_reward"])
        rows.append(
            {
                "episode_id": int(episode_id),
                "create_time": episode["create_time"],
                "seat": own_seat,
                "result": local["result"],
                "own_reward": own_reward,
                "opponent_reward": opponent_reward,
                "margin": own_reward - opponent_reward,
                "own_initial_rating": own_initial,
                "own_updated_rating": own_updated,
                "rating_change": (
                    own_updated - own_initial
                    if own_updated is not None and own_initial is not None
                    else None
                ),
                "opponent_initial_rating": opponent_initial,
                "opponent_submission_id": int(episode[f"agent_{opponent_seat}_submission_id"]),
            }
        )
    rows.sort(key=lambda row: (row["create_time"], row["episode_id"]))
    if not rows:
        raise RuntimeError(f"no episodes for {version}")

    thirds: list[dict[str, Any]] = []
    for index in range(3):
        start = len(rows) * index // 3
        end = len(rows) * (index + 1) // 3
        local = rows[start:end]
        thirds.append(
            {
                "third": index + 1,
                **_result_summary(local),
                "own_initial_rating": _summary(
                    [
                        float(row["own_initial_rating"])
                        for row in local
                        if row["own_initial_rating"] is not None
                    ]
                ),
                "opponent_initial_rating": _summary(
                    [
                        float(row["opponent_initial_rating"])
                        for row in local
                        if row["opponent_initial_rating"] is not None
                    ]
                ),
            }
        )

    rated_rows = [
        row
        for row in rows
        if row["own_initial_rating"] is not None and row["own_updated_rating"] is not None
    ]
    updated_ratings = [float(row["own_updated_rating"]) for row in rows if row["own_updated_rating"] is not None]
    return {
        "version": version,
        "submission_id": submission_id,
        "reported_rating": metadata["reported_rating"],
        "episodes_with_complete_rating_fields": len(rated_rows),
        "period": {"start": rows[0]["create_time"], "end": rows[-1]["create_time"]},
        "rating": {
            "initial": round(float(rated_rows[0]["own_initial_rating"]), 3),
            "final": round(float(rated_rows[-1]["own_updated_rating"]), 3),
            "change": round(
                float(
                    rated_rows[-1]["own_updated_rating"]
                    - rated_rows[0]["own_initial_rating"]
                ),
                3,
            ),
            "updated_minimum": round(min(updated_ratings), 3),
            "updated_maximum": round(max(updated_ratings), 3),
        },
        "overall": _result_summary(rows),
        "opponent_initial_rating": _summary(
            [
                float(row["opponent_initial_rating"])
                for row in rows
                if row["opponent_initial_rating"] is not None
            ]
        ),
        "rating_change": _summary(
            [float(row["rating_change"]) for row in rows if row["rating_change"] is not None]
        ),
        "by_seat": {
            str(seat): _result_summary([row for row in rows if row["seat"] == seat])
            for seat in (0, 1)
        },
        "chronological_thirds": thirds,
        "rows": rows,
    }


def main() -> None:
    reports = [_load(version, submission_id) for version, submission_id in SUBMISSIONS]
    result = {
        "format": "kaggriculture-public-submission-rating-comparison-v1",
        "limits": [
            "ratings are observed at different times and opponent pools",
            "public win rate is not adjusted for opponent strength",
            "54 V14 episodes are evidence of live performance, not proof of future rating",
        ],
        "submissions": reports,
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = [
        {
            "version": report["version"],
            "rating": report["rating"],
            "episodes": report["overall"]["episodes"],
            "win_rate": report["overall"]["win_rate"],
            "margin": report["overall"]["margin"],
            "opponent_rating": report["opponent_initial_rating"],
        }
        for report in reports
    ]
    print(json.dumps(compact, ensure_ascii=False, indent=2))
    print(f"result: {OUTPUT}")


if __name__ == "__main__":
    main()
