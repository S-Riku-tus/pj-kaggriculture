"""Measure late farm service capacity, backlog, and future state.

This report follows the V78 observation that V11 owns at least as many late
productive assets as the Top-3, but performs fewer productive actions per
asset.  It does not assume that more actions are intrinsically better.  It
checks whether the lower density coincides with missed service, worker-turn
pressure, or weaker 24/72-hour states, keeping sources and episode splits
separate.
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_v21_workforce_gap import (  # noqa: E402
    SOURCES,
    _day_row,
    _farm,
)
from scripts.analyze_v78_late_action_density import _asset_counts  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    _manifest,
    _observation,
    _replay_path,
    _split,
)

OUTPUT = ROOT / "data/analysis/v79_late_capacity_backlog.json"
DAYS = tuple(range(20, 25))
CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
METRICS = (
    "start_money",
    "money_h24",
    "money_h72",
    "productive_start",
    "productive_h24",
    "productive_h72",
    "worker_turns",
    "all_productive",
    "productive_per_worker_turn",
    "water",
    "water_per_crop",
    "harvest",
    "plant",
    "service",
    "pickup_drop_place",
    "hand_productive_rate",
    "hand_move_rate",
    "hand_pass_rate",
    "missed_water_next_day",
    "missed_water_rate_next_day",
    "missed_feed_next_day",
    "missed_feed_rate_next_day",
    "weeds_next_day",
    "reward",
    "margin",
)


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = probability * (len(ordered) - 1)
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "median": 0.0, "p10": 0.0, "p90": 0.0}
    return {
        "mean": mean(values),
        "median": median(values),
        "p10": _percentile(values, 0.10),
        "p90": _percentile(values, 0.90),
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"episode_days": 0}
    return {
        "episode_days": len(rows),
        **{
            metric: _stats([float(row[metric]) for row in rows])
            for metric in METRICS
        },
        "missed_water_by_crop": {
            crop: _stats(
                [float(row[f"missed_water_{crop.lower()}_next_day"]) for row in rows]
            )
            for crop in CROPS
        },
    }


def _enrich(row: dict[str, Any], replay: dict[str, Any], seat: int) -> None:
    start_obs = _observation(replay, int(row["day"]) * 24, seat)
    start_farm = _farm(start_obs, seat)
    crops, animals = _asset_counts(start_farm)
    crop_count = float(sum(crops.values()))
    animal_count = float(sum(animals.values()))
    worker_turns = max(1.0, float(row["worker_turns"]))
    row.update(
        {
            "crop_count": crop_count,
            "animal_count": animal_count,
            "productive_per_worker_turn": float(row["all_productive"])
            / worker_turns,
            "water_per_crop": float(row["water"]) / max(1.0, crop_count),
            "missed_water_rate_next_day": float(row["missed_water_next_day"])
            / max(1.0, crop_count),
            "missed_feed_rate_next_day": float(row["missed_feed_next_day"])
            / max(1.0, animal_count),
        }
    )


def main() -> None:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    skipped: Counter[str] = Counter()
    source_sides: Counter[str] = Counter()
    split_episodes: dict[str, set[str]] = defaultdict(set)
    for source, directory in SOURCES.items():
        manifests = _manifest(directory)
        for index, manifest in enumerate(manifests, start=1):
            if index == 1 or index % 50 == 0:
                print(f"[{source} {index}/{len(manifests)}]", flush=True)
            episode_id = str(manifest["episode_id"])
            seat = int(manifest["submission_seat"])
            key = (source, episode_id, seat)
            if key in seen:
                skipped["duplicate_side"] += 1
                continue
            seen.add(key)
            replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
            result = str(manifest.get("result") or "unknown")
            split = _split(episode_id)
            split_episodes[split].add(episode_id)
            metadata = {
                "episode_id": episode_id,
                "seat": seat,
                "source": source,
                "split": split,
                "result": result,
                "reward": float(manifest.get("own_reward") or 0),
                "margin": float(manifest.get("own_reward") or 0)
                - float(manifest.get("opponent_reward") or 0),
            }
            made = 0
            for day in DAYS:
                row = _day_row(replay, seat, day, metadata)
                if row is None:
                    continue
                _enrich(row, replay, seat)
                rows.append(row)
                made += 1
            if made != len(DAYS):
                skipped["missing_day"] += len(DAYS) - made
            source_sides[f"{source}_{result}"] += 1

    def selected(source: str, result: str | None = None) -> list[dict[str, Any]]:
        return [
            row
            for row in rows
            if row["source"] == source
            and (result is None or row["result"] == result)
        ]

    cohorts: dict[str, list[dict[str, Any]]] = {
        source: selected(source) for source in SOURCES
    }
    cohorts["top3_all"] = [row for row in rows if str(row["source"]).startswith("rank")]
    cohorts["top3_win"] = [
        row
        for row in rows
        if str(row["source"]).startswith("rank") and row["result"] == "win"
    ]
    payload = {
        "format": "kaggriculture-v79-late-capacity-backlog-v1",
        "runtime_policy_enabled": False,
        "scope": {
            "days": list(DAYS),
            "teacher": "Top-3 submission sides; all and winner-only kept separate",
            "action_alignment": "actions are attributed to the observation that chose them",
            "causal_warning": "descriptive replay comparison, not an intervention estimate",
        },
        "data": {
            "episode_days": len(rows),
            "episodes": len({row["episode_id"] for row in rows}),
            "source_sides": dict(source_sides),
            "split_episodes": {
                split: len(episodes) for split, episodes in sorted(split_episodes.items())
            },
            "split_disjoint": all(
                split_episodes[left].isdisjoint(split_episodes[right])
                for index, left in enumerate(split_episodes)
                for right in list(split_episodes)[index + 1 :]
            ),
            "skipped": dict(skipped),
        },
        "cohorts": {
            name: {
                "all": _summary(cohort),
                "by_day": {
                    str(day): _summary([row for row in cohort if row["day"] == day])
                    for day in DAYS
                },
            }
            for name, cohort in cohorts.items()
        },
        "v11_by_split": {
            split: _summary(
                [row for row in cohorts["v11"] if row["split"] == split]
            )
            for split in ("train", "validation", "test")
        },
        "status": {
            "facts": "counts and public states read from stored replays",
            "inferences": "capacity/backlog interpretation",
            "unverified": "causal benefit of changing late asset targets",
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = (
        "productive_start",
        "worker_turns",
        "productive_per_worker_turn",
        "water_per_crop",
        "missed_water_rate_next_day",
        "missed_feed_rate_next_day",
        "money_h72",
        "margin",
    )
    print(
        json.dumps(
            {
                source: {
                    metric: payload["cohorts"][source]["all"][metric]["mean"]
                    for metric in compact
                }
                for source in ("v11", "rank1", "rank2", "rank3", "top3_win")
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"result: {OUTPUT}")


if __name__ == "__main__":
    main()
