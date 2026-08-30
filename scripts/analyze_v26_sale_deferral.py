"""Screen V11 phase-0 sales for bounded one-turn deferral candidates.

The price model predicts 24-turn residual prices from public history.  This
report only considers Town-consumption phase 0, where delaying to phase 1 has
a first-principles price-recovery mechanism.  Financing and shed headroom are
strict gates.  Observed next prices are diagnostic lower bounds under the
logged trajectory, not closed-loop causal values.
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

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v14 import main as v14  # noqa: E402
from scripts.build_v22_opponent_supply_rows import (  # noqa: E402
    _history_values,
    _public_values,
    _tile_signals,
    _town_rate,
)
from scripts.train_v12_relative_policy import _manifest, _observation, _replay_path, _split  # noqa: E402
from scripts.train_v22_opponent_supply import _predict_forest  # noqa: E402

FORMAT = "kaggriculture-v26-sale-deferral-screen-v1"
MODEL_FORMAT = "kaggriculture-v25-public-price-forecast-v1"
V11 = ROOT / "data/submissions/v11_submission_55787906"
ITEMS = ("WHEAT", "STRAWBERRY", "MILK", "WOOL")
BASE_PRICE = {"WHEAT": 25.0, "STRAWBERRY": 120.0, "MILK": 160.0, "WOOL": 200.0}
MIN_NORMALIZED_UPSIDE = 0.05
MAX_CAPACITY_PROJECTION = 70
MIN_POST_PURCHASE_MONEY = 100.0


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


def _inventory_total(value: Any) -> int:
    return sum(max(0, int(amount or 0)) for amount in (value or {}).values())


def _deposits(orders: list[list[Any]]) -> int:
    return sum(
        max(0, int(order[2] or 0))
        for order in orders
        if len(order) >= 3 and order[0] in {"BUY_PRODUCT", "BUY_ANIMAL"}
    )


def _declared_sales(orders: list[list[Any]], shed: dict[str, Any]) -> dict[str, int]:
    available = {item: int(shed.get(item, 0) or 0) for item in ITEMS}
    sales: Counter[str] = Counter()
    for order in orders:
        if len(order) < 3 or order[0] != "SELL" or str(order[1]) not in ITEMS:
            continue
        item = str(order[1])
        amount = min(available[item], max(0, int(order[2] or 0)))
        available[item] -= amount
        sales[item] += amount
    return dict(sales)


def _side(
    replay: dict[str, Any],
    seat: int,
    episode_id: str,
    model: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = []
    feature_names = list(model["feature_names"])
    uncertainty_limit = float(model["public_uncertainty_p90"])
    steps = replay.get("steps") or []
    for step in range(len(steps) - 2):
        obs = _observation(replay, step, seat)
        next_obs = _observation(replay, step + 1, seat)
        if obs is None or next_obs is None:
            continue
        day = int(obs.get("day", 0) or 0)
        hour = int(obs.get("hour", 0) or 0)
        if not 5 <= day <= 24 or hour % 4 != 0:
            continue
        action = steps[step + 1][seat].get("action") or {}
        orders = [list(value) for value in (action.get("market") or [])[:10] if isinstance(value, list)]
        private = obs.get("private") or {}
        shed = private.get("shed") or {}
        sales = _declared_sales(orders, shed)
        if not sales:
            continue
        public = _public_values(obs, seat)
        public.update(_history_values(replay, step, seat, obs))
        x = np.asarray([[float(public[name]) for name in feature_names]], dtype=np.float64)
        residual, deviation = _predict_forest(model["public_forest"], x)
        uncertainty = float(np.mean(deviation))
        farm = (obs.get("farms") or [])[seat]
        current_prices = (obs.get("market") or {}).get("prices") or {}
        next_prices = (next_obs.get("market") or {}).get("prices") or {}
        purchase_cost = float(v14.v9._purchase_cost(orders, farm, obs))
        carried = sum(_inventory_total(value) for value in (private.get("inventories") or []))
        signals = _tile_signals(farm, day, 1)
        incoming = sum(
            int(signals.get(f"ready_{item}", 0) + signals.get(f"scheduled_{item}", 0))
            for item in ITEMS
        )
        capacity_projection = _inventory_total(shed) + carried + incoming + _deposits(orders)
        money_after_purchases = float(farm.get("money", 0) or 0) - purchase_cost
        town = _town_rate(obs)
        next_action = steps[step + 2][seat].get("action") or {}
        next_orders = [
            list(value) for value in (next_action.get("market") or [])[:10] if isinstance(value, list)
        ]
        next_private = next_obs.get("private") or {}
        next_sales = _declared_sales(next_orders, next_private.get("shed") or {})
        for item, quantity in sales.items():
            item_index = ITEMS.index(item)
            base = BASE_PRICE[item]
            current_price = float(current_prices.get(item, base) or 1)
            predicted_price_h24 = max(1.0, current_price + float(residual[0, item_index]) * base)
            normalized_upside = (predicted_price_h24 - current_price) / base
            gate = {
                "confident": uncertainty <= uncertainty_limit,
                "forecast_upside": normalized_upside >= MIN_NORMALIZED_UPSIDE,
                "capacity": capacity_projection <= MAX_CAPACITY_PROJECTION,
                "financing": money_after_purchases >= MIN_POST_PURCHASE_MONEY,
                "town_demand": float(town[item]) > 0.25,
            }
            selected = all(gate.values())
            next_price = float(next_prices.get(item, base) or 1)
            rows.append(
                {
                    "episode_id": episode_id,
                    "split": _split(episode_id),
                    "day": day,
                    "hour": hour,
                    "item": item,
                    "quantity": quantity,
                    "current_price": current_price,
                    "predicted_price_h24": predicted_price_h24,
                    "normalized_upside": normalized_upside,
                    "next_price_logged": next_price,
                    "logged_next_price_delta": next_price - current_price,
                    "logged_next_turn_sale": int(next_sales.get(item, 0)),
                    "capacity_projection": capacity_projection,
                    "money_after_purchases": money_after_purchases,
                    "uncertainty": uncertainty,
                    "gate": gate,
                    "selected": selected,
                }
            )
    return rows


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    selected = [row for row in rows if row["selected"]]
    gate_failures = Counter()
    for row in rows:
        for gate, value in row["gate"].items():
            if not value:
                gate_failures[gate] += 1
    return {
        "sale_events": len(rows),
        "sale_quantity": sum(int(row["quantity"]) for row in rows),
        "selected_events": len(selected),
        "selected_quantity": sum(int(row["quantity"]) for row in selected),
        "selected_by_item": dict(Counter(row["item"] for row in selected)),
        "gate_failures": dict(gate_failures),
        "selected_logged_next_price_increase_rate": (
            sum(float(row["logged_next_price_delta"]) > 0 for row in selected) / len(selected)
            if selected
            else 0.0
        ),
        "selected_logged_next_price_delta": _stats(
            [float(row["logged_next_price_delta"]) for row in selected]
        ),
        "selected_forecast_upside": _stats([float(row["normalized_upside"]) for row in selected]),
        "selected_next_turn_sale_rate": (
            sum(int(row["logged_next_turn_sale"]) > 0 for row in selected) / len(selected)
            if selected
            else 0.0
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model", type=Path, default=Path("data/models/v25_public_price_model.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("data/analysis/v26_sale_deferral_screen.json")
    )
    args = parser.parse_args()
    model_path = args.model if args.model.is_absolute() else ROOT / args.model
    model = json.loads(model_path.read_text(encoding="utf-8"))
    if model.get("format") != MODEL_FORMAT or model.get("target_mode") != "residual":
        raise ValueError("a residual V25 public price model is required")
    rows = []
    for manifest in _manifest(V11):
        episode_id = str(manifest["episode_id"])
        replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
        rows.extend(_side(replay, int(manifest["submission_seat"]), episode_id, model))
    payload = {
        "format": FORMAT,
        "objective": "bounded phase-0 to phase-1 sale deferral screen on submitted V11 logs",
        "screen": {
            "days": [5, 24],
            "phase": 0,
            "minimum_normalized_h24_upside": MIN_NORMALIZED_UPSIDE,
            "max_capacity_projection": MAX_CAPACITY_PROJECTION,
            "min_post_purchase_money": MIN_POST_PURCHASE_MONEY,
            "requires_town_shop_demand": True,
            "requires_model_confidence": True,
        },
        "summary": _summary(rows),
        "split_summary": {
            split: _summary([row for row in rows if row["split"] == split])
            for split in ("train", "validation", "test")
        },
        "selected_events": [row for row in rows if row["selected"]],
        "interpretation": {
            "fact": "all selection gates use information available at decision time",
            "limit": "logged next price is not a closed-loop causal value after changing the sale",
            "runtime": "not implemented unless support is stable and paired closed-loop tests pass",
        },
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(json.dumps(payload["split_summary"], ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
