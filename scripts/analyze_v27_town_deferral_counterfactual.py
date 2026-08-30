"""Evaluate one-turn pre-Town sale deferral from the exact market mechanics.

The environment processes market orders before Town consumption.  For a sale
chosen at hour ``h % 4 == 0``, this report reconstructs the next observation's
market inventory without our sale and compares two deliberately conservative
revenues:

* sell now: our whole batch is quoted before any opponent sale;
* sell after Town: the opponent's whole next-turn requested batch is inserted
  before ours.

When the latter still wins, the price advantage is robust to market-order
interleaving along the logged opponent trajectory.  This remains an offline
counterfactual, not proof that an opponent would keep the same next action.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kaggle_environments.envs.kaggriculture import kaggriculture as game  # noqa: E402

from agents.v14 import main as v14  # noqa: E402
from scripts.analyze_v22_market_timing import ITEMS  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    TEACHERS,
    _manifest,
    _observation,
    _replay_path,
    _split,
)

FORMAT = "kaggriculture-v27-town-deferral-counterfactual-v1"
V11 = ROOT / "data/submissions/v11_submission_55787906"
SOURCES = {"v11": V11, **TEACHERS}
MIN_CASH_RESERVE = 100.0
MAX_SHED_AFTER_PURCHASES = 90
RUNTIME_ITEMS = frozenset({"STRAWBERRY", "MILK", "WOOL"})
MIN_RUNTIME_GAIN = 40.0
MIN_RUNTIME_GAIN_PER_UNIT = 3.0


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * quantile
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - position) + ordered[high] * (position - low)


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "median": 0.0, "p10": 0.0, "p90": 0.0}
    return {
        "mean": mean(values),
        "median": median(values),
        "p10": _percentile(values, 0.10),
        "p90": _percentile(values, 0.90),
    }


def _orders(replay: dict[str, Any], stored_step: int, seat: int) -> list[list[Any]]:
    steps = replay.get("steps") or []
    if not 0 <= stored_step < len(steps) or not 0 <= seat < len(steps[stored_step]):
        return []
    action = steps[stored_step][seat].get("action") or {}
    return [list(order) for order in (action.get("market") or [])[:10] if isinstance(order, list)]


def _requested(orders: list[list[Any]], verb: str, item: str) -> int:
    return sum(
        max(0, int(order[2] or 0))
        for order in orders
        if len(order) >= 3 and order[0] == verb and str(order[1]) == item
    )


def _actual_sales(orders: list[list[Any]], shed: dict[str, Any]) -> dict[str, int]:
    available = {item: max(0, int(shed.get(item, 0) or 0)) for item in ITEMS}
    sales: Counter[str] = Counter()
    for order in orders:
        if len(order) < 3 or order[0] != "SELL" or str(order[1]) not in ITEMS:
            continue
        item = str(order[1])
        amount = min(available[item], max(0, int(order[2] or 0)))
        available[item] -= amount
        if amount > 0:
            sales[item] += amount
    return dict(sales)


def _town_consumption(obs: dict[str, Any], item: str) -> int:
    amount = 0
    for shop in (obs.get("town") or {}).get("unlocked_shops") or []:
        products = game.SHOPS.get(shop, [])
        if item in products:
            amount += 2 if len(products) == 1 else 1
    if int(obs.get("hour", 0) or 0) == 0 and item != "FERTILIZER":
        amount += 1
    return amount


def _inventory_total(shed: dict[str, Any]) -> int:
    return sum(max(0, int(value or 0)) for value in shed.values())


def _purchase_deposits(orders: list[list[Any]]) -> int:
    return sum(
        max(0, int(order[2] or 0))
        for order in orders
        if len(order) >= 3 and order[0] in {"BUY_PRODUCT", "BUY_ANIMAL"}
    )


def _batch_revenue(item: str, inventory: int, quantity: int, params: Any) -> float:
    revenue = 0.0
    cursor = int(inventory)
    for _ in range(quantity):
        price = game.market_price(item, cursor, params)
        revenue += price
        if price > 1:
            cursor += 1
    return revenue


def _side(
    replay: dict[str, Any],
    seat: int,
    episode_id: str,
    source: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    steps = replay.get("steps") or []
    opponent = 1 - seat
    for decision_step in range(len(steps) - 2):
        obs = _observation(replay, decision_step, seat)
        next_obs = _observation(replay, decision_step + 1, seat)
        if obs is None or next_obs is None:
            continue
        day = int(obs.get("day", 0) or 0)
        hour = int(obs.get("hour", 0) or 0)
        if not 5 <= day <= 24 or hour % 4 != 0:
            continue
        private = obs.get("private") or {}
        shed = private.get("shed") or {}
        own_now = _orders(replay, decision_step + 1, seat)
        sales = _actual_sales(own_now, shed)
        if not sales:
            continue
        opponent_now = _orders(replay, decision_step + 1, opponent)
        opponent_next = _orders(replay, decision_step + 2, opponent)
        farm = (obs.get("farms") or [])[seat]
        market = obs.get("market") or {}
        next_market = next_obs.get("market") or {}
        params = market.get("params")
        current_inventory = market.get("inventory") or {}
        next_inventory = next_market.get("inventory") or {}
        current_prices = market.get("prices") or {}
        purchase_cost = float(v14.v9._purchase_cost(own_now, farm, obs))
        money_without_sales = float(farm.get("money", 0) or 0) - purchase_cost
        projected_shed = _inventory_total(shed) + _purchase_deposits(own_now)
        for item, quantity in sales.items():
            town_units = _town_consumption(obs, item)
            own_item_buy = _requested(own_now, "BUY_PRODUCT", item)
            opponent_item_buy = _requested(opponent_now, "BUY_PRODUCT", item)
            start_inventory = int(current_inventory.get(item, 0) or 0)
            opponent_now_sale = _requested(opponent_now, "SELL", item)
            worst_end_inventory = start_inventory + quantity + opponent_now_sale
            remains_above_floor = game.market_price(item, worst_end_inventory, params) > 1
            exact_inventory = (
                town_units > 0
                and own_item_buy == 0
                and opponent_item_buy == 0
                and remains_above_floor
            )
            counterfactual_next_inventory = int(next_inventory.get(item, 0) or 0) - quantity
            opponent_next_sale = _requested(opponent_next, "SELL", item)
            immediate_upper = _batch_revenue(item, start_inventory, quantity, params)
            delayed_lower = _batch_revenue(
                item,
                counterfactual_next_inventory + opponent_next_sale,
                quantity,
                params,
            )
            gain = delayed_lower - immediate_upper
            mechanical_delayed = _batch_revenue(
                item,
                start_inventory - town_units,
                quantity,
                params,
            )
            mechanical_gain = mechanical_delayed - immediate_upper
            gate = {
                "exact_inventory": exact_inventory,
                "cash_independent": money_without_sales >= MIN_CASH_RESERVE,
                "shed_safe": projected_shed <= MAX_SHED_AFTER_PURCHASES,
                "positive_lower_bound": gain > 0,
            }
            runtime_gate = {
                "supported_item": item in RUNTIME_ITEMS,
                "cash_independent": money_without_sales >= MIN_CASH_RESERVE,
                "shed_safe": projected_shed <= MAX_SHED_AFTER_PURCHASES,
                "mechanical_gain": mechanical_gain >= MIN_RUNTIME_GAIN,
                "mechanical_gain_per_unit": (
                    mechanical_gain / quantity >= MIN_RUNTIME_GAIN_PER_UNIT
                ),
            }
            rows.append(
                {
                    "source": source,
                    "episode_id": episode_id,
                    "split": _split(episode_id),
                    "day": day,
                    "hour": hour,
                    "item": item,
                    "quantity": quantity,
                    "town_consumption": town_units,
                    "current_price": float(current_prices.get(item, 0) or 0),
                    "current_inventory": start_inventory,
                    "logged_next_inventory": int(next_inventory.get(item, 0) or 0),
                    "counterfactual_next_inventory": counterfactual_next_inventory,
                    "opponent_next_requested_sale": opponent_next_sale,
                    "immediate_revenue_upper": immediate_upper,
                    "delayed_revenue_lower": delayed_lower,
                    "revenue_gain_lower_bound": gain,
                    "gain_per_unit_lower_bound": gain / quantity,
                    "mechanical_revenue_gain": mechanical_gain,
                    "mechanical_gain_per_unit": mechanical_gain / quantity,
                    "money_without_sales": money_without_sales,
                    "projected_shed": projected_shed,
                    "gate": gate,
                    "selected": all(gate.values()),
                    "runtime_gate": runtime_gate,
                    "runtime_selected": all(runtime_gate.values()),
                }
            )
    return rows


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    selected = [row for row in rows if row["selected"]]
    runtime = [row for row in rows if row["runtime_selected"]]
    failures: Counter[str] = Counter()
    for row in rows:
        for name, passed in row["gate"].items():
            if not passed:
                failures[name] += 1
    return {
        "phase0_sale_events": len(rows),
        "phase0_sale_quantity": sum(int(row["quantity"]) for row in rows),
        "selected_events": len(selected),
        "selected_quantity": sum(int(row["quantity"]) for row in selected),
        "selected_by_item": dict(Counter(row["item"] for row in selected)),
        "gate_failures": dict(failures),
        "selected_revenue_gain_lower_bound": _stats(
            [float(row["revenue_gain_lower_bound"]) for row in selected]
        ),
        "selected_gain_per_unit_lower_bound": _stats(
            [float(row["gain_per_unit_lower_bound"]) for row in selected]
        ),
        "runtime_candidate_events": len(runtime),
        "runtime_candidate_quantity": sum(int(row["quantity"]) for row in runtime),
        "runtime_candidate_by_item": dict(Counter(row["item"] for row in runtime)),
        "runtime_positive_logged_lower_bound_rate": (
            sum(float(row["revenue_gain_lower_bound"]) > 0 for row in runtime) / len(runtime)
            if runtime
            else 0.0
        ),
        "runtime_logged_revenue_gain_lower_bound": _stats(
            [float(row["revenue_gain_lower_bound"]) for row in runtime]
        ),
        "runtime_mechanical_revenue_gain": _stats(
            [float(row["mechanical_revenue_gain"]) for row in runtime]
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v27_town_deferral_counterfactual.json"),
    )
    args = parser.parse_args()
    rows: list[dict[str, Any]] = []
    for source, directory in SOURCES.items():
        manifests = _manifest(directory)
        for index, manifest in enumerate(manifests, start=1):
            episode_id = str(manifest["episode_id"])
            print(f"[{source} {index}/{len(manifests)}] {episode_id}", flush=True)
            replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
            rows.extend(
                _side(replay, int(manifest["submission_seat"]), episode_id, source)
            )
    payload = {
        "format": FORMAT,
        "objective": "exact-mechanics screen for one-turn pre-Town sale deferral",
        "screen": {
            "days": [5, 24],
            "phase": 0,
            "minimum_cash_without_sale": MIN_CASH_RESERVE,
            "maximum_shed_after_same_turn_purchases": MAX_SHED_AFTER_PURCHASES,
            "runtime_items": sorted(RUNTIME_ITEMS),
            "minimum_runtime_mechanical_gain": MIN_RUNTIME_GAIN,
            "minimum_runtime_mechanical_gain_per_unit": MIN_RUNTIME_GAIN_PER_UNIT,
            "current_revenue_assumption": "own batch before opponent (optimistic)",
            "delayed_revenue_assumption": "all requested opponent next-turn sales before own batch (pessimistic)",
        },
        "source_summary": {
            source: _summary([row for row in rows if row["source"] == source])
            for source in SOURCES
        },
        "v11_split_summary": {
            split: _summary(
                [row for row in rows if row["source"] == "v11" and row["split"] == split]
            )
            for split in ("train", "validation", "test")
        },
        "selected_events": [row for row in rows if row["selected"]],
        "runtime_candidates": [row for row in rows if row["runtime_selected"]],
        "interpretation": {
            "fact": "selected price gains follow the official market curve and logged public inventory",
            "inference": "a one-turn deferral may monetize Town demand when cash and shed gates pass",
            "limit": "the opponent next action and later farm trajectory are not causally replayed",
            "runtime": "not implemented unless split stability and paired closed-loop tests support it",
        },
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["source_summary"], ensure_ascii=False, indent=2))
    print(json.dumps(payload["v11_split_summary"], ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
