"""Compare V11 and Rank-1 worker pipelines on Days 11-12."""

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

from agents.v11 import main as v11  # noqa: E402
from scripts.train_v12_relative_policy import _manifest, _observation, _replay_path, _split  # noqa: E402

FORMAT = "kaggriculture-v32-worker-pipeline-v1"
SOURCES = {
    "v11": ROOT / "data/submissions/v11_submission_55787906",
    "rank1": ROOT / "data/submissions/leaderboard_rank1_submission_55614463",
}
DAYS = (11, 12)
MOVEMENT = {"NORTH", "SOUTH", "EAST", "WEST"}


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


def _farm(obs: dict[str, Any], seat: int) -> dict[str, Any]:
    farms = obs.get("farms") or []
    player = int(obs.get("player", seat))
    return farms[player] if 0 <= player < len(farms) else {}


def _positions(farm: dict[str, Any]) -> list[tuple[int, int]]:
    result = [tuple(farm.get("farmer") or [0, 0])]
    result.extend(tuple(value) for value in (farm.get("hands") or []))
    return result


def _actions(replay: dict[str, Any], stored_step: int, seat: int) -> list[list[Any]]:
    steps = replay.get("steps") or []
    if not 0 <= stored_step < len(steps):
        return []
    action = steps[stored_step][seat].get("action") or {}
    result = [list(action.get("farmer") or ["PASS"])]
    result.extend(list(value or ["PASS"]) for value in (action.get("hands") or []))
    return result


def _tile(farm: dict[str, Any], position: tuple[int, int]) -> Any:
    x, y = position
    tiles = farm.get("tiles") or []
    return tiles[y][x] if 0 <= y < len(tiles) and 0 <= x < len(tiles[y]) else None


def _place(farm: dict[str, Any], position: tuple[int, int]) -> str:
    tile = _tile(farm, position)
    if v11.base._get(tile, "animal") in v11.base.ANIMAL_DATA:
        return "animal"
    if v11.base._tile_kind(tile) == "PLANT":
        return "plant"
    size = len(farm.get("tiles") or [])
    if size and position in set(v11.base._shed_tiles(size)):
        return "shed"
    return "other"


def _kind(action: list[Any]) -> str:
    op = str(action[0]) if action else "PASS"
    if op == "PASS":
        return "pass"
    if op in MOVEMENT:
        return "move"
    return "productive"


def _side(replay: dict[str, Any], seat: int, episode_id: str, source: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    steps = replay.get("steps") or []
    for step in range(len(steps) - 2):
        obs = _observation(replay, step, seat)
        next_obs = _observation(replay, step + 1, seat)
        if obs is None or next_obs is None or int(obs.get("day", -1)) not in DAYS:
            continue
        farm = _farm(obs, seat)
        next_farm = _farm(next_obs, seat)
        positions = _positions(farm)
        next_positions = _positions(next_farm)
        actions = _actions(replay, step + 1, seat)
        next_actions = _actions(replay, step + 2, seat)
        transition: Counter[str] = Counter()
        operation: Counter[str] = Counter()
        place_action: Counter[str] = Counter()
        move_next_place: Counter[str] = Counter()
        animal_chain = 0
        animal_actions = 0
        move_productive = 0
        moves = 0
        for unit in range(1, min(len(positions), len(actions))):
            current_action = actions[unit]
            current_kind = _kind(current_action)
            current_op = str(current_action[0]) if current_action else "PASS"
            operation[current_op] += 1
            current_place = _place(farm, positions[unit])
            place_action[f"{current_place}:{current_kind}"] += 1
            if unit >= len(next_actions) or unit >= len(next_positions):
                continue
            next_action = next_actions[unit]
            next_kind = _kind(next_action)
            transition[f"{current_kind}->{next_kind}"] += 1
            if current_kind == "move":
                moves += 1
                destination = _place(next_farm, next_positions[unit])
                move_next_place[f"{destination}:{next_kind}"] += 1
                move_productive += next_kind == "productive"
            if current_kind == "productive" and current_place == "animal":
                animal_actions += 1
                if (
                    next_kind == "productive"
                    and positions[unit] == next_positions[unit]
                    and _place(next_farm, next_positions[unit]) == "animal"
                ):
                    animal_chain += 1
        occupancy = Counter(positions[1:])
        collision = sum(max(0, count - 1) for count in occupancy.values())
        animal_occupancy = sum(
            count for position, count in occupancy.items() if _place(farm, position) == "animal"
        )
        animal_collision = sum(
            max(0, count - 1)
            for position, count in occupancy.items()
            if _place(farm, position) == "animal"
        )
        rows.append(
            {
                "source": source,
                "episode_id": episode_id,
                "split": _split(episode_id),
                "day": int(obs.get("day", 0) or 0),
                "hour": int(obs.get("hour", 0) or 0),
                "hands": max(0, len(positions) - 1),
                "transition": dict(transition),
                "operation": dict(operation),
                "place_action": dict(place_action),
                "move_next_place": dict(move_next_place),
                "moves": moves,
                "move_productive": move_productive,
                "animal_actions": animal_actions,
                "animal_chain": animal_chain,
                "worker_collision": collision,
                "animal_occupancy": animal_occupancy,
                "animal_collision": animal_collision,
            }
        )
    return rows


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    transition: Counter[str] = Counter()
    operation: Counter[str] = Counter()
    place_action: Counter[str] = Counter()
    move_next_place: Counter[str] = Counter()
    for row in rows:
        transition.update(row["transition"])
        operation.update(row["operation"])
        place_action.update(row["place_action"])
        move_next_place.update(row["move_next_place"])
    decisions = max(1, len(rows))
    moves = sum(int(row["moves"]) for row in rows)
    animal_actions = sum(int(row["animal_actions"]) for row in rows)
    return {
        "decision_states": len(rows),
        "hands": _stats([float(row["hands"]) for row in rows]),
        "operations_per_state": {name: value / decisions for name, value in operation.items()},
        "transitions_per_state": {name: value / decisions for name, value in transition.items()},
        "place_actions_per_state": {name: value / decisions for name, value in place_action.items()},
        "move_destination_next_action_per_state": {
            name: value / decisions for name, value in move_next_place.items()
        },
        "move_to_productive_rate": sum(int(row["move_productive"]) for row in rows)
        / max(1, moves),
        "animal_productive_chain_rate": sum(int(row["animal_chain"]) for row in rows)
        / max(1, animal_actions),
        "worker_collision": _stats([float(row["worker_collision"]) for row in rows]),
        "animal_occupancy": _stats([float(row["animal_occupancy"]) for row in rows]),
        "animal_collision": _stats([float(row["animal_collision"]) for row in rows]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=Path("data/analysis/v32_worker_pipeline.json")
    )
    args = parser.parse_args()
    rows: list[dict[str, Any]] = []
    for source, directory in SOURCES.items():
        manifests = _manifest(directory)
        for index, manifest in enumerate(manifests, start=1):
            if index == 1 or index % 25 == 0:
                print(f"[{source} {index}/{len(manifests)}]", flush=True)
            replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
            rows.extend(
                _side(
                    replay,
                    int(manifest["submission_seat"]),
                    str(manifest["episode_id"]),
                    source,
                )
            )
    payload = {
        "format": FORMAT,
        "objective": "compare movement conversion, service chains, and worker clustering",
        "source_day_summary": {
            source: {
                str(day): _summary(
                    [row for row in rows if row["source"] == source and row["day"] == day]
                )
                for day in DAYS
            }
            for source in SOURCES
        },
        "v11_split_summary": {
            split: _summary(
                [row for row in rows if row["source"] == "v11" and row["split"] == split]
            )
            for split in ("train", "validation", "test")
        },
        "interpretation": {
            "fact": "worker indices are compared only while present in consecutive observations",
            "limit": "transition frequencies describe behavior and do not establish causal value",
        },
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["source_day_summary"], ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
