"""Summarize the full Top-3 corpus as evidence for V8's design.

This consumes the per-episode full-corpus table produced by
``analyze_replay_corpus.py``.  It reports robust trajectories and conditional
portfolio responses; no local-agent win rate enters the result.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXPERTS = ("rank1", "rank2", "rank3")
SNAPSHOT_DAYS = (1, 3, 5, 6, 7, 8, 9, 10, 11, 12, 15, 18, 20, 24, 27, 29)
ASSETS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "COW", "SHEEP")


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _distribution(values: list[float]) -> dict[str, float]:
    return {
        "p10": round(_percentile(values, 0.10), 4),
        "p25": round(_percentile(values, 0.25), 4),
        "median": round(_percentile(values, 0.50), 4),
        "p75": round(_percentile(values, 0.75), 4),
        "p90": round(_percentile(values, 0.90), 4),
    }


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def _load(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            if _as_bool(raw["is_self_play"]):
                continue
            row: dict[str, Any] = dict(raw)
            row["day_snapshots"] = json.loads(raw["day_snapshots"])
            for key in (
                "own_reward",
                "opponent_reward",
                "max_wheat",
                "max_carrot",
                "max_tomato",
                "max_strawberry",
                "max_melon",
                "max_cow",
                "max_sheep",
                "demand_carrot",
                "demand_tomato",
                "demand_strawberry",
                "demand_milk",
                "demand_wool",
                "unlock_2_day",
                "unlock_3_day",
            ):
                row[key] = float(raw[key]) if raw.get(key) not in {None, ""} else math.nan
            own = row["own_reward"]
            opponent = row["opponent_reward"]
            row["coin_share"] = own / max(1.0, own + opponent)
            rows.append(row)
    return rows


def _asset(snapshot: dict[str, Any], asset: str) -> float:
    section = "animals" if asset in {"COW", "SHEEP"} else "crops"
    return float(snapshot[section].get(asset, 0))


def _trajectory(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for day in SNAPSHOT_DAYS:
        snapshots = [row["day_snapshots"][str(day)] for row in rows]
        result[str(day)] = {
            "money": _distribution([float(snapshot["money"]) for snapshot in snapshots]),
            "productive_tiles": _distribution(
                [float(snapshot["productive_tiles"]) for snapshot in snapshots]
            ),
            "utilization": _distribution([float(snapshot["utilization"]) for snapshot in snapshots]),
            "land": _distribution([float(snapshot["unlocked"]) for snapshot in snapshots]),
            "assets": {
                asset: _distribution([_asset(snapshot, asset) for snapshot in snapshots])
                for asset in ASSETS
            },
        }
    return result


def _demand_response(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pairs = {
        "MILK_to_COW": ("demand_milk", "max_cow"),
        "WOOL_to_SHEEP": ("demand_wool", "max_sheep"),
        "STRAWBERRY_to_STRAWBERRY": ("demand_strawberry", "max_strawberry"),
        "CARROT_to_CARROT": ("demand_carrot", "max_carrot"),
        "TOMATO_to_TOMATO": ("demand_tomato", "max_tomato"),
    }
    result = {}
    for name, (demand_name, asset_name) in pairs.items():
        buckets: dict[int, list[float]] = defaultdict(list)
        for row in rows:
            demand = row[demand_name]
            asset = row[asset_name]
            if not math.isnan(demand) and not math.isnan(asset):
                buckets[int(demand)].append(asset)
        result[name] = {
            str(demand): {"episodes": len(values), **_distribution(values)}
            for demand, values in sorted(buckets.items())
        }
    return result


def _robustness(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: row["coin_share"])
    quartile = max(1, len(ordered) // 4)
    bottom = ordered[:quartile]
    top = ordered[-quartile:]

    def summarize(group: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "episodes": len(group),
            "coin_share": _distribution([row["coin_share"] for row in group]),
            "day12_productive": _distribution(
                [float(row["day_snapshots"]["12"]["productive_tiles"]) for row in group]
            ),
            "day12_money": _distribution(
                [float(row["day_snapshots"]["12"]["money"]) for row in group]
            ),
            "day24_productive": _distribution(
                [float(row["day_snapshots"]["24"]["productive_tiles"]) for row in group]
            ),
        }

    return {"bottom_share_quartile": summarize(bottom), "top_share_quartile": summarize(top)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--episodes",
        type=Path,
        default=Path("data/analysis/v8_top3_full_episodes.csv"),
    )
    parser.add_argument(
        "--validation",
        type=Path,
        default=Path("data/analysis/v8_expert_policy_validation.json"),
    )
    parser.add_argument(
        "--opening",
        type=Path,
        default=Path("agents/v8/expert_opening_actions.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v8_teacher_strategy_analysis.json"),
    )
    args = parser.parse_args()
    episodes_path = args.episodes if args.episodes.is_absolute() else ROOT / args.episodes
    validation_path = args.validation if args.validation.is_absolute() else ROOT / args.validation
    opening_path = args.opening if args.opening.is_absolute() else ROOT / args.opening
    rows = _load(episodes_path)

    by_expert = {expert: [row for row in rows if row["label"] == expert] for expert in EXPERTS}
    opening = json.loads(opening_path.read_text(encoding="utf-8"))
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    result = {
        "created_at": datetime.now().astimezone().isoformat(),
        "selection_rule": "Top-3 replay fidelity and trajectory robustness; local old-agent win rates excluded",
        "episodes": {expert: len(by_expert[expert]) for expert in EXPERTS},
        "opening": {
            "source": opening["source"],
            "episodes": opening["episodes"],
            "first_day": opening["first_day"],
            "last_day": opening["last_day"],
            "minimum_action_consensus": opening["minimum_action_consensus"],
            "minimum_field_consensus": opening.get("minimum_field_consensus"),
        },
        "validation": validation,
        "experts": {
            expert: {
                "trajectory": _trajectory(expert_rows),
                "demand_response": _demand_response(expert_rows),
                "robustness": _robustness(expert_rows),
                "land_timing": {
                    "second_land_day": _distribution(
                        [row["unlock_2_day"] for row in expert_rows if not math.isnan(row["unlock_2_day"])]
                    ),
                    "third_land_day": _distribution(
                        [row["unlock_3_day"] for row in expert_rows if not math.isnan(row["unlock_3_day"])]
                    ),
                },
            }
            for expert, expert_rows in by_expert.items()
        },
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"analysis: {output} ({output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
