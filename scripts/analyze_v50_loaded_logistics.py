"""Compare loaded-worker logistics in V11 and Top-3 replay logs."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_v33_asset_labor import _actions, _farm, _positions  # noqa: E402
from scripts.analyze_v34_labor_value import SOURCES, _stats  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    _manifest,
    _observation,
    _replay_path,
    _split,
)

FORMAT = "kaggriculture-v50-loaded-logistics-v1"
DAYS = tuple(range(6, 13))
ITEMS = ("WHEAT", "FERTILIZER")
MOVES = {"NORTH", "SOUTH", "EAST", "WEST"}


def _count(inventory: Any, item: str) -> int:
    try:
        return max(0, int((inventory or {}).get(item, 0) or 0))
    except (AttributeError, TypeError, ValueError):
        return 0


def _day_row(
    replay: dict[str, Any], manifest: dict[str, str], source: str, day: int
) -> dict[str, Any] | None:
    seat = int(manifest["submission_seat"])
    episode_id = str(manifest["episode_id"])
    counts: Counter[str] = Counter()
    for step in range(day * 24, (day + 1) * 24):
        obs = _observation(replay, step, seat)
        next_obs = _observation(replay, step + 1, seat)
        if obs is None or next_obs is None:
            continue
        private = obs.get("private") or {}
        next_private = next_obs.get("private") or {}
        inventories = list(private.get("inventories") or [])
        next_inventories = list(next_private.get("inventories") or [])
        positions = _positions(_farm(obs, seat))
        actions = _actions(replay, step, seat)
        for unit in range(1, min(len(positions), len(actions), len(inventories))):
            action = actions[unit]
            op = str(action[0]) if action else "PASS"
            inventory = inventories[unit]
            next_inventory = (
                next_inventories[unit] if unit < len(next_inventories) else {}
            )
            loaded_items = [item for item in ITEMS if _count(inventory, item) > 0]
            if loaded_items:
                counts["loaded_turns"] += 1
                counts["loaded_pass"] += op == "PASS"
                counts["loaded_move"] += op in MOVES
                counts["loaded_productive"] += op != "PASS" and op not in MOVES
            for item in loaded_items:
                counts[f"{item.lower()}_loaded_turns"] += 1
                counts[f"{item.lower()}_unit_turns"] += _count(inventory, item)
                counts[f"{item.lower()}_pass"] += op == "PASS"
                counts[f"{item.lower()}_move"] += op in MOVES
                counts[f"{item.lower()}_productive"] += op != "PASS" and op not in MOVES
            if op == "PICKUP" and len(action) >= 2 and str(action[1]) in ITEMS:
                item = str(action[1])
                before = _count(inventory, item)
                after = _count(next_inventory, item)
                counts[f"pickup_{item.lower()}_actions"] += 1
                counts[f"pickup_{item.lower()}_units"] += max(0, after - before)
            if op == "FEED":
                counts["feed"] += 1
            elif op == "FERTILIZE":
                counts["fertilize"] += 1
            elif op == "DROP":
                counts["drop"] += 1
    return {
        "source": source,
        "episode_id": episode_id,
        "split": _split(episode_id),
        "result": str(manifest.get("result") or "unknown").lower(),
        "day": day,
        "counts": dict(counts),
    }


def _features(row: dict[str, Any]) -> dict[str, float]:
    counts = row["counts"]
    loaded = max(1, int(counts.get("loaded_turns", 0)))
    values = {
        key: float(counts.get(key, 0))
        for key in (
            "loaded_turns",
            "loaded_pass",
            "loaded_move",
            "loaded_productive",
            "pickup_wheat_actions",
            "pickup_wheat_units",
            "pickup_fertilizer_actions",
            "pickup_fertilizer_units",
            "feed",
            "fertilize",
            "drop",
        )
    }
    values.update(
        {
            "loaded_pass_rate": counts.get("loaded_pass", 0) / loaded,
            "loaded_move_rate": counts.get("loaded_move", 0) / loaded,
            "loaded_productive_rate": counts.get("loaded_productive", 0) / loaded,
        }
    )
    for item in ITEMS:
        prefix = item.lower()
        turns = max(1, int(counts.get(f"{prefix}_loaded_turns", 0)))
        values.update(
            {
                f"{prefix}_loaded_turns": float(
                    counts.get(f"{prefix}_loaded_turns", 0)
                ),
                f"{prefix}_mean_load": counts.get(f"{prefix}_unit_turns", 0)
                / turns,
                f"{prefix}_pass_rate": counts.get(f"{prefix}_pass", 0) / turns,
                f"{prefix}_move_rate": counts.get(f"{prefix}_move", 0) / turns,
                f"{prefix}_productive_rate": counts.get(
                    f"{prefix}_productive", 0
                )
                / turns,
            }
        )
    return values


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    features = [_features(row) for row in rows]
    return {
        "episode_days": len(rows),
        **(
            {
                metric: _stats([row[metric] for row in features])
                for metric in features[0]
            }
            if features
            else {}
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v50_loaded_logistics.json"),
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
            for day in DAYS:
                row = _day_row(replay, manifest, source, day)
                if row is not None:
                    rows.append(row)
    payload = {
        "format": FORMAT,
        "runtime_policy_enabled": False,
        "objective": "separate transport volume from loaded-worker execution quality",
        "data": {
            "episode_days": len(rows),
            "episodes": len({row["episode_id"] for row in rows}),
            "episode_disjoint_split": True,
        },
        "source_daily": {
            source: {
                str(day): {
                    "all": _summary(
                        [
                            row
                            for row in rows
                            if row["source"] == source and row["day"] == day
                        ]
                    ),
                    "win": _summary(
                        [
                            row
                            for row in rows
                            if row["source"] == source
                            and row["day"] == day
                            and row["result"] == "win"
                        ]
                    ),
                }
                for day in DAYS
            }
            for source in SOURCES
        },
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
            "metrics cover hired hands only; the permanent farmer is excluded",
            "successful pickup units use observed inventory delta and can be affected by same-turn consumption",
            "loaded productive includes any non-move non-PASS operation, not only one consuming the carried item",
            "teacher wins and source-specific branches remain separate",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["data"], ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
