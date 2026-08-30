"""Explain Wheat pickup and FEED-chain residuals in complete replay sets."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MOVEMENT = {"NORTH", "SOUTH", "EAST", "WEST"}


def _tile(farm: dict[str, Any], position: list[int] | tuple[int, int]) -> dict[str, Any] | None:
    x, y = int(position[0]), int(position[1])
    tiles = farm.get("tiles") or []
    value = tiles[y][x] if 0 <= y < len(tiles) and 0 <= x < len(tiles[y]) else None
    return value if isinstance(value, dict) else None


def _farm(obs: dict[str, Any], seat: int) -> dict[str, Any]:
    farms = obs.get("farms") or []
    player = int(obs.get("player", seat))
    return farms[player] if 0 <= player < len(farms) else {}


def _positions(farm: dict[str, Any]) -> list[list[int]]:
    return [list(farm.get("farmer") or [0, 0]), *(list(value) for value in (farm.get("hands") or []))]


def _actions(state: dict[str, Any]) -> list[list[Any]]:
    action = state.get("action") or {}
    return [list(action.get("farmer") or ["PASS"]), *(list(value) for value in (action.get("hands") or []))]


def _emergencies(obs: dict[str, Any], farm: dict[str, Any]) -> tuple[int, int]:
    hour = int(obs.get("hour", 0) or 0)
    unfed = 0
    unwatered = 0
    for row in farm.get("tiles") or []:
        for tile in row:
            if not isinstance(tile, dict):
                continue
            if tile.get("animal") and not bool(tile.get("fed_today", False)):
                unfed += int(tile.get("consecutive_unfed", 0) or 0) >= 1 or hour >= 18
            if tile.get("kind") == "PLANT" and not bool(tile.get("watered_today", False)):
                unwatered += int(tile.get("consecutive_unwatered", 0) or 0) >= 1 or hour >= 18
    return unfed, unwatered


def _phase(day: int) -> str:
    if day <= 5:
        return "opening_d0_5"
    if day <= 10:
        return "capital_d6_10"
    if day <= 20:
        return "growth_d11_20"
    if day <= 26:
        return "rotation_d21_26"
    return "liquidation_d27_29"


def analyze(entries: list[tuple[Path, int]]) -> dict[str, Any]:
    operations: Counter[str] = Counter()
    breaks: Counter[str] = Counter()
    pickup_amounts: Counter[int] = Counter()
    pickup_context: list[dict[str, float]] = []
    field_targets: Counter[tuple[str, str, str]] = Counter()
    harvested_units: Counter[tuple[str, str]] = Counter()
    market_sales: Counter[tuple[str, str]] = Counter()
    games = 0
    for path, seat in entries:
        replay = json.loads(path.read_text(encoding="utf-8"))
        steps = replay.get("steps") or []
        if len(steps) < 2:
            continue
        games += 1
        for index in range(len(steps) - 1):
            state = steps[index][seat]
            following = steps[index + 1][seat]
            obs = state.get("observation") or {}
            next_obs = following.get("observation") or {}
            farm = _farm(obs, seat)
            next_farm = _farm(next_obs, seat)
            actions = _actions(state)
            positions = _positions(farm)
            next_actions = _actions(following)
            next_positions = _positions(next_farm)
            phase = _phase(int(obs.get("day", 0) or 0))
            market = (state.get("action") or {}).get("market") or []
            for order in market:
                if len(order) >= 3 and order[0] == "SELL":
                    market_sales[(phase, str(order[1]))] += max(0, int(order[2] or 0))
            for unit, action in enumerate(actions):
                op = str(action[0]) if action else "PASS"
                operations[op] += 1
                tile = _tile(farm, positions[unit]) if unit < len(positions) else None
                crop = str((tile or {}).get("crop") or "")
                if crop and op in {"WATER", "FERTILIZE", "HARVEST"}:
                    field_targets[(phase, op, crop)] += 1
                    if op == "HARVEST":
                        harvested_units[(phase, crop)] += max(0, int((tile or {}).get("yield_units", 0) or 0))
                if op == "PICKUP" and len(action) >= 2 and action[1] == "WHEAT":
                    amount = max(0, int(action[2] if len(action) > 2 else 1))
                    pickup_amounts[amount] += 1
                    unfed = sum(
                        bool(isinstance(tile, dict) and tile.get("animal")) and not bool(tile.get("fed_today", False))
                        for row in farm.get("tiles") or []
                        for tile in row
                    )
                    pickup_context.append({"amount": float(amount), "unfed": float(unfed)})
                if op != "FEED" or unit >= len(next_actions):
                    continue
                next_op = str(next_actions[unit][0]) if next_actions[unit] else "PASS"
                if next_op not in MOVEMENT:
                    continue
                breaks["feed_to_move"] += 1
                if unit >= len(next_positions):
                    breaks["missing_unit"] += 1
                    continue
                tile = _tile(next_farm, next_positions[unit])
                if tile is None or not tile.get("animal"):
                    breaks["tile_missing_or_empty"] += 1
                    continue
                if bool(tile.get("cared_today", False)):
                    breaks["care_already_done"] += 1
                else:
                    breaks["care_remaining"] += 1
                emergency_feed, emergency_water = _emergencies(next_obs, next_farm)
                if emergency_feed:
                    breaks["with_emergency_feed"] += 1
                if emergency_water:
                    breaks["with_emergency_water"] += 1
                if not emergency_feed and not emergency_water:
                    breaks["without_emergency"] += 1
    pickups = sum(pickup_amounts.values())
    return {
        "games": games,
        "operations": dict(operations),
        "wheat_pickups": {
            "actions": pickups,
            "amount_distribution": dict(sorted(pickup_amounts.items())),
            "mean_amount": (
                sum(amount * count for amount, count in pickup_amounts.items()) / pickups if pickups else 0.0
            ),
            "mean_unfed_at_pickup": mean(row["unfed"] for row in pickup_context) if pickup_context else 0.0,
            "units_per_feed": (
                sum(amount * count for amount, count in pickup_amounts.items()) / max(1, operations["FEED"])
            ),
        },
        "feed_breaks": dict(breaks),
        "field_targets": {
            phase: {
                operation: {
                    crop: count / games
                    for (target_phase, target_operation, crop), count in sorted(field_targets.items())
                    if target_phase == phase and target_operation == operation
                }
                for operation in ("WATER", "FERTILIZE", "HARVEST")
            }
            for phase in (
                "opening_d0_5",
                "capital_d6_10",
                "growth_d11_20",
                "rotation_d21_26",
                "liquidation_d27_29",
            )
        },
        "harvested_units": {
            phase: {
                crop: count / games
                for (target_phase, crop), count in sorted(harvested_units.items())
                if target_phase == phase
            }
            for phase in (
                "opening_d0_5",
                "capital_d6_10",
                "growth_d11_20",
                "rotation_d21_26",
                "liquidation_d27_29",
            )
        },
        "market_sales": {
            phase: {
                item: count / games
                for (target_phase, item), count in sorted(market_sales.items())
                if target_phase == phase
            }
            for phase in (
                "opening_d0_5",
                "capital_d6_10",
                "growth_d11_20",
                "rotation_d21_26",
                "liquidation_d27_29",
            )
        },
    }


def _run_entries(path: Path) -> list[tuple[Path, int]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        (
            replay if (replay := Path(game["replay"])).is_absolute() else ROOT / replay,
            int(game["seat"]),
        )
        for game in payload.get("games") or []
    ]


def _teacher_entries(directory: Path, limit: int) -> list[tuple[Path, int]]:
    with (directory / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = [
            row
            for row in csv.DictReader(handle)
            if row.get("replay_status") in {"downloaded", "skipped_existing"}
            and row.get("team_name") != row.get("opponent_team_name")
        ][:limit]
    result = []
    for row in rows:
        replay = ROOT / row["replay_path"]
        replay = replay if replay.is_file() else ROOT / "data" / row["replay_path"]
        result.append((replay, int(row["submission_seat"])))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--run", type=Path)
    source.add_argument("--teacher", type=Path)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.run:
        path = args.run if args.run.is_absolute() else ROOT / args.run
        entries = _run_entries(path)
    else:
        path = args.teacher if args.teacher.is_absolute() else ROOT / args.teacher
        entries = _teacher_entries(path, args.limit)
    result = analyze(entries)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
