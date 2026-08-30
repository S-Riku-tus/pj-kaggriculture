"""Compare V10/V11 and Top-3 daily strategy states on identical axes."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = {
    "v10": ROOT / "data/analysis/v15_v10_v11_public_episodes.csv",
    "v11": ROOT / "data/analysis/v15_v10_v11_public_episodes.csv",
    "rank1": ROOT / "data/analysis/v8_top3_full_episodes.csv",
    "rank2": ROOT / "data/analysis/v8_top3_full_episodes.csv",
    "rank3": ROOT / "data/analysis/v8_top3_full_episodes.csv",
}
DAYS = (1, 4, 5, 6, 7, 8, 9, 10, 11, 12, 15, 20, 24, 27, 29)
ASSETS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "GOOSE", "COW", "SHEEP")


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * quantile
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - position) + ordered[high] * (position - low)


def _load_rows(path: Path, label: str) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("label") == label]
    result = []
    for row in rows:
        if str(row.get("is_self_play", "")).lower() == "true":
            continue
        parsed: dict[str, Any] = dict(row)
        parsed["day_snapshots"] = json.loads(row.get("day_snapshots") or "{}")
        for key, value in row.items():
            if key == "day_snapshots" or value in (None, ""):
                continue
            try:
                parsed[key] = float(value)
            except ValueError:
                pass
        result.append(parsed)
    return result


def _asset(snapshot: dict[str, Any], asset: str) -> float:
    group = "animals" if asset in {"GOOSE", "COW", "SHEEP"} else "crops"
    return float((snapshot.get(group) or {}).get(asset, 0) or 0)


def _daily(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for day in DAYS:
        snapshots = [row["day_snapshots"].get(str(day)) for row in rows]
        snapshots = [snapshot for snapshot in snapshots if isinstance(snapshot, dict)]
        if not snapshots:
            continue
        money = [float(snapshot.get("money", 0) or 0) for snapshot in snapshots]
        result[str(day)] = {
            "money": {
                "mean": mean(money),
                "median": median(money),
                "p10": _percentile(money, 0.10),
            },
            "productive_tiles": mean(float(snapshot.get("productive_tiles", 0) or 0) for snapshot in snapshots),
            "utilization": mean(float(snapshot.get("utilization", 0) or 0) for snapshot in snapshots),
            "unlocked": mean(float(snapshot.get("unlocked", 0) or 0) for snapshot in snapshots),
            "assets": {asset: mean(_asset(snapshot, asset) for snapshot in snapshots) for asset in ASSETS},
        }
    return result


def _cohort(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rewards = [float(row["own_reward"]) for row in rows]
    cutoff = _percentile(rewards, 0.25)
    bottom = [row for row in rows if float(row["own_reward"]) <= cutoff]
    operational = (
        "hand_pass_rate",
        "productive_actions_per_hire",
        "field_feed",
        "field_care",
        "field_collect_fertilizer",
        "field_water",
        "field_harvest",
        "terminal_inventory_value",
        "max_cow",
        "max_sheep",
        "max_wheat",
        "max_strawberry",
    )
    return {
        "episodes": len(rows),
        "reward": {
            "mean": mean(rewards),
            "p10": _percentile(rewards, 0.10),
            "p25": cutoff,
            "minimum": min(rewards),
        },
        "daily": _daily(rows),
        "bottom_quartile": {
            "episodes": len(bottom),
            "reward_mean": mean(float(row["own_reward"]) for row in bottom),
            "operational": {metric: mean(float(row.get(metric, 0) or 0) for row in bottom) for metric in operational},
            "daily": _daily(bottom),
        },
    }


def _pool_top(cohorts: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    pooled: list[dict[str, Any]] = []
    for label in ("rank1", "rank2", "rank3"):
        pooled.extend(cohorts[label])
    return pooled


def _daily_gap(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for day in DAYS:
        key = str(day)
        if key not in left or key not in right:
            continue
        result[key] = {
            "money_mean": left[key]["money"]["mean"] - right[key]["money"]["mean"],
            "productive_tiles": left[key]["productive_tiles"] - right[key]["productive_tiles"],
            "utilization": left[key]["utilization"] - right[key]["utilization"],
            "unlocked": left[key]["unlocked"] - right[key]["unlocked"],
            "assets": {asset: left[key]["assets"][asset] - right[key]["assets"][asset] for asset in ASSETS},
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/analysis/v15_strategy_gap.json"))
    args = parser.parse_args()
    cohorts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for label, path in DEFAULT_SOURCES.items():
        cohorts[label] = _load_rows(path, label)
    cohorts["top3_pooled"] = _pool_top(cohorts)
    summaries = {label: _cohort(rows) for label, rows in cohorts.items()}
    payload = {
        "sources": {label: str(path.relative_to(ROOT)) for label, path in DEFAULT_SOURCES.items()},
        "cohorts": summaries,
        "gaps": {
            "v11_minus_rank1": _daily_gap(summaries["v11"]["daily"], summaries["rank1"]["daily"]),
            "v11_minus_top3_pooled": _daily_gap(summaries["v11"]["daily"], summaries["top3_pooled"]["daily"]),
        },
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"result: {output}")


if __name__ == "__main__":
    main()
