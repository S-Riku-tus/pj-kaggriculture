"""Explain why V104's frozen replay forks remained action-equivalent."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v104 import main as v104  # noqa: E402

RUN = ROOT / "data/runs/v104_recent_replay_forks.json"
OUTPUT = ROOT / "data/analysis/v104_latch_exit.json"


def _task_counter(tasks: list[dict[str, Any]]) -> Counter[tuple[Any, ...]]:
    return Counter(
        (
            str(task.get("label", "")),
            tuple(task.get("action") or ()),
            tuple(task.get("pos") or ()),
            int(task.get("priority", 0)),
        )
        for task in tasks
    )


def _tasks(obs: dict[str, Any], targets: tuple[Any, ...]) -> list[dict[str, Any]]:
    safe = v104.base._safe_observation(obs)
    if safe is None:
        return []
    farm, opponent_farm, private = safe
    positions = [tuple(v104.base._get(farm, "farmer", [0, 0]))]
    positions.extend(tuple(position) for position in (v104.base._get(farm, "hands", []) or []))
    raw = list(v104.base._get(private, "inventories", []) or [])
    inventories = [raw[index] if index < len(raw) else {} for index in range(len(positions))]
    tasks, _reserved = v104.v11._field_tasks(
        obs,
        farm,
        private,
        positions,
        inventories,
        v104.base._farm_summary(farm),
        targets[0],
        targets[1],
        targets[5],
        opponent_farm,
    )
    return tasks


def main() -> None:
    run = json.loads(RUN.read_text(encoding="utf-8"))
    records = []
    for game in run["games"]:
        if game["mode"] != "candidate":
            continue
        replay = json.loads((ROOT / game["replay"]).read_text(encoding="utf-8"))
        seat = int(game["seat"])
        fork_step = int(game["fork_day"]) * 24
        obs = replay["steps"][fork_step][seat].get("observation") or {}
        safe = v104.base._safe_observation(obs)
        if safe is None:
            continue
        farm, opponent_farm, private = safe
        decision = v104.v102._gate_decision(obs, farm, opponent_farm, private)
        baseline = decision["baseline"]
        candidate = (
            decision.get("candidate_animals", baseline[0]),
            decision.get("candidate_crops", baseline[1]),
            *baseline[2:],
        )
        safe_tasks = _task_counter(_tasks(obs, baseline))
        candidate_tasks = _task_counter(_tasks(obs, candidate))
        reason_timeline = []
        for step in range(fork_step, min(fork_step + 10, len(replay["steps"]))):
            current = replay["steps"][step][seat].get("observation") or {}
            current_safe = v104.base._safe_observation(current)
            if current_safe is None:
                continue
            current_farm, current_opponent, _current_private = current_safe
            prediction = v104.v14._winner_prediction(current, current_farm, current_opponent)
            reason_timeline.append(
                {
                    "step": step,
                    "day": int(current.get("day", 0) or 0),
                    "hour": int(current.get("hour", 0) or 0),
                    "active": bool(prediction.get("active")),
                    "reason": str(prediction.get("reason", "")),
                    "money_gap_ratio": prediction.get("money_gap_ratio"),
                    "confidence": prediction.get("confidence"),
                    "uncertainty": prediction.get("uncertainty"),
                }
            )
        records.append(
            {
                "source": game["source"],
                "episode_id": game["episode_id"],
                "seat": seat,
                "fork_day": game["fork_day"],
                "baseline_crops": baseline[1],
                "candidate_crops": candidate[1],
                "crop_delta": {
                    crop: int(candidate[1][crop]) - int(baseline[1][crop])
                    for crop in v104.v14.CROPS
                },
                "safe_task_count": sum(safe_tasks.values()),
                "candidate_task_count": sum(candidate_tasks.values()),
                "added_tasks": [list(value) + [count] for value, count in (candidate_tasks - safe_tasks).items()],
                "removed_tasks": [list(value) + [count] for value, count in (safe_tasks - candidate_tasks).items()],
                "reason_timeline": reason_timeline,
            }
        )
    reason_counts = Counter(
        timeline["reason"]
        for record in records
        for timeline in record["reason_timeline"][1:]
        if not timeline["active"]
    )
    result = {
        "format": "kaggriculture-v104-latch-exit-v1",
        "input": str(RUN.relative_to(ROOT)),
        "episodes": len(records),
        "episodes_with_task_set_change_at_entry": sum(
            bool(record["added_tasks"] or record["removed_tasks"]) for record in records
        ),
        "post_entry_inactive_reason_counts": dict(reason_counts),
        "records": records,
        "interpretation_limit": "task-set equality does not prove assignment or market-plan equality",
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "episodes": result["episodes"],
                "episodes_with_task_set_change_at_entry": result[
                    "episodes_with_task_set_change_at_entry"
                ],
                "post_entry_inactive_reason_counts": result[
                    "post_entry_inactive_reason_counts"
                ],
                "crop_deltas": [record["crop_delta"] for record in records],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"result: {OUTPUT}")


if __name__ == "__main__":
    main()
