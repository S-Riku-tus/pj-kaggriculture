"""Find price-floor sales that have capital and shed slack to wait.

At price one the engine pays one coin but deliberately does not add the sold
unit to market inventory.  Holding therefore retains price-recovery option
value.  This report applies a strict, public-state safety screen and measures
how often the observed market price later recovered; it does not claim that
all of that ex-post price difference is causally realizable.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v14 import main as v14  # noqa: E402
from scripts.build_v22_opponent_supply_rows import _farm, _tile_signals, _town_rate  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    TEACHERS,
    _manifest,
    _observation,
    _replay_path,
    _split,
)

FORMAT = "kaggriculture-v23-floor-sale-analysis-v1"
V11 = ROOT / "data/submissions/v11_submission_55787906"
SOURCES = {"v11": V11, **TEACHERS}
ITEMS = ("STRAWBERRY", "MILK", "WOOL", "MELON")


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


def _purchase_deposits(orders: list[list[Any]]) -> int:
    return sum(
        max(0, int(order[2] or 0))
        for order in orders
        if isinstance(order, list)
        and len(order) >= 3
        and order[0] in {"BUY_PRODUCT", "BUY_ANIMAL"}
    )


def _future_prices(replay: dict[str, Any], seat: int, step: int, item: str, horizon: int) -> list[int]:
    prices = []
    for future in range(step + 1, min(len(replay.get("steps") or []), step + horizon + 1)):
        obs = _observation(replay, future, seat)
        if obs is not None:
            prices.append(int(((obs.get("market") or {}).get("prices") or {}).get(item, 1) or 1))
    return prices


def _side(replay: dict[str, Any], seat: int, metadata: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {**metadata, "declared_floor": Counter(), "safe_hold": Counter(), "events": []}
    steps = replay.get("steps") or []
    for decision_step in range(len(steps) - 1):
        obs = _observation(replay, decision_step, seat)
        if obs is None:
            continue
        day = int(obs.get("day", 0) or 0)
        if not 5 <= day <= 26:
            continue
        farm = _farm(obs, seat)
        private = obs.get("private") or {}
        shed = private.get("shed") or {}
        available = {item: int(shed.get(item, 0) or 0) for item in ITEMS}
        market = obs.get("market") or {}
        prices = market.get("prices") or {}
        action = steps[decision_step + 1][seat].get("action") or {}
        orders = [list(order) for order in (action.get("market") or [])[:10] if isinstance(order, list)]
        purchase_cost = v14.v9._purchase_cost(orders, farm, obs)
        deposits = _purchase_deposits(orders)
        shed_total = _inventory_total(shed)
        carried = sum(_inventory_total(value) for value in (private.get("inventories") or []))
        scheduled = _tile_signals(farm, day, 1)
        incoming = sum(
            int(scheduled.get(f"ready_{item}", 0) + scheduled.get(f"scheduled_{item}", 0))
            for item in ITEMS
        )
        money = float(farm.get("money", 0) or 0)
        town = _town_rate(obs)
        for order in orders:
            if len(order) < 3 or order[0] != "SELL" or str(order[1]) not in ITEMS:
                continue
            item = str(order[1])
            amount = min(available[item], max(0, int(order[2] or 0)))
            available[item] -= amount
            if amount <= 0 or int(prices.get(item, 1) or 1) > 1:
                continue
            result["declared_floor"][item] += amount
            capacity_projection = shed_total + carried + incoming + deposits
            financing_slack = money - purchase_cost
            safe_hold = (
                day <= 24
                and capacity_projection <= 70
                and financing_slack >= 100
                and float(town[item]) > 0.25
            )
            if not safe_hold:
                continue
            result["safe_hold"][item] += amount
            prices24 = _future_prices(replay, seat, decision_step, item, 24)
            prices72 = _future_prices(replay, seat, decision_step, item, 72)
            result["events"].append(
                {
                    "split": metadata["split"],
                    "day": day,
                    "hour": int(obs.get("hour", 0) or 0),
                    "item": item,
                    "quantity": amount,
                    "shed_total": shed_total,
                    "capacity_projection": capacity_projection,
                    "financing_slack": financing_slack,
                    "max_price_h24": max(prices24, default=1),
                    "max_price_h72": max(prices72, default=1),
                }
            )
    result["declared_floor"] = dict(result["declared_floor"])
    result["safe_hold"] = dict(result["safe_hold"])
    return result


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    events = [event for row in rows for event in row["events"]]
    declared = Counter()
    safe = Counter()
    for row in rows:
        declared.update(row["declared_floor"])
        safe.update(row["safe_hold"])
    quantities = sum(event["quantity"] for event in events)
    return {
        "sides": len(rows),
        "declared_floor_quantity": dict(declared),
        "strict_safe_hold_quantity": dict(safe),
        "strict_events": len(events),
        "strict_quantity": quantities,
        "price_recovery_h24_event_rate": (
            sum(event["max_price_h24"] > 1 for event in events) / len(events) if events else 0.0
        ),
        "price_recovery_h72_event_rate": (
            sum(event["max_price_h72"] > 1 for event in events) / len(events) if events else 0.0
        ),
        "max_price_h24": _stats([float(event["max_price_h24"]) for event in events]),
        "max_price_h72": _stats([float(event["max_price_h72"]) for event in events]),
        "events_by_item": dict(Counter(event["item"] for event in events)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/analysis/v23_floor_sales.json"))
    args = parser.parse_args()
    rows = []
    for source, directory in SOURCES.items():
        for manifest in _manifest(directory):
            replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
            rows.append(
                _side(
                    replay,
                    int(manifest["submission_seat"]),
                    {
                        "episode_id": str(manifest["episode_id"]),
                        "source": source,
                        "result": str(manifest.get("result") or "unknown"),
                        "split": _split(str(manifest["episode_id"])),
                    },
                )
            )
    cohorts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        cohorts[f"{row['source']}_all"].append(row)
        cohorts[f"{row['source']}_{row['result']}"] .append(row)
    selected = ("v11_all", "rank1_win", "rank2_win", "rank3_win")
    payload = {
        "format": FORMAT,
        "strict_screen": {
            "days": [5, 24],
            "capacity_projection_max": 70,
            "post_purchase_money_min": 100,
            "requires_unlocked_shop_demand": True,
            "note": "ex-post recovery is diagnostic, not a causal reward estimate",
        },
        "cohorts": {name: _summary(cohorts[name]) for name in selected},
        "split_cohorts": {
            name: {
                split: _summary([row for row in cohorts[name] if row["split"] == split])
                for split in ("train", "validation", "test")
            }
            for name in selected
        },
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["cohorts"], ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
