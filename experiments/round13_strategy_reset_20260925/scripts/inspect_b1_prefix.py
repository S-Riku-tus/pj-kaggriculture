"""Print a compact, deterministic trace of a saved B1 opening.

This script is diagnostic only: it reads a reactive replay produced in Round12
and never evaluates a counterfactual action against a fixed opponent tape.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter
from pathlib import Path


def board_summary(observation: dict, seat: int) -> dict:
    crops: Counter[str] = Counter()
    animals: Counter[str] = Counter()
    animal_cells: list[dict] = []
    crop_cells: list[dict] = []
    empty: list[list[int]] = []
    farm = observation["farms"][seat]
    for y, row in enumerate(farm["tiles"]):
        for x, tile in enumerate(row):
            if tile is None:
                empty.append([x, y])
            elif isinstance(tile, dict) and tile.get("kind") == "PLANT":
                crops[tile["crop"]] += 1
                crop_cells.append({"xy": [x, y], "crop": tile["crop"], "yield": tile.get("yield_units", 0)})
            elif isinstance(tile, dict) and tile.get("animal"):
                animals[tile["animal"]] += 1
                animal_cells.append(
                    {
                        "xy": [x, y],
                        "animal": tile["animal"],
                        "yield": tile.get("yield_units", 0),
                        "fertilizer": tile.get("fertilizer_available", False),
                        "fed": tile.get("fed_today", False),
                    }
                )
    return {
        "money": farm["money"],
        "farmer": farm["farmer"],
        "hands": len(farm["hands"]),
        "unlocked": farm["unlocked_quadrants"],
        "crops": dict(crops),
        "animals": dict(animals),
        "animal_cells": animal_cells,
        "crop_cells": crop_cells,
        "empty": empty,
        "shed": {k: v for k, v in observation["private"]["shed"].items() if v},
        "seeds": {k: v for k, v in observation["private"]["seeds"].items() if v},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("replay", type=Path)
    parser.add_argument("--seat", type=int, default=0)
    parser.add_argument("--through-step", type=int, default=96)
    parser.add_argument("--snapshots", default="0,24,48,65,72,96")
    args = parser.parse_args()
    with gzip.open(args.replay, "rt", encoding="utf-8") as stream:
        data = json.load(stream)
    snapshots = {int(value) for value in args.snapshots.split(",") if value}
    for record in data["decisions"]:
        step = int(record["step"])
        if step > args.through_step:
            break
        action = record["actions"][args.seat]
        commands = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
        active = [[index, command] for index, command in enumerate(commands) if command != ["PASS"]]
        market = action.get("market") or []
        if step in snapshots or market or any(command[1][0] in {"PLANT", "HARVEST", "BUILD_PASTURE", "PLACE"} for command in active):
            row = {
                "step": step,
                "day": record["observations"][args.seat]["day"],
                "hour": record["observations"][args.seat]["hour"],
                "market": market,
                "active": active,
            }
            if step in snapshots:
                row["state"] = board_summary(record["observations"][args.seat], args.seat)
            print(json.dumps(row, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
