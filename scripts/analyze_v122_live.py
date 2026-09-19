#!/usr/bin/env python3
"""Reproduce the compact V122 live-forensics summary from exported CSVs."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from statistics import mean
from typing import Any

CHECKPOINTS = (0, 3, 6, 9, 12, 15, 18, 20, 21, 24, 27, 29)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def _route(row: dict[str, str], day: int) -> str:
    goose = _int(row.get(f"GOOSE_d{day}"))
    cow = _int(row.get(f"COW_d{day}"))
    sheep = _int(row.get(f"SHEEP_d{day}"))
    if goose == 0 and sheep >= 8:
        return "WOOL"
    if cow >= 9 and sheep <= 6:
        return "MILK"
    return "BALANCED"


def _cohort(rows: Iterable[dict[str, str]]) -> dict[str, Any]:
    records = list(rows)
    wins = sum(row.get("result") == "W" for row in records)
    losses = sum(row.get("result") == "L" for row in records)
    draws = len(records) - wins - losses
    return {
        "games": len(records),
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": wins / len(records) if records else None,
        "mean_margin": mean(_float(row.get("margin")) for row in records) if records else None,
    }


def _group(rows: list[dict[str, str]], key: Any) -> dict[str, Any]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[str(key(row))].append(row)
    return {name: _cohort(group) for name, group in sorted(groups.items())}


def analyze(metrics_path: Path, route_path: Path, clone_path: Path) -> dict[str, Any]:
    rows = _rows(metrics_path)
    route_rows = _rows(route_path)
    clone_rows = _rows(clone_path)
    by_episode = {row["eid"]: row for row in rows}

    route_changes: Counter[str] = Counter()
    for row in rows:
        before = _route(row, 12)
        after = _route(row, 24)
        route_changes[f"{before}->{after}"] += 1

    high = [row for row in rows if _float(row.get("own_init_rating")) >= 1600]
    recent_by_submission: dict[str, Any] = {}
    for submission in sorted({row["subid"] for row in rows}):
        subset = [row for row in rows if row["subid"] == submission]
        recent_by_submission[submission] = _cohort(subset[:20])

    margins_by_result: dict[str, dict[str, float]] = {}
    for result in ("W", "L", "D"):
        subset = [row for row in rows if row.get("result") == result]
        if not subset:
            continue
        margins_by_result[result] = {
            f"day_{day}": mean(_float(row.get(f"margin_money_d{day}")) for row in subset) for day in CHECKPOINTS
        }

    switch_joined = [(row, by_episode[row["eid"]]) for row in route_rows if row.get("eid") in by_episode]
    switch_by_result: dict[str, Any] = {}
    for result in ("W", "L", "D"):
        subset = [(route, metric) for route, metric in switch_joined if metric.get("result") == result]
        if subset:
            switch_by_result[result] = {
                "games": len(subset),
                "mean_selected_sources": mean(_float(route.get("selected_sources")) for route, _ in subset),
                "mean_daily_switches": mean(_float(route.get("daily_source_switches")) for route, _ in subset),
            }

    collision_bins: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        fraction = _float(row.get("same_sell_turn_frac"))
        bucket = "lt_0.50" if fraction < 0.50 else "0.50_0.70" if fraction < 0.70 else "ge_0.70"
        collision_bins[bucket].append(row)

    clone_exact = [row for row in clone_rows if str(row.get("same_h100", "")).lower() == "true"]
    clone_exact_metrics = [by_episode[row["eid"]] for row in clone_exact if row.get("eid") in by_episode]

    return {
        "overall": _cohort(rows),
        "by_submission": _group(rows, lambda row: row["subid"]),
        "recent_20_by_submission": recent_by_submission,
        "rating_1600_plus": _cohort(high),
        "rating_1600_plus_by_route_day12": _group(high, lambda row: _route(row, 12)),
        "all_by_route_day12": _group(rows, lambda row: _route(row, 12)),
        "route_changes_day12_to_day24": dict(sorted(route_changes.items())),
        "margin_trajectory_by_result": margins_by_result,
        "continuation_switching_by_result": switch_by_result,
        "same_sell_turn_fraction_bins": {name: _cohort(group) for name, group in sorted(collision_bins.items())},
        "exact_opening_h100": _cohort(clone_exact_metrics),
        "exact_opening_h100_episode_ids": [row["eid"] for row in clone_exact],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--routes", type=Path, required=True)
    parser.add_argument("--clones", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = analyze(args.metrics, args.routes, args.clones)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
