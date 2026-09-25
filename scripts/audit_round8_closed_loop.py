"""Independently reaggregate Round8 closed-loop replays and diagnostic traces."""

from __future__ import annotations

import copy
import csv
import gzip
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from kaggle_environments.envs.kaggriculture import kaggriculture as engine

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "round8_execution_reset_20260922"
RUNS = {
    "phase_b_f0": EXPERIMENT / "phase_b_f0",
    "phase_b_f1": EXPERIMENT / "phase_b_f1",
    "phase_b_f2": EXPERIMENT / "phase_b_f2",
    "phase_b_f2_no_plan": EXPERIMENT / "phase_b_f2_no_plan",
    "spatial_pure_v6": EXPERIMENT / "phase_c_spatial" / "pilot_pure_v6",
    "spatial_hybrid_v6": EXPERIMENT / "phase_c_spatial" / "pilot_hybrid_v6",
}
OUTPUT = EXPERIMENT / "independent_closed_loop_reaggregation_v1.json"
CSV_OUTPUT = EXPERIMENT / "independent_closed_loop_games_v1.csv"
WORK_OPS = {
    "PICKUP",
    "PLACE",
    "DROP",
    "PLANT",
    "WATER",
    "HARVEST",
    "FEED",
    "CARE",
    "FERTILIZE",
    "COLLECT_FERTILIZER",
    "DIG",
    "BUILD_COOP",
    "BUILD_PASTURE",
}
ANIMAL_PRODUCT = {"GOOSE": "EGG", "COW": "MILK", "SHEEP": "WOOL"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def focal(states: list[dict[str, Any]], seat: int) -> dict[str, Any]:
    public = copy.deepcopy(states[0]["observation"])
    private = states[seat]["observation"]
    public["player"] = seat
    public["private"] = copy.deepcopy(private["private"])
    return public


def units(action: dict[str, Any]) -> list[list[Any]]:
    return [list(action.get("farmer") or ["PASS"]), *[list(value) for value in action.get("hands") or []]]


def positions(farm: dict[str, Any]) -> list[list[int]]:
    return [list(farm["farmer"]), *[list(value) for value in farm.get("hands") or []]]


def fingerprint(observation: dict[str, Any], index: int) -> str:
    seat = int(observation["player"])
    farm = observation["farms"][seat]
    actor_positions = positions(farm)
    inventory = observation["private"].get("inventories", [])
    position = actor_positions[index]
    x, y = int(position[0]), int(position[1])
    value = {
        "position": position,
        "tile": farm["tiles"][y][x],
        "inventory": inventory[index] if index < len(inventory) else {},
        "shed": observation["private"].get("shed", {}),
        "seeds": observation["private"].get("seeds", {}),
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def blocked_plants(actor_actions: list[list[Any]], seeds: dict[str, Any]) -> set[str]:
    demand = Counter(
        str(action[1])
        for action in actor_actions
        if len(action) >= 2 and action[0] == "PLANT"
    )
    return {crop for crop, count in demand.items() if count > int(seeds.get(crop, 0))}


def replay_metrics(replay: dict[str, Any], seat: int) -> dict[str, Any]:
    first_hire = first_land = first_crop = first_animal = first_sale = None
    no_effect = Counter()
    requests = Counter()
    harvest = Counter()
    sales = Counter()
    work_requests = work_effects = target_duplicate_turns = 0
    max_crops = max_animals = max_hands = 0
    for record, states in enumerate(replay["steps"]):
        observation = focal(states, seat)
        farm = observation["farms"][seat]
        tiles = [tile for row in farm["tiles"] for tile in row if isinstance(tile, dict)]
        crop_count = sum(tile.get("kind") == "PLANT" for tile in tiles)
        animal_count = sum(bool(tile.get("animal")) for tile in tiles)
        max_crops = max(max_crops, crop_count)
        max_animals = max(max_animals, animal_count)
        max_hands = max(max_hands, len(farm.get("hands") or []))
        if first_land is None and len(farm.get("unlocked_quadrants") or []) > 1:
            first_land = record
        if first_crop is None and crop_count:
            first_crop = record
        if first_animal is None and animal_count:
            first_animal = record
        if record == 0:
            continue
        action = states[seat].get("action") or {}
        if first_hire is None and any(order and order[0] == "HIRE" for order in action.get("market") or []):
            first_hire = record
        before = focal(replay["steps"][record - 1], seat)
        shadow = copy.deepcopy(before)
        actor_actions = units(action)
        blocked = blocked_plants(actor_actions, shadow["private"].get("seeds", {}))
        targets = []
        for index, requested in enumerate(actor_actions):
            if index >= len(shadow["private"].get("inventories", [])) or not requested:
                continue
            op = str(requested[0])
            requests[op] += 1
            if op in WORK_OPS:
                work_requests += 1
                target = tuple(positions(shadow["farms"][seat])[index])
                targets.append((target, op))
            resolved = copy.deepcopy(requested)
            if len(resolved) >= 2 and resolved[0] == "PLANT" and resolved[1] in blocked:
                resolved = ["PASS"]
            before_hash = fingerprint(shadow, index)
            before_inventory = copy.deepcopy(shadow["private"]["inventories"][index])
            farm = shadow["farms"][seat]
            actor_position = positions(farm)[index]
            x, y = int(actor_position[0]), int(actor_position[1])
            target_before = copy.deepcopy(farm["tiles"][y][x])
            engine._apply_unit_action(
                farm,
                shadow["private"],
                index,
                resolved,
                10,
                int(shadow.get("day", 0)),
                24,
                100,
            )
            changed = before_hash != fingerprint(shadow, index)
            if op != "PASS" and not changed:
                no_effect[op] += 1
            if op in WORK_OPS and changed:
                work_effects += 1
            if op == "HARVEST" and changed and isinstance(target_before, dict):
                item = target_before.get("crop") or ANIMAL_PRODUCT.get(str(target_before.get("animal")))
                if item:
                    after_inventory = shadow["private"]["inventories"][index]
                    amount = int(after_inventory.get(item, 0)) - int(before_inventory.get(item, 0))
                    if amount > 0:
                        harvest[str(item)] += amount
        coordinate_counts = Counter(target for target, _op in targets)
        if any(count > 1 for count in coordinate_counts.values()):
            target_duplicate_turns += 1
        shed = shadow["private"].get("shed", {})
        bought_before_sale: set[str] = set()
        for order in action.get("market") or []:
            if not order:
                continue
            op = str(order[0])
            if op.startswith("BUY_") and len(order) >= 2:
                bought_before_sale.add(str(order[1]))
            if op != "SELL" or len(order) < 3:
                continue
            item, quantity = str(order[1]), max(0, int(order[2]))
            if item in bought_before_sale:
                continue
            actual = min(quantity, max(0, int(shed.get(item, 0))))
            shed[item] = int(shed.get(item, 0)) - actual
            if actual:
                sales[item] += actual
                if first_sale is None:
                    first_sale = record
    final = focal(replay["steps"][-1], seat)
    return {
        "stored_states": len(replay["steps"]),
        "independent_final_cash": float(final["farms"][seat].get("money", 0)),
        "first_hire_record": first_hire,
        "first_land_record": first_land,
        "first_crop_record": first_crop,
        "first_animal_record": first_animal,
        "first_unambiguous_sale_record": first_sale,
        "max_hands": max_hands,
        "max_crops": max_crops,
        "max_animals": max_animals,
        "work_requests": work_requests,
        "work_effects": work_effects,
        "work_effect_rate": work_effects / max(1, work_requests),
        "no_effect_by_operation": dict(no_effect),
        "request_by_operation": dict(requests),
        "actual_harvest_units": dict(harvest),
        "unambiguous_actual_sell_units": dict(sales),
        "sell_limit": "sales after a prior same-item BUY in the same turn are excluded as ambiguous",
        "same_coordinate_multiwork_turns": target_duplicate_turns,
    }


def trace_metrics(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"available": False}
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        diagnostic = json.load(stream)
    traces = [row for rows in (diagnostic.get("trace") or {}).values() for row in rows]
    plan_interventions = plan_changes = raw_mask_changes = final_changes = 0
    effect_status = Counter()
    for row in traces:
        interventions = row.get("plan", {}).get("interventions", [])
        plan_interventions += len(interventions)
        plan_changes += sum(value.get("before") != value.get("after") for value in interventions)
        raw_mask_changes += sum(
            actor.get("raw_model", {}).get("token") != actor.get("mask", {}).get("token")
            for actor in row.get("decoder", {}).get("actors", [])
        )
        final_changes += int(row.get("plan_action") != row.get("final_action"))
        effect_status[str(row.get("effect", {}).get("status", "UNKNOWN"))] += 1
    return {
        "available": True,
        "trace_records": len(traces),
        "plan_interventions": plan_interventions,
        "plan_action_changes": plan_changes,
        "plan_intervention_rate": plan_changes / max(1, len(traces)),
        "raw_to_mask_token_changes": raw_mask_changes,
        "plan_to_final_changed_turns": final_changes,
        "effect_status": dict(effect_status),
        "diagnostic_sha256": sha256(path),
    }


def main() -> None:
    if OUTPUT.exists() or CSV_OUTPUT.exists():
        raise FileExistsError("refusing to overwrite independent Round8 reaggregation")
    games = []
    for arm, directory in RUNS.items():
        with (directory / "games.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            replay_path = ROOT / row["replay"]
            with gzip.open(replay_path, "rt", encoding="utf-8") as stream:
                replay = json.load(stream)
            seat = int(row["seat"])
            metrics = replay_metrics(replay, seat)
            diagnostic_path = ROOT / row["diagnostics"] if row.get("diagnostics") else Path()
            trace = trace_metrics(diagnostic_path)
            reported = float(row["our_cash"])
            games.append(
                {
                    "arm": arm,
                    "anchor": row["anchor"],
                    "seed": int(row["seed"]),
                    "seat": seat,
                    "reported_cash": reported,
                    "cash_matches": reported == metrics["independent_final_cash"],
                    "replay": row["replay"],
                    "replay_sha256": sha256(replay_path),
                    **metrics,
                    **{f"trace_{key}": value for key, value in trace.items()},
                }
            )
    summaries = {}
    for arm in RUNS:
        selected = [row for row in games if row["arm"] == arm]
        summaries[arm] = {
            "games": len(selected),
            "all_cash_recounts_match": all(row["cash_matches"] for row in selected),
            "mean_cash": mean(row["independent_final_cash"] for row in selected),
            "games_with_hire": sum(row["first_hire_record"] is not None for row in selected),
            "games_with_crop": sum(row["first_crop_record"] is not None for row in selected),
            "games_with_animal": sum(row["first_animal_record"] is not None for row in selected),
            "games_with_sale": sum(row["first_unambiguous_sale_record"] is not None for row in selected),
            "harvest_units": dict(sum((Counter(row["actual_harvest_units"]) for row in selected), Counter())),
            "sell_units": dict(
                sum((Counter(row["unambiguous_actual_sell_units"]) for row in selected), Counter())
            ),
            "work_effect_rate": sum(row["work_effects"] for row in selected)
            / max(1, sum(row["work_requests"] for row in selected)),
            "no_effect_by_operation": dict(
                sum((Counter(row["no_effect_by_operation"]) for row in selected), Counter())
            ),
            "mean_plan_intervention_rate": mean(
                float(row.get("trace_plan_intervention_rate", 0)) for row in selected
            ),
        }
    payload = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "purpose": "post-hoc independent replay cash/effect reaggregation; does not alter policy execution",
        "engine_sha256": sha256(
            ROOT / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py"
        ),
        "summaries": summaries,
        "games": games,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    flat_fields = [
        "arm",
        "anchor",
        "seed",
        "seat",
        "reported_cash",
        "independent_final_cash",
        "cash_matches",
        "first_hire_record",
        "first_land_record",
        "first_crop_record",
        "first_animal_record",
        "first_unambiguous_sale_record",
        "max_hands",
        "max_crops",
        "max_animals",
        "work_requests",
        "work_effects",
        "work_effect_rate",
        "same_coordinate_multiwork_turns",
        "replay",
        "replay_sha256",
    ]
    with CSV_OUTPUT.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=flat_fields)
        writer.writeheader()
        writer.writerows({key: row.get(key) for key in flat_fields} for row in games)
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
