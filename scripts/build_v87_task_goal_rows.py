"""Build episode-disjoint multi-turn task-goal teacher rows.

Each example begins when a Top-3 worker starts a movement segment.  The label
is not the next action: it is the first non-movement operation reached within
six turns, its public endpoint/asset, completion horizon, and 24/72-turn
relative farm state.  Incomplete routes remain explicit negative examples.
"""

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

from agents.v3.feature_schema import (  # noqa: E402
    ANIMALS,
    CROPS,
    FEATURE_NAMES,
    PRODUCTS,
    encode_observation,
    inventory_count,
)
from agents.v14 import main as v14  # noqa: E402
from scripts.analyze_v33_asset_labor import (  # noqa: E402
    _actions,
    _farm,
    _positions,
    _tile,
)
from scripts.analyze_v34_labor_value import SOURCES  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    _manifest,
    _observation,
    _replay_path,
    _split,
)

OUTPUT = ROOT / "data/training/v87_task_goal_rows.json"
SOURCE_CACHE_DIR = ROOT / "data/training/v87_task_goal_sources"
TEACHERS = ("rank1", "rank2", "rank3")
MOVES = {"NORTH", "SOUTH", "EAST", "WEST"}
LOOKAHEAD = 6
PREVIOUS_OPS = (
    "START",
    "PASS",
    "WATER",
    "HARVEST",
    "FEED",
    "CARE",
    "COLLECT_FERTILIZER",
    "FERTILIZE",
    "PLANT",
    "PICKUP",
    "DROP",
    "PLACE",
    "DIG",
    "BUILD_PASTURE",
    "BUILD_COOP",
    "OTHER",
)
TILE_CLASSES = (
    "EMPTY",
    "LOCKED",
    "WEED",
    "COOP",
    "PASTURE",
    *(f"CROP_{crop}" for crop in CROPS),
    *(f"ANIMAL_{animal}" for animal in ANIMALS),
    "OTHER",
)
LOCAL_FEATURE_NAMES = (
    "hour",
    "worker_x",
    "worker_y",
    "worker_index",
    "worker_fraction",
    *(f"inventory_{item}" for item in (*PRODUCTS, *ANIMALS)),
    *(f"previous_{op.lower()}" for op in PREVIOUS_OPS),
    *(f"tile_{name.lower()}" for name in TILE_CLASSES),
)
FEATURES = (*FEATURE_NAMES, *LOCAL_FEATURE_NAMES)


def _op(action: list[Any] | None) -> str:
    value = str(action[0]) if action else "PASS"
    if value in MOVES:
        return "MOVE"
    return value if value in PREVIOUS_OPS else "OTHER"


def _tile_class(tile: Any) -> str:
    if tile is None:
        return "EMPTY"
    if tile == "LOCKED":
        return "LOCKED"
    if not isinstance(tile, dict):
        return "OTHER"
    crop = str(tile.get("crop") or "")
    animal = str(tile.get("animal") or "")
    if crop in CROPS:
        return f"CROP_{crop}"
    if animal in ANIMALS:
        return f"ANIMAL_{animal}"
    kind = str(tile.get("kind") or "OTHER")
    return kind if kind in TILE_CLASSES else "OTHER"


def _local_features(obs: dict[str, Any], farm: dict[str, Any], seat: int, unit: int, previous: str) -> list[float]:
    positions = _positions(farm)
    position = positions[unit]
    board_size = max(1, len(farm.get("tiles") or []))
    private = obs.get("private") or {}
    inventories = private.get("inventories") or []
    inventory = inventories[unit] if unit < len(inventories) else {}
    previous_value = previous if previous in PREVIOUS_OPS else "OTHER"
    tile_value = _tile_class(_tile(farm, position))
    return [
        float(obs.get("hour", 0) or 0) / 23.0,
        position[0] / max(1, board_size - 1),
        position[1] / max(1, board_size - 1),
        unit / max(1, len(positions) - 1),
        len(positions) / 14.0,
        *(min(3.0, inventory_count(inventory, item) / 10.0) for item in (*PRODUCTS, *ANIMALS)),
        *(float(previous_value == value) for value in PREVIOUS_OPS),
        *(float(tile_value == value) for value in TILE_CLASSES),
    ]


def _goal(action: list[Any], tile: Any) -> str:
    op = str(action[0]) if action else "PASS"
    item = ""
    if op in {"PLANT", "PLACE", "PICKUP"} and len(action) >= 2:
        item = str(action[1])
    elif isinstance(tile, dict):
        item = str(tile.get("crop") or tile.get("animal") or tile.get("kind") or "")
    return f"{op}:{item or 'NONE'}"


def _relative_state(obs: dict[str, Any] | None, seat: int) -> dict[str, float]:
    if obs is None:
        return {
            "money_gap_ratio": 0.0,
            "productive_gap": 0.0,
            "own_productive": 0.0,
        }
    farms = obs.get("farms") or []
    if len(farms) < 2:
        return {
            "money_gap_ratio": 0.0,
            "productive_gap": 0.0,
            "own_productive": 0.0,
        }
    own, other = farms[seat], farms[1 - seat]
    own_summary = v14.base._farm_summary(own)
    other_summary = v14.base._farm_summary(other)
    own_money = float(own.get("money", 0) or 0)
    other_money = float(other.get("money", 0) or 0)
    return {
        "money_gap_ratio": (own_money - other_money) / max(1.0, own_money + other_money),
        "productive_gap": (float(own_summary["productive"]) - float(other_summary["productive"])) / 75.0,
        "own_productive": float(own_summary["productive"]) / 75.0,
    }


def _route_label(
    step: int,
    unit: int,
    day: int,
    observations: list[dict[str, Any] | None],
    farms: list[dict[str, Any]],
    positions_by_step: list[list[tuple[int, int]]],
    actions_by_step: list[list[list[Any]]],
) -> dict[str, Any]:
    for horizon in range(1, LOOKAHEAD + 1):
        future_step = step + horizon
        if future_step >= len(observations):
            break
        obs = observations[future_step]
        if obs is None or int(obs.get("day", -1) or -1) != day:
            break
        farm = farms[future_step]
        positions = positions_by_step[future_step]
        actions = actions_by_step[future_step]
        if unit >= len(positions) or unit >= len(actions):
            break
        action = actions[unit]
        op = str(action[0]) if action else "PASS"
        if op in MOVES:
            continue
        if op == "PASS":
            break
        position = positions[unit]
        return {
            "completed": 1.0,
            "goal": _goal(action, _tile(farm, position)),
            "endpoint_x": position[0] / max(1, len(farm.get("tiles") or []) - 1),
            "endpoint_y": position[1] / max(1, len(farm.get("tiles") or []) - 1),
            "horizon": horizon / LOOKAHEAD,
        }
    farm = farms[step]
    positions = positions_by_step[step] or [(0, 0)]
    position = positions[unit] if unit < len(positions) else (0, 0)
    return {
        "completed": 0.0,
        "goal": "INCOMPLETE:NONE",
        "endpoint_x": position[0] / max(1, len(farm.get("tiles") or []) - 1),
        "endpoint_y": position[1] / max(1, len(farm.get("tiles") or []) - 1),
        "horizon": (LOOKAHEAD + 1) / LOOKAHEAD,
    }


def _side(replay: dict[str, Any], manifest: dict[str, str], source: str) -> list[dict[str, Any]]:
    seat = int(manifest["submission_seat"])
    episode_id = str(manifest["episode_id"])
    result = str(manifest.get("result") or "unknown").lower()
    rows: list[dict[str, Any]] = []
    previous: list[list[Any]] = []
    step_count = max(0, len(replay.get("steps") or []) - 1)
    observations = [_observation(replay, step, seat) for step in range(step_count)]
    farms = [_farm(obs, seat) if obs is not None else {} for obs in observations]
    positions_by_step = [_positions(farm) if farm else [] for farm in farms]
    actions_by_step = [_actions(replay, step, seat) for step in range(step_count)]
    encoded_cache: dict[int, list[float]] = {}
    relative_cache: dict[int, dict[str, float]] = {}

    def relative_at(target_step: int) -> dict[str, float]:
        if not observations:
            return _relative_state(None, seat)
        target_step = min(len(observations) - 1, target_step)
        if target_step not in relative_cache:
            relative_cache[target_step] = _relative_state(observations[target_step], seat)
        return relative_cache[target_step]

    for step, obs in enumerate(observations):
        if obs is None:
            previous = []
            continue
        farm = farms[step]
        positions = positions_by_step[step]
        actions = actions_by_step[step]
        day = int(obs.get("day", 0) or 0)
        hour = int(obs.get("hour", 0) or 0)
        for unit, action in enumerate(actions):
            if unit >= len(positions):
                continue
            current_op = str(action[0]) if action else "PASS"
            previous_op = str(previous[unit][0]) if unit < len(previous) and previous[unit] else "START"
            if current_op not in MOVES or previous_op in MOVES:
                continue
            label = _route_label(
                step,
                unit,
                day,
                observations,
                farms,
                positions_by_step,
                actions_by_step,
            )
            future24 = relative_at(step + 24)
            future72 = relative_at(step + 72)
            if step not in encoded_cache:
                encoded_cache[step] = encode_observation(obs)
            features = [
                *encoded_cache[step],
                *_local_features(
                    obs,
                    farm,
                    seat,
                    unit,
                    _op(previous[unit]) if unit < len(previous) else "START",
                ),
            ]
            if len(features) != len(FEATURES):
                raise RuntimeError(f"feature mismatch: {len(features)} != {len(FEATURES)}")
            rows.append(
                {
                    "source": source,
                    "episode_id": episode_id,
                    "seat": seat,
                    "split": _split(episode_id),
                    "result": result,
                    "winner": result == "win",
                    "step": step,
                    "day": day,
                    "hour": hour,
                    "unit": unit,
                    "features": features,
                    "labels": {
                        **label,
                        "future24_money_gap_ratio": future24["money_gap_ratio"],
                        "future72_money_gap_ratio": future72["money_gap_ratio"],
                        "future24_productive_gap": future24["productive_gap"],
                        "future72_productive_gap": future72["productive_gap"],
                        "future24_own_productive": future24["own_productive"],
                        "future72_own_productive": future72["own_productive"],
                    },
                }
            )
        previous = [list(action or ["PASS"]) for action in actions]
        if hour == 23:
            previous = []
    return rows


def _source_rows(source: str) -> tuple[list[dict[str, Any]], Counter[str]]:
    cache_path = SOURCE_CACHE_DIR / f"{source}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("format") == "kaggriculture-v87-task-goal-source-v2":
            print(f"[{source} cache] {cache_path}", flush=True)
            return list(cached["rows"]), Counter(cached["source_sides"])

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    source_sides: Counter[str] = Counter()
    manifests = _manifest(SOURCES[source])
    for index, manifest in enumerate(manifests, start=1):
        if index == 1 or index % 25 == 0:
            print(f"[{source} {index}/{len(manifests)}]", flush=True)
        key = (source, str(manifest["episode_id"]), int(manifest["submission_seat"]))
        if key in seen:
            continue
        seen.add(key)
        replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
        rows.extend(_side(replay, manifest, source))
        result = str(manifest.get("result") or "unknown").lower()
        source_sides[f"{source}_{result}"] += 1
    cache = {
        "format": "kaggriculture-v87-task-goal-source-v2",
        "source": source,
        "source_sides": dict(source_sides),
        "rows": rows,
    }
    SOURCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    print(f"[{source} saved] {cache_path}", flush=True)
    return rows, source_sides


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=TEACHERS)
    args = parser.parse_args()
    teachers = (args.source,) if args.source else TEACHERS
    rows: list[dict[str, Any]] = []
    source_sides: Counter[str] = Counter()
    for source in teachers:
        made, made_sides = _source_rows(source)
        rows.extend(made)
        source_sides.update(made_sides)
    if args.source:
        print(
            json.dumps(
                {
                    "source": args.source,
                    "rows": len(rows),
                    "winner_rows": sum(bool(row["winner"]) for row in rows),
                    "episodes": len({row["episode_id"] for row in rows}),
                    "source_sides": dict(source_sides),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    goals = Counter(str(row["labels"]["goal"]) for row in rows if row["winner"])
    payload = {
        "format": "kaggriculture-v87-task-goal-rows-v1",
        "lookahead": LOOKAHEAD,
        "feature_names": list(FEATURES),
        "data": {
            "rows": len(rows),
            "winner_rows": sum(bool(row["winner"]) for row in rows),
            "episodes": len({row["episode_id"] for row in rows}),
            "winner_episodes": len({row["episode_id"] for row in rows if row["winner"]}),
            "source_sides": dict(source_sides),
            "split_episodes": {
                split: len({row["episode_id"] for row in rows if row["split"] == split})
                for split in ("train", "validation", "test")
            },
            "episode_disjoint_split": True,
            "winner_goal_counts": dict(goals.most_common()),
        },
        "rows": rows,
        "limits": [
            "worker indices are stable within a day but are not persistent across days",
            "the goal is the first non-move non-PASS operation within six turns",
            "teacher route outcomes remain observational and policy/source confounded",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload["data"], ensure_ascii=False, indent=2))
    print(f"result: {OUTPUT}")


if __name__ == "__main__":
    main()
