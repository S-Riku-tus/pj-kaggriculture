"""Measure hourly Day 11--12 watering curves for V11 and Top-3 sides."""

from __future__ import annotations

import argparse
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

from agents.v14 import main as v14  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    TEACHERS,
    _manifest,
    _observation,
    _replay_path,
    _split,
)

FORMAT = "kaggriculture-v21-water-timing-v1"
V11 = ROOT / "data/submissions/v11_submission_55787906"
SOURCES = {"v11": V11, **TEACHERS}
DAYS = (11, 12)
MOVEMENT = {"NORTH", "SOUTH", "EAST", "WEST"}


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * quantile
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - position) + ordered[high] * (position - low)


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "median": 0.0, "p10": 0.0, "p90": 0.0}
    return {
        "mean": mean(values),
        "median": median(values),
        "p10": _percentile(values, 0.10),
        "p90": _percentile(values, 0.90),
    }


def _farm(obs: dict[str, Any] | None, seat: int) -> dict[str, Any]:
    if obs is None:
        return {}
    farms = obs.get("farms") or []
    player = int(obs.get("player", seat))
    return farms[player] if 0 <= player < len(farms) else {}


def _water_state(farm: dict[str, Any], day: int) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in farm.get("tiles") or []:
        for tile in row or []:
            if not isinstance(tile, dict) or tile.get("kind") != "PLANT":
                continue
            counts["plants"] += 1
            if bool(tile.get("watered_today", False)):
                counts["watered"] += 1
                continue
            counts["unwatered"] += 1
            if int(tile.get("consecutive_unwatered", 0) or 0) >= 1:
                counts["risk"] += 1
            elif not v14.v4._ongoing_finished(tile, day) and not v14.v4._water_is_useful(tile, day):
                counts["preventive_candidates"] += 1
            else:
                counts["useful_candidates"] += 1
    return counts


def _decision(replay: dict[str, Any], seat: int, step: int) -> Counter[str]:
    """Return the action selected at ``step`` from the replay's t+1 state."""
    counts: Counter[str] = Counter()
    states = replay.get("steps") or []
    recorded = step + 1
    if not 0 <= recorded < len(states) or not 0 <= seat < len(states[recorded]):
        return counts
    action = states[recorded][seat].get("action") or {}
    units = [("farmer", action.get("farmer") or ["PASS"])]
    units.extend(("hand", value or ["PASS"]) for value in action.get("hands") or [])
    for unit, value in units:
        verb = str(value[0]) if value else "PASS"
        counts[f"{unit}_actions"] += 1
        counts[f"field_{verb}"] += 1
        if verb == "PASS":
            counts[f"{unit}_pass"] += 1
        elif verb in MOVEMENT:
            counts[f"{unit}_move"] += 1
        else:
            counts[f"{unit}_productive"] += 1
    return counts


def _hour_rows(replay: dict[str, Any], seat: int, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for day in DAYS:
        for hour in range(24):
            step = day * 24 + hour
            obs = _observation(replay, step, seat)
            farm = _farm(obs, seat)
            if not farm:
                continue
            water = _water_state(farm, day)
            action = _decision(replay, seat, step)
            hand_actions = action["hand_actions"]
            rows.append(
                {
                    **metadata,
                    "day": day,
                    "hour": hour,
                    "hands": len(farm.get("hands") or []),
                    "plants": water["plants"],
                    "watered": water["watered"],
                    "unwatered": water["unwatered"],
                    "risk": water["risk"],
                    "preventive_candidates": water["preventive_candidates"],
                    "useful_candidates": water["useful_candidates"],
                    "water_actions": action["field_WATER"],
                    "hand_pass_rate": action["hand_pass"] / hand_actions if hand_actions else 0.0,
                    "hand_move_rate": action["hand_move"] / hand_actions if hand_actions else 0.0,
                    "hand_productive_rate": action["hand_productive"] / hand_actions if hand_actions else 0.0,
                }
            )
    return rows


METRICS = (
    "hands",
    "plants",
    "watered",
    "unwatered",
    "risk",
    "preventive_candidates",
    "useful_candidates",
    "water_actions",
    "hand_pass_rate",
    "hand_move_rate",
    "hand_productive_rate",
)


def _hourly(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for day in DAYS:
        result[str(day)] = {}
        for hour in range(24):
            selected = [row for row in rows if row["day"] == day and row["hour"] == hour]
            if selected:
                result[str(day)][str(hour)] = {
                    "sides": len(selected),
                    "metrics": {
                        metric: _stats([float(row[metric]) for row in selected]) for metric in METRICS
                    },
                }
    return result


def _cohorts(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    cohorts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        source = str(row["source"])
        result = str(row["result"])
        cohorts[source].append(row)
        cohorts[f"{source}_{result}"].append(row)
        if source.startswith("rank"):
            cohorts["top3_all"].append(row)
            cohorts[f"top3_{result}"].append(row)
        else:
            cohorts["v11_all"].append(row)
    return cohorts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/analysis/v21_water_timing.json"))
    args = parser.parse_args()
    rows: list[dict[str, Any]] = []
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
            result = str(manifest.get("result") or "unknown")
            replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
            rows.extend(
                _hour_rows(
                    replay,
                    seat,
                    {
                        "episode_id": episode_id,
                        "seat": seat,
                        "source": source,
                        "result": result,
                        "split": _split(episode_id),
                    },
                )
            )
            source_sides[f"{source}_{result}"] += 1
    cohorts = _cohorts(rows)
    payload = {
        "format": FORMAT,
        "scope": {
            "days": list(DAYS),
            "action_alignment": "state t+1 action is attributed to observation t",
            "preventive_definition": "not watered, no prior miss, not output-useful, not expired",
        },
        "source_sides": dict(source_sides),
        "cohorts": {cohort: _hourly(selected) for cohort, selected in sorted(cohorts.items())},
        "split_cohorts": {
            cohort: {
                split: _hourly([row for row in selected if row["split"] == split])
                for split in ("train", "validation", "test")
            }
            for cohort, selected in cohorts.items()
            if cohort in {"v11_all", "rank1_win", "rank2_win", "rank3_win"}
        },
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"format": FORMAT, "rows": len(rows), "source_sides": dict(source_sides)}, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
