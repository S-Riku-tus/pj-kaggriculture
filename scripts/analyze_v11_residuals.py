"""Analyze V10's late-rotation and monetization residuals.

The input is a ``run_match.py`` result with saved replays.  Both seats are
measured from the same games so demand, market prices, and random events are
paired.  Opponent results are diagnostic context only; the Rank-1 aggregate
remains the strategy reference.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
ANIMALS = ("COW", "SHEEP", "GOOSE")
PHASES = {"rotation": range(20, 27), "liquidation": range(27, 30)}
FINAL_AGE = {"TOMATO": 11, "STRAWBERRY": 16}
SHOP_DEMAND = {
    "BAKERY": {"WHEAT": 1},
    "PIZZA_SHOP": {"MILK": 1, "TOMATO": 1, "WHEAT": 1},
    "BRUNCH_SPOT": {"WHEAT": 1, "STRAWBERRY": 1},
    "YARN_STORE": {"WOOL": 2},
    "ICE_CREAM_SHOP": {"STRAWBERRY": 1, "MILK": 1, "WHEAT": 1},
    "PET_CAFE": {"CARROT": 2},
    "SMOOTHIE_SHOP": {"STRAWBERRY": 1, "MILK": 1},
    "FARMERS_MARKET": {"WHEAT": 1, "CARROT": 1, "TOMATO": 1, "STRAWBERRY": 1},
}


def _count(inventory: dict[str, Any], item: str) -> int:
    return max(0, int(inventory.get(item, 0) or 0))


def _percentile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _distribution(values: list[float]) -> dict[str, float]:
    return {
        "minimum": round(min(values, default=0.0), 4),
        "p10": round(_percentile(values, 0.10), 4),
        "median": round(_percentile(values, 0.50), 4),
        "mean": round(mean(values), 4) if values else 0.0,
        "maximum": round(max(values, default=0.0), 4),
    }


def _snapshot(obs: dict[str, Any], seat: int) -> dict[str, Any]:
    farm = (obs.get("farms") or [])[seat]
    private = obs.get("private") or {}
    day = int(obs.get("day", 0) or 0)
    crops: Counter[str] = Counter()
    animals: Counter[str] = Counter()
    planted_days: Counter[str] = Counter()
    pastures = 0
    weeds = 0
    free = 0
    finished = 0
    final_wave = 0
    for row in farm.get("tiles") or []:
        for tile in row:
            if not isinstance(tile, dict):
                free += tile is None
                continue
            kind = tile.get("kind")
            crop = str(tile.get("crop") or "")
            if kind == "PLANT":
                crops[crop] += 1
                planted_day = int(tile.get("planted_day", day) or day)
                planted_days[f"{crop}:{planted_day}"] += 1
                final_age = FINAL_AGE.get(crop)
                if final_age is not None and day - planted_day >= final_age:
                    final_wave += 1
                    finished += int(tile.get("yield_units", 0) or 0) == 0
            elif kind == "PASTURE":
                pastures += 1
            elif kind == "WEED":
                weeds += 1
            animal = str(tile.get("animal") or "")
            if animal:
                animals[animal] += 1
    seeds = private.get("seeds") or {}
    shed = private.get("shed") or {}
    carried = Counter()
    for inventory in private.get("inventories") or []:
        for item, quantity in (inventory or {}).items():
            carried[str(item)] += max(0, int(quantity or 0))
    productive = sum(crops.values()) + sum(animals.values())
    demand: Counter[str] = Counter()
    shops = (obs.get("town") or {}).get("unlocked_shops") or []
    for shop in shops:
        demand.update(SHOP_DEMAND.get(str(shop), {}))
    return {
        "money": float(farm.get("money", 0) or 0),
        "productive": productive,
        "crops": {crop: crops[crop] for crop in CROPS},
        "animals": {animal: animals[animal] for animal in ANIMALS},
        "pastures": pastures,
        "weeds": weeds,
        "free": free,
        "finished_ongoing": finished,
        "final_wave_ongoing": final_wave,
        "seed_units": sum(_count(seeds, crop) for crop in CROPS),
        "seeds": {crop: _count(seeds, crop) for crop in CROPS},
        "carried_units": sum(carried.values()),
        "shed_units": sum(max(0, int(value or 0)) for value in shed.values()),
        "shed": {
            item: _count(shed, item)
            for item in (*CROPS, "MILK", "WOOL", "FERTILIZER")
        },
        "hands": len(farm.get("hands") or []),
        "demand": dict(demand),
        "shops": [str(shop) for shop in shops],
        "planted_cohorts": dict(sorted(planted_days.items())),
    }


def _seat_trace(replay: dict[str, Any], seat: int) -> dict[str, Any]:
    checkpoints: dict[str, dict[str, Any]] = {}
    timeline: list[dict[str, Any]] = []
    daily_field: dict[int, Counter[str]] = {}
    daily_market: dict[int, Counter[str]] = {}
    for states in replay.get("steps") or []:
        state = states[seat]
        obs = state.get("observation") or {}
        day = int(obs.get("day", 0) or 0)
        hour = int(obs.get("hour", 0) or 0)
        if hour == 0:
            checkpoints[str(day)] = _snapshot(obs, seat)
        if 20 <= day <= 26 and (hour % 6 == 0 or hour == 23):
            timeline.append({"day": day, "hour": hour, **_snapshot(obs, seat)})
        action = state.get("action") or {}
        field = daily_field.setdefault(day, Counter())
        for unit_action in [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]:
            field[str(unit_action[0]) if unit_action else "PASS"] += 1
        market = daily_market.setdefault(day, Counter())
        for order in action.get("market") or []:
            if not order:
                continue
            verb = str(order[0])
            item = str(order[1]) if len(order) > 1 else ""
            quantity = max(0, int(order[2] or 0)) if len(order) > 2 else 1
            market[verb] += quantity
            if item:
                market[f"{verb}_{item}"] += quantity
    phases: dict[str, Any] = {}
    for phase, days in PHASES.items():
        field = Counter()
        market = Counter()
        for day in days:
            field.update(daily_field.get(day, {}))
            market.update(daily_market.get(day, {}))
        phases[phase] = {"field": dict(field), "market": dict(market)}
    return {
        "checkpoints": checkpoints,
        "timeline": timeline,
        "daily_field": {str(day): dict(value) for day, value in daily_field.items()},
        "daily_market": {str(day): dict(value) for day, value in daily_market.items()},
        "phases": phases,
    }


def _phase_average(games: list[dict[str, Any]], role: str, phase: str, section: str) -> dict[str, float]:
    keys = {
        key
        for game in games
        for key in game[role]["phases"][phase][section]
    }
    return {
        key: round(
            mean(game[role]["phases"][phase][section].get(key, 0) for game in games),
            4,
        )
        for key in sorted(keys)
    }


def _checkpoint_summary(games: list[dict[str, Any]], role: str, day: int) -> dict[str, Any]:
    rows = [game[role]["checkpoints"][str(day)] for game in games]
    return {
        metric: _distribution([float(row[metric]) for row in rows])
        for metric in ("money", "productive", "weeds", "free", "finished_ongoing", "seed_units")
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument(
        "--teacher-gap",
        type=Path,
        default=Path("data/analysis/v10_v9_teacher_gap.json"),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    run_path = args.run if args.run.is_absolute() else ROOT / args.run
    run = json.loads(run_path.read_text(encoding="utf-8"))
    games: list[dict[str, Any]] = []
    for game in run.get("games") or []:
        replay_path = ROOT / str(game["replay"])
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
        seat = int(game["seat"])
        games.append(
            {
                "seed": int(game["seed"]),
                "seat": seat,
                "our_reward": float(game["ours"]),
                "opponent_reward": float(game["theirs"]),
                "margin": float(game["margin"]),
                "ours": _seat_trace(replay, seat),
                "opponent": _seat_trace(replay, 1 - seat),
            }
        )
    teacher_path = args.teacher_gap if args.teacher_gap.is_absolute() else ROOT / args.teacher_gap
    teacher = json.loads(teacher_path.read_text(encoding="utf-8"))
    worst = min(games, key=lambda game: game["ours"]["checkpoints"]["24"]["productive"])
    result = {
        "objective": "Find general late-rotation and monetization causes; opponent is diagnostic only",
        "run": str(run_path.relative_to(ROOT)),
        "games": games,
        "aggregate": {
            role: {
                "checkpoints": {
                    str(day): _checkpoint_summary(games, role, day)
                    for day in (20, 24, 27, 29)
                },
                "rotation_field_per_game": _phase_average(games, role, "rotation", "field"),
                "rotation_market_quantity_per_game": _phase_average(
                    games, role, "rotation", "market"
                ),
                "liquidation_market_quantity_per_game": _phase_average(
                    games, role, "liquidation", "market"
                ),
            }
            for role in ("ours", "opponent")
        },
        "worst_day24": {
            "seed": worst["seed"],
            "seat": worst["seat"],
            "reward": worst["our_reward"],
            "margin": worst["margin"],
            "timeline": worst["ours"]["timeline"],
            "daily_field": worst["ours"]["daily_field"],
            "daily_market": worst["ours"]["daily_market"],
        },
        "rank1_reference": {
            "rotation": teacher["operations"]["rank1"]["rotation"],
            "day20": teacher["trajectory"]["rank1"]["20"],
            "day24": teacher["trajectory"]["rank1"]["24"],
        },
        "v9_public_reference": {
            "rotation": teacher["operations"]["v9"]["rotation"],
            "day20": teacher["trajectory"]["v9"]["20"],
            "day24": teacher["trajectory"]["v9"]["24"],
        },
    }
    output = args.output
    if output:
        output = output if output.is_absolute() else ROOT / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    public = {key: value for key, value in result.items() if key != "games"}
    print(json.dumps(public, ensure_ascii=False, indent=2))
    if output:
        print(f"result: {output}")


if __name__ == "__main__":
    main()
