"""Compare daily worker-role portfolios in V11 and Top-3 replay logs."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, pstdev
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

FORMAT = "kaggriculture-v56-daily-worker-roles-v1"
DAYS = tuple(range(6, 13))
MOVES = {"NORTH", "SOUTH", "EAST", "WEST"}
ROLE_FOR_OP = {
    "FEED": "ANIMAL",
    "CARE": "ANIMAL",
    "COLLECT_FERTILIZER": "ANIMAL",
    "PLACE": "ANIMAL",
    "WATER": "CROP",
    "PLANT": "CROP",
    "FERTILIZE": "CROP",
    "PICKUP": "LOGISTICS",
    "DROP": "LOGISTICS",
    "BUILD_PASTURE": "INFRA",
    "DIG": "INFRA",
}


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = probability * (len(ordered) - 1)
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _tile_at(farm: Any, position: tuple[int, int]) -> Any:
    tiles = farm.get("tiles", []) if isinstance(farm, dict) else []
    x, y = position
    if 0 <= y < len(tiles) and 0 <= x < len(tiles[y]):
        return tiles[y][x]
    return None


def _role(op: str, tile: Any) -> str | None:
    if op == "HARVEST":
        if isinstance(tile, dict) and tile.get("animal"):
            return "ANIMAL"
        if isinstance(tile, dict) and tile.get("kind") == "PLANT":
            return "CROP"
        return "HARVEST_OTHER"
    if op in MOVES or op == "PASS":
        return None
    return ROLE_FOR_OP.get(op, "OTHER")


def _entropy(counts: Counter[str]) -> float:
    total = sum(counts.values())
    active = sum(value > 0 for value in counts.values())
    if total <= 0 or active <= 1:
        return 0.0
    raw = -sum(
        (value / total) * math.log(value / total)
        for value in counts.values()
        if value > 0
    )
    return raw / math.log(active)


def _day_row(
    replay: dict[str, Any], manifest: dict[str, str], source: str, day: int
) -> dict[str, Any] | None:
    seat = int(manifest["submission_seat"])
    episode_id = str(manifest["episode_id"])
    counts: dict[int, Counter[str]] = defaultdict(Counter)
    roles: dict[int, Counter[str]] = defaultdict(Counter)
    previous: dict[int, tuple[str, tuple[int, int]]] = {}
    transitions: Counter[str] = Counter()
    workers: set[int] = set()
    for step in range(day * 24, (day + 1) * 24):
        obs = _observation(replay, step, seat)
        if obs is None:
            continue
        farm = _farm(obs, seat)
        positions = _positions(farm)
        actions = _actions(replay, step, seat)
        for unit in range(1, min(len(positions), len(actions))):
            workers.add(unit)
            action = actions[unit]
            op = str(action[0]) if action else "PASS"
            counts[unit]["turns"] += 1
            if op in MOVES:
                counts[unit]["move"] += 1
                continue
            if op == "PASS":
                counts[unit]["pass"] += 1
                continue
            counts[unit]["productive"] += 1
            current_role = _role(op, _tile_at(farm, positions[unit]))
            if current_role is None:
                continue
            roles[unit][current_role] += 1
            old = previous.get(unit)
            if old is not None:
                old_role, old_position = old
                transitions["total"] += 1
                transitions["same_role"] += old_role == current_role
                transitions["same_position"] += old_position == positions[unit]
                transitions["distance"] += abs(old_position[0] - positions[unit][0]) + abs(
                    old_position[1] - positions[unit][1]
                )
            previous[unit] = (current_role, positions[unit])
    if not workers:
        return None
    ordered = sorted(workers)
    productive = [float(counts[unit]["productive"]) for unit in ordered]
    passes = [float(counts[unit]["pass"]) for unit in ordered]
    moves = [float(counts[unit]["move"]) for unit in ordered]
    role_events = sum(sum(roles[unit].values()) for unit in ordered)
    role_dominant = sum(max(roles[unit].values(), default=0) for unit in ordered)
    total_productive = sum(productive)
    total_pass = sum(passes)
    total_move = sum(moves)
    productivity_mean = mean(productive)
    role_workers = {
        role: sum(roles[unit][role] > 0 for unit in ordered)
        for role in ("ANIMAL", "CROP", "LOGISTICS", "INFRA")
    }
    role_ops = {
        role: sum(roles[unit][role] for unit in ordered)
        for role in ("ANIMAL", "CROP", "LOGISTICS", "INFRA")
    }
    return {
        "source": source,
        "episode_id": episode_id,
        "split": _split(episode_id),
        "result": str(manifest.get("result") or "unknown").lower(),
        "day": day,
        "metrics": {
            "hands_peak": float(len(ordered)),
            "productive_actions": total_productive,
            "productive_per_hand": productivity_mean,
            "productive_p10_hand": _percentile(productive, 0.10),
            "productive_min_hand": min(productive),
            "zero_productive_hands": float(sum(value <= 0 for value in productive)),
            "worker_productivity_cv": pstdev(productive) / max(1.0, productivity_mean),
            "move_per_productive": total_move / max(1.0, total_productive),
            "pass_per_hand": total_pass / len(ordered),
            "pass_concentration": max(passes) / max(1.0, total_pass),
            "dominant_role_share": role_dominant / max(1, role_events),
            "mean_role_entropy": mean([_entropy(roles[unit]) for unit in ordered]),
            "multi_role_hands": float(sum(len(roles[unit]) >= 2 for unit in ordered)),
            "same_role_transition_rate": transitions["same_role"] / max(1, transitions["total"]),
            "same_position_transition_rate": transitions["same_position"] / max(1, transitions["total"]),
            "productive_transition_distance": transitions["distance"] / max(1, transitions["total"]),
            "animal_workers": float(role_workers["ANIMAL"]),
            "animal_ops_per_worker": role_ops["ANIMAL"] / max(1, role_workers["ANIMAL"]),
            "crop_workers": float(role_workers["CROP"]),
            "crop_ops_per_worker": role_ops["CROP"] / max(1, role_workers["CROP"]),
            "logistics_workers": float(role_workers["LOGISTICS"]),
            "infra_workers": float(role_workers["INFRA"]),
        },
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"episode_days": 0}
    metrics = tuple(rows[0]["metrics"])
    return {
        "episode_days": len(rows),
        **{metric: _stats([row["metrics"][metric] for row in rows]) for metric in metrics},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v56_daily_roles.json"),
    )
    args = parser.parse_args()
    rows = []
    seen: set[tuple[str, str, int]] = set()
    for source, directory in SOURCES.items():
        manifests = _manifest(directory)
        for index, manifest in enumerate(manifests, start=1):
            if index == 1 or index % 50 == 0:
                print(f"[{source} {index}/{len(manifests)}]", flush=True)
            key = (source, str(manifest["episode_id"]), int(manifest["submission_seat"]))
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
        "objective": "separate daily role portfolios from unstable per-turn task edits",
        "data": {
            "episode_days": len(rows),
            "episodes": len({row["episode_id"] for row in rows}),
            "episode_disjoint_split": True,
        },
        "source_daily": {
            source: {
                str(day): {
                    "all": _summary([row for row in rows if row["source"] == source and row["day"] == day]),
                    "win": _summary(
                        [
                            row
                            for row in rows
                            if row["source"] == source and row["day"] == day and row["result"] == "win"
                        ]
                    ),
                }
                for day in DAYS
            }
            for source in SOURCES
        },
        "v11_by_split": {
            split: _summary([row for row in rows if row["source"] == "v11" and row["split"] == split])
            for split in ("train", "validation", "test")
        },
        "interpretation_limits": [
            "worker indices are treated as stable only within a day",
            "roles are inferred from visible operations and the tile under the worker",
            "high specialization is descriptive and is not assumed to be causally optimal",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["data"], ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
