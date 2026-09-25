"""Run the preregistered eight-game Round7 normal-start diagnostic pilot."""

from __future__ import annotations

import argparse
import copy
import csv
import gzip
import hashlib
import json
import math
import random
import shutil
import sys
import tarfile
import tempfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CANDIDATE = ROOT / "artifacts/submissions/learning_round7_20260922_arm_b_plan_v2.tar.gz"
ANCHORS = {
    "v122": ROOT / "artifacts/submissions/v122.tar.gz",
    "v124": ROOT / "artifacts/submissions/v124.tar.gz",
}
ALL_ANCHORS = {
    **ANCHORS,
    "v123": ROOT / "artifacts/submissions/v123.tar.gz",
}
SEEDS = (2026102201, 2026102202)
ENGINE = ROOT / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py"
OUTPUT = ROOT / "experiments/learning_round7_20260922/pilot"
ROUND6_REPLAYS = (
    ROOT / "experiments/learning_round6_20260922/development_evaluation/replays/round6_sequence_bc_v1"
)
SHED_ACCESS = {(4, 4), (5, 4), (4, 5), (5, 5)}
ANIMAL_PRODUCT = {"GOOSE": "EGG", "COW": "MILK", "SHEEP": "WOOL"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_extract(archive: Path, target: Path) -> Path:
    target.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive, "r:gz") as stream:
        stream.extractall(target, filter="data")
    main = target / "main.py"
    if not main.is_file():
        raise FileNotFoundError(main)
    return main


def run_game(task: dict[str, Any]) -> dict[str, Any]:
    sys.path.insert(0, str(Path(task["opponent_main"]).parent))
    sys.path.insert(0, str(Path(task["agent_main"]).parent))
    sys.path.insert(0, str(ROOT / "scripts"))
    from learning_next_evaluate import _run_game

    return _run_game(task)


def focal_observation(states: list[dict[str, Any]], seat: int) -> dict[str, Any]:
    public = states[0]["observation"]
    private = states[seat]["observation"]
    result = copy.deepcopy(public)
    result["player"] = seat
    result["private"] = copy.deepcopy(private["private"])
    return result


def units(action: dict[str, Any]) -> list[list[Any]]:
    return [list(action.get("farmer") or ["PASS"]), *[list(value) for value in action.get("hands") or []]]


def positions(farm: dict[str, Any]) -> list[list[int]]:
    return [list(farm["farmer"]), *[list(value) for value in farm.get("hands", [])]]


def inventory_total(private: dict[str, Any], item: str) -> int:
    return int(private.get("shed", {}).get(item, 0)) + sum(
        int(inventory.get(item, 0)) for inventory in private.get("inventories", [])
    )


def tile_counts(observation: dict[str, Any], seat: int) -> dict[str, int]:
    farm = observation["farms"][seat]
    tiles = [tile for row in farm["tiles"] for tile in row if isinstance(tile, dict)]
    return {
        "land_quadrants": len(farm.get("unlocked_quadrants", [])),
        "crop_cells": sum(tile.get("kind") == "PLANT" for tile in tiles),
        "mature_crop_cells": sum(tile.get("kind") == "PLANT" and int(tile.get("yield_units", 0)) > 0 for tile in tiles),
        "animals": sum("animal" in tile for tile in tiles),
        "animals_fed_today": sum("animal" in tile and bool(tile.get("fed_today")) for tile in tiles),
        "animal_product_units_on_tiles": sum(
            int(tile.get("yield_units", 0)) for tile in tiles if "animal" in tile
        ),
    }


def simulate_actor_shed(before: dict[str, Any], seat: int, action: dict[str, Any]) -> dict[str, int]:
    farm = before["farms"][seat]
    private = copy.deepcopy(before["private"])
    shed = private["shed"]
    inventories = private["inventories"]
    actor_positions = positions(farm)
    for index, request in enumerate(units(action)):
        if index >= len(actor_positions) or index >= len(inventories) or not request:
            continue
        op = str(request[0])
        position = tuple(actor_positions[index])
        inventory = inventories[index]
        if op == "PICKUP" and position in SHED_ACCESS and len(request) >= 2:
            item = str(request[1])
            quantity = max(0, int(request[2]) if len(request) >= 3 else 1)
            quantity = min(quantity, int(shed.get(item, 0)))
            shed[item] = int(shed.get(item, 0)) - quantity
            inventory[item] = int(inventory.get(item, 0)) + quantity
        elif op == "DROP" and position in SHED_ACCESS:
            for item, available in list(inventory.items()):
                room = max(0, 100 - sum(int(value) for value in shed.values()))
                moved = min(max(0, int(available)), room)
                shed[item] = int(shed.get(item, 0)) + moved
                inventory.pop(item, None)
        elif op == "PLACE" and position in SHED_ACCESS and len(request) >= 2:
            item = str(request[1])
            y, x = position[1], position[0]
            tile = farm["tiles"][y][x]
            structure = {"GOOSE": "COOP", "COW": "PASTURE", "SHEEP": "PASTURE"}.get(item)
            is_animal_placement = (
                structure is not None
                and isinstance(tile, dict)
                and tile.get("kind") == structure
                and "animal" not in tile
            )
            if not is_animal_placement:
                quantity = max(0, int(request[2]) if len(request) >= 3 else 1)
                quantity = min(quantity, int(inventory.get(item, 0)))
                room = max(0, 100 - sum(int(value) for value in shed.values()))
                quantity = min(quantity, room)
                shed[item] = int(shed.get(item, 0)) + quantity
                inventory[item] = int(inventory.get(item, 0)) - quantity
    return {str(item): int(value) for item, value in shed.items()}


def effect_counts(before: dict[str, Any], after: dict[str, Any], seat: int, action: dict[str, Any]) -> dict[str, Any]:
    farm = before["farms"][seat]
    actor_positions = positions(farm)
    actor_inventories = copy.deepcopy(before["private"]["inventories"])
    consumed_tiles: set[tuple[int, int]] = set()
    harvested = Counter()
    feed_successes = 0
    care_successes = 0
    for index, request in enumerate(units(action)):
        if index >= len(actor_positions) or index >= len(actor_inventories) or not request:
            continue
        x, y = actor_positions[index]
        tile = farm["tiles"][y][x]
        op = str(request[0])
        target = (x, y)
        if op == "HARVEST" and target not in consumed_tiles and isinstance(tile, dict):
            amount = int(tile.get("yield_units", 0))
            if amount > 0:
                item = tile.get("crop") or ANIMAL_PRODUCT.get(str(tile.get("animal")))
                if item:
                    harvested[str(item)] += amount
                    consumed_tiles.add(target)
        elif op == "FEED" and isinstance(tile, dict) and "animal" in tile and not tile.get("fed_today"):
            if int(actor_inventories[index].get("WHEAT", 0)) > 0 and target not in consumed_tiles:
                feed_successes += 1
                actor_inventories[index]["WHEAT"] -= 1
                consumed_tiles.add(target)
        elif op == "CARE" and isinstance(tile, dict) and "animal" in tile and not tile.get("cared_today"):
            if target not in consumed_tiles:
                care_successes += 1
                consumed_tiles.add(target)
    shed = simulate_actor_shed(before, seat, action)
    sold = Counter()
    ambiguous_sell_items: set[str] = set()
    for order in action.get("market") or []:
        if not order:
            continue
        op = str(order[0])
        item = str(order[1]) if len(order) >= 2 else ""
        quantity = max(0, int(order[2]) if len(order) >= 3 else 1)
        if op.startswith("BUY_"):
            ambiguous_sell_items.add(item)
        elif op == "SELL":
            actual = min(quantity, int(shed.get(item, 0)))
            shed[item] = int(shed.get(item, 0)) - actual
            sold[item] += actual
    return {
        "harvested": dict(harvested),
        "feed_successes": feed_successes,
        "care_successes": care_successes,
        "sold_units_exact_unless_prior_same_item_buy": dict(sold),
        "sell_items_with_prior_buy_ambiguity": sorted(ambiguous_sell_items & set(sold)),
    }


def first_divergence(candidate: dict[str, Any], baseline_path: Path, seat: int) -> dict[str, Any]:
    if not baseline_path.is_file():
        return {"available": False}
    with gzip.open(baseline_path, "rt", encoding="utf-8") as stream:
        baseline = json.load(stream)
    limit = min(len(candidate["steps"]), len(baseline["steps"]))
    for record in range(1, limit):
        left = candidate["steps"][record][seat].get("action")
        right = baseline["steps"][record][seat].get("action")
        if left != right:
            return {
                "available": True,
                "record": record,
                "input_state_step": record - 1,
                "candidate": left,
                "round6_sequence_bc_v1": right,
            }
    return {"available": True, "record": None}


def analyze_replay(path: Path, anchor: str, seed: int, seat: int) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        replay = json.load(stream)
    first_land = None
    first_animal_yield = None
    first_animal_harvest = None
    first_crop_harvest = None
    harvested = Counter()
    sold = Counter()
    feed_successes = 0
    care_successes = 0
    animal_exits: list[dict[str, Any]] = []
    sell_ambiguities: set[str] = set()
    for record in range(1, len(replay["steps"])):
        before = focal_observation(replay["steps"][record - 1], seat)
        after = focal_observation(replay["steps"][record], seat)
        before_counts = tile_counts(before, seat)
        after_counts = tile_counts(after, seat)
        if first_land is None and after_counts["land_quadrants"] > 1:
            first_land = record
        if first_animal_yield is None and after_counts["animal_product_units_on_tiles"] > 0:
            first_animal_yield = record
        if after_counts["animals"] < before_counts["animals"]:
            animal_exits.append(
                {
                    "record": record,
                    "count": before_counts["animals"] - after_counts["animals"],
                    "remaining_steps": len(replay["steps"]) - 1 - record,
                    "day_changed": int(after.get("day", 0)) != int(before.get("day", 0)),
                }
            )
        action = replay["steps"][record][seat].get("action") or {"farmer": ["PASS"], "hands": [], "market": []}
        effects = effect_counts(before, after, seat, action)
        for item, amount in effects["harvested"].items():
            harvested[item] += amount
            if item in ANIMAL_PRODUCT.values() and first_animal_harvest is None:
                first_animal_harvest = record
            if item not in ANIMAL_PRODUCT.values() and item != "FERTILIZER" and first_crop_harvest is None:
                first_crop_harvest = record
        sold.update(effects["sold_units_exact_unless_prior_same_item_buy"])
        sell_ambiguities.update(effects["sell_items_with_prior_buy_ambiguity"])
        feed_successes += int(effects["feed_successes"])
        care_successes += int(effects["care_successes"])
    snapshots = {}
    for step in (192, len(replay["steps"]) - 1):
        observation = focal_observation(replay["steps"][step], seat)
        snapshots[str(step)] = {
            **tile_counts(observation, seat),
            "cash": float(observation["farms"][seat].get("money", 0)),
            "shed": observation["private"].get("shed", {}),
            "carried_wheat": sum(
                int(value.get("WHEAT", 0)) for value in observation["private"].get("inventories", [])
            ),
        }
    baseline = ROUND6_REPLAYS / anchor / f"seed_{seed}_seat_{seat}.json.gz"
    return {
        "first_land_record": first_land,
        "first_animal_yield_record": first_animal_yield,
        "first_animal_harvest_record": first_animal_harvest,
        "first_crop_harvest_record": first_crop_harvest,
        "successful_feed_actions": feed_successes,
        "successful_care_actions": care_successes,
        "actual_harvest_units": dict(harvested),
        "actual_sell_units": dict(sold),
        "sell_unit_limit": (
            "exact from pre-market shed unless the same item was bought earlier in the market sequence"
        ),
        "sell_items_with_prior_buy_ambiguity": sorted(sell_ambiguities),
        "animal_exits": animal_exits,
        "snapshots": snapshots,
        "first_action_divergence": first_divergence(replay, baseline, seat),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def block_statistics(rows: list[dict[str, Any]], anchors: dict[str, Path]) -> dict[str, Any]:
    result = {}
    for anchor in anchors:
        selected = [row for row in rows if row["anchor"] == anchor]
        by_seed: dict[int, list[float]] = {}
        for row in selected:
            by_seed.setdefault(int(row["seed"]), []).append(float(row["score"]))
        blocks = [mean(by_seed[seed]) for seed in sorted(by_seed)]
        point = mean(blocks) if blocks else 0.0
        radius = math.sqrt(math.log(1.0 / 0.05) / (2.0 * len(blocks))) if blocks else 1.0
        rng = random.Random(20260922 + sum(map(ord, anchor)))
        bootstrap = [mean(rng.choices(blocks, k=len(blocks))) for _ in range(10000)] if blocks else []
        bootstrap.sort()
        result[anchor] = {
            "games": len(selected),
            "seed_blocks": len(blocks),
            "wins": sum(float(row["score"]) == 1.0 for row in selected),
            "draws": sum(float(row["score"]) == 0.5 for row in selected),
            "losses": sum(float(row["score"]) == 0.0 for row in selected),
            "seed_block_point_rate": point,
            "one_sided_95_hoeffding_lower": max(0.0, point - radius),
            "descriptive_seed_block_bootstrap_95": (
                [bootstrap[int(0.025 * len(bootstrap))], bootstrap[int(0.975 * len(bootstrap)) - 1]]
                if bootstrap
                else [None, None]
            ),
            "mean_our_cash": mean(float(row["our_cash"]) for row in selected) if selected else None,
            "mean_margin": mean(float(row["margin"]) for row in selected) if selected else None,
            "point_threshold_0_60_met": point >= 0.60,
            "promotion_lower_above_0_50_met": point - radius > 0.50,
        }
    return result


def main(
    workers: int,
    candidate: Path,
    label: str,
    output: Path,
    anchors: dict[str, Path],
    seeds: tuple[int, ...],
    purpose: str,
) -> None:
    temp_parent = ROOT.parent / ".round7_tmp"
    temp_parent.mkdir(parents=True, exist_ok=True)
    extraction_root = Path(tempfile.mkdtemp(prefix="round7_pilot_", dir=temp_parent))
    output.mkdir(parents=True, exist_ok=True)
    try:
        mains = {label: safe_extract(candidate, extraction_root / label)}
        mains.update({name: safe_extract(path, extraction_root / name) for name, path in anchors.items()})
        tasks = [
            {
                "arm": label,
                "opponent": anchor,
                "seed": seed,
                "seat": seat,
                "agent_main": str(mains[label]),
                "opponent_main": str(mains[anchor]),
                "replay_path": str(output / "replays" / anchor / f"seed_{seed}_seat_{seat}.json.gz"),
            }
            for anchor in anchors
            for seed in seeds
            for seat in (0, 1)
        ]
        completed_rows = []
        failures = []
        with ProcessPoolExecutor(max_workers=workers, max_tasks_per_child=1) as executor:
            futures = {executor.submit(run_game, task): task for task in tasks}
            for index, future in enumerate(as_completed(futures), 1):
                task = futures[future]
                try:
                    result = future.result()
                    completed_rows.append(result)
                    print(
                        f"{index}/{len(tasks)} {task['opponent']} seed={task['seed']} seat={task['seat']} "
                        f"score={result['score']} margin={result['margin']}",
                        flush=True,
                    )
                except Exception as exc:
                    failures.append({**task, "error": f"{type(exc).__name__}: {exc}"})
                    print(f"{index}/8 FAILURE {failures[-1]['error']}", flush=True)
        rows = []
        shops = {}
        diagnostics_dir = output / "diagnostics"
        diagnostics_dir.mkdir(exist_ok=True)
        for result in sorted(completed_rows, key=lambda row: (row["opponent"], row["seed"], row["seat"])):
            replay_path = Path(result["replay_path"])
            lifecycle = analyze_replay(replay_path, result["opponent"], int(result["seed"]), int(result["seat"]))
            diagnostic_path = diagnostics_dir / (
                f"{result['opponent']}_seed_{result['seed']}_seat_{result['seat']}.json.gz"
            )
            with gzip.open(diagnostic_path, "wt", encoding="utf-8") as stream:
                json.dump(result.get("diagnostics", {}), stream, ensure_ascii=False, separators=(",", ":"))
            with gzip.open(replay_path, "rt", encoding="utf-8") as stream:
                replay = json.load(stream)
            shop_history = []
            prior = None
            for record, states in enumerate(replay["steps"]):
                current = states[0]["observation"]["town"].get("unlocked_shops", [])
                if current != prior:
                    shop_history.append({"record": record, "shops": current})
                    prior = current
            key = f"{result['opponent']}|{result['seed']}|{result['seat']}"
            shops[key] = shop_history
            rows.append(
                {
                    "candidate": result["arm"],
                    "anchor": result["opponent"],
                    "seed": result["seed"],
                    "seat": result["seat"],
                    "score": result["score"],
                    "our_cash": result["our_cash"],
                    "opponent_cash": result["opponent_cash"],
                    "margin": result["margin"],
                    "statuses": "/".join(result["statuses"]),
                    "states": result["stored_states"],
                    "elapsed_seconds": result["elapsed_seconds"],
                    "inference_p99_seconds": result["inference"]["p99_seconds"],
                    "inference_max_seconds": result["inference"]["max_seconds"],
                    "replay": str(replay_path.relative_to(ROOT)),
                    "replay_sha256": sha256(replay_path),
                    "diagnostics": str(diagnostic_path.relative_to(ROOT)),
                    "diagnostics_sha256": sha256(diagnostic_path),
                    "first_land_record": lifecycle["first_land_record"],
                    "first_animal_yield_record": lifecycle["first_animal_yield_record"],
                    "first_animal_harvest_record": lifecycle["first_animal_harvest_record"],
                    "first_crop_harvest_record": lifecycle["first_crop_harvest_record"],
                    "successful_feed_actions": lifecycle["successful_feed_actions"],
                    "successful_care_actions": lifecycle["successful_care_actions"],
                    "actual_harvest_units_json": json.dumps(lifecycle["actual_harvest_units"], sort_keys=True),
                    "actual_sell_units_json": json.dumps(lifecycle["actual_sell_units"], sort_keys=True),
                    "animal_exit_count": sum(value["count"] for value in lifecycle["animal_exits"]),
                    "state192_land": lifecycle["snapshots"]["192"]["land_quadrants"],
                    "state192_crops": lifecycle["snapshots"]["192"]["crop_cells"],
                    "state192_animals": lifecycle["snapshots"]["192"]["animals"],
                    "final_land": lifecycle["snapshots"]["719"]["land_quadrants"],
                    "final_crops": lifecycle["snapshots"]["719"]["crop_cells"],
                    "final_animals": lifecycle["snapshots"]["719"]["animals"],
                    "first_divergence_record": lifecycle["first_action_divergence"].get("record"),
                    "lifecycle_json": json.dumps(lifecycle, ensure_ascii=False, separators=(",", ":")),
                }
            )
        if rows:
            write_csv(output / "games.csv", rows)
        (output / "shop_histories.json").write_text(
            json.dumps(shops, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        summary = {
            "created_at_utc": datetime.now(UTC).isoformat(),
            "purpose": purpose,
            "candidate": {
                "archive": str(candidate.relative_to(ROOT)),
                "sha256": sha256(candidate),
            },
            "anchors": {
                name: {"archive": str(path.relative_to(ROOT)), "sha256": sha256(path)}
                for name, path in anchors.items()
            },
            "seeds": list(seeds),
            "seats": [0, 1],
            "v123_omitted_as_preregistered": "v123" not in anchors,
            "completed_games": len(rows),
            "failures": failures,
            "wins_draws_losses": {
                "wins": sum(float(row["score"]) == 1.0 for row in rows),
                "draws": sum(float(row["score"]) == 0.5 for row in rows),
                "losses": sum(float(row["score"]) == 0.0 for row in rows),
            },
            "mean_our_cash": mean(float(row["our_cash"]) for row in rows) if rows else None,
            "mean_margin": mean(float(row["margin"]) for row in rows) if rows else None,
            "games_with_first_animal_yield": sum(row["first_animal_yield_record"] not in (None, "") for row in rows),
            "games_with_first_animal_harvest": sum(
                row["first_animal_harvest_record"] not in (None, "") for row in rows
            ),
            "games_with_land_expansion": sum(row["first_land_record"] not in (None, "") for row in rows),
            "all_replays_included": len(rows) == len(tasks),
            "sealed_seeds_opened": False,
            "statistics_by_anchor": block_statistics(rows, anchors),
            "engine": {"version": "1.32.7", "source": str(ENGINE.relative_to(ROOT)), "sha256": sha256(ENGINE)},
        }
        (output / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        manifest = {
            "created_at_utc": datetime.now(UTC).isoformat(),
            "files": [
                {
                    "path": str(path.relative_to(ROOT)),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
                for path in sorted(output.rglob("*"))
                if path.is_file() and path.name != "evaluation_manifest.json"
            ],
        }
        (output / "evaluation_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        shutil.rmtree(extraction_root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--label", default="arm_b_plan_v2")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--full-development", action="store_true")
    arguments = parser.parse_args()
    anchors = ALL_ANCHORS if arguments.full_development else ANCHORS
    seeds = tuple(range(2026102201, 2026102209)) if arguments.full_development else SEEDS
    purpose = (
        "48-game development evaluation against v122/v123/v124; not sealed final confirmation"
        if arguments.full_development
        else "normal-start production/reinvestment diagnostic; not a win-rate estimate"
    )
    main(
        max(1, arguments.workers),
        arguments.candidate.resolve(),
        arguments.label,
        arguments.output.resolve(),
        anchors,
        seeds,
        purpose,
    )
