"""Align replay SELL actions to their decision-time Town phase.

Replay state t+1 stores the action chosen from observation t.  Earlier corpus
counts that use the recorded-state index shift the apparent market phase by
one turn.  This report corrects that shift and separates pre-Town phase 0 from
post-Town phase 1.
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

from scripts.train_v12_relative_policy import TEACHERS, _manifest, _observation, _replay_path, _split  # noqa: E402

FORMAT = "kaggriculture-v22-market-timing-v1"
V11 = ROOT / "data/submissions/v11_submission_55787906"
SOURCES = {"v11": V11, **TEACHERS}
ITEMS = ("WHEAT", "STRAWBERRY", "MILK", "WOOL", "MELON")
PHASES = ((3, 9), (10, 17), (18, 26), (27, 29))


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


def _phase_name(day: int) -> str:
    for lower, upper in PHASES:
        if lower <= day <= upper:
            return f"{lower}-{upper}"
    return "opening"


def _side(replay: dict[str, Any], seat: int, metadata: dict[str, Any]) -> dict[str, Any]:
    quantities: Counter[tuple[str, str, int]] = Counter()
    events: Counter[tuple[str, str, int]] = Counter()
    quote_values: Counter[tuple[str, str, int]] = Counter()
    floor_quantities: Counter[tuple[str, str, int]] = Counter()
    steps = replay.get("steps") or []
    for decision_step in range(len(steps) - 1):
        obs = _observation(replay, decision_step, seat)
        if obs is None or seat >= len(steps[decision_step + 1]):
            continue
        day = int(obs.get("day", 0) or 0)
        hour = int(obs.get("hour", 0) or 0)
        phase = hour % 4
        period = _phase_name(day)
        private = obs.get("private") or {}
        available = {
            item: int((private.get("shed") or {}).get(item, 0) or 0)
            for item in ITEMS
        }
        prices = (obs.get("market") or {}).get("prices") or {}
        action = steps[decision_step + 1][seat].get("action") or {}
        for order in (action.get("market") or [])[:10]:
            if not isinstance(order, list) or len(order) < 3 or order[0] != "SELL":
                continue
            item = str(order[1])
            if item not in ITEMS:
                continue
            amount = min(available[item], max(0, int(order[2] or 0)))
            if amount <= 0:
                continue
            available[item] -= amount
            key = (period, item, phase)
            quantities[key] += amount
            events[key] += 1
            price = int(prices.get(item, 0) or 0)
            quote_values[key] += amount * price
            if price <= 1:
                floor_quantities[key] += amount
    result: dict[str, Any] = {**metadata, "cells": {}}
    for period in (*[f"{lower}-{upper}" for lower, upper in PHASES], "opening"):
        result["cells"][period] = {}
        for item in ITEMS:
            by_phase = {}
            total = sum(quantities[period, item, phase] for phase in range(4))
            for phase in range(4):
                quantity = quantities[period, item, phase]
                by_phase[str(phase)] = {
                    "quantity": quantity,
                    "quantity_share": quantity / total if total else 0.0,
                    "events": events[period, item, phase],
                    "mean_quote": quote_values[period, item, phase] / quantity if quantity else 0.0,
                    "floor_quantity": floor_quantities[period, item, phase],
                }
            result["cells"][period][item] = {"total_quantity": total, "by_phase": by_phase}
    return result


def _cohorts(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    cohorts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        source = str(row["source"])
        result = str(row["result"])
        cohorts[source].append(row)
        cohorts[f"{source}_{result}"].append(row)
        if source.startswith("rank"):
            cohorts["top3_all"].append(row)
            cohorts[f"top3_{result}"].append(row)
        else:
            cohorts["v11_all"].append(row)
    return cohorts


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"sides": len(rows), "periods": {}}
    for period in (*[f"{lower}-{upper}" for lower, upper in PHASES], "opening"):
        result["periods"][period] = {}
        for item in ITEMS:
            phase_stats = {}
            for phase in range(4):
                cells = [row["cells"][period][item]["by_phase"][str(phase)] for row in rows]
                phase_stats[str(phase)] = {
                    "quantity": _stats([float(cell["quantity"]) for cell in cells]),
                    "quantity_share": _stats([float(cell["quantity_share"]) for cell in cells]),
                    "events": _stats([float(cell["events"]) for cell in cells]),
                    "mean_quote_on_selling_sides": _stats(
                        [float(cell["mean_quote"]) for cell in cells if cell["quantity"] > 0]
                    ),
                    "floor_quantity": _stats([float(cell["floor_quantity"]) for cell in cells]),
                }
            result["periods"][period][item] = {"by_decision_phase": phase_stats}
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/analysis/v22_market_timing.json"))
    args = parser.parse_args()
    rows: list[dict[str, Any]] = []
    source_sides: Counter[str] = Counter()
    total = sum(len(_manifest(directory)) for directory in SOURCES.values())
    progress = 0
    for source, directory in SOURCES.items():
        for manifest in _manifest(directory):
            progress += 1
            if progress == 1 or progress % 25 == 0:
                print(f"[{progress}/{total}] {source} episode {manifest['episode_id']}", flush=True)
            result = str(manifest.get("result") or "unknown")
            replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
            rows.append(
                _side(
                    replay,
                    int(manifest["submission_seat"]),
                    {
                        "episode_id": str(manifest["episode_id"]),
                        "source": source,
                        "result": result,
                        "split": _split(str(manifest["episode_id"])),
                    },
                )
            )
            source_sides[f"{source}_{result}"] += 1
    cohorts = _cohorts(rows)
    payload = {
        "format": FORMAT,
        "scope": {
            "alignment": "decision observation t uses action stored in replay state t+1",
            "phase_0": "market executes before the scheduled Town consumption",
            "phase_1": "first observation after scheduled Town consumption",
            "quantity": "declared SELL capped by pre-action shed",
        },
        "source_sides": dict(source_sides),
        "cohorts": {cohort: _summary(selected) for cohort, selected in sorted(cohorts.items())},
        "split_cohorts": {
            cohort: {
                split: _summary([row for row in selected if row["split"] == split])
                for split in ("train", "validation", "test")
            }
            for cohort, selected in cohorts.items()
            if cohort in {"v11_all", "rank1_win", "rank2_win", "rank3_win"}
        },
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"format": FORMAT, "sides": len(rows), "source_sides": dict(source_sides)}, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
