"""Separate V58 service coverage from changed animal/crop portfolio size."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v14 import main as v14  # noqa: E402
from scripts.analyze_v33_asset_labor import _actions, _farm, _positions  # noqa: E402
from scripts.train_v12_relative_policy import _observation  # noqa: E402

FORMAT = "kaggriculture-v59-v58-service-capacity-v1"
DAYS = tuple(range(6, 13))
RUN_PAIRS = {
    "v14_calibration": (
        Path("data/runs/v58_interaction_safe_v14_20265821.json"),
        Path("data/runs/v58_interaction_roles_v14_20265821.json"),
    ),
    "v14_holdout": (
        Path("data/runs/v58_interaction_safe_v14_holdout_20265831.json"),
        Path("data/runs/v58_interaction_roles_v14_holdout_20265831.json"),
    ),
    "v18_diagnostic": (
        Path("data/runs/v58_interaction_safe_v18_20265841.json"),
        Path("data/runs/v58_interaction_roles_v18_20265841.json"),
    ),
}


def _tiles(farm: Any) -> list[tuple[int, int, dict[str, Any]]]:
    result = []
    for y, row in enumerate((farm or {}).get("tiles") or []):
        for x, tile in enumerate(row):
            if isinstance(tile, dict):
                result.append((x, y, tile))
    return result


def _issued_final_service(
    replay: dict[str, Any], seat: int, step: int, op: str
) -> set[tuple[int, int]]:
    obs = _observation(replay, step, seat)
    if obs is None:
        return set()
    farm = _farm(obs, seat)
    positions = _positions(farm)
    actions = _actions(replay, step, seat)
    return {
        positions[unit]
        for unit in range(min(len(positions), len(actions)))
        if actions[unit] and str(actions[unit][0]) == op
    }


def _day(replay: dict[str, Any], seat: int, day: int) -> dict[str, float] | None:
    start = _observation(replay, day * 24, seat)
    final = _observation(replay, day * 24 + 23, seat)
    future = _observation(replay, (day + 1) * 24, seat)
    if start is None or final is None or future is None:
        return None
    start_farm = _farm(start, seat)
    final_farm = _farm(final, seat)
    future_farm = _farm(future, seat)
    final_animals = {
        (x, y): tile
        for x, y, tile in _tiles(final_farm)
        if tile.get("animal") in v14.base.ANIMAL_DATA
    }
    final_crops = {
        (x, y): tile
        for x, y, tile in _tiles(final_farm)
        if tile.get("kind") == "PLANT"
    }
    final_feed = _issued_final_service(replay, seat, day * 24 + 23, "FEED")
    final_care = _issued_final_service(replay, seat, day * 24 + 23, "CARE")
    final_water = _issued_final_service(replay, seat, day * 24 + 23, "WATER")
    fed = sum(
        bool(tile.get("fed_today", False)) or position in final_feed
        for position, tile in final_animals.items()
    )
    cared = sum(
        bool(tile.get("cared_today", False)) or position in final_care
        for position, tile in final_animals.items()
    )
    watered = sum(
        bool(tile.get("watered_today", False)) or position in final_water
        for position, tile in final_crops.items()
    )
    operations = {"FEED": 0, "CARE": 0, "WATER": 0, "PLACE": 0}
    for step in range(day * 24, (day + 1) * 24):
        for action in _actions(replay, step, seat):
            op = str(action[0]) if action else "PASS"
            if op in operations:
                operations[op] += 1
    start_summary = v14.base._farm_summary(start_farm)
    future_summary = v14.base._farm_summary(future_farm)
    animal_count = len(final_animals)
    crop_count = len(final_crops)
    return {
        "animal_count": float(animal_count),
        "crop_count": float(crop_count),
        "fed_count": float(fed),
        "cared_count": float(cared),
        "watered_count": float(watered),
        "feed_coverage": fed / max(1, animal_count),
        "care_coverage": cared / max(1, animal_count),
        "water_coverage": watered / max(1, crop_count),
        "feed_deficit": float(max(0, animal_count - fed)),
        "care_deficit": float(max(0, animal_count - cared)),
        "water_deficit": float(max(0, crop_count - watered)),
        "feed_actions": float(operations["FEED"]),
        "care_actions": float(operations["CARE"]),
        "water_actions": float(operations["WATER"]),
        "place_actions": float(operations["PLACE"]),
        "start_productive": float(start_summary["productive"]),
        "future_productive": float(future_summary["productive"]),
        "start_animals": float(start_summary["animal_total"]),
        "future_animals": float(future_summary["animal_total"]),
        "future_crops": float(sum(future_summary["crops"].values())),
        "future_money": float((future_farm or {}).get("money", 0) or 0),
    }


def _game(run_game: dict[str, Any]) -> dict[str, Any]:
    replay = json.loads((ROOT / run_game["replay"]).read_text(encoding="utf-8"))
    seat = int(run_game["seat"])
    days = [row for day in DAYS if (row := _day(replay, seat, day)) is not None]
    metrics = {
        metric: mean(row[metric] for row in days)
        for metric in days[0]
    }
    metrics.update(
        {
            "reward": float(run_game["ours"]),
            "margin": float(run_game["margin"]),
        }
    )
    return {
        "seed": int(run_game["seed"]),
        "seat": seat,
        "metrics": metrics,
    }


def _run(path: Path) -> list[dict[str, Any]]:
    payload = json.loads((ROOT / path).read_text(encoding="utf-8"))
    return [_game(game) for game in payload["games"]]


def _comparison(safe: list[dict[str, Any]], candidate: list[dict[str, Any]]) -> dict[str, Any]:
    if [(row["seed"], row["seat"]) for row in safe] != [
        (row["seed"], row["seat"]) for row in candidate
    ]:
        raise ValueError("paired run order mismatch")
    metrics = tuple(safe[0]["metrics"])
    deltas = [
        {
            metric: candidate_row["metrics"][metric] - safe_row["metrics"][metric]
            for metric in metrics
        }
        for safe_row, candidate_row in zip(safe, candidate, strict=True)
    ]
    return {
        "games": len(safe),
        "safe_mean": {
            metric: mean(row["metrics"][metric] for row in safe) for metric in metrics
        },
        "candidate_mean": {
            metric: mean(row["metrics"][metric] for row in candidate) for metric in metrics
        },
        "mean_delta": {
            metric: mean(row[metric] for row in deltas) for metric in metrics
        },
        "positive_reward_games": sum(row["reward"] > 0 for row in deltas),
        "negative_reward_games": sum(row["reward"] < 0 for row in deltas),
        "per_game_delta": [
            {
                "seed": safe_row["seed"],
                "seat": safe_row["seat"],
                **delta,
            }
            for safe_row, delta in zip(safe, deltas, strict=True)
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v59_v58_service_capacity.json"),
    )
    args = parser.parse_args()
    comparisons = {
        name: _comparison(_run(safe), _run(candidate))
        for name, (safe, candidate) in RUN_PAIRS.items()
    }
    payload = {
        "format": FORMAT,
        "runtime_policy_enabled": False,
        "objective": "determine whether V58 feed/care count changes are service failures or portfolio changes",
        "comparisons": comparisons,
        "interpretation_limits": [
            "hour-23 issued FEED/CARE/WATER is counted as completed by the deterministic legal executor",
            "coverage describes visible daily service, not hidden marginal product value",
            "V14/V18 interactions diagnose reachable states and are not leaderboard win-rate estimates",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                name: {
                    "games": value["games"],
                    "mean_delta": value["mean_delta"],
                    "positive_reward_games": value["positive_reward_games"],
                    "negative_reward_games": value["negative_reward_games"],
                }
                for name, value in comparisons.items()
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"result: {output}")


if __name__ == "__main__":
    main()
