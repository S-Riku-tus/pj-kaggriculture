"""Compare early capital allocation and pasture filling across V11 and Top 3."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v3.feature_schema import farm_summary  # noqa: E402
from agents.v11 import main as v11  # noqa: E402
from scripts.analyze_v33_asset_labor import _actions, _farm, _positions, _tile  # noqa: E402
from scripts.analyze_v34_labor_value import SOURCES, _market_actions, _stats  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    _manifest,
    _observation,
    _replay_path,
    _split,
)

FORMAT = "kaggriculture-v37-early-capital-v1"
DAYS = tuple(range(3, 11))
ANIMAL_COST = {"COW": 400, "SHEEP": 500}
SEED_COST = {"WHEAT": 10, "CARROT": 20, "TOMATO": 50, "STRAWBERRY": 100, "MELON": 80}


def _owned(obs: dict[str, Any], seat: int, animal: str) -> int:
    farm = _farm(obs, seat)
    placed = farm_summary(farm)["animals"].get(animal, 0)
    private = obs.get("private") or {}
    shed = int((private.get("shed") or {}).get(animal, 0) or 0)
    carried = sum(int((inventory or {}).get(animal, 0) or 0) for inventory in private.get("inventories", []))
    return int(placed + shed + carried)


def _successful_plants(
    replay: dict[str, Any], step: int, seat: int
) -> Counter[str]:
    obs = _observation(replay, step, seat)
    next_obs = _observation(replay, step + 1, seat)
    result: Counter[str] = Counter()
    if obs is None or next_obs is None:
        return result
    farm = _farm(obs, seat)
    next_farm = _farm(next_obs, seat)
    positions = _positions(farm)
    for unit, action in enumerate(_actions(replay, step, seat)):
        if unit >= len(positions) or len(action) < 2 or str(action[0]) != "PLANT":
            continue
        crop = str(action[1])
        after = _tile(next_farm, positions[unit])
        if isinstance(after, dict) and after.get("kind") == "PLANT" and after.get("crop") == crop:
            result[crop] += 1
    return result


def _day_row(
    replay: dict[str, Any], seat: int, source: str, episode_id: str, day: int
) -> dict[str, Any] | None:
    start = _observation(replay, day * 24, seat)
    end = _observation(replay, (day + 1) * 24, seat)
    if start is None or end is None:
        return None
    requested: Counter[str] = Counter()
    actual_animals: Counter[str] = Counter()
    actual_seeds: Counter[str] = Counter()
    for step in range(day * 24, (day + 1) * 24):
        obs = _observation(replay, step, seat)
        next_obs = _observation(replay, step + 1, seat)
        if obs is None or next_obs is None:
            continue
        for order in _market_actions(replay, step, seat):
            verb = str(order[0]) if order else "PASS"
            item = str(order[1]) if len(order) >= 2 else ""
            try:
                quantity = max(0, int(order[2])) if len(order) >= 3 else 1
            except (TypeError, ValueError):
                quantity = 0
            requested[f"{verb}:{item}" if item else verb] += quantity

        for animal in ANIMAL_COST:
            if any(
                len(order) >= 2
                and str(order[0]) == "BUY_ANIMAL"
                and str(order[1]) == animal
                for order in _market_actions(replay, step, seat)
            ):
                actual_animals[animal] += max(
                    0, _owned(next_obs, seat, animal) - _owned(obs, seat, animal)
                )

        plants = _successful_plants(replay, step, seat)
        current_seeds = (obs.get("private") or {}).get("seeds") or {}
        next_seeds = (next_obs.get("private") or {}).get("seeds") or {}
        for crop in SEED_COST:
            if any(
                len(order) >= 2
                and str(order[0]) == "BUY_SEED"
                and str(order[1]) == crop
                for order in _market_actions(replay, step, seat)
            ):
                delta = int(next_seeds.get(crop, 0) or 0) - int(current_seeds.get(crop, 0) or 0)
                actual_seeds[crop] += max(0, delta + plants[crop])

    farm = _farm(start, seat)
    end_farm = _farm(end, seat)
    summary = farm_summary(farm, day)
    end_summary = farm_summary(end_farm, day + 1)
    target_animals: dict[str, int] = {}
    target_crops: dict[str, int] = {}
    if source == "v11":
        farms = start.get("farms") or []
        player = int(start.get("player", seat))
        targets = v11._strategy_targets(start, farm, farms[1 - player], start.get("private") or {})
        target_animals = dict(targets[0])
        target_crops = dict(targets[1])
    return {
        "source": source,
        "episode_id": episode_id,
        "split": _split(episode_id),
        "day": day,
        "money_start": float(farm.get("money", 0) or 0),
        "money_end": float(end_farm.get("money", 0) or 0),
        "money_delta": float(end_farm.get("money", 0) or 0) - float(farm.get("money", 0) or 0),
        "animals_start": {
            animal: int(summary["animals"].get(animal, 0)) for animal in ANIMAL_COST
        },
        "animals_end": {
            animal: int(end_summary["animals"].get(animal, 0)) for animal in ANIMAL_COST
        },
        "empty_pastures_start": int(summary["empty_structures"]),
        "crops_start": dict(summary["crops"]),
        "requested": dict(requested),
        "actual_animal_buys": dict(actual_animals),
        "actual_seed_buys": dict(actual_seeds),
        "animal_spend": sum(actual_animals[item] * cost for item, cost in ANIMAL_COST.items()),
        "seed_spend": sum(actual_seeds[item] * cost for item, cost in SEED_COST.items()),
        "v11_target_animals": target_animals,
        "v11_target_crops": target_crops,
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "rows": len(rows),
        "episodes": len({row["episode_id"] for row in rows}),
        "money_start": _stats([row["money_start"] for row in rows]),
        "money_delta": _stats([row["money_delta"] for row in rows]),
        "cow_start": _stats([row["animals_start"]["COW"] for row in rows]),
        "sheep_start": _stats([row["animals_start"]["SHEEP"] for row in rows]),
        "empty_pastures_start": _stats([row["empty_pastures_start"] for row in rows]),
        "actual_cow_buys": _stats([row["actual_animal_buys"].get("COW", 0) for row in rows]),
        "actual_sheep_buys": _stats([row["actual_animal_buys"].get("SHEEP", 0) for row in rows]),
        "animal_spend": _stats([row["animal_spend"] for row in rows]),
        "seed_spend": _stats([row["seed_spend"] for row in rows]),
        "requested_per_game_day": {
            key: sum(float(row["requested"].get(key, 0)) for row in rows) / max(1, len(rows))
            for key in sorted({key for row in rows for key in row["requested"]})
        },
    }


def _episode_window(rows: list[dict[str, Any]], lower: int, upper: int) -> dict[str, Any]:
    selected = [row for row in rows if lower <= int(row["day"]) <= upper]
    by_episode: dict[str, list[dict[str, Any]]] = {}
    for row in selected:
        by_episode.setdefault(str(row["episode_id"]), []).append(row)
    aggregates = []
    for episode_rows in by_episode.values():
        aggregates.append(
            {
                "animal_spend": sum(row["animal_spend"] for row in episode_rows),
                "seed_spend": sum(row["seed_spend"] for row in episode_rows),
                "cow_buys": sum(row["actual_animal_buys"].get("COW", 0) for row in episode_rows),
                "sheep_buys": sum(row["actual_animal_buys"].get("SHEEP", 0) for row in episode_rows),
                "money_delta": sum(row["money_delta"] for row in episode_rows),
            }
        )
    return {
        "episodes": len(aggregates),
        **{
            name: _stats([row[name] for row in aggregates])
            for name in ("animal_spend", "seed_spend", "cow_buys", "sheep_buys", "money_delta")
        },
    }


def _v11_target_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        str(day): {
            "cow_target": _stats(
                [row["v11_target_animals"].get("COW", 0) for row in rows if row["day"] == day]
            ),
            "sheep_target": _stats(
                [row["v11_target_animals"].get("SHEEP", 0) for row in rows if row["day"] == day]
            ),
            "cow_owned_gap": _stats(
                [
                    row["v11_target_animals"].get("COW", 0) - row["animals_start"]["COW"]
                    for row in rows
                    if row["day"] == day
                ]
            ),
        }
        for day in DAYS
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=Path("data/analysis/v37_early_capital.json")
    )
    args = parser.parse_args()
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for source, directory in SOURCES.items():
        manifests = _manifest(directory)
        for index, manifest in enumerate(manifests, start=1):
            if index == 1 or index % 50 == 0:
                print(f"[{source} {index}/{len(manifests)}]", flush=True)
            episode_id = str(manifest["episode_id"])
            seat = int(manifest["submission_seat"])
            key = (source, episode_id, seat)
            if key in seen:
                continue
            seen.add(key)
            replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
            for day in DAYS:
                row = _day_row(replay, seat, source, episode_id, day)
                if row is not None:
                    rows.append(row)

    payload = {
        "format": FORMAT,
        "runtime_policy_enabled": False,
        "objective": "compare Day-3..10 fixed-cost capital allocation before the V11 layout gap",
        "data": {
            "rows": len(rows),
            "episodes": len({row["episode_id"] for row in rows}),
            "source_rows": dict(Counter(row["source"] for row in rows)),
            "episode_disjoint_split": True,
        },
        "daily_summary": {
            source: {
                str(day): _summary(
                    [row for row in rows if row["source"] == source and row["day"] == day]
                )
                for day in DAYS
            }
            for source in SOURCES
        },
        "window_summary": {
            source: {
                f"{lower}-{upper}": _episode_window(
                    [row for row in rows if row["source"] == source], lower, upper
                )
                for lower, upper in ((3, 5), (6, 8), (9, 10), (3, 10))
            }
            for source in SOURCES
        },
        "v11_target_summary": _v11_target_summary(
            [row for row in rows if row["source"] == "v11"]
        ),
        "interpretation_limits": [
            "animal and seed purchases are inferred from successful inventory-state changes",
            "requested SELL/BUY_PRODUCT quantities are not treated as committed quantities",
            "money change includes all sales, variable-price purchases, hires, and land",
            "capital allocation similarity is descriptive and not causal final-score value",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
