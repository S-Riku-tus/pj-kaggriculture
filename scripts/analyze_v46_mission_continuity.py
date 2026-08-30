"""Measure multi-turn worker mission continuity in V11 and Top-3 logs.

The one-step Hungarian executor is highly path-sensitive: V43/V45 improved
farm geometry but a single omitted PLANT action changed thousands of later
actions.  This analysis asks whether top workers commit to a destination more
reliably.  Each requested move is followed for up to six turns for the same
unit, stopping at PASS or the first non-movement operation.  We report actual
blocking, immediate reversal, completion horizons, route excess, and whether
the first move makes progress toward the eventual operation coordinate.
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

from scripts.analyze_v33_asset_labor import _actions, _farm, _positions  # noqa: E402
from scripts.analyze_v34_labor_value import SOURCES, _stats  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    _manifest,
    _observation,
    _replay_path,
    _split,
)

FORMAT = "kaggriculture-v46-mission-continuity-v1"
MOVES = {"NORTH", "SOUTH", "EAST", "WEST"}
OPPOSITE = {"NORTH": "SOUTH", "SOUTH": "NORTH", "EAST": "WEST", "WEST": "EAST"}
PHASES = {
    "expansion_5_8": range(5, 9),
    "branch_9_10": range(9, 11),
    "compound_11_14": range(11, 15),
}
LOOKAHEAD = 6


def _distance(left: tuple[int, int], right: tuple[int, int]) -> int:
    return abs(left[0] - right[0]) + abs(left[1] - right[1])


def _phase(day: int) -> str | None:
    return next((name for name, days in PHASES.items() if day in days), None)


def _new_counts() -> Counter[str]:
    return Counter(
        {
            "moves": 0,
            "blocked": 0,
            "immediate_reverse": 0,
            "completed_1": 0,
            "completed_3": 0,
            "completed_6": 0,
            "progress": 0,
            "neutral": 0,
            "regress": 0,
            "route_reverse": 0,
            "route_turn": 0,
            "completed_distance": 0,
            "completed_moves": 0,
            "completed_route_excess": 0,
            "immediate_reverse_completed": 0,
            "regress_completed": 0,
        }
    )


def _side(
    replay: dict[str, Any], manifest: dict[str, str], source: str
) -> list[dict[str, Any]]:
    seat = int(manifest["submission_seat"])
    episode_id = str(manifest["episode_id"])
    phase_counts = {name: _new_counts() for name in PHASES}
    phase_operations = {name: Counter() for name in PHASES}
    phase_reverse_operations = {name: Counter() for name in PHASES}
    phase_regress_operations = {name: Counter() for name in PHASES}
    steps = replay.get("steps") or []
    last_day = max((day for days in PHASES.values() for day in days), default=14)
    for step in range(min(len(steps) - 1, (last_day + 1) * 24)):
        obs = _observation(replay, step, seat)
        next_obs = _observation(replay, step + 1, seat)
        if obs is None or next_obs is None:
            continue
        day = int(obs.get("day", -1) or -1)
        phase = _phase(day)
        if phase is None:
            continue
        positions = _positions(_farm(obs, seat))
        next_positions = _positions(_farm(next_obs, seat))
        actions = _actions(replay, step, seat)
        counts = phase_counts[phase]
        operations = phase_operations[phase]
        for unit, action in enumerate(actions):
            if unit >= len(positions):
                continue
            op = str(action[0]) if action else "PASS"
            if op not in MOVES:
                continue
            counts["moves"] += 1
            start = positions[unit]
            after = next_positions[unit] if unit < len(next_positions) else start
            counts["blocked"] += after == start
            route = [op]
            immediate_reverse = False
            endpoint: tuple[int, int] | None = None
            completion = 0
            terminal_op = ""
            for horizon in range(1, LOOKAHEAD + 1):
                future_obs = _observation(replay, step + horizon, seat)
                if future_obs is None or int(future_obs.get("day", -1) or -1) != day:
                    break
                future_positions = _positions(_farm(future_obs, seat))
                future_actions = _actions(replay, step + horizon, seat)
                if unit >= len(future_positions) or unit >= len(future_actions):
                    break
                future_action = future_actions[unit]
                future_op = str(future_action[0]) if future_action else "PASS"
                if horizon == 1:
                    immediate_reverse = future_op == OPPOSITE[op]
                    counts["immediate_reverse"] += immediate_reverse
                if future_op in MOVES:
                    route.append(future_op)
                    continue
                if future_op != "PASS":
                    endpoint = future_positions[unit]
                    completion = horizon
                    terminal_op = future_op
                break
            if endpoint is None:
                continue
            counts["completed_6"] += 1
            counts["completed_3"] += completion <= 3
            counts["completed_1"] += completion <= 1
            operations[terminal_op] += 1
            if immediate_reverse:
                counts["immediate_reverse_completed"] += 1
                phase_reverse_operations[phase][terminal_op] += 1
            before_distance = _distance(start, endpoint)
            after_distance = _distance(after, endpoint)
            counts["progress"] += after_distance < before_distance
            counts["neutral"] += after_distance == before_distance
            regressed = after_distance > before_distance
            counts["regress"] += regressed
            if regressed:
                counts["regress_completed"] += 1
                phase_regress_operations[phase][terminal_op] += 1
            counts["route_reverse"] += any(
                right == OPPOSITE[left]
                for left, right in zip(route, route[1:], strict=False)
            )
            counts["route_turn"] += any(
                left != right for left, right in zip(route, route[1:], strict=False)
            )
            counts["completed_distance"] += before_distance
            counts["completed_moves"] += len(route)
            counts["completed_route_excess"] += max(0, len(route) - before_distance)
    return [
        {
            "source": source,
            "episode_id": episode_id,
            "split": _split(episode_id),
            "result": str(manifest.get("result") or "unknown").lower(),
            "phase": phase,
            "counts": dict(phase_counts[phase]),
            "terminal_operations": dict(phase_operations[phase]),
            "immediate_reverse_terminal_operations": dict(
                phase_reverse_operations[phase]
            ),
            "regress_terminal_operations": dict(phase_regress_operations[phase]),
        }
        for phase in PHASES
    ]


def _rates(row: dict[str, Any]) -> dict[str, float]:
    counts = row["counts"]
    moves = max(1, int(counts["moves"]))
    completed = max(1, int(counts["completed_6"]))
    return {
        "moves": float(counts["moves"]),
        "blocked_rate": counts["blocked"] / moves,
        "immediate_reverse_rate": counts["immediate_reverse"] / moves,
        "completion_1_rate": counts["completed_1"] / moves,
        "completion_3_rate": counts["completed_3"] / moves,
        "completion_6_rate": counts["completed_6"] / moves,
        "progress_rate": counts["progress"] / completed,
        "neutral_rate": counts["neutral"] / completed,
        "regress_rate": counts["regress"] / completed,
        "route_reverse_rate": counts["route_reverse"] / completed,
        "route_turn_rate": counts["route_turn"] / completed,
        "mean_completed_distance": counts["completed_distance"] / completed,
        "mean_completed_moves": counts["completed_moves"] / completed,
        "mean_route_excess": counts["completed_route_excess"] / completed,
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rates = [_rates(row) for row in rows]
    operations = sum((Counter(row["terminal_operations"]) for row in rows), Counter())
    reverse_operations = sum(
        (Counter(row["immediate_reverse_terminal_operations"]) for row in rows),
        Counter(),
    )
    regress_operations = sum(
        (Counter(row["regress_terminal_operations"]) for row in rows), Counter()
    )
    completed = sum(int(row["counts"]["completed_6"]) for row in rows)
    reverse_completed = sum(
        int(row["counts"]["immediate_reverse_completed"]) for row in rows
    )
    regress_completed = sum(int(row["counts"]["regress_completed"]) for row in rows)
    return {
        "episodes": len(rows),
        **(
            {
                metric: _stats([row[metric] for row in rates])
                for metric in rates[0]
            }
            if rates
            else {}
        ),
        "terminal_operation_share": {
            operation: count / max(1, completed)
            for operation, count in operations.items()
        },
        "immediate_reverse_terminal_operation_share": {
            operation: count / max(1, reverse_completed)
            for operation, count in reverse_operations.items()
        },
        "regress_terminal_operation_share": {
            operation: count / max(1, regress_completed)
            for operation, count in regress_operations.items()
        },
    }


def _source_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        phase: {
            "all": _summary([row for row in rows if row["phase"] == phase]),
            "win": _summary(
                [
                    row
                    for row in rows
                    if row["phase"] == phase and row["result"] == "win"
                ]
            ),
            "loss": _summary(
                [
                    row
                    for row in rows
                    if row["phase"] == phase and row["result"] == "loss"
                ]
            ),
        }
        for phase in PHASES
    }


def main() -> None:
    global PHASES
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v46_mission_continuity.json"),
    )
    parser.add_argument(
        "--days",
        help="optional comma-separated days, reported as one custom phase",
    )
    args = parser.parse_args()
    if args.days:
        days = tuple(
            sorted({int(value) for value in args.days.split(",") if value.strip()})
        )
        if not days or any(day < 0 or day > 29 for day in days):
            parser.error("--days must contain game days in [0, 29]")
        PHASES = {f"custom_{days[0]}_{days[-1]}": days}
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
            rows.extend(_side(replay, manifest, source))
    payload = {
        "format": FORMAT,
        "runtime_policy_enabled": False,
        "objective": "compare six-turn worker mission continuity without action-match optimization",
        "data": {
            "episode_phase_rows": len(rows),
            "episodes": len({row["episode_id"] for row in rows}),
            "episode_disjoint_split": True,
            "lookahead": LOOKAHEAD,
        },
        "source_phase": {
            source: _source_report([row for row in rows if row["source"] == source])
            for source in SOURCES
        },
        "v11_by_split": {
            split: {
                phase: _summary(
                    [
                        row
                        for row in rows
                        if row["source"] == "v11"
                        and row["split"] == split
                        and row["phase"] == phase
                    ]
                )
                for phase in PHASES
            }
            for split in ("train", "validation", "test")
        },
        "interpretation_limits": [
            "requested movement is followed by unit index within one day; "
            "the game keeps hired-hand indices stable during a day",
            "completion means the next non-move action occurs within six turns without an intervening PASS",
            "route excess includes collision blocking and intentional detours, "
            "so it is diagnostic rather than causal waste",
            "teacher wins and losses remain separate and no runtime policy is enabled",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["data"], ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
