"""Summarize operational KPIs from a run_match.py result and its replays."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MOVES = {"NORTH", "SOUTH", "EAST", "WEST"}
ANIMALS = ("COW", "SHEEP", "GOOSE")
CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
CHECKPOINTS = (7, 10, 12, 15, 20, 24, 27, 29)


def _count(inventory: dict[str, Any], item: str) -> int:
    return max(0, int(inventory.get(item, 0) or 0))


def _snapshot(obs: dict[str, Any], seat: int) -> dict[str, Any]:
    farm = obs["farms"][seat]
    private = obs.get("private") or {}
    crops: Counter[str] = Counter()
    placed: Counter[str] = Counter()
    pastures = 0
    weeds = 0
    for row in farm.get("tiles") or []:
        for tile in row:
            if not isinstance(tile, dict):
                continue
            if tile.get("kind") == "PLANT":
                crops[str(tile.get("crop"))] += 1
            if tile.get("kind") == "PASTURE":
                pastures += 1
            if tile.get("kind") == "WEED":
                weeds += 1
            if tile.get("animal") in ANIMALS:
                placed[str(tile["animal"])] += 1
    owned = Counter(placed)
    shed = private.get("shed") or {}
    for animal in ANIMALS:
        owned[animal] += _count(shed, animal)
        owned[animal] += sum(_count(inventory, animal) for inventory in private.get("inventories") or [])
    unlocked = len(farm.get("unlocked_quadrants") or [])
    productive = sum(crops.values()) + sum(placed.values())
    empty_structures = max(0, pastures - sum(placed.values()))
    return {
        "money": float(farm.get("money") or 0),
        "utilization": productive / max(25, unlocked * 25),
        "unlocked": unlocked,
        "productive": productive,
        "empty_tiles": max(0, unlocked * 25 - productive - weeds - empty_structures),
        "pastures": pastures,
        "weeds": weeds,
        "placed": dict(placed),
        "owned": dict(owned),
        "crops": dict(crops),
        "seed_units": sum(_count(private.get("seeds") or {}, crop) for crop in CROPS),
    }


def analyze_game(game: dict[str, Any]) -> dict[str, Any]:
    replay_path = ROOT / str(game["replay"])
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    seat = int(game["seat"])
    actions: Counter[str] = Counter()
    transitions: Counter[str] = Counter()
    plant_hours: Counter[int] = Counter()
    daily_field: dict[int, Counter[str]] = {}
    daily_market: dict[int, Counter[str]] = {}
    previous_actions: dict[int, str] = {}
    previous_observation: dict[str, Any] | None = None
    previous_action_day = -1
    hand_actions = 0
    hand_moves = 0
    checkpoints: dict[str, dict[str, Any]] = {}
    last_day = -1
    final_obs: dict[str, Any] = {}
    for states in replay.get("steps") or []:
        state = states[seat]
        obs = state.get("observation") or {}
        day = int(obs.get("day") or 0)
        if day != last_day:
            last_day = day
            if day in CHECKPOINTS:
                checkpoints[str(day)] = _snapshot(obs, seat)
        if previous_observation is None:
            previous_observation = obs
            final_obs = obs
            continue
        action_day = int(previous_observation.get("day") or 0)
        action_hour = int(previous_observation.get("hour") or 0)
        if action_day != previous_action_day:
            previous_action_day = action_day
            previous_actions = {}
        action = state.get("action") or {}
        units = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
        field_today = daily_field.setdefault(action_day, Counter())
        next_previous: dict[int, str] = {}
        for index, unit_action in enumerate(units):
            op = unit_action[0] if unit_action else "PASS"
            actions[op] += 1
            field_today[op] += 1
            previous = previous_actions.get(index)
            if previous is not None:
                transitions[f"{previous}->{op if op not in MOVES else 'MOVE'}"] += 1
            next_previous[index] = op
            if op == "PLANT":
                plant_hours[action_hour] += 1
                crop = str(unit_action[1]) if len(unit_action) > 1 else "UNKNOWN"
                field_today[f"PLANT_{crop}"] += 1
            if index > 0:
                hand_actions += 1
                hand_moves += op in MOVES
        previous_actions = next_previous
        market_today = daily_market.setdefault(action_day, Counter())
        for order in action.get("market") or []:
            if not order:
                continue
            op = str(order[0])
            item = str(order[1]) if len(order) > 1 else ""
            quantity = max(0, int(order[2])) if len(order) > 2 else 1
            market_today[op] += quantity
            if item:
                market_today[f"{op}_{item}"] += quantity
        previous_observation = obs
        final_obs = obs
    final = _snapshot(final_obs, seat)
    hires = sum(
        1
        for states in replay.get("steps") or []
        for order in ((states[seat].get("action") or {}).get("market") or [])
        if order and order[0] == "HIRE"
    )
    core = sum(actions[op] for op in ("HARVEST", "FEED", "CARE", "COLLECT_FERTILIZER", "FERTILIZE", "DIG", "PLANT"))
    return {
        "seat": seat,
        "reward": float(game["ours"]),
        "margin": float(game["margin"]),
        "movement_rate": hand_moves / hand_actions if hand_actions else 0.0,
        "core_work_per_hire": core / hires if hires else 0.0,
        "hires": hires,
        "actions": dict(actions),
        "transitions": dict(transitions),
        "plant_hours": {str(hour): count for hour, count in plant_hours.items()},
        "daily_field": {str(day): dict(counts) for day, counts in daily_field.items()},
        "daily_market": {str(day): dict(counts) for day, counts in daily_market.items()},
        "checkpoints": checkpoints,
        "final": final,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    run_path = args.run if args.run.is_absolute() else ROOT / args.run
    run = json.loads(run_path.read_text(encoding="utf-8"))
    games = [analyze_game(game) for game in run.get("games") or [] if game.get("replay")]
    action_names = sorted({op for game in games for op in game["actions"]})
    transition_names = sorted({transition for game in games for transition in game["transitions"]})
    summary = {
        "games": len(games),
        "mean_reward": mean(game["reward"] for game in games),
        "mean_margin": mean(game["margin"] for game in games),
        "movement_rate": mean(game["movement_rate"] for game in games),
        "core_work_per_hire": mean(game["core_work_per_hire"] for game in games),
        "action_avg": {
            op: mean(game["actions"].get(op, 0) for game in games) for op in action_names
        },
        "transition_avg": {
            transition: mean(game["transitions"].get(transition, 0) for game in games)
            for transition in transition_names
        },
        "plant_hour_avg": {
            str(hour): mean(game["plant_hours"].get(str(hour), 0) for game in games)
            for hour in range(24)
            if any(game["plant_hours"].get(str(hour), 0) for game in games)
        },
        "daily_activity": {
            str(day): {
                "field": {
                    key: mean(game["daily_field"].get(str(day), {}).get(key, 0) for game in games)
                    for key in sorted(
                        {
                            key
                            for game in games
                            for key in game["daily_field"].get(str(day), {})
                        }
                    )
                },
                "market": {
                    key: mean(game["daily_market"].get(str(day), {}).get(key, 0) for game in games)
                    for key in sorted(
                        {
                            key
                            for game in games
                            for key in game["daily_market"].get(str(day), {})
                        }
                    )
                },
            }
            for day in range(30)
            if any(
                game["daily_field"].get(str(day)) or game["daily_market"].get(str(day))
                for game in games
            )
        },
        "daily": {
            str(day): {
                **{
                    key: mean(
                        game["checkpoints"][str(day)][key]
                        for game in games
                        if str(day) in game["checkpoints"]
                    )
                    for key in (
                        "money",
                        "utilization",
                        "unlocked",
                        "productive",
                        "empty_tiles",
                        "pastures",
                        "weeds",
                        "seed_units",
                    )
                },
                "crops": {
                    crop: mean(
                        game["checkpoints"][str(day)]["crops"].get(crop, 0)
                        for game in games
                        if str(day) in game["checkpoints"]
                    )
                    for crop in CROPS
                },
                "animals": {
                    animal: mean(
                        game["checkpoints"][str(day)]["placed"].get(animal, 0)
                        for game in games
                        if str(day) in game["checkpoints"]
                    )
                    for animal in ANIMALS
                },
            }
            for day in CHECKPOINTS
            if any(str(day) in game["checkpoints"] for game in games)
        },
        "final_seed_units": mean(game["final"]["seed_units"] for game in games),
        "games_detail": games,
    }
    output = args.output
    if output:
        output = output if output.is_absolute() else ROOT / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    public_summary = {key: value for key, value in summary.items() if key != "games_detail"}
    print(json.dumps(public_summary, ensure_ascii=False, indent=2))
    if output:
        print(f"result: {output}")


if __name__ == "__main__":
    main()
