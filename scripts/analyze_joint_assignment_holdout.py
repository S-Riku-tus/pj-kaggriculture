"""Evaluate candidate ranking as a joint multi-worker assignment on held-out Top-3 games.

Unlike V90/V91, sampling is state-level rather than worker-level.  Every route
start at the sampled state is retained, so the evaluation can measure whether
individually attractive candidates remain correct after the global Hungarian
matching and whether the first changes occur in adverse 24/72-hour states.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v92 import main as v92  # noqa: E402
from scripts import analyze_v89_candidate_coverage as v89  # noqa: E402
from scripts.train_v12_relative_policy import _manifest, _replay_path  # noqa: E402

OUTPUT = ROOT / "data/analysis/joint_assignment_holdout.json"
STATE_SAMPLE_MODULUS = 120
MIN_SCORE_GAP = 0.16
MAX_BASE_RANK = 3
CANDIDATE_BONUS = 1_600
MAX_EFFECTIVE_PRIORITY = 14_900
SPLITS = {"validation", "test"}


def _state_sample_key(row: dict[str, Any]) -> int:
    episode = str(row["episode_id"])
    episode_value = int(episode) if episode.isdigit() else sum(map(ord, episode))
    return episode_value * 1_000_003 + int(row["step"]) * 37


def _previous_actions(replay: dict[str, Any], seat: int, step: int) -> list[list[Any]]:
    if step <= 0:
        return []
    state = (replay.get("steps") or [])[step - 1][seat]
    action = state.get("action") or {}
    return [list(action.get("farmer") or ["PASS"]), *(list(value or ["PASS"]) for value in action.get("hands") or [])]


def _decode(costs: list[list[int]], task_count: int) -> dict[int, int]:
    unit_count = len(costs)
    if not unit_count or not task_count:
        return {}
    impossible = 10**8
    dummy = 0
    selected: dict[int, int] = {}
    if unit_count <= task_count:
        matrix = [
            [*row[:task_count], *([dummy] * unit_count)]
            for row in costs
        ]
        for unit, column in enumerate(v92.v14.v3._hungarian(matrix)):
            if 0 <= column < task_count and matrix[unit][column] < min(dummy, impossible):
                selected[unit] = column
    else:
        matrix = [
            [*(costs[unit][task] for unit in range(unit_count)), *([dummy] * task_count)]
            for task in range(task_count)
        ]
        for task, column in enumerate(v92.v14.v3._hungarian(matrix)):
            if 0 <= column < unit_count and matrix[task][column] < min(dummy, impossible):
                selected[column] = task
    return selected


def _constrained_joint_decode(
    baseline: dict[int, int],
    joint_costs: list[list[int]],
    positions: list[tuple[int, int]],
    tasks: list[dict[str, Any]],
) -> dict[int, int]:
    """Pin V14 emergency/immediate work, then solve only the residual matching."""
    pinned = {
        unit: task
        for unit, task in baseline.items()
        if int(tasks[task].get("priority", 0)) >= 15_000
        or v89.base._manhattan(positions[unit], tasks[task]["pos"]) == 0
    }
    pinned_tasks = set(pinned.values())
    remaining_units = [unit for unit in range(len(positions)) if unit not in pinned]
    remaining_tasks = [task for task in range(len(tasks)) if task not in pinned_tasks]
    if not remaining_units or not remaining_tasks:
        return dict(pinned)
    compact_costs = [
        [joint_costs[unit][task] for task in remaining_tasks]
        for unit in remaining_units
    ]
    compact = _decode(compact_costs, len(remaining_tasks))
    result = dict(pinned)
    result.update(
        {
            remaining_units[compact_unit]: remaining_tasks[compact_task]
            for compact_unit, compact_task in compact.items()
        }
    )
    return result


def _injective(positive: dict[int, set[int]]) -> bool:
    matched: dict[int, int] = {}

    def visit(unit: int, seen: set[int]) -> bool:
        for task in positive[unit]:
            if task in seen:
                continue
            seen.add(task)
            if task not in matched or visit(matched[task], seen):
                matched[task] = unit
                return True
        return False

    return all(visit(unit, set()) for unit in sorted(positive, key=lambda value: len(positive[value])))


def _method_metrics(
    assignment: dict[int, int],
    labeled: dict[int, dict[str, Any]],
    positives: dict[int, set[int]],
    task_goals: list[str],
    tasks: list[dict[str, Any]],
) -> dict[str, float]:
    exact = goal = operation = endpoint = 0
    for unit, teacher in labeled.items():
        chosen = assignment.get(unit)
        if chosen is None:
            continue
        exact += chosen in positives[unit]
        chosen_goal = task_goals[chosen]
        goal += chosen_goal == teacher["goal"]
        operation += chosen_goal.split(":", 1)[0] == teacher["goal"].split(":", 1)[0]
        endpoint += tuple(tasks[chosen]["pos"]) == teacher["endpoint"]
    count = max(1, len(labeled))
    return {
        "worker_exact": exact / count,
        "worker_goal": goal / count,
        "worker_operation": operation / count,
        "worker_endpoint": endpoint / count,
        "all_exact": float(exact == len(labeled)),
    }


def _money_bin(value: float) -> str:
    if value < -0.25:
        return "lt_-0.25"
    if value < 0.0:
        return "-0.25_0"
    if value < 0.25:
        return "0_0.25"
    return "ge_0.25"


def _evaluate_state(
    rows: list[dict[str, Any]],
    replay: dict[str, Any],
    seat: int,
) -> tuple[str, dict[str, Any] | None]:
    step = int(rows[0]["step"])
    state = v89._state(replay, seat, step)
    if state is None:
        return "missing_state", None
    obs, farm, positions, inventories, tasks = state
    if not positions or not tasks:
        return "empty_state", None
    board_size = max(1, len(v89.base._get(farm, "tiles", []) or []))
    task_goals = [v89._task_goal(task, farm) for task in tasks]
    density = Counter(task["pos"] for task in tasks)
    labeled: dict[int, dict[str, Any]] = {}
    positives: dict[int, set[int]] = {}
    for row in rows:
        unit = int(row["unit"])
        if unit >= len(positions) or unit >= len(inventories):
            continue
        labels = row["labels"]
        endpoint = (
            round(float(labels["endpoint_x"]) * max(1, board_size - 1)),
            round(float(labels["endpoint_y"]) * max(1, board_size - 1)),
        )
        feasible = {
            index
            for index, task in enumerate(tasks)
            if v89.base._can_do(task, unit, inventories[unit])
        }
        exact = {
            index
            for index in feasible
            if task_goals[index] == str(labels["goal"])
            and tuple(tasks[index].get("pos", ())) == endpoint
        }
        labeled[unit] = {"goal": str(labels["goal"]), "endpoint": endpoint}
        positives[unit] = exact
    if len(labeled) < 2:
        return "fewer_than_two_valid_workers", None
    if any(not positives[unit] for unit in labeled):
        return "teacher_task_not_feasible", None
    if not _injective(positives):
        return "teacher_tasks_conflict", None

    base_costs = [
        [
            v92._SAFE_ASSIGNMENT_COST(unit, task, positions, inventories, density)
            for task in tasks
        ]
        for unit in range(len(positions))
    ]
    gated_costs = [list(row) for row in base_costs]
    joint_costs = [list(row) for row in base_costs]
    previous = _previous_actions(replay, seat, step)
    annotations: dict[int, dict[str, Any]] = {}
    independent_choices: list[int] = []
    scores_by_unit: dict[int, dict[int, float]] = {}
    ood_workers = 0

    for unit, position in enumerate(positions):
        if unit >= len(inventories):
            continue
        prior = previous[unit] if unit < len(previous) else None
        if v92.v88._previous_op(prior) == "MOVE":
            continue
        state_features = v92.v88._features(obs, farm, positions, inventories[unit], unit, prior)
        if v92._is_ood(state_features):
            ood_workers += 1
            continue
        feasible = [
            index
            for index, task in enumerate(tasks)
            if v89.base._can_do(task, unit, inventories[unit])
            and v89.base._manhattan(position, task["pos"]) > 0
        ]
        if len(feasible) < 2:
            continue
        maximum_priority = max(int(tasks[index].get("priority", 0)) for index in feasible)
        scores = {
            index: v92._score(
                [
                    *state_features,
                    *v92._candidate_features(
                        tasks[index],
                        task_goals[index],
                        unit,
                        positions,
                        inventories,
                        density,
                        maximum_priority,
                    ),
                ]
            )
            for index in feasible
        }
        scores_by_unit[unit] = scores
        for index, score in scores.items():
            joint_costs[unit][index] -= round(CANDIDATE_BONUS * 100 * score)
        ranked = sorted(feasible, key=lambda index: (-scores[index], base_costs[unit][index], index))
        independent_choices.append(ranked[0])
        gap = scores[ranked[0]] - scores[ranked[1]]
        base_order = sorted(feasible, key=lambda index: (base_costs[unit][index], index))
        base_rank = base_order.index(ranked[0]) + 1
        chosen = ranked[0]
        priority = int(tasks[chosen].get("priority", 0))
        bonus = min(CANDIDATE_BONUS, max(0, MAX_EFFECTIVE_PRIORITY - priority))
        accepted = gap >= MIN_SCORE_GAP and base_rank <= MAX_BASE_RANK and bonus > 0
        if accepted:
            gated_costs[unit][chosen] -= bonus * 100
        annotations[unit] = {
            "chosen": chosen,
            "gap": gap,
            "base_rank": base_rank,
            "accepted": accepted,
            "bonus": bonus if accepted else 0,
        }

    baseline = _decode(base_costs, len(tasks))
    gated = _decode(gated_costs, len(tasks))
    joint = _constrained_joint_decode(baseline, joint_costs, positions, tasks)
    methods = {
        "baseline": _method_metrics(baseline, labeled, positives, task_goals, tasks),
        "v100_gate": _method_metrics(gated, labeled, positives, task_goals, tasks),
        "joint_blend": _method_metrics(joint, labeled, positives, task_goals, tasks),
    }
    changed = [unit for unit in range(len(positions)) if baseline.get(unit) != gated.get(unit)]
    labeled_changed = [unit for unit in labeled if baseline.get(unit) != gated.get(unit)]
    accepted = [value for value in annotations.values() if value["accepted"]]
    changed_scores = []
    priority_delta = 0
    distance_delta = 0
    emergency_displaced = 0
    for unit in changed:
        before = baseline.get(unit)
        after = gated.get(unit)
        if before is not None and after is not None:
            scores = scores_by_unit.get(unit, {})
            if before in scores and after in scores:
                changed_scores.append(scores[after] - scores[before])
            priority_delta += int(tasks[after].get("priority", 0)) - int(tasks[before].get("priority", 0))
            distance_delta += v89.base._manhattan(positions[unit], tasks[after]["pos"]) - v89.base._manhattan(
                positions[unit], tasks[before]["pos"]
            )
        if before is not None and int(tasks[before].get("priority", 0)) >= 15_000 and before != after:
            emergency_displaced += 1

    labels = rows[0]["labels"]
    farms = list(v89.base._get(obs, "farms", []) or [])
    player = int(v89.base._get(obs, "player", seat) or seat)
    opponent_farm = farms[1 - player] if len(farms) >= 2 else {}
    own_money = float(v89.base._get(farm, "money", 0) or 0)
    opponent_money = float(v89.base._get(opponent_farm, "money", 0) or 0)
    current_money_gap_ratio = (own_money - opponent_money) / max(1.0, own_money + opponent_money)
    current_productive_gap = float(
        v89.base._farm_summary(farm)["productive"]
        - v89.base._farm_summary(opponent_farm)["productive"]
    )
    joint_changed = [unit for unit in range(len(positions)) if baseline.get(unit) != joint.get(unit)]
    joint_labeled_changed = [unit for unit in labeled if baseline.get(unit) != joint.get(unit)]
    joint_score_gains: list[float] = []
    joint_priority_delta = 0
    joint_distance_delta = 0
    joint_emergency_displaced = 0
    joint_immediate_displaced = 0
    joint_same_operation = 0
    joint_after_operations: Counter[str] = Counter()
    for unit in joint_changed:
        before = baseline.get(unit)
        after = joint.get(unit)
        if before is not None and after is not None:
            scores = scores_by_unit.get(unit, {})
            if before in scores and after in scores:
                joint_score_gains.append(scores[after] - scores[before])
            joint_priority_delta += int(tasks[after].get("priority", 0)) - int(tasks[before].get("priority", 0))
            joint_distance_delta += v89.base._manhattan(
                positions[unit], tasks[after]["pos"]
            ) - v89.base._manhattan(positions[unit], tasks[before]["pos"])
            before_operation = task_goals[before].split(":", 1)[0]
            after_operation = task_goals[after].split(":", 1)[0]
            joint_same_operation += before_operation == after_operation
            joint_after_operations[after_operation] += 1
        if before is not None and int(tasks[before].get("priority", 0)) >= 15_000 and before != after:
            joint_emergency_displaced += 1
        if (
            before is not None
            and before != after
            and v89.base._manhattan(positions[unit], tasks[before]["pos"]) == 0
        ):
            joint_immediate_displaced += 1
    meta = {
        "changed_units": len(changed),
        "labeled_changed_units": len(labeled_changed),
        "accepted_workers": len(accepted),
        "minimum_accepted_gap": min((float(value["gap"]) for value in accepted), default=0.0),
        "mean_accepted_gap": mean((float(value["gap"]) for value in accepted)) if accepted else 0.0,
        "maximum_accepted_base_rank": max((int(value["base_rank"]) for value in accepted), default=0),
        "mean_changed_model_gain": mean(changed_scores) if changed_scores else 0.0,
        "priority_delta": priority_delta,
        "distance_delta": distance_delta,
        "emergency_displaced": emergency_displaced,
        "independent_duplicate_choices": len(independent_choices) - len(set(independent_choices)),
        "teacher_exact_delta": methods["v100_gate"]["worker_exact"] - methods["baseline"]["worker_exact"],
        "eligible_workers": len(scores_by_unit),
        "ood_workers": ood_workers,
        "joint_changed_units": len(joint_changed),
        "joint_labeled_changed_units": len(joint_labeled_changed),
        "joint_mean_model_gain": mean(joint_score_gains) if joint_score_gains else 0.0,
        "joint_minimum_model_gain": min(joint_score_gains, default=0.0),
        "joint_maximum_model_gain": max(joint_score_gains, default=0.0),
        "joint_priority_delta": joint_priority_delta,
        "joint_distance_delta": joint_distance_delta,
        "joint_emergency_displaced": joint_emergency_displaced,
        "joint_immediate_displaced": joint_immediate_displaced,
        "joint_same_operation_rate": joint_same_operation / max(1, len(joint_changed)),
        "joint_after_operations": dict(joint_after_operations),
        "joint_teacher_exact_delta": methods["joint_blend"]["worker_exact"] - methods["baseline"]["worker_exact"],
    }
    return "evaluated", {
        "source": rows[0]["source"],
        "episode_id": str(rows[0]["episode_id"]),
        "seat": seat,
        "split": rows[0]["split"],
        "step": step,
        "day": int(rows[0]["day"]),
        "hour": int(rows[0]["hour"]),
        "labeled_workers": len(labeled),
        "tasks": len(tasks),
        "hands": len(positions),
        "global_features": [float(value) for value in v92.v14.v3.encode_observation(obs)],
        "current_money_gap_ratio": current_money_gap_ratio,
        "current_productive_gap": current_productive_gap,
        "future24_money_gap_ratio": float(labels["future24_money_gap_ratio"]),
        "future72_money_gap_ratio": float(labels["future72_money_gap_ratio"]),
        "future24_productive_gap": float(labels["future24_productive_gap"]),
        "future72_productive_gap": float(labels["future72_productive_gap"]),
        "future72_money_bin": _money_bin(float(labels["future72_money_gap_ratio"])),
        "methods": methods,
        "meta": meta,
    }


def _finalize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"states": 0, "episodes": 0}
    episode_counts = Counter(row["episode_id"] for row in rows)
    weights = [1.0 / episode_counts[row["episode_id"]] for row in rows]
    denominator = sum(weights)
    result: dict[str, Any] = {
        "states": len(rows),
        "episodes": len(episode_counts),
        "mean_labeled_workers": round(sum(row["labeled_workers"] * w for row, w in zip(rows, weights, strict=True)) / denominator, 4),
        "methods": {},
        "v100_changed_state_rate": round(
            sum(float(row["meta"]["changed_units"] > 0) * w for row, w in zip(rows, weights, strict=True)) / denominator,
            5,
        ),
        "v100_better_rate": round(
            sum(float(row["meta"]["teacher_exact_delta"] > 0) * w for row, w in zip(rows, weights, strict=True)) / denominator,
            5,
        ),
        "v100_worse_rate": round(
            sum(float(row["meta"]["teacher_exact_delta"] < 0) * w for row, w in zip(rows, weights, strict=True)) / denominator,
            5,
        ),
        "joint_changed_state_rate": round(
            sum(float(row["meta"]["joint_changed_units"] > 0) * w for row, w in zip(rows, weights, strict=True)) / denominator,
            5,
        ),
        "joint_better_rate": round(
            sum(float(row["meta"]["joint_teacher_exact_delta"] > 0) * w for row, w in zip(rows, weights, strict=True)) / denominator,
            5,
        ),
        "joint_worse_rate": round(
            sum(float(row["meta"]["joint_teacher_exact_delta"] < 0) * w for row, w in zip(rows, weights, strict=True)) / denominator,
            5,
        ),
        "independent_conflict_state_rate": round(
            sum(float(row["meta"]["independent_duplicate_choices"] > 0) * w for row, w in zip(rows, weights, strict=True)) / denominator,
            5,
        ),
    }
    for method in ("baseline", "v100_gate", "joint_blend"):
        result["methods"][method] = {
            metric: round(
                sum(float(row["methods"][method][metric]) * w for row, w in zip(rows, weights, strict=True))
                / denominator,
                5,
            )
            for metric in ("worker_exact", "worker_goal", "worker_operation", "worker_endpoint", "all_exact")
        }
    return result


def main() -> None:
    global CANDIDATE_BONUS
    parser = argparse.ArgumentParser()
    parser.add_argument("--modulus", type=int, default=STATE_SAMPLE_MODULUS)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--splits", default=",".join(sorted(SPLITS)))
    parser.add_argument("--bonus", type=int, default=CANDIDATE_BONUS)
    args = parser.parse_args()
    if args.modulus <= 0:
        raise ValueError("modulus must be positive")
    if args.bonus < 0:
        raise ValueError("bonus must be nonnegative")
    CANDIDATE_BONUS = args.bonus
    selected_splits = {value.strip() for value in args.splits.split(",") if value.strip()}
    if not selected_splits or not selected_splits <= {"validation", "test"}:
        raise ValueError("splits must be validation, test, or validation,test")
    evaluated: list[dict[str, Any]] = []
    coverage: Counter[str] = Counter()
    seen: set[tuple[str, int, int]] = set()
    for source in v89.TEACHERS:
        manifests = {
            (str(row["episode_id"]), int(row["submission_seat"])): row
            for row in _manifest(v89.SOURCES[source])
        }
        print(f"[{source}] loading", flush=True)
        payload = json.loads((v89.SOURCE_DIR / f"{source}.json").read_text(encoding="utf-8"))
        grouped: defaultdict[tuple[str, int, int], list[dict[str, Any]]] = defaultdict(list)
        for row in payload["rows"]:
            if (
                not row["winner"]
                or str(row["split"]) not in selected_splits
                or not row["labels"]["completed"]
                or _state_sample_key(row) % args.modulus
            ):
                continue
            key = (str(row["episode_id"]), int(row["seat"]), int(row["step"]))
            grouped[key].append(row)
        del payload
        gc.collect()
        coverage[f"{source}:sampled_states"] += len(grouped)
        by_side: defaultdict[tuple[str, int], list[tuple[tuple[str, int, int], list[dict[str, Any]]]]] = defaultdict(list)
        for key, rows in grouped.items():
            by_side[(key[0], key[1])].append((key, rows))
        state_index = 0
        for side_key, states in by_side.items():
            manifest = manifests.get(side_key)
            if manifest is None:
                coverage[f"{source}:missing_manifest"] += len(states)
                continue
            replay: dict[str, Any] | None = None
            for key, rows in states:
                state_index += 1
                index = state_index
                if len(rows) < 2:
                    coverage[f"{source}:single_worker_states"] += 1
                    continue
                dedupe_key = (key[0], key[1], key[2])
                if dedupe_key in seen:
                    coverage[f"{source}:duplicate_states"] += 1
                    continue
                seen.add(dedupe_key)
                if replay is None:
                    replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
                if index == 1 or index % 100 == 0:
                    print(f"[{source} {index}/{len(grouped)}]", flush=True)
                status, made = _evaluate_state(rows, replay, key[1])
                coverage[f"{source}:{status}"] += 1
                if made is not None:
                    evaluated.append(made)
            if replay is not None:
                del replay
        gc.collect()

    buckets: dict[str, Any] = {}
    for split in ("validation", "test"):
        local = [row for row in evaluated if row["split"] == split]
        buckets[split] = _finalize(local)
        for source in v89.TEACHERS:
            buckets[f"{split}:{source}"] = _finalize([row for row in local if row["source"] == source])
        for money_bin in ("lt_-0.25", "-0.25_0", "0_0.25", "ge_0.25"):
            buckets[f"{split}:future72:{money_bin}"] = _finalize(
                [row for row in local if row["future72_money_bin"] == money_bin]
            )
    result = {
        "format": "kaggriculture-joint-assignment-holdout-v1",
        "state_sample_modulus": args.modulus,
        "splits": sorted(selected_splits),
        "configuration": {
            "minimum_score_gap": MIN_SCORE_GAP,
            "maximum_base_rank": MAX_BASE_RANK,
            "candidate_bonus": CANDIDATE_BONUS,
        },
        "coverage": dict(coverage),
        "buckets": buckets,
        "rows": evaluated,
        "limits": [
            "only states with at least two simultaneous completed route starts are scored",
            "every labeled exact endpoint must exist in the deterministic V14 task set and admit an injective matching",
            "future states are observational stratifiers, not counterfactual values of rejected assignments",
            "V14 task reconstruction does not reproduce every hidden mission-continuation global from the teacher policy",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({"coverage": dict(coverage), "buckets": buckets}, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
