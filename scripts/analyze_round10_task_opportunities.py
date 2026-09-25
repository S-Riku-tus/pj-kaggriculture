"""Audit executable one-extra-primitive task opportunities in Round10 L1 traces."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CROPS = {
    "WHEAT": {"first": 2, "max_day": 4, "interval": 0, "max_yield": 6, "ongoing": False},
    "CARROT": {"first": 2, "max_day": 3, "interval": 0, "max_yield": 4, "ongoing": False},
    "TOMATO": {"first": 8, "max_day": 8, "interval": 1, "max_yield": 4, "ongoing": True},
    "STRAWBERRY": {"first": 10, "max_day": 10, "interval": 2, "max_yield": 4, "ongoing": True},
    "MELON": {"first": 10, "max_day": 12, "interval": 0, "max_yield": 6, "ongoing": False},
}


def integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def own_state(observation: dict[str, Any]) -> tuple[dict[str, Any], list[list[int]], list[dict[str, Any]]]:
    player = integer(observation.get("player"), -1)
    farms = observation.get("farms") or []
    farm = farms[player] if 0 <= player < len(farms) else {}
    positions = [list(farm.get("farmer") or [0, 0]), *[list(value) for value in (farm.get("hands") or [])]]
    inventories = list((observation.get("private") or {}).get("inventories") or [])
    inventories = [value if isinstance(value, dict) else {} for value in inventories]
    return farm, positions, inventories


def tile_at(farm: dict[str, Any], position: list[int]) -> dict[str, Any] | None:
    x, y = integer(position[0], -1), integer(position[1], -1)
    rows = farm.get("tiles") or []
    value = rows[y][x] if 0 <= y < len(rows) and 0 <= x < len(rows[y]) else None
    return value if isinstance(value, dict) else None


def action_units(action: dict[str, Any]) -> list[list[Any]]:
    return [list(action.get("farmer") or ["PASS"]), *[list(value or ["PASS"]) for value in action.get("hands") or []]]


def fertilizer_changes_current_production(tile: dict[str, Any], day: int) -> bool:
    rule = CROPS.get(str(tile.get("crop") or ""))
    if not rule or integer(tile.get("yield_units")) >= int(rule["max_yield"]):
        return False
    age = day - integer(tile.get("planted_day"))
    if not bool(rule["ongoing"]):
        window_start = (int(rule["max_day"]) + 1) // 2
        return window_start <= age <= int(rule["max_day"])
    since_first = day + 1 - integer(tile.get("planted_day")) - int(rule["first"])
    return since_first >= 0 and since_first % int(rule["interval"]) == 0 and (
        since_first // int(rule["interval"]) + 1 <= int(rule["max_yield"])
    )


def load_games(csv_path: Path, arm: str) -> list[dict[str, Any]]:
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        return [row for row in csv.DictReader(stream) if not arm or row["arm"] == arm]


def analyze(games: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    for game in games:
        replay_path = ROOT / game["replay"]
        with gzip.open(replay_path, "rt", encoding="utf-8") as stream:
            replay = json.load(stream)
        seat = integer(game["seat"])
        decisions = replay.get("decisions") or []
        for index, decision in enumerate(decisions):
            observation = decision["observations"][seat]
            action = decision["actions"][seat]
            farm, positions, inventories = own_state(observation)
            units = action_units(action)
            for actor, unit in enumerate(units):
                op = str(unit[0]) if unit else "PASS"
                counts[f"op:{op}"] += 1
                if actor >= len(positions):
                    continue
                tile = tile_at(farm, positions[actor])
                inventory = inventories[actor] if actor < len(inventories) else {}
                day = integer(observation.get("day"))
                candidate = ""
                if tile and tile.get("animal") and not bool(tile.get("fed_today")) and op == "CARE":
                    counts["care_on_unfed"] += 1
                    if integer(inventory.get("WHEAT")) > 0:
                        candidate = "feed_then_care"
                if (
                    tile
                    and tile.get("kind") == "PLANT"
                    and op == "WATER"
                    and integer(inventory.get("FERTILIZER")) > 0
                    and integer(tile.get("fertilized_until_day"), -1) < day
                    and fertilizer_changes_current_production(tile, day)
                    and integer(observation.get("hour")) <= 22
                ):
                    candidate = "fertilize_then_water"
                if tile and tile.get("animal") and bool(tile.get("fertilizer_available")) and op == "CARE":
                    candidate = "collect_then_care"
                if not candidate:
                    continue
                counts[f"candidate:{candidate}"] += 1
                if len(examples) < 500:
                    examples.append(
                        {
                            "candidate": candidate,
                            "arm": game["arm"],
                            "opponent": game["opponent_id"],
                            "seed": integer(game["seed"]),
                            "seat": seat,
                            "step": integer(observation.get("step"), index),
                            "day": day,
                            "hour": integer(observation.get("hour")),
                            "actor": actor,
                            "position": positions[actor],
                            "baseline_action": unit,
                            "inventory": inventory,
                            "tile": tile,
                        }
                    )
    by_candidate = Counter(example["candidate"] for example in examples)
    return {
        "games": len(games),
        "counts": dict(sorted(counts.items())),
        "recorded_examples": dict(sorted(by_candidate.items())),
        "examples": examples,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("games_csv", type=Path)
    parser.add_argument("--arm", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    csv_path = args.games_csv if args.games_csv.is_absolute() else ROOT / args.games_csv
    output = args.output if args.output.is_absolute() else ROOT / args.output
    result = analyze(load_games(csv_path, args.arm))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("games", "counts", "recorded_examples")}, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
