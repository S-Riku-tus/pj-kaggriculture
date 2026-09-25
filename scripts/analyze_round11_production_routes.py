"""Measure complete production routes in a Round11 panel's raw replays."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")


def crop_counts(farm: dict) -> Counter[str]:
    result: Counter[str] = Counter()
    for tile_row in farm.get("tiles", []):
        for tile in tile_row:
            if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                result[str(tile.get("crop"))] += 1
    return result


def animal_count(farm: dict) -> int:
    return sum(
        1
        for tile_row in farm.get("tiles", [])
        for tile in tile_row
        if isinstance(tile, dict) and tile.get("animal")
    )


def unlocked_count(farm: dict) -> int:
    return len(farm.get("unlocked_quadrants", []))


def load_replay(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def analyze_game(row: dict[str, str]) -> dict[str, object]:
    seat = int(row["seat"])
    payload = load_replay(ROOT / row["replay"])
    first_crop_day: dict[str, int | None] = {crop: None for crop in CROPS}
    max_crops: Counter[str] = Counter()
    day15: Counter[str] = Counter()
    day18: Counter[str] = Counter()
    day24: Counter[str] = Counter()
    max_animals = 0
    max_workers = 0
    max_quadrants = 0
    hire_orders = 0
    land_orders = 0
    plant_actions: Counter[str] = Counter()
    for decision in payload["decisions"]:
        obs = decision["observations"][seat]
        farm = obs["farms"][seat]
        counts = crop_counts(farm)
        for crop in CROPS:
            max_crops[crop] = max(max_crops[crop], counts[crop])
        for tile_row in farm.get("tiles", []):
            for tile in tile_row:
                if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                    crop = str(tile.get("crop"))
                    planted = int(tile.get("planted_day", obs.get("day", 99)))
                    current = first_crop_day.get(crop)
                    first_crop_day[crop] = planted if current is None else min(current, planted)
        if int(obs.get("hour", -1)) == 0:
            day = int(obs.get("day", -1))
            if day == 15:
                day15 = counts
            elif day == 18:
                day18 = counts
            elif day == 24:
                day24 = counts
        max_animals = max(max_animals, animal_count(farm))
        private = obs.get("private") or {}
        max_workers = max(max_workers, max(0, len(private.get("inventories", [])) - 1))
        max_quadrants = max(max_quadrants, unlocked_count(farm))
        action = decision["actions"][seat]
        market = action.get("market") or []
        hire_orders += sum(1 for order in market if order and order[0] == "HIRE")
        land_orders += sum(1 for order in market if order and order[0] == "BUY_LAND")
        farm_actions = [action.get("farmer")] + list(action.get("hands") or [])
        for farm_action in farm_actions:
            if farm_action and farm_action[0] == "PLANT" and len(farm_action) > 1:
                plant_actions[str(farm_action[1])] += 1
    result: dict[str, object] = {
        "arm": row["arm"],
        "opponent_id": row["opponent_id"],
        "seed": int(row["seed"]),
        "seat": seat,
        "result": row["result"],
        "self_final_cash": float(row["self_final_cash"]),
        "margin": float(row["margin"]),
        "max_workers": max_workers,
        "max_unlocked_quadrants": max_quadrants,
        "max_animals": max_animals,
        "hire_order_turns": hire_orders,
        "buy_land_order_turns": land_orders,
    }
    for crop in CROPS:
        label = crop.lower()
        result[f"first_{label}_day"] = first_crop_day[crop]
        result[f"max_{label}_tiles"] = max_crops[crop]
        result[f"day15_{label}_tiles"] = day15[crop]
        result[f"day18_{label}_tiles"] = day18[crop]
        result[f"day24_{label}_tiles"] = day24[crop]
        result[f"plant_{label}_actions"] = plant_actions[crop]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("panel", type=Path)
    args = parser.parse_args()
    panel = args.panel if args.panel.is_absolute() else ROOT / args.panel
    with (panel / "games.csv").open(encoding="utf-8-sig", newline="") as handle:
        game_rows = list(csv.DictReader(handle))
    analyzed = [analyze_game(row) for row in game_rows]
    with (panel / "production_routes_per_game.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(analyzed[0]))
        writer.writeheader()
        writer.writerows(analyzed)

    by_arm: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in analyzed:
        by_arm[str(row["arm"])].append(row)
    summary = {"schema": "round11-production-route-summary-v1", "arms": {}}
    selected = [
        "self_final_cash", "margin", "max_workers", "max_unlocked_quadrants", "max_animals",
        "hire_order_turns", "buy_land_order_turns", "first_strawberry_day",
        "max_strawberry_tiles", "day15_strawberry_tiles", "first_tomato_day",
        "max_tomato_tiles", "day18_tomato_tiles", "plant_strawberry_actions",
    ]
    for arm, rows in sorted(by_arm.items()):
        arm_result: dict[str, object] = {"games": len(rows)}
        for key in selected:
            values = [row[key] for row in rows if row[key] is not None]
            arm_result[f"mean_{key}"] = statistics.mean(float(v) for v in values) if values else None
            if key.startswith("first_"):
                arm_result[f"distribution_{key}"] = dict(
                    sorted(Counter(str(v) for v in values).items())
                )
        summary["arms"][arm] = arm_result
    (panel / "production_routes_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
