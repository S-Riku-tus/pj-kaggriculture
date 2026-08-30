"""Analyze Day 6--12 hiring and field throughput without action imitation.

The existing ``utilization`` metric is productive farm occupancy, not worker
utilization.  This report therefore keeps four different quantities separate:

* successful daily hires and the hour at which they become available;
* available farm-hand turns;
* movement, pass, and productive field actions;
* 24-hour and 72-hour farm states.

Top-3 submission sides are the primary reference.  Winning and losing games,
rank sources, and deterministic episode splits remain separate so outcome
conditioning and source-specific quirks are visible in the report.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v3.feature_schema import farm_summary  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    TEACHERS,
    _manifest,
    _observation,
    _replay_path,
    _split,
)

FORMAT = "kaggriculture-v21-workforce-gap-v2"
DAYS = tuple(range(6, 13))
CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
MOVEMENT = {"NORTH", "SOUTH", "EAST", "WEST"}
SERVICE = {"FEED", "CARE", "COLLECT_FERTILIZER"}
PRODUCTIVE = {
    "BUILD_COOP",
    "BUILD_PASTURE",
    "CARE",
    "COLLECT_FERTILIZER",
    "DIG",
    "DROP",
    "FEED",
    "FERTILIZE",
    "HARVEST",
    "PICKUP",
    "PLACE",
    "PLANT",
    "WATER",
}
V11 = ROOT / "data/submissions/v11_submission_55787906"
SOURCES = {"v11": V11, **TEACHERS}


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * quantile
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - position) + ordered[high] * (position - low)


def _stats(values: Iterable[float]) -> dict[str, float]:
    materialized = [float(value) for value in values]
    if not materialized:
        return {"mean": 0.0, "median": 0.0, "p10": 0.0, "p90": 0.0}
    return {
        "mean": mean(materialized),
        "median": median(materialized),
        "p10": _percentile(materialized, 0.10),
        "p90": _percentile(materialized, 0.90),
    }


def _farm(obs: dict[str, Any] | None, seat: int) -> dict[str, Any]:
    if obs is None:
        return {}
    farms = obs.get("farms") or []
    player = int(obs.get("player", seat))
    return farms[player] if 0 <= player < len(farms) else {}


def _productive(farm: dict[str, Any]) -> int:
    summary = farm_summary(farm)
    return int(sum(summary["crops"].values()) + sum(summary["animals"].values()))


def _risk(farm: dict[str, Any]) -> dict[str, int]:
    missed_by_crop: Counter[str] = Counter()
    missed_feed = 0
    weeds = 0
    for row in farm.get("tiles") or []:
        for tile in row or []:
            if not isinstance(tile, dict):
                continue
            kind = tile.get("kind")
            if kind == "WEED":
                weeds += 1
            elif kind == "PLANT" and int(tile.get("consecutive_unwatered", 0) or 0) >= 1:
                missed_by_crop[str(tile.get("crop") or "UNKNOWN")] += 1
            elif kind in {"COOP", "PASTURE"} and tile.get("animal"):
                missed_feed += int(tile.get("consecutive_unfed", 0) or 0) >= 1
    return {
        "missed_water": sum(missed_by_crop.values()),
        "missed_feed": missed_feed,
        "weeds": weeds,
        **{f"missed_water_{crop.lower()}": missed_by_crop[crop] for crop in CROPS},
    }


def _payroll(hires: int) -> int:
    previous, current = 1, 1
    total = 0
    for index in range(max(0, hires)):
        if index <= 1:
            cost = 1
        else:
            previous, current = current, previous + current
            cost = current
        total += cost
    return total


def _field_counts(replay: dict[str, Any], seat: int, day: int) -> Counter[str]:
    """Count decisions made on ``day`` despite replay actions being one step late."""
    counts: Counter[str] = Counter()
    steps = replay.get("steps") or []
    # State t+1 stores the action chosen from observation t.  Include the next
    # day's hour-0 state so the decision from hour 23 is attributed correctly.
    start = day * 24 + 1
    stop = min((day + 1) * 24 + 1, len(steps))
    for step in range(start, stop):
        if not 0 <= seat < len(steps[step]):
            continue
        action = steps[step][seat].get("action") or {}
        units = [("farmer", action.get("farmer") or ["PASS"])]
        units.extend(("hand", value or ["PASS"]) for value in action.get("hands") or [])
        for unit, value in units:
            verb = str(value[0]) if value else "PASS"
            counts[f"field_{verb}"] += 1
            counts[f"{unit}_actions"] += 1
            if verb == "PASS":
                counts[f"{unit}_pass"] += 1
            elif verb in MOVEMENT:
                counts[f"{unit}_move"] += 1
            else:
                counts[f"{unit}_active"] += 1
            if verb in PRODUCTIVE:
                counts[f"{unit}_productive"] += 1
            if verb in SERVICE:
                counts[f"{unit}_service"] += 1
        for order in action.get("market") or []:
            if order:
                counts[f"market_{order[0]}"] += 1
    return counts


def _safe_rate(numerator: float, denominator: float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _day_row(
    replay: dict[str, Any],
    seat: int,
    day: int,
    metadata: dict[str, Any],
) -> dict[str, Any] | None:
    start_obs = _observation(replay, day * 24, seat)
    post_obs = _observation(replay, day * 24 + 1, seat)
    h24_obs = _observation(replay, (day + 1) * 24, seat)
    h72_obs = _observation(replay, (day + 3) * 24, seat)
    if any(obs is None for obs in (start_obs, post_obs, h24_obs, h72_obs)):
        return None
    start = _farm(start_obs, seat)
    post = _farm(post_obs, seat)
    h24 = _farm(h24_obs, seat)
    h72 = _farm(h72_obs, seat)
    if not all((start, post, h24, h72)):
        return None

    observations = [_observation(replay, day * 24 + hour, seat) for hour in range(24)]
    farms = [_farm(obs, seat) for obs in observations]
    hands = [len(farm.get("hands") or []) for farm in farms]
    hires = [int(farm.get("hires_today", len(farm.get("hands") or [])) or 0) for farm in farms]
    peak_hands = max(hires, default=0)
    completion_hour = next((hour for hour, count in enumerate(hires) if count >= peak_hands), 24)
    target = 7 if day <= 7 else (10 if day <= 9 else 12)
    target_hour = next((hour for hour, count in enumerate(hires) if count >= target), 24)
    counts = _field_counts(replay, seat, day)
    worker_turns = sum(hands)
    risk = _risk(h24)
    summary = farm_summary(start)
    capacity = max(1, 25 * int(summary["unlocked"]))

    return {
        **metadata,
        "day": day,
        "start_money": float(start.get("money", 0) or 0),
        "post_open_money": float(post.get("money", 0) or 0),
        "money_h24": float(h24.get("money", 0) or 0),
        "money_h72": float(h72.get("money", 0) or 0),
        "productive_start": _productive(start),
        "productive_h24": _productive(h24),
        "productive_h72": _productive(h72),
        "farm_occupancy_start": _productive(start) / capacity,
        "peak_hands": peak_hands,
        "worker_turns": worker_turns,
        "hire_completion_hour": completion_hour,
        "target_hands": target,
        "target_reached_hour": target_hour,
        "target_shortfall_turns": sum(max(0, target - count) for count in hands),
        "estimated_payroll": _payroll(peak_hands),
        "market_hire_orders": counts["market_HIRE"],
        "hand_actions": counts["hand_actions"],
        "hand_productive": counts["hand_productive"],
        "hand_active": counts["hand_active"],
        "hand_move": counts["hand_move"],
        "hand_pass": counts["hand_pass"],
        "hand_productive_rate": _safe_rate(counts["hand_productive"], counts["hand_actions"]),
        "hand_active_rate": _safe_rate(counts["hand_active"], counts["hand_actions"]),
        "hand_move_rate": _safe_rate(counts["hand_move"], counts["hand_actions"]),
        "hand_pass_rate": _safe_rate(counts["hand_pass"], counts["hand_actions"]),
        "farmer_productive": counts["farmer_productive"],
        "all_productive": counts["farmer_productive"] + counts["hand_productive"],
        "water": counts["field_WATER"],
        "harvest": counts["field_HARVEST"],
        "plant": counts["field_PLANT"],
        "service": counts["farmer_service"] + counts["hand_service"],
        "pickup_drop_place": counts["field_PICKUP"] + counts["field_DROP"] + counts["field_PLACE"],
        "build_dig": counts["field_BUILD_COOP"] + counts["field_BUILD_PASTURE"] + counts["field_DIG"],
        "missed_water_next_day": risk["missed_water"],
        "missed_feed_next_day": risk["missed_feed"],
        "weeds_next_day": risk["weeds"],
        **{f"missed_water_{crop.lower()}_next_day": risk[f"missed_water_{crop.lower()}"] for crop in CROPS},
    }


METRICS = (
    "start_money",
    "post_open_money",
    "money_h24",
    "money_h72",
    "productive_start",
    "productive_h24",
    "productive_h72",
    "farm_occupancy_start",
    "peak_hands",
    "worker_turns",
    "hire_completion_hour",
    "target_reached_hour",
    "target_shortfall_turns",
    "estimated_payroll",
    "market_hire_orders",
    "hand_productive",
    "hand_productive_rate",
    "hand_active_rate",
    "hand_move_rate",
    "hand_pass_rate",
    "farmer_productive",
    "all_productive",
    "water",
    "harvest",
    "plant",
    "service",
    "pickup_drop_place",
    "build_dig",
    "missed_water_next_day",
    "missed_water_wheat_next_day",
    "missed_water_carrot_next_day",
    "missed_water_tomato_next_day",
    "missed_water_strawberry_next_day",
    "missed_water_melon_next_day",
    "missed_feed_next_day",
    "weeds_next_day",
    "reward",
    "margin",
)


def _daily(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for day in DAYS:
        selected = [row for row in rows if row["day"] == day]
        if selected:
            result[str(day)] = {
                "sides": len(selected),
                "metrics": {metric: _stats(row[metric] for row in selected) for metric in METRICS},
            }
    return result


def _pearson(rows: list[dict[str, Any]], left: str, right: str) -> float:
    if len(rows) < 3:
        return 0.0
    xs = [float(row[left]) for row in rows]
    ys = [float(row[right]) for row in rows]
    x_mean = mean(xs)
    y_mean = mean(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True))
    x_scale = math.sqrt(sum((x - x_mean) ** 2 for x in xs))
    y_scale = math.sqrt(sum((y - y_mean) ** 2 for y in ys))
    return numerator / (x_scale * y_scale) if x_scale and y_scale else 0.0


def _associations(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for day in DAYS:
        selected = [row for row in rows if row["day"] == day]
        result[str(day)] = {
            "sides": len(selected),
            "pearson": {
                predictor: {
                    outcome: _pearson(selected, predictor, outcome)
                    for outcome in ("productive_h24", "productive_h72", "money_h72", "reward")
                }
                for predictor in (
                    "worker_turns",
                    "target_shortfall_turns",
                    "hand_productive_rate",
                    "hand_move_rate",
                    "hand_pass_rate",
                    "all_productive",
                )
            },
        }
    return result


def _cash_band(value: float) -> str:
    if value < 500:
        return "lt500"
    if value < 2000:
        return "500-1999"
    return "ge2000"


def _conditional(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for day in DAYS:
        by_band: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            if row["day"] == day:
                by_band[_cash_band(float(row["start_money"]))].append(row)
        result[str(day)] = {
            band: {
                "sides": len(selected),
                "peak_hands": _stats(row["peak_hands"] for row in selected),
                "worker_turns": _stats(row["worker_turns"] for row in selected),
                "target_shortfall_turns": _stats(row["target_shortfall_turns"] for row in selected),
                "hand_productive_rate": _stats(row["hand_productive_rate"] for row in selected),
                "money_h72": _stats(row["money_h72"] for row in selected),
            }
            for band, selected in sorted(by_band.items())
        }
    return result


def _cohorts(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        source = str(row["source"])
        result[source].append(row)
        result[f"{source}_{row['result']}"].append(row)
        if source.startswith("rank"):
            result["top3_all"].append(row)
            result[f"top3_{row['result']}"].append(row)
        else:
            result["v11_all"].append(row)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/analysis/v21_workforce_gap.json"))
    args = parser.parse_args()
    rows: list[dict[str, Any]] = []
    seen_sides: set[tuple[str, int, str]] = set()
    split_episodes: dict[str, set[str]] = defaultdict(set)
    skipped: Counter[str] = Counter()
    source_sides: Counter[str] = Counter()
    total = sum(len(_manifest(directory)) for directory in SOURCES.values())
    progress = 0
    for source, directory in SOURCES.items():
        for manifest in _manifest(directory):
            progress += 1
            if progress == 1 or progress % 25 == 0:
                print(f"[{progress}/{total}] {source} episode {manifest['episode_id']}", flush=True)
            episode_id = str(manifest["episode_id"])
            seat = int(manifest["submission_seat"])
            side_key = (episode_id, seat, source)
            if side_key in seen_sides:
                skipped["duplicate_side"] += 1
                continue
            seen_sides.add(side_key)
            replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
            if len(replay.get("steps") or []) < (max(DAYS) + 3) * 24 + 1:
                skipped["short_replay"] += 1
                continue
            split = _split(episode_id)
            split_episodes[split].add(episode_id)
            result = str(manifest.get("result") or "unknown")
            metadata = {
                "episode_id": episode_id,
                "seat": seat,
                "source": source,
                "split": split,
                "result": result,
                "reward": float(manifest.get("own_reward") or 0),
                "margin": float(manifest.get("own_reward") or 0) - float(manifest.get("opponent_reward") or 0),
            }
            made = 0
            for day in DAYS:
                row = _day_row(replay, seat, day, metadata)
                if row is not None:
                    rows.append(row)
                    made += 1
            if made != len(DAYS):
                skipped["missing_day"] += len(DAYS) - made
            source_sides[f"{source}_{result}"] += 1

    cohort_rows = _cohorts(rows)
    split_summary = {
        cohort: {
            split: _daily([row for row in selected if row["split"] == split])
            for split in ("train", "validation", "test")
        }
        for cohort, selected in cohort_rows.items()
        if cohort in {"v11_all", "top3_win", "rank1_win", "rank2_win", "rank3_win"}
    }
    payload = {
        "format": FORMAT,
        "scope": {
            "days": [min(DAYS), max(DAYS)],
            "top_teacher": "Top-3 submitted sides; wins/losses and ranks kept separate",
            "action_alignment": "state t+1 action is attributed to observation t",
            "farm_occupancy_note": "productive tiles / unlocked cells; not worker utilization",
            "association_warning": "Pearson values are descriptive and not causal estimates",
        },
        "sources": {name: str(path.relative_to(ROOT)) for name, path in SOURCES.items()},
        "source_sides": dict(source_sides),
        "split_episodes": {split: len(values) for split, values in sorted(split_episodes.items())},
        "split_disjoint": all(
            split_episodes[left].isdisjoint(split_episodes[right])
            for index, left in enumerate(split_episodes)
            for right in list(split_episodes)[index + 1 :]
        ),
        "skipped": dict(skipped),
        "cohorts": {cohort: _daily(selected) for cohort, selected in sorted(cohort_rows.items())},
        "split_cohorts": split_summary,
        "top3_win_cash_conditionals": _conditional(cohort_rows.get("top3_win", [])),
        "top3_win_associations": _associations(cohort_rows.get("top3_win", [])),
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "format": FORMAT,
                "source_sides": payload["source_sides"],
                "split_episodes": payload["split_episodes"],
                "split_disjoint": payload["split_disjoint"],
                "rows": len(rows),
                "skipped": payload["skipped"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"result: {output}")


if __name__ == "__main__":
    main()
