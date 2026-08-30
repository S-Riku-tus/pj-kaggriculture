"""Measure whether Top-3 terminal route goals exist in V14's legal task set."""

from __future__ import annotations

import gc
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v14 import main as v14  # noqa: E402
from scripts.analyze_v34_labor_value import SOURCES  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    _manifest,
    _observation,
    _replay_path,
)

SOURCE_DIR = ROOT / "data/training/v87_task_goal_sources"
OUTPUT = ROOT / "data/analysis/v89_candidate_coverage.json"
TEACHERS = ("rank1", "rank2", "rank3")
SAMPLE_MODULUS = 30
base = v14.base
v11 = v14.v11
v5 = v14.v5


def _sample_key(row: dict[str, Any]) -> int:
    episode = str(row["episode_id"])
    episode_value = int(episode) if episode.isdigit() else sum(map(ord, episode))
    return episode_value * 1_000_003 + int(row["step"]) * 37 + int(row["unit"]) * 101


def _phase(day: int) -> str:
    if day <= 4:
        return "d00_04"
    if day <= 12:
        return "d05_12"
    if day <= 19:
        return "d13_19"
    if day <= 24:
        return "d20_24"
    return "d25_29"


def _tile_at(farm: Any, position: tuple[int, int]) -> Any:
    tiles = base._get(farm, "tiles", []) or []
    x, y = position
    if 0 <= y < len(tiles) and 0 <= x < len(tiles[y]):
        return tiles[y][x]
    return None


def _task_goal(task: dict[str, Any], farm: Any) -> str:
    action = list(task.get("action") or ["PASS"])
    operation = str(action[0])
    item = ""
    if operation in {"PLANT", "PLACE", "PICKUP"} and len(action) >= 2:
        item = str(action[1])
    else:
        tile = _tile_at(farm, task.get("pos", (0, 0)))
        item = str(base._get(tile, "crop", "") or base._get(tile, "animal", "") or base._get(tile, "kind", "") or "")
    return f"{operation}:{item or 'NONE'}"


def _state(
    replay: dict[str, Any], seat: int, step: int
) -> tuple[Any, Any, list[tuple[int, int]], list[Any], list[dict[str, Any]]] | None:
    obs = _observation(replay, step, seat)
    safe = base._safe_observation(obs) if obs is not None else None
    if safe is None:
        return None
    farm, opponent_farm, private = safe
    summary = base._farm_summary(farm)
    animal_targets, crop_targets, _hands, _land, _weights, pasture_target = v14._strategy_targets(
        obs, farm, opponent_farm, private
    )
    positions = [tuple(base._get(farm, "farmer", [0, 0]))]
    positions.extend(tuple(position) for position in (base._get(farm, "hands", []) or []))
    raw_inventories = list(base._get(private, "inventories", []) or [])
    inventories = [raw_inventories[index] if index < len(raw_inventories) else {} for index in range(len(positions))]
    tasks, _reserved = v11._field_tasks(
        obs,
        farm,
        private,
        positions,
        inventories,
        summary,
        animal_targets,
        crop_targets,
        pasture_target,
        opponent_farm,
    )
    return obs, farm, positions, inventories, tasks


def _blank() -> dict[str, float]:
    return {
        "rows": 0.0,
        "operation_available": 0.0,
        "exact_goal_available": 0.0,
        "exact_endpoint_available": 0.0,
        "exact_goal_feasible": 0.0,
        "exact_endpoint_feasible": 0.0,
        "exact_goal_top1_individual": 0.0,
        "candidate_count_sum": 0.0,
        "feasible_count_sum": 0.0,
        "exact_best_rank_sum": 0.0,
        "exact_best_rank_rows": 0.0,
    }


def _add(bucket: dict[str, float], values: dict[str, float]) -> None:
    for key, value in values.items():
        bucket[key] += value


def _finalize(bucket: dict[str, float]) -> dict[str, float | int]:
    rows = max(1.0, bucket["rows"])
    rank_rows = max(1.0, bucket["exact_best_rank_rows"])
    return {
        "rows": int(bucket["rows"]),
        "operation_available_rate": round(bucket["operation_available"] / rows, 5),
        "exact_goal_available_rate": round(bucket["exact_goal_available"] / rows, 5),
        "exact_endpoint_available_rate": round(bucket["exact_endpoint_available"] / rows, 5),
        "exact_goal_feasible_rate": round(bucket["exact_goal_feasible"] / rows, 5),
        "exact_endpoint_feasible_rate": round(bucket["exact_endpoint_feasible"] / rows, 5),
        "exact_goal_top1_individual_rate": round(bucket["exact_goal_top1_individual"] / rows, 5),
        "mean_candidates": round(bucket["candidate_count_sum"] / rows, 3),
        "mean_feasible_candidates": round(bucket["feasible_count_sum"] / rows, 3),
        "mean_exact_best_individual_rank_when_feasible": round(bucket["exact_best_rank_sum"] / rank_rows, 3),
    }


def _measure(
    row: dict[str, Any],
    farm: Any,
    positions: list[tuple[int, int]],
    inventories: list[Any],
    tasks: list[dict[str, Any]],
) -> dict[str, float] | None:
    unit = int(row["unit"])
    if unit >= len(positions) or unit >= len(inventories):
        return None
    goal = str(row["goal"])
    operation = goal.split(":", 1)[0]
    board_size = max(1, len(base._get(farm, "tiles", []) or []))
    endpoint = (
        round(float(row["endpoint_x"]) * max(1, board_size - 1)),
        round(float(row["endpoint_y"]) * max(1, board_size - 1)),
    )
    task_goals = [_task_goal(task, farm) for task in tasks]
    feasible_indices = [index for index, task in enumerate(tasks) if base._can_do(task, unit, inventories[unit])]
    exact_indices = [index for index, value in enumerate(task_goals) if value == goal]
    exact_endpoint = [index for index in exact_indices if tasks[index].get("pos") == endpoint]
    exact_feasible = [index for index in exact_indices if index in feasible_indices]
    endpoint_feasible = [index for index in exact_endpoint if index in feasible_indices]
    density = Counter(task["pos"] for task in tasks)
    ranked = sorted(
        feasible_indices,
        key=lambda index: v5._assignment_cost(unit, tasks[index], positions, inventories, density),
    )
    ranks = {task_index: rank for rank, task_index in enumerate(ranked, start=1)}
    exact_ranks = [ranks[index] for index in exact_feasible]
    return {
        "rows": 1.0,
        "operation_available": float(any(value.split(":", 1)[0] == operation for value in task_goals)),
        "exact_goal_available": float(bool(exact_indices)),
        "exact_endpoint_available": float(bool(exact_endpoint)),
        "exact_goal_feasible": float(bool(exact_feasible)),
        "exact_endpoint_feasible": float(bool(endpoint_feasible)),
        "exact_goal_top1_individual": float(bool(exact_ranks) and min(exact_ranks) == 1),
        "candidate_count_sum": float(len(tasks)),
        "feasible_count_sum": float(len(feasible_indices)),
        "exact_best_rank_sum": float(min(exact_ranks)) if exact_ranks else 0.0,
        "exact_best_rank_rows": float(bool(exact_ranks)),
    }


def main() -> None:
    buckets: defaultdict[str, dict[str, float]] = defaultdict(_blank)
    sampled: Counter[str] = Counter()
    skipped_incomplete: Counter[str] = Counter()
    for source in TEACHERS:
        manifests = {(str(row["episode_id"]), int(row["submission_seat"])): row for row in _manifest(SOURCES[source])}
        print(f"[{source}] loading route rows", flush=True)
        payload = json.loads((SOURCE_DIR / f"{source}.json").read_text(encoding="utf-8"))
        grouped: defaultdict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        for row in payload["rows"]:
            if not row["winner"] or _sample_key(row) % SAMPLE_MODULUS:
                continue
            labels = row["labels"]
            if not labels["completed"]:
                skipped_incomplete[source] += 1
                continue
            grouped[(str(row["episode_id"]), int(row["seat"]))].append(
                {
                    "split": str(row["split"]),
                    "step": int(row["step"]),
                    "day": int(row["day"]),
                    "unit": int(row["unit"]),
                    "goal": str(labels["goal"]),
                    "endpoint_x": float(labels["endpoint_x"]),
                    "endpoint_y": float(labels["endpoint_y"]),
                }
            )
        del payload
        gc.collect()

        for episode_index, (key, rows) in enumerate(grouped.items(), start=1):
            if episode_index == 1 or episode_index % 25 == 0:
                print(f"[{source} episodes {episode_index}/{len(grouped)}]", flush=True)
            manifest = manifests.get(key)
            if manifest is None:
                continue
            replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
            state_cache: dict[int, Any] = {}
            for row in rows:
                step = int(row["step"])
                if step not in state_cache:
                    state_cache[step] = _state(replay, key[1], step)
                state = state_cache[step]
                if state is None:
                    continue
                _obs, farm, positions, inventories, tasks = state
                values = _measure(row, farm, positions, inventories, tasks)
                if values is None:
                    continue
                sampled[source] += 1
                split = str(row["split"])
                phase = _phase(int(row["day"]))
                operation = str(row["goal"]).split(":", 1)[0]
                for bucket in (
                    "all",
                    f"source:{source}",
                    f"split:{split}",
                    f"source:{source}:split:{split}",
                    f"source:{source}:phase:{phase}",
                    f"operation:{operation}",
                ):
                    _add(buckets[bucket], values)
            del replay
        gc.collect()

    result = {
        "format": "kaggriculture-v89-candidate-coverage-v1",
        "sample_modulus": SAMPLE_MODULUS,
        "sampled_completed_routes": dict(sampled),
        "sampled_incomplete_routes_excluded": dict(skipped_incomplete),
        "buckets": {key: _finalize(value) for key, value in sorted(buckets.items())},
        "definitions": {
            "available": "a V14 task exists regardless of this worker's current inventory",
            "feasible": "base._can_do allows this V14 task for the teacher worker now",
            "exact_endpoint": "goal and public endpoint both match the teacher terminal operation",
            "top1_individual": "lowest V5 cost for this worker, before global Hungarian competition",
        },
        "limits": [
            "terminal goals may require a pickup/drop precursor and need not be immediately feasible",
            "individual cost rank is not the final multi-worker Hungarian assignment",
            "V14 task generation is evaluated on teacher states, not states induced by V14",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "sampled": dict(sampled),
                "all": result["buckets"].get("all", {}),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"result: {OUTPUT}")


if __name__ == "__main__":
    main()
