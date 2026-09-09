"""Bronze replay analysis of post-trigger Sheep continuation co-movements.

This script is descriptive E1 evidence only.  It never converts replay action
trajectories into a closed-loop win-rate claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import train_v111_strategy as trainer  # noqa: E402

START = 216
WINDOWS = {"h72": 288, "h144": 360, "terminal": 719}
ANIMALS = ("COW", "SHEEP", "GOOSE")
CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
SELL_PRODUCTS = (*CROPS, "EGG", "MILK", "WOOL", "FERTILIZER")
MARKET_BUY_OPS = {"BUY_PRODUCT", "BUY_SEED", "BUY_ANIMAL", "BUY_LAND", "HIRE"}


def _private_units(private: dict[str, Any], item: str) -> int:
    return max(0, int((private.get("shed") or {}).get(item, 0) or 0)) + sum(
        max(0, int((inventory or {}).get(item, 0) or 0))
        for inventory in private.get("inventories") or []
    )


def _private_seed_units(private: dict[str, Any], crop: str) -> int:
    return max(0, int((private.get("seeds") or {}).get(crop, 0) or 0))


def _farm(obs: dict[str, Any], seat: int) -> dict[str, Any]:
    farms = list(obs.get("farms") or [])
    return farms[seat] if seat < len(farms) else {}


def _worker_positions(farm: dict[str, Any]) -> list[list[int]]:
    return [list(farm.get("farmer") or []), *[list(value) for value in (farm.get("hands") or [])]]


def _tile(farm: dict[str, Any], position: list[int]) -> dict[str, Any] | None:
    if len(position) != 2:
        return None
    x, y = int(position[0]), int(position[1])
    tiles = farm.get("tiles") or []
    if not (0 <= y < len(tiles) and 0 <= x < len(tiles[y])):
        return None
    value = tiles[y][x]
    return value if isinstance(value, dict) else None


def _portfolio(farm: dict[str, Any]) -> Counter[str]:
    result: Counter[str] = Counter()
    for row in farm.get("tiles") or []:
        for tile in row or []:
            if not isinstance(tile, dict):
                continue
            if tile.get("crop"):
                result[str(tile["crop"])] += 1
            if tile.get("animal"):
                result[str(tile["animal"])] += 1
    return result


def _timing(values: list[tuple[int, int]]) -> dict[str, float | None]:
    if not values:
        return {
            "active": 0.0,
            "active_steps": 0.0,
            "first_step": None,
            "mean_step": None,
            "last_step": None,
        }
    total = sum(quantity for _, quantity in values)
    return {
        "active": 1.0,
        "active_steps": float(len({step for step, _ in values})),
        "first_step": float(min(step for step, _ in values)),
        "mean_step": sum(step * quantity for step, quantity in values) / total,
        "last_step": float(max(step for step, _ in values)),
    }


def _window(replay: dict[str, Any], seat: int, end: int) -> dict[str, float | None]:
    before = trainer._observation(replay, START, seat) or {}
    end_step = min(end, len(replay.get("steps") or []) - 1)
    after = trainer._observation(replay, end_step, seat) or {}
    before_farm = _farm(before, seat)
    after_farm = _farm(after, seat)
    before_portfolio = _portfolio(before_farm)
    after_portfolio = _portfolio(after_farm)
    operations: Counter[str] = Counter()
    hand_operations: Counter[str] = Counter()
    market: Counter[str] = Counter()
    sale_steps: dict[str, list[tuple[int, int]]] = defaultdict(list)
    market_item_active_steps: dict[str, set[int]] = defaultdict(set)
    market_active_steps: set[int] = set()
    price_series: dict[str, list[float]] = defaultdict(list)
    inventory_series: dict[str, list[float]] = defaultdict(list)
    private_exposure: Counter[str] = Counter()
    marked_to_market_exposure: Counter[str] = Counter()
    requested_sell_value: Counter[str] = Counter()
    requested_sell_priced_units: Counter[str] = Counter()
    hand_slots = 0
    hand_active = 0
    first_animal_change: int | None = None
    animal_change_steps = 0
    for step in range(START, end_step):
        obs = trainer._observation(replay, step, seat) or {}
        farm = _farm(obs, seat)
        current_portfolio = _portfolio(farm)
        if (
            current_portfolio["COW"] != before_portfolio["COW"]
            or current_portfolio["SHEEP"] != before_portfolio["SHEEP"]
        ):
            animal_change_steps += 1
            if first_animal_change is None:
                first_animal_change = step
        private = obs.get("private") or {}
        public_market = obs.get("market") or {}
        prices = public_market.get("prices") or {}
        inventories = public_market.get("inventory") or {}
        for product in SELL_PRODUCTS:
            price = float(prices.get(product, 0) or 0)
            inventory = float(inventories.get(product, 0) or 0)
            units = float(_private_units(private, product))
            price_series[product].append(price)
            inventory_series[product].append(inventory)
            private_exposure[product] += units
            marked_to_market_exposure[product] += units * price
        emitted = trainer._action(replay, step, seat)
        actors = [emitted.get("farmer") or ["PASS"], *(emitted.get("hands") or [])]
        positions = _worker_positions(farm)
        hand_slots += max(0, len(actors) - 1)
        for index, actor_action in enumerate(actors):
            op = str(actor_action[0]) if actor_action else "PASS"
            operations[op] += 1
            if index > 0 and op != "PASS":
                hand_active += 1
            if index > 0:
                hand_operations[op] += 1
            tile = _tile(farm, positions[index]) if index < len(positions) else None
            item = ""
            if op == "PLANT" and len(actor_action) >= 2:
                item = str(actor_action[1])
            elif tile is not None:
                item = str(tile.get("crop") or "")
                animal = str(tile.get("animal") or "")
                if animal == "COW":
                    item = "MILK"
                elif animal == "SHEEP":
                    item = "WOOL"
                elif animal == "GOOSE":
                    item = "EGG"
            if item:
                operations[f"{op}_{item}_ACTIONS"] += 1
                if index > 0:
                    hand_operations[f"{op}_{item}_ACTIONS"] += 1
            if op == "HARVEST" and item and tile is not None:
                quantity = max(0, int(tile.get("yield_units", 0) or 0))
                operations[f"HARVEST_{item}_UNITS"] += quantity
        for order in emitted.get("market") or []:
            if not isinstance(order, list) or not order:
                continue
            op = str(order[0])
            item = str(order[1]) if len(order) >= 2 else ""
            quantity = max(0, int(order[2] or 0)) if len(order) >= 3 else 1
            market["ORDER_COUNT"] += 1
            market[op] += quantity
            market[f"{op}_ORDER_COUNT"] += 1
            market_active_steps.add(step)
            if item:
                market[f"{op}_{item}"] += quantity
                market_item_active_steps[item].add(step)
            if op == "SELL" and item:
                sale_steps[item].append((step, quantity))
                price = float(prices.get(item, 0) or 0)
                if price > 0:
                    requested_sell_value[item] += quantity * price
                    requested_sell_priced_units[item] += quantity
    before_private = before.get("private") or {}
    after_private = after.get("private") or {}
    after_market = after.get("market") or {}
    after_prices = after_market.get("prices") or {}
    after_inventories = after_market.get("inventory") or {}
    step_count = max(0, end_step - START)
    result: dict[str, float | None] = {
        "window_steps": float(step_count),
        "cow_delta": float(after_portfolio["COW"] - before_portfolio["COW"]),
        "sheep_delta": float(after_portfolio["SHEEP"] - before_portfolio["SHEEP"]),
        "goose_delta": float(after_portfolio["GOOSE"] - before_portfolio["GOOSE"]),
        "wheat_crop_delta": float(after_portfolio["WHEAT"] - before_portfolio["WHEAT"]),
        "wheat_held_delta": float(
            _private_units(after_private, "WHEAT") - _private_units(before_private, "WHEAT")
        ),
        "feed_actions": float(operations["FEED"]),
        "care_actions": float(operations["CARE"]),
        "harvest_actions": float(operations["HARVEST"]),
        "harvest_wheat_units": float(operations["HARVEST_WHEAT_UNITS"]),
        "harvest_wool_units": float(operations["HARVEST_WOOL_UNITS"]),
        "harvest_milk_units": float(operations["HARVEST_MILK_UNITS"]),
        "hand_slots": float(hand_slots),
        "hand_active_actions": float(hand_active),
        "hand_active_rate": hand_active / hand_slots if hand_slots else 0.0,
        "mean_hands_available": hand_slots / step_count if step_count else 0.0,
        "hand_feed_actions": float(hand_operations["FEED"]),
        "hand_care_actions": float(hand_operations["CARE"]),
        "hand_harvest_actions": float(hand_operations["HARVEST"]),
        "hand_plant_actions": float(hand_operations["PLANT"]),
        "hand_water_actions": float(hand_operations["WATER"]),
        "buy_wheat_units": float(market["BUY_PRODUCT_WHEAT"]),
        "buy_wheat_seed_units": float(market["BUY_SEED_WHEAT"]),
        "sell_wheat_units": float(market["SELL_WHEAT"]),
        "sell_wool_units": float(market["SELL_WOOL"]),
        "sell_milk_units": float(market["SELL_MILK"]),
        "market_requested_order_count": float(market["ORDER_COUNT"]),
        "market_requested_buy_order_count": float(
            sum(market[f"{op}_ORDER_COUNT"] for op in MARKET_BUY_OPS)
        ),
        "market_requested_sell_order_count": float(market["SELL_ORDER_COUNT"]),
        "market_active_steps": float(len(market_active_steps)),
        "market_active_rate": len(market_active_steps) / step_count if step_count else 0.0,
        "market_requested_buy_units": float(
            sum(market[op] for op in ("BUY_PRODUCT", "BUY_SEED", "BUY_ANIMAL"))
        ),
        "market_requested_sell_units": float(market["SELL"]),
        "market_hire_orders": float(market["HIRE"]),
        "market_buy_land_orders": float(market["BUY_LAND"]),
        "first_animal_change_step": float(first_animal_change) if first_animal_change is not None else None,
        "animal_changed_state_count": float(animal_change_steps),
    }
    for op in ("FEED", "CARE"):
        for animal, product in (("COW", "MILK"), ("SHEEP", "WOOL"), ("GOOSE", "EGG")):
            result[f"{op.lower()}_{animal.lower()}_actions"] = float(
                operations[f"{op}_{product}_ACTIONS"]
            )
    for crop in CROPS:
        key = crop.lower()
        result[f"{key}_crop_delta"] = float(
            after_portfolio[crop] - before_portfolio[crop]
        )
        result[f"{key}_seed_delta"] = float(
            _private_seed_units(after_private, crop) - _private_seed_units(before_private, crop)
        )
        result[f"{key}_held_delta"] = float(
            _private_units(after_private, crop) - _private_units(before_private, crop)
        )
        result[f"plant_{key}_actions"] = float(operations[f"PLANT_{crop}_ACTIONS"])
        result[f"water_{key}_actions"] = float(operations[f"WATER_{crop}_ACTIONS"])
        result[f"harvest_{key}_actions"] = float(operations[f"HARVEST_{crop}_ACTIONS"])
        result[f"harvest_{key}_units"] = float(operations[f"HARVEST_{crop}_UNITS"])
        result[f"buy_{key}_seed_units"] = float(market[f"BUY_SEED_{crop}"])
        result[f"sell_{key}_units"] = float(market[f"SELL_{crop}"])
    other_crops = CROPS[1:]
    aggregate_keys = {
        "crop_delta": lambda crop: f"{crop.lower()}_crop_delta",
        "plant_actions": lambda crop: f"plant_{crop.lower()}_actions",
        "water_actions": lambda crop: f"water_{crop.lower()}_actions",
        "harvest_actions": lambda crop: f"harvest_{crop.lower()}_actions",
        "harvest_units": lambda crop: f"harvest_{crop.lower()}_units",
        "buy_seed_units": lambda crop: f"buy_{crop.lower()}_seed_units",
        "sell_units": lambda crop: f"sell_{crop.lower()}_units",
    }
    for suffix, metric_key in aggregate_keys.items():
        result[f"other_crops_{suffix}"] = sum(
            float(result[metric_key(crop)] or 0.0) for crop in other_crops
        )
    for product in SELL_PRODUCTS:
        key = product.lower()
        prices = price_series.get(product) or []
        inventories = inventory_series.get(product) or []
        boundary_prices = [*prices, float(after_prices.get(product, 0) or 0)]
        boundary_inventories = [
            *inventories,
            float(after_inventories.get(product, 0) or 0),
        ]
        timing = _timing(sale_steps.get(product) or [])
        result[f"sell_{key}_active"] = timing["active"]
        result[f"sell_{key}_active_steps"] = timing["active_steps"]
        result[f"first_{key}_sell_step"] = timing["first_step"]
        result[f"mean_{key}_sell_step"] = timing["mean_step"]
        result[f"last_{key}_sell_step"] = timing["last_step"]
        result[f"market_{key}_active_steps"] = float(len(market_item_active_steps[product]))
        result[f"private_{key}_exposure_unit_steps"] = float(private_exposure[product])
        result[f"private_{key}_mean_units_exposed"] = (
            private_exposure[product] / step_count if step_count else 0.0
        )
        result[f"private_{key}_marked_to_market_coin_steps"] = float(
            marked_to_market_exposure[product]
        )
        priced_units = requested_sell_priced_units[product]
        result[f"requested_sell_{key}_public_value"] = float(requested_sell_value[product])
        result[f"requested_sell_{key}_mean_public_price"] = (
            requested_sell_value[product] / priced_units if priced_units else None
        )
        if boundary_prices:
            result[f"market_{key}_price_start"] = boundary_prices[0]
            result[f"market_{key}_price_end"] = boundary_prices[-1]
            result[f"market_{key}_price_change"] = boundary_prices[-1] - boundary_prices[0]
            result[f"market_{key}_price_mean"] = mean(boundary_prices)
            result[f"market_{key}_price_range"] = max(boundary_prices) - min(boundary_prices)
        if boundary_inventories:
            result[f"market_{key}_inventory_start"] = boundary_inventories[0]
            result[f"market_{key}_inventory_end"] = boundary_inventories[-1]
            result[f"market_{key}_inventory_change"] = (
                boundary_inventories[-1] - boundary_inventories[0]
            )
            result[f"market_{key}_inventory_mean"] = mean(boundary_inventories)
            result[f"market_{key}_inventory_range"] = (
                max(boundary_inventories) - min(boundary_inventories)
            )
    return result


def _flatten(record: dict[str, Any]) -> dict[str, float]:
    result: dict[str, float] = {}
    for window, values in record["windows"].items():
        for key, value in values.items():
            if isinstance(value, int | float) and math.isfinite(float(value)):
                result[f"{window}.{key}"] = float(value)
    return result


def _lineage_profiles(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["lineage"])].append(record)
    profiles: dict[str, dict[str, Any]] = {}
    for lineage, selected in sorted(
        grouped.items(), key=lambda item: (-len(item[1]), item[0])
    ):
        flattened = [_flatten(record) for record in selected]
        metrics = sorted({key for values in flattened for key in values})
        profiles[lineage] = {
            "episodes": len(selected),
            "episode_ids": [int(record["episode_id"]) for record in selected],
            "labels": dict(Counter(str(record["label"]) for record in selected)),
            "material_episodes": sum(bool(record["material_animal_change"]) for record in selected),
            "mean_predicted_tilt": mean(float(record["predicted_tilt"]) for record in selected),
            "mean_actual_tilt": mean(float(record["actual_tilt"]) for record in selected),
            "metric_means": {
                key: mean(values[key] for values in flattened if key in values)
                for key in metrics
            },
        }
    return profiles


def _summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    flattened = [_flatten(record) for record in records]
    metrics = sorted({key for values in flattened for key in values})
    episode = {
        key: mean(values[key] for values in flattened if key in values)
        for key in metrics
    }
    by_lineage: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_lineage[str(record["lineage"])].append(record)
    lineage_means: dict[str, dict[str, float]] = {}
    for lineage, selected in by_lineage.items():
        selected_flattened = [_flatten(record) for record in selected]
        lineage_means[lineage] = {
            key: mean(values[key] for values in selected_flattened if key in values)
            for key in metrics
            if any(key in values for values in selected_flattened)
        }
    lineage = {
        key: mean(values[key] for values in lineage_means.values() if key in values)
        for key in metrics
        if any(key in values for values in lineage_means.values())
    }
    return {
        "episodes": len(records),
        "distinct_lineages": len(by_lineage),
        "episode_weighted_means": episode,
        "lineage_weighted_means": lineage,
        "lineage_profiles": _lineage_profiles(records),
    }


def _mean_difference(
    left: dict[str, Any], right: dict[str, Any], weighting: str
) -> dict[str, float]:
    left_values = left[weighting]
    right_values = right[weighting]
    return {
        key: float(left_values[key]) - float(right_values[key])
        for key in sorted(left_values.keys() & right_values.keys())
    }


def _dominant_no_material_lineage(records: list[dict[str, Any]]) -> tuple[str | None, int]:
    counts = Counter(
        str(record["lineage"])
        for record in records
        if not bool(record["material_animal_change"])
    )
    if not counts:
        return None, 0
    lineage, count = min(counts.items(), key=lambda item: (-item[1], item[0]))
    return lineage, count


def _animal_movement_pattern(record: dict[str, Any]) -> str:
    def direction(value: float) -> str:
        if value > 0:
            return "up"
        if value < 0:
            return "down"
        return "flat"

    return (
        f"cow_{direction(float(record['actual_cow_delta']))}_"
        f"sheep_{direction(float(record['actual_sheep_delta']))}"
    )


def _correlation(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < 3:
        return None
    left = [value[0] for value in pairs]
    right = [value[1] for value in pairs]
    left_mean, right_mean = mean(left), mean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in pairs)
    denominator = math.sqrt(
        sum((x - left_mean) ** 2 for x in left) * sum((y - right_mean) ** 2 for y in right)
    )
    return numerator / denominator if denominator else None


def _lineage_correlations(
    records: list[dict[str, Any]],
) -> tuple[dict[str, float | None], dict[str, int]]:
    grouped: dict[str, list[tuple[float, dict[str, float]]]] = defaultdict(list)
    for record in records:
        grouped[str(record["lineage"])].append(
            (float(record["actual_tilt"]), _flatten(record))
        )
    metrics = sorted({key for selected in grouped.values() for _, values in selected for key in values})
    result: dict[str, float | None] = {}
    support: dict[str, int] = {}
    for metric in metrics:
        pairs = []
        for selected in grouped.values():
            values = [flattened[metric] for _, flattened in selected if metric in flattened]
            if values:
                pairs.append((mean(actual for actual, _ in selected), mean(values)))
        result[metric] = _correlation(pairs)
        support[metric] = len(pairs)
    return result, support


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_gate_rows(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows_detail")
    if not isinstance(rows, list):
        raise ValueError(f"gate audit has no rows_detail list: {path}")
    required = {
        "label",
        "source_name",
        "episode_id",
        "lineage",
        "seat",
        "replay_path",
        "predicted_tilt",
        "actual_tilt",
        "actual_cow_delta",
        "actual_sheep_delta",
        "max_abs_z",
    }
    for index, row in enumerate(rows):
        missing = required - set(row)
        if missing:
            raise ValueError(f"gate audit row {index} is missing {sorted(missing)}")
    return rows, {
        "path": str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path),
        "sha256": _sha256(path),
        "format": payload.get("format"),
        "dataset_rows": len(rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--gate-audit",
        type=Path,
        default=Path("data/analysis/v113_strategy_gate_audit_v2.json"),
        help="Frozen Development audit whose rows_detail selects the replay cohort.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v113_continuation_package_bronze_v2.json"),
    )
    args = parser.parse_args()
    gate_audit = args.gate_audit if args.gate_audit.is_absolute() else ROOT / args.gate_audit
    rows, gate_audit_provenance = _load_gate_rows(gate_audit)
    selected = [
        row
        for row in rows
        if float(row["max_abs_z"]) <= 4.0 and float(row["predicted_tilt"]) >= 1.5
    ]
    records = []
    for index, row in enumerate(selected, start=1):
        replay = json.loads((ROOT / row["replay_path"]).read_text(encoding="utf-8"))
        record = {
            key: row[key]
            for key in (
                "label",
                "source_name",
                "episode_id",
                "lineage",
                "seat",
                "predicted_tilt",
                "actual_tilt",
                "actual_cow_delta",
                "actual_sheep_delta",
            )
        }
        record["material_animal_change"] = abs(float(row["actual_tilt"])) >= 1.0
        record["windows"] = {
            name: _window(replay, int(row["seat"]), end) for name, end in WINDOWS.items()
        }
        records.append(record)
        if index % 20 == 0:
            print(f"processed {index}/{len(selected)}", flush=True)
    material = [record for record in records if record["material_animal_change"]]
    no_material = [record for record in records if not record["material_animal_change"]]
    dominant_lineage, dominant_count = _dominant_no_material_lineage(records)
    dominant_no_material = [
        record for record in no_material if record["lineage"] == dominant_lineage
    ]
    other_no_material = [
        record for record in no_material if record["lineage"] != dominant_lineage
    ]
    for record in records:
        if record["material_animal_change"]:
            record["continuation_archetype"] = "material_cow_to_sheep"
        elif record["lineage"] == dominant_lineage:
            record["continuation_archetype"] = "no_material_dominant_lineage"
        else:
            record["continuation_archetype"] = "no_material_other_lineages"
    correlations, correlation_support = _lineage_correlations(records)
    cohort_summaries = {
        "all_triggered": _summarize(records),
        "material_animal_change": _summarize(material),
        "no_material_animal_change": _summarize(no_material),
        "no_material_dominant_lineage": _summarize(dominant_no_material),
        "no_material_other_lineages": _summarize(other_no_material),
    }
    payload = {
        "format": "kaggriculture-v113-bronze-continuation-package-v2",
        "evidence_level": "E1_replay_descriptive_correlation",
        "evidence_ceiling": "E1_without_preregistered_lineage-held-out_prediction",
        "dataset_role": "Development",
        "production_eligible": False,
        "agent_change_authorized": False,
        "trigger_rule": "step216, max_abs_z <= 4, predicted Sheep-minus-Cow tilt >= 1.5",
        "source_gate_audit": gate_audit_provenance,
        "coverage": {
            "all_rows": len(rows),
            "triggered": len(records),
            "trigger_rate": len(records) / len(rows) if rows else None,
            "material": len(material),
            "no_material": len(no_material),
            "distinct_lineages": len({record["lineage"] for record in records}),
        },
        "animal_movement_characterization": {
            "label_horizon": "step216_to_step288_72_turn_state_delta",
            "material_pattern_counts": dict(
                Counter(_animal_movement_pattern(record) for record in material)
            ),
            "no_material_pattern_counts": dict(
                Counter(_animal_movement_pattern(record) for record in no_material)
            ),
            "material_cow_delta_distribution": dict(
                Counter(str(record["actual_cow_delta"]) for record in material)
            ),
            "material_sheep_delta_distribution": dict(
                Counter(str(record["actual_sheep_delta"]) for record in material)
            ),
            "interpretation": (
                "A positive Sheep-minus-Cow tilt is not automatically a literal Cow removal. "
                "The component deltas must be retained when forming a future continuation "
                "hypothesis."
            ),
        },
        "archetype_partition": {
            "selection_rule": (
                "The most frequent lineage among no-material triggers is isolated before "
                "cohort comparison; ties resolve by lexical lineage id."
            ),
            "dominant_no_material_lineage": dominant_lineage,
            "dominant_no_material_episodes": dominant_count,
            "dominant_share_of_no_material": (
                dominant_count / len(no_material) if no_material else None
            ),
            "other_no_material_episodes": len(other_no_material),
            "other_no_material_lineages": len(
                {record["lineage"] for record in other_no_material}
            ),
        },
        "cohorts": cohort_summaries,
        "cohort_differences": {
            "material_minus_all_no_material": {
                weighting: _mean_difference(
                    cohort_summaries["material_animal_change"],
                    cohort_summaries["no_material_animal_change"],
                    weighting,
                )
                for weighting in ("episode_weighted_means", "lineage_weighted_means")
            },
            "dominant_no_material_minus_other_no_material": {
                weighting: _mean_difference(
                    cohort_summaries["no_material_dominant_lineage"],
                    cohort_summaries["no_material_other_lineages"],
                    weighting,
                )
                for weighting in ("episode_weighted_means", "lineage_weighted_means")
            },
        },
        "lineage_weighted_actual_tilt_correlations": correlations,
        "lineage_correlation_support": correlation_support,
        "candidate_bundle_signals": {
            key: {
                "correlation": value,
                "lineage_support": correlation_support[key],
            }
            for key, value in correlations.items()
            if value is not None and abs(value) >= 0.30
        },
        "metric_definitions": {
            "window": (
                "Actions emitted from step216 inclusive to the named end step exclusive; "
                "state deltas compare observations at those boundary steps."
            ),
            "action_counts": (
                "Recorded requested actions, not a claim that every silent engine transaction "
                "committed. HARVEST *_units use pre-action tile yield_units."
            ),
            "hands": (
                "hand_slots counts available hand-turns; hand_active_rate excludes PASS only. "
                "Task counts are separately exposed for FEED/CARE/HARVEST/PLANT/WATER."
            ),
            "other_crops": (
                "CARROT, TOMATO, STRAWBERRY, and MELON; each crop also has separate portfolio, "
                "seed, held-product, planting, watering, harvest, buy-seed, and sale metrics."
            ),
            "sell_timing": (
                "Absolute replay step of requested SELL orders; mean is quantity-weighted. "
                "active and active_steps preserve coverage when a lineage never sells an item."
            ),
            "market_exposure": (
                "private_*_exposure_unit_steps integrates shed plus carried sellable units over "
                "pre-action observations. marked_to_market_coin_steps weights those units by "
                "the contemporaneous public price; it is diagnostic exposure, not realized PnL."
            ),
            "public_market": (
                "Per-product public price/inventory start, end, change, mean, and range. "
                "requested_sell_*_public_value prices emitted sells at that observation and is "
                "not audited committed revenue."
            ),
        },
        "interpretation_limits": [
            "Recorded Top actions are Bronze trajectories and cannot adapt to a changed focal policy.",
            (
                "Co-movement may reflect state, lineage, or continuation-package selection rather "
                "than an isolated causal effect."
            ),
            (
                "Any Sheep Continuation candidate must be implemented and evaluated later at E3/E4; "
                "this analysis cannot promote it."
            ),
            (
                "The dominant no-material lineage is an observed archetype, not evidence that "
                "its source name is an independent policy family."
            ),
            (
                "E2 requires a future preregistered lineage-held-out predictive test; this "
                "Development analysis remains E1 even when reported lineage-weighted."
            ),
        ],
        "records": records,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["coverage"], ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
