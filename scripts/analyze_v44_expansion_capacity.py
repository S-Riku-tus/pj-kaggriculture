"""Compare whole-farm capacity choices during the first land expansion.

V42 established that Rank 1/2 preserve central newly unlocked cells for later
animal use while V11 fills them with crops.  This analysis checks the missing
counterfactual: whether the teachers move those crops elsewhere or deliberately
run a smaller crop portfolio and maintenance load.  Results are descriptive;
win/loss cohorts and episode-disjoint V11 splits are kept separate.
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

from agents.v3.feature_schema import CROPS, farm_summary  # noqa: E402
from scripts.analyze_v33_asset_labor import _farm  # noqa: E402
from scripts.analyze_v34_labor_value import SOURCES, _stats  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    _manifest,
    _observation,
    _replay_path,
    _split,
)

FORMAT = "kaggriculture-v44-expansion-capacity-v1"
DAYS = (5, 6, 7, 8, 9, 11, 14)
METRICS = (
    "money",
    "money_gap",
    "peak_workers",
    "unlocked_cells",
    "productive",
    "crops",
    "animals",
    "empty_land",
    "empty_pastures",
    "weeds",
    "unwatered",
    "unfed",
    "maintenance_actions",
    "maintenance_per_worker",
    *(f"crop_{crop.lower()}" for crop in CROPS),
    "cow",
    "sheep",
)


def _cell_counts(farm: dict[str, Any]) -> tuple[int, int]:
    unlocked = 0
    empty = 0
    for row in farm.get("tiles") or []:
        for tile in row:
            if tile == "LOCKED":
                continue
            unlocked += 1
            if tile is None:
                empty += 1
    return unlocked, empty


def _snapshot(obs: dict[str, Any], seat: int, peak_workers: int) -> dict[str, float]:
    farm = _farm(obs, seat)
    farms = obs.get("farms") or []
    player = int(obs.get("player", seat))
    opponent = farms[1 - player] if len(farms) >= 2 else {}
    summary = farm_summary(farm, int(obs.get("day", 0) or 0))
    unlocked, empty = _cell_counts(farm)
    crops = float(sum(summary["crops"].values()))
    animals = float(summary["animals"]["COW"] + summary["animals"]["SHEEP"])
    workers = float(max(1, peak_workers))
    maintenance = crops + 2.0 * animals
    return {
        "money": float(farm.get("money", 0) or 0),
        "money_gap": float(farm.get("money", 0) or 0)
        - float(opponent.get("money", 0) or 0),
        "peak_workers": workers,
        "unlocked_cells": float(unlocked),
        "productive": float(summary["productive"]),
        "crops": crops,
        "animals": animals,
        "empty_land": float(empty),
        "empty_pastures": float(summary["empty_structures"]),
        "weeds": float(summary["weeds"]),
        "unwatered": float(summary["unwatered"]),
        "unfed": float(summary["unfed"]),
        "maintenance_actions": maintenance,
        "maintenance_per_worker": maintenance / max(1.0, workers),
        **{
            f"crop_{crop.lower()}": float(summary["crops"][crop])
            for crop in CROPS
        },
        "cow": float(summary["animals"]["COW"]),
        "sheep": float(summary["animals"]["SHEEP"]),
    }


def _episode_row(
    replay: dict[str, Any], manifest: dict[str, str], source: str
) -> dict[str, Any] | None:
    seat = int(manifest["submission_seat"])
    snapshots: dict[str, dict[str, float]] = {}
    day5_obs = _observation(replay, 5 * 24, seat)
    if day5_obs is None:
        return None
    shops = sorted(
        str(shop)
        for shop in ((day5_obs.get("town") or {}).get("unlocked_shops") or [])
    )
    for day in DAYS:
        obs = _observation(replay, day * 24, seat)
        if obs is None:
            return None
        peak_workers = 1
        for step in range(day * 24, (day + 1) * 24):
            hourly = _observation(replay, step, seat)
            if hourly is None:
                continue
            peak_workers = max(
                peak_workers,
                1 + len(_farm(hourly, seat).get("hands") or []),
            )
        snapshots[str(day)] = _snapshot(obs, seat, peak_workers)
    return {
        "source": source,
        "episode_id": str(manifest["episode_id"]),
        "split": _split(str(manifest["episode_id"])),
        "result": str(manifest.get("result") or "unknown").lower(),
        "day5_shop": "+".join(shops) if shops else "NONE",
        "snapshots": snapshots,
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        str(day): {
            "rows": len(rows),
            **{
                metric: _stats(
                    [float(row["snapshots"][str(day)][metric]) for row in rows]
                )
                for metric in METRICS
            },
        }
        for day in DAYS
    }


def _cohorts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for source in SOURCES:
        source_rows = [row for row in rows if row["source"] == source]
        result[source] = {
            "all": _summary(source_rows),
            "win": _summary([row for row in source_rows if row["result"] == "win"]),
            "loss": _summary([row for row in source_rows if row["result"] == "loss"]),
        }
    top_rows = [row for row in rows if row["source"] != "v11"]
    result["top3_pooled"] = {
        "all": _summary(top_rows),
        "win": _summary([row for row in top_rows if row["result"] == "win"]),
        "loss": _summary([row for row in top_rows if row["result"] == "loss"]),
    }
    return result


def _shop_cohorts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    shops = sorted({row["day5_shop"] for row in rows})
    result = {}
    for source in (*SOURCES, "top3_pooled"):
        source_rows = (
            [row for row in rows if row["source"] != "v11"]
            if source == "top3_pooled"
            else [row for row in rows if row["source"] == source]
        )
        result[source] = {
            shop: _summary(
                [
                    row
                    for row in source_rows
                    if row["day5_shop"] == shop and row["result"] == "win"
                ]
            )
            for shop in shops
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v44_expansion_capacity.json"),
    )
    args = parser.parse_args()
    rows = []
    seen: set[tuple[str, str, int]] = set()
    for source, directory in SOURCES.items():
        manifests = _manifest(directory)
        for index, manifest in enumerate(manifests, start=1):
            if index == 1 or index % 50 == 0:
                print(f"[{source} {index}/{len(manifests)}]", flush=True)
            key = (
                source,
                str(manifest["episode_id"]),
                int(manifest["submission_seat"]),
            )
            if key in seen:
                continue
            seen.add(key)
            replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
            row = _episode_row(replay, manifest, source)
            if row is not None:
                rows.append(row)

    payload = {
        "format": FORMAT,
        "runtime_policy_enabled": False,
        "objective": (
            "separate crop relocation from deliberate capacity restraint during "
            "Day-5..14 expansion"
        ),
        "data": {
            "rows": len(rows),
            "episodes": len({row["episode_id"] for row in rows}),
            "source_rows": {
                source: sum(row["source"] == source for row in rows)
                for source in SOURCES
            },
            "episode_disjoint_split": True,
        },
        "cohorts": _cohorts(rows),
        "day5_shop_win_cohorts": _shop_cohorts(rows),
        "v11_by_split": {
            split: _summary(
                [
                    row
                    for row in rows
                    if row["source"] == "v11" and row["split"] == split
                ]
            )
            for split in ("train", "validation", "test")
        },
        "interpretation_limits": [
            "snapshot counts are descriptive and do not prove causal score effects",
            "maintenance_actions is a lower-bound proxy: one water per crop and "
            "feed plus care per animal, excluding movement and harvest",
            "top-team wins and losses are reported separately to avoid treating every logged trajectory as optimal",
            "source-specific branches remain visible alongside the pooled Top-3 summary",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["data"], ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
