"""Connect opening market perturbations to day-0/1 structure and terminal result."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def snapshot(observation: dict[str, Any]) -> dict[str, Any]:
    player = integer(observation.get("player"), -1)
    farms = observation.get("farms") or []
    farm = farms[player] if 0 <= player < len(farms) else {}
    private = observation.get("private") or {}
    tiles = [tile for row in (farm.get("tiles") or []) for tile in row if isinstance(tile, dict)]
    crops = Counter(str(tile.get("crop")) for tile in tiles if tile.get("kind") == "PLANT")
    animals = Counter(str(tile.get("animal")) for tile in tiles if tile.get("animal"))
    return {
        "step": integer(observation.get("step")),
        "day": integer(observation.get("day")),
        "hour": integer(observation.get("hour")),
        "money": float(farm.get("money", 0) or 0),
        "hands": len(farm.get("hands") or []),
        "land_quadrants": len(farm.get("unlocked_quadrants") or []),
        "shed": dict(private.get("shed") or {}),
        "seeds": dict(private.get("seeds") or {}),
        "crops": dict(crops),
        "animals": dict(animals),
    }


def action_counts(decisions: list[dict[str, Any]], seat: int, max_day: int) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for decision in decisions:
        observation = decision["observations"][seat]
        if integer(observation.get("day")) > max_day:
            continue
        action = decision["actions"][seat]
        units = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
        for unit in units:
            counts[f"actor:{unit[0] if unit else 'PASS'}"] += 1
        for order in action.get("market") or []:
            if not order:
                continue
            op = str(order[0])
            quantity = integer(order[2], 1) if len(order) > 2 else 1
            counts[f"market_orders:{op}"] += 1
            counts[f"market_quantity:{op}:{order[1] if len(order) > 1 else ''}"] += quantity
    return dict(sorted(counts.items()))


def at_step(decisions: list[dict[str, Any]], seat: int, step: int) -> dict[str, Any]:
    index = min(step, len(decisions) - 1)
    return snapshot(decisions[index]["observations"][seat])


def flatten(prefix: str, value: dict[str, Any], output: dict[str, Any]) -> None:
    for key, child in value.items():
        if isinstance(child, dict):
            flatten(f"{prefix}{key}.", child, output)
        else:
            output[f"{prefix}{key}"] = child


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("games_csv", type=Path)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    games_path = args.games_csv if args.games_csv.is_absolute() else ROOT / args.games_csv
    with games_path.open(encoding="utf-8-sig", newline="") as stream:
        games = list(csv.DictReader(stream))
    rows = []
    for game in games:
        with gzip.open(ROOT / game["replay"], "rt", encoding="utf-8") as stream:
            replay = json.load(stream)
        seat = integer(game["seat"])
        decisions = replay["decisions"]
        row: dict[str, Any] = {
            "arm": game["arm"],
            "opponent_id": game["opponent_id"],
            "seed": integer(game["seed"]),
            "seat": seat,
            "result": game["result"],
            "self_final_cash": float(game["self_final_cash"]),
            "opp_final_cash": float(game["opp_final_cash"]),
            "margin": float(game["margin"]),
            "shop_sequence_hash": game["shop_sequence_hash"],
            "self_opening_market_json": json.dumps(decisions[0]["actions"][seat]["market"], separators=(",", ":")),
            "opp_opening_market_json": json.dumps(decisions[0]["actions"][1 - seat]["market"], separators=(",", ":")),
        }
        for name, step in (
            ("after_step0", 1),
            ("after_step1", 2),
            ("day0_final_decision", 23),
            ("day1_start", 24),
            ("day2_start", 48),
        ):
            flatten(f"{name}.", at_step(decisions, seat, step), row)
        flatten("day0_1_actions.", action_counts(decisions, seat, 1), row)
        rows.append(row)
    columns = sorted({key for row in rows for key in row})
    output_csv = args.output_csv if args.output_csv.is_absolute() else ROOT / args.output_csv
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["arm"], row["opponent_id"])].append(row)
    summary = {
        "games": len(rows),
        "groups": [
            {
                "arm": key[0],
                "opponent_id": key[1],
                "games": len(values),
                "wins": sum(row["result"] == "W" for row in values),
                "losses": sum(row["result"] == "L" for row in values),
                "ties": sum(row["result"] == "T" for row in values),
                "mean_margin": mean(row["margin"] for row in values),
                "after_step0_money": mean(row["after_step0.money"] for row in values),
                "day1_start_money": mean(row["day1_start.money"] for row in values),
                "after_step1_hands": mean(row["after_step1.hands"] for row in values),
                "after_step1_shed_wheat": mean(row.get("after_step1.shed.WHEAT", 0) for row in values),
                "day1_start_hands": mean(row["day1_start.hands"] for row in values),
                "day1_start_crop_tiles": mean(
                    sum(value for name, value in row.items() if name.startswith("day1_start.crops."))
                    for row in values
                ),
                "day1_start_animals": mean(
                    sum(value for name, value in row.items() if name.startswith("day1_start.animals."))
                    for row in values
                ),
                "distinct_shop_sequences": len({row["shop_sequence_hash"] for row in values}),
            }
            for key, values in sorted(grouped.items())
        ],
    }
    summary_path = args.summary if args.summary.is_absolute() else ROOT / args.summary
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
