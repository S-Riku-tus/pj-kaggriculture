"""Relate early Cow purchase timing to financing and placement-day slippage.

This report separates three mechanisms that were conflated by raw placement
latency: the hour a Cow is bought, whether the purchase relies on same-turn
sales, and whether placement crosses a day boundary.  It remains descriptive;
the immediate-placement production schedule is a mechanics-based opportunity
count, not a causal score estimate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v3.feature_schema import farm_summary  # noqa: E402
from scripts.analyze_v33_asset_labor import _farm, _positions  # noqa: E402
from scripts.analyze_v34_labor_value import SOURCES, _market_actions, _stats  # noqa: E402
from scripts.analyze_v37_early_capital import _owned  # noqa: E402
from scripts.analyze_v38_animal_placement_latency import _side  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    _manifest,
    _observation,
    _replay_path,
    _split,
)

FORMAT = "kaggriculture-v39-cow-purchase-timing-v1"
FIRST_YIELD_DAY = 8
YIELD_INTERVAL = 2
FINAL_DAY = 30
EARLY_DAYS = tuple(range(3, 11))
HOUR_BANDS = {
    "early_0-11": range(0, 12),
    "mid_12-17": range(12, 18),
    "late_18-20": range(18, 21),
    "deadline_21-23": range(21, 24),
}


def _schedule_count(placed_day: int) -> int:
    first = placed_day + FIRST_YIELD_DAY
    if first > FINAL_DAY:
        return 0
    return 1 + (FINAL_DAY - first) // YIELD_INTERVAL


def _quoted_sales(obs: dict[str, Any], orders: list[list[Any]]) -> dict[str, float]:
    shed = (obs.get("private") or {}).get("shed") or {}
    prices = (obs.get("market") or {}).get("prices") or {}
    values: dict[str, float] = {}
    for order in orders:
        if len(order) < 3 or str(order[0]) != "SELL":
            continue
        item = str(order[1])
        quantity = min(int(shed.get(item, 0) or 0), max(0, int(order[2] or 0)))
        values[item] = values.get(item, 0.0) + (
            0.75 * quantity * max(1, int(prices.get(item, 1) or 1))
        )
    return values


def _purchase_events(
    replay: dict[str, Any], seat: int, source: str, episode_id: str
) -> list[dict[str, Any]]:
    events = []
    for step in range(EARLY_DAYS[0] * 24, (EARLY_DAYS[-1] + 1) * 24):
        obs = _observation(replay, step, seat)
        next_obs = _observation(replay, step + 1, seat)
        if obs is None or next_obs is None:
            continue
        orders = _market_actions(replay, step, seat)
        if not any(
            len(order) >= 2
            and str(order[0]) == "BUY_ANIMAL"
            and str(order[1]) == "COW"
            for order in orders
        ):
            continue
        quantity = max(0, _owned(next_obs, seat, "COW") - _owned(obs, seat, "COW"))
        if not quantity:
            continue
        farm = _farm(obs, seat)
        next_farm = _farm(next_obs, seat)
        summary = farm_summary(farm, step // 24)
        money = float(farm.get("money", 0) or 0)
        sale_values = _quoted_sales(obs, orders)
        sale_value = sum(sale_values.values())
        purchase_cost = 400 * quantity
        prices = (obs.get("market") or {}).get("prices") or {}
        animal_total = sum(int(value) for value in summary["animals"].values())
        reserve = 50 + animal_total * max(
            10, int(prices.get("WHEAT", 25) or 25)
        )
        empty_pastures = int(farm_summary(next_farm, step // 24)["empty_structures"])
        remaining_actions = 23 - step % 24
        # Each counted worker can make at least one idealized PICKUP/PLACE trip
        # only when two action slots remain. Distances and competing work make
        # this an optimistic one-trip bound, not an execution guarantee.
        one_trip_capacity = min(
            empty_pastures,
            len(_positions(next_farm)) if remaining_actions >= 2 else 0,
        )
        events.append(
            {
                "source": source,
                "episode_id": episode_id,
                "split": _split(episode_id),
                "step": step,
                "day": step // 24,
                "hour": step % 24,
                "quantity": quantity,
                "money_before": money,
                "purchase_cost": purchase_cost,
                "estimated_feed_reserve": reserve,
                "quoted_same_turn_sales": sale_value,
                "quoted_same_turn_sales_by_item": sale_values,
                "raw_cash_shortfall": max(0.0, purchase_cost - money),
                "reserve_cash_shortfall": max(0.0, purchase_cost + reserve - money),
                "raw_sale_financed": money < purchase_cost <= money + sale_value,
                "reserve_sale_financed": money < purchase_cost + reserve <= money + sale_value,
                "empty_pastures_after_market": empty_pastures,
                "workers_after_market": len(_positions(next_farm)),
                "remaining_actions_after_market": remaining_actions,
                "optimistic_one_trip_capacity": one_trip_capacity,
                "requires_repeat_or_next_day_trip": quantity > one_trip_capacity,
            }
        )
    return events


def _unit_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    episode_rows: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        episode_rows.setdefault(str(row["episode_id"]), []).append(row)
    aggregates = []
    for selected in episode_rows.values():
        aggregates.append(
            {
                "purchases": len(selected),
                "late_units": sum(row["purchase_hour"] >= 18 for row in selected),
                "cross_day_units": sum(not row["same_day"] for row in selected),
                "placement_day_delay": sum(
                    int(row["place_day"]) - int(row["purchase_day"]) for row in selected
                ),
                "base_yield_opportunity_delta": sum(
                    _schedule_count(int(row["purchase_day"]))
                    - _schedule_count(int(row["place_day"]))
                    for row in selected
                ),
            }
        )
    return {
        "units": len(rows),
        "episodes": len(episode_rows),
        "purchase_hour": _stats([row["purchase_hour"] for row in rows]),
        "same_day_fraction": sum(bool(row["same_day"]) for row in rows) / max(1, len(rows)),
        "cross_day_units": sum(not row["same_day"] for row in rows),
        "placement_day_delay": _stats(
            [int(row["place_day"]) - int(row["purchase_day"]) for row in rows]
        ),
        "base_yield_opportunity_delta_through_day_30": sum(
            _schedule_count(int(row["purchase_day"]))
            - _schedule_count(int(row["place_day"]))
            for row in rows
        ),
        "per_episode": {
            key: _stats([row[key] for row in aggregates])
            for key in (
                "purchases",
                "late_units",
                "cross_day_units",
                "placement_day_delay",
                "base_yield_opportunity_delta",
            )
        },
    }


def _event_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    units = sum(int(row["quantity"]) for row in rows)
    sale_items = sorted(
        {
            item
            for row in rows
            for item in row["quoted_same_turn_sales_by_item"]
        }
    )
    return {
        "events": len(rows),
        "units": units,
        "episodes": len({row["episode_id"] for row in rows}),
        "money_before": _stats([row["money_before"] for row in rows]),
        "quoted_same_turn_sales": _stats([row["quoted_same_turn_sales"] for row in rows]),
        "quoted_sales_by_item": {
            item: {
                "events": sum(
                    item in row["quoted_same_turn_sales_by_item"] for row in rows
                ),
                "total_value": sum(
                    row["quoted_same_turn_sales_by_item"].get(item, 0.0)
                    for row in rows
                ),
            }
            for item in sale_items
        },
        "raw_sale_financed_unit_fraction": sum(
            int(row["quantity"]) for row in rows if row["raw_sale_financed"]
        )
        / max(1, units),
        "reserve_sale_financed_unit_fraction": sum(
            int(row["quantity"]) for row in rows if row["reserve_sale_financed"]
        )
        / max(1, units),
        "requires_repeat_or_next_day_trip_event_fraction": sum(
            bool(row["requires_repeat_or_next_day_trip"]) for row in rows
        )
        / max(1, len(rows)),
        "remaining_actions_after_market": _stats(
            [row["remaining_actions_after_market"] for row in rows]
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v39_cow_purchase_timing.json"),
    )
    args = parser.parse_args()
    unit_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
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
            latency, _snapshots = _side(replay, seat, source, episode_id)
            unit_rows.extend(
                row
                for row in latency
                if row["animal"] == "COW" and row["purchase_day"] in EARLY_DAYS
            )
            event_rows.extend(_purchase_events(replay, seat, source, episode_id))

    payload = {
        "format": FORMAT,
        "runtime_policy_enabled": False,
        "objective": "separate Cow financing hour from cross-day placement and mechanics opportunity",
        "data": {
            "unit_rows": len(unit_rows),
            "purchase_events": len(event_rows),
            "episodes": len({row["episode_id"] for row in unit_rows}),
            "episode_disjoint_split": True,
        },
        "unit_summary": {
            source: {
                "overall": _unit_summary(
                    [row for row in unit_rows if row["source"] == source]
                ),
                "by_hour_band": {
                    name: _unit_summary(
                        [
                            row
                            for row in unit_rows
                            if row["source"] == source and row["purchase_hour"] in hours
                        ]
                    )
                    for name, hours in HOUR_BANDS.items()
                },
                "by_day": {
                    str(day): _unit_summary(
                        [
                            row
                            for row in unit_rows
                            if row["source"] == source and row["purchase_day"] == day
                        ]
                    )
                    for day in EARLY_DAYS
                },
                "by_split": {
                    split: _unit_summary(
                        [
                            row
                            for row in unit_rows
                            if row["source"] == source and row["split"] == split
                        ]
                    )
                    for split in ("train", "validation", "test")
                },
            }
            for source in SOURCES
        },
        "event_summary": {
            source: {
                "overall": _event_summary(
                    [row for row in event_rows if row["source"] == source]
                ),
                "by_hour_band": {
                    name: _event_summary(
                        [
                            row
                            for row in event_rows
                            if row["source"] == source and row["hour"] in hours
                        ]
                    )
                    for name, hours in HOUR_BANDS.items()
                },
            }
            for source in SOURCES
        },
        "mechanics": {
            "cow_first_yield_day": FIRST_YIELD_DAY,
            "cow_interval_days": YIELD_INTERVAL,
            "comparison_horizon_day": FINAL_DAY,
            "cross_day_placement_shifts_the_entire_production_parity": True,
            "shed_animals_expire": False,
            "carried_animals_return_to_shed_at_day_end": True,
        },
        "interpretation_limits": [
            "FIFO purchase-to-placement matching cannot identify physical Cow units",
            "same-turn sale proceeds use the pre-commit quoted price and may differ after market ordering",
            "the feed reserve reproduces the deterministic planner formula but omits earlier same-turn purchases",
            "the one-trip capacity ignores travel distance and competing tasks and is intentionally optimistic",
            "yield opportunity assumes a same-day counterfactual placement; it is not a causal score estimate",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
