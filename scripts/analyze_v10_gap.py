"""Diagnose V9 public trajectories against the Rank-1 teacher.

The report separates three possible causes of a trajectory gap:

* strategy: the expert atlas proposes a different future portfolio;
* execution: the proposed 24/72-hour anchor is not reached in closed loop;
* operations: field-action transitions spend work on routing or fail to chain
  animal service.

All aggregates are episode based.  Public V9 episodes are never mixed into the
teacher model, and old-agent match outcomes are not used by this analysis.
"""

from __future__ import annotations

import argparse
import csv
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

from agents.v9 import main as v9  # noqa: E402

DAYS = (1, 3, 5, 6, 7, 8, 9, 10, 11, 12, 15, 18, 20, 24, 27, 29)
ASSETS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "COW", "SHEEP")
TARGETS = (*ASSETS, "HANDS", "LAND", "PASTURES")
MOVES = {"NORTH", "SOUTH", "EAST", "WEST"}
PHASES = (
    ("opening", 0, 5),
    ("expansion", 6, 10),
    ("capital", 11, 19),
    ("rotation", 20, 26),
    ("liquidation", 27, 30),
)


def _percentile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _distribution(values: list[float]) -> dict[str, float]:
    return {
        "minimum": round(min(values, default=0.0), 4),
        "p10": round(_percentile(values, 0.10), 4),
        "p25": round(_percentile(values, 0.25), 4),
        "median": round(_percentile(values, 0.50), 4),
        "mean": round(mean(values), 4) if values else 0.0,
        "p75": round(_percentile(values, 0.75), 4),
        "p90": round(_percentile(values, 0.90), 4),
        "maximum": round(max(values, default=0.0), 4),
    }


def _manifest(path: Path) -> list[dict[str, str]]:
    with (path / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [
        row
        for row in rows
        if row.get("replay_status") in {"downloaded", "skipped_existing"}
        and row.get("submission_id") != row.get("opponent_submission_id")
        and row.get("team_name") != row.get("opponent_team_name")
    ]


def _replay_path(row: dict[str, str]) -> Path:
    path = ROOT / row["replay_path"]
    if not path.is_file():
        path = ROOT / "data" / row["replay_path"]
    return path


def _phase(day: int) -> str:
    for name, start, stop in PHASES:
        if start <= day < stop:
            return name
    return "unknown"


def _tile_counts(farm: dict[str, Any]) -> tuple[Counter[str], Counter[str], int]:
    crops: Counter[str] = Counter()
    animals: Counter[str] = Counter()
    pastures = 0
    for row in farm.get("tiles", []) or []:
        for tile in row:
            if not isinstance(tile, dict):
                continue
            if tile.get("kind") == "PLANT":
                crops[str(tile.get("crop"))] += 1
            if tile.get("animal"):
                animals[str(tile.get("animal"))] += 1
            if tile.get("kind") == "PASTURE":
                pastures += 1
    return crops, animals, pastures


def _snapshot(obs: dict[str, Any], seat: int) -> dict[str, float]:
    farm = (obs.get("farms") or [])[seat]
    crops, animals, pastures = _tile_counts(farm)
    unlocked = len(farm.get("unlocked_quadrants", []) or [])
    productive = sum(crops.values()) + sum(animals.values())
    values: dict[str, float] = {
        **{asset: float(animals[asset] if asset in {"COW", "SHEEP"} else crops[asset]) for asset in ASSETS},
        "HANDS": float(len(farm.get("hands", []) or [])),
        "LAND": float(unlocked),
        "PASTURES": float(pastures),
        "money": float(farm.get("money") or 0),
        "productive": float(productive),
        "utilization": productive / max(1, unlocked * 25),
    }
    return values


def _student_prediction(obs: dict[str, Any], seat: int) -> dict[str, Any] | None:
    farms = obs.get("farms") or []
    if seat >= len(farms):
        return None
    private = obs.get("private") or {}
    prediction = v9.v8._expert_prediction(obs, farms[seat], farms[1 - seat], private)
    if prediction is None:
        return None
    short, long, confidence, distance = prediction
    intent = v9._intent_prediction(obs, farms[seat], farms[1 - seat], private)
    return {
        "h24": short,
        "h72": long,
        "atlas_confidence": float(confidence),
        "atlas_distance": float(distance),
        "intent_confidence": float(intent["confidence"]) if intent else 0.0,
    }


def _fertilize_targets(replay: dict[str, Any], seat: int) -> dict[str, Counter[str]]:
    """Count crops under FERTILIZE using the observation that chose the action."""
    result: dict[str, Counter[str]] = defaultdict(Counter)
    steps = replay.get("steps", []) or []
    for step in range(len(steps) - 1):
        if seat >= len(steps[step]) or seat >= len(steps[step + 1]):
            continue
        obs = steps[step][seat].get("observation") or {}
        farms = obs.get("farms") or []
        if seat >= len(farms):
            continue
        farm = farms[seat]
        positions = [farm.get("farmer") or [0, 0], *(farm.get("hands") or [])]
        action = steps[step + 1][seat].get("action") or {}
        units = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
        phase = _phase(int(obs.get("day", 0) or 0))
        tiles = farm.get("tiles") or []
        for unit, unit_action in enumerate(units):
            if not unit_action or unit_action[0] != "FERTILIZE" or unit >= len(positions):
                continue
            x, y = positions[unit]
            tile = tiles[y][x] if 0 <= y < len(tiles) and 0 <= x < len(tiles[y]) else None
            crop = str(tile.get("crop", "UNKNOWN")) if isinstance(tile, dict) else "INVALID"
            result[phase][crop] += 1
    return result


def _episode(path: Path, row: dict[str, str], *, student: bool) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        replay = json.load(handle)
    seat = int(row["submission_seat"])
    snapshots: dict[int, dict[str, float]] = {}
    predictions: dict[int, dict[str, Any]] = {}
    actions: dict[str, Counter[str]] = defaultdict(Counter)
    transitions: dict[str, Counter[str]] = defaultdict(Counter)
    market_actions: dict[str, Counter[str]] = defaultdict(Counter)
    market_quantities: dict[str, Counter[str]] = defaultdict(Counter)
    previous: dict[int, str] = {}
    previous_day = -1
    for states in replay.get("steps", []) or []:
        if seat >= len(states):
            continue
        state = states[seat]
        obs = state.get("observation") or {}
        farms = obs.get("farms") or []
        if seat >= len(farms):
            continue
        day = int(obs.get("day", 0) or 0)
        hour = int(obs.get("hour", 0) or 0)
        if day not in snapshots:
            snapshots[day] = _snapshot(obs, seat)
        if student and 3 <= day <= 26 and hour == 0:
            prediction = _student_prediction(obs, seat)
            if prediction is not None:
                predictions[day] = prediction
        if day != previous_day:
            previous.clear()
            previous_day = day
        phase = _phase(day)
        action = state.get("action") or {}
        for order in action.get("market", []) or []:
            if not order:
                continue
            verb = str(order[0])
            market_actions[phase][verb] += 1
            if len(order) >= 3:
                market_quantities[phase][f"{verb}_{order[1]}"] += max(0, int(order[2] or 0))
        units = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
        for unit, unit_action in enumerate(units):
            raw = str(unit_action[0]) if unit_action else "PASS"
            op = "MOVE" if raw in MOVES else raw
            actions[phase][op] += 1
            if unit in previous:
                transitions[phase][f"{previous[unit]}->{op}"] += 1
            previous[unit] = op
    result = {
        "episode_id": str(row["episode_id"]),
        "result": row.get("result", "unknown"),
        "reward": float(row.get("own_reward") or 0),
        "margin": float(row.get("own_reward") or 0) - float(row.get("opponent_reward") or 0),
        "snapshots": snapshots,
        "predictions": predictions,
        "actions": {name: dict(counts) for name, counts in actions.items()},
        "transitions": {name: dict(counts) for name, counts in transitions.items()},
        "market_actions": {name: dict(counts) for name, counts in market_actions.items()},
        "market_quantities": {name: dict(counts) for name, counts in market_quantities.items()},
        "fertilize_targets": {
            name: dict(counts) for name, counts in _fertilize_targets(replay, seat).items()
        },
    }
    del replay
    gc.collect()
    return result


def _sum_nested(episodes: list[dict[str, Any]], section: str, phase: str) -> Counter[str]:
    result: Counter[str] = Counter()
    for episode in episodes:
        result.update(episode[section].get(phase, {}))
    return result


def _operational(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    selected_transitions = (
        "FEED->MOVE",
        "FEED->CARE",
        "CARE->MOVE",
        "CARE->COLLECT_FERTILIZER",
        "HARVEST->MOVE",
        "PLANT->WATER",
    )
    for phase, _start, _stop in PHASES:
        actions = _sum_nested(episodes, "actions", phase)
        transitions = _sum_nested(episodes, "transitions", phase)
        market_actions = _sum_nested(episodes, "market_actions", phase)
        market_quantities = _sum_nested(episodes, "market_quantities", phase)
        fertilize_targets = _sum_nested(episodes, "fertilize_targets", phase)
        total = sum(actions.values())
        non_pass = max(1, total - actions["PASS"])
        result[phase] = {
            "actions_per_episode": {
                key: round(value / max(1, len(episodes)), 4) for key, value in sorted(actions.items())
            },
            "movement_share_non_pass": round(actions["MOVE"] / non_pass, 6),
            "pass_share": round(actions["PASS"] / max(1, total), 6),
            "selected_transitions_per_episode": {
                key: round(transitions[key] / max(1, len(episodes)), 4) for key in selected_transitions
            },
            "market_actions_per_episode": {
                key: round(value / max(1, len(episodes)), 4)
                for key, value in sorted(market_actions.items())
            },
            "market_quantities_per_episode": {
                key: round(value / max(1, len(episodes)), 4)
                for key, value in sorted(market_quantities.items())
            },
            "fertilize_targets_per_episode": {
                key: round(value / max(1, len(episodes)), 4)
                for key, value in sorted(fertilize_targets.items())
            },
        }
    return result


def _trajectories(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for day in DAYS:
        rows = [episode["snapshots"][day] for episode in episodes if day in episode["snapshots"]]
        if not rows:
            continue
        result[str(day)] = {
            metric: _distribution([row[metric] for row in rows])
            for metric in ("money", "productive", "utilization", "LAND", *ASSETS)
        }
    return result


def _prediction_realization(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    samples: dict[str, dict[str, list[float]]] = {
        horizon: {target: [] for target in TARGETS} for horizon in ("h24", "h72")
    }
    signed: dict[str, dict[str, list[float]]] = {
        horizon: {target: [] for target in TARGETS} for horizon in ("h24", "h72")
    }
    confidences: list[float] = []
    intent_confidences: list[float] = []
    distances: list[float] = []
    by_day: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for episode in episodes:
        for day, prediction in episode["predictions"].items():
            confidences.append(prediction["atlas_confidence"])
            intent_confidences.append(prediction["intent_confidence"])
            distances.append(prediction["atlas_distance"])
            by_day[day]["atlas_confidence"].append(prediction["atlas_confidence"])
            by_day[day]["intent_confidence"].append(prediction["intent_confidence"])
            for horizon in ("h24", "h72"):
                for target in TARGETS:
                    by_day[day][f"{horizon}_{target}"].append(float(prediction[horizon][target]))
            for horizon, offset in (("h24", 1), ("h72", 3)):
                future = episode["snapshots"].get(day + offset)
                if future is None:
                    continue
                for target in TARGETS:
                    error = future[target] - float(prediction[horizon][target])
                    samples[horizon][target].append(abs(error))
                    signed[horizon][target].append(error)
    return {
        "states": len(confidences),
        "atlas_confidence": _distribution(confidences),
        "intent_confidence": _distribution(intent_confidences),
        "atlas_distance": _distribution(distances),
        "low_atlas_confidence_fraction": round(
            sum(value < 0.35 for value in confidences) / max(1, len(confidences)), 6
        ),
        "low_intent_confidence_fraction": round(
            sum(value < 0.35 for value in intent_confidences) / max(1, len(intent_confidences)), 6
        ),
        "closed_loop_future_mae": {
            horizon: {target: round(mean(values), 4) if values else None for target, values in targets.items()}
            for horizon, targets in samples.items()
        },
        "closed_loop_future_signed_error": {
            horizon: {target: round(mean(values), 4) if values else None for target, values in targets.items()}
            for horizon, targets in signed.items()
        },
        "confidence_by_day": {
            str(day): {name: _distribution(values) for name, values in metrics.items()}
            for day, metrics in sorted(by_day.items())
        },
    }


def _lower_tail(episodes: list[dict[str, Any]], teacher: dict[str, Any]) -> dict[str, Any]:
    threshold = float(teacher["experts"]["rank1"]["trajectory"]["12"]["productive_tiles"]["p10"])
    low = [
        episode
        for episode in episodes
        if episode["snapshots"].get(12, {}).get("productive", math.inf) < threshold
    ]
    return {
        "rank1_day12_productive_p10": threshold,
        "episodes_below_teacher_p10": len(low),
        "fraction": round(len(low) / max(1, len(episodes)), 6),
        "day12_productive": _distribution(
            [episode["snapshots"][12]["productive"] for episode in low if 12 in episode["snapshots"]]
        ),
        "day24_productive": _distribution(
            [episode["snapshots"][24]["productive"] for episode in low if 24 in episode["snapshots"]]
        ),
        "reward": _distribution([episode["reward"] for episode in low]),
        "margin": _distribution([episode["margin"] for episode in low]),
        "episode_ids": [episode["episode_id"] for episode in sorted(low, key=lambda item: item["margin"])],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--student",
        type=Path,
        default=Path("data/submissions/v9_submission_55732462"),
    )
    parser.add_argument(
        "--teacher",
        type=Path,
        default=Path("data/submissions/leaderboard_rank1_submission_55614463"),
    )
    parser.add_argument(
        "--teacher-analysis",
        type=Path,
        default=Path("data/analysis/v8_teacher_strategy_analysis.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v10_v9_teacher_gap.json"),
    )
    args = parser.parse_args()
    student_path = args.student if args.student.is_absolute() else ROOT / args.student
    teacher_path = args.teacher if args.teacher.is_absolute() else ROOT / args.teacher
    analysis_path = args.teacher_analysis if args.teacher_analysis.is_absolute() else ROOT / args.teacher_analysis
    teacher_analysis = json.loads(analysis_path.read_text(encoding="utf-8"))

    corpora: dict[str, list[dict[str, Any]]] = {}
    for label, path, student in (("v9", student_path, True), ("rank1", teacher_path, False)):
        rows = _manifest(path)
        episodes = []
        for index, row in enumerate(rows, 1):
            print(f"[{label}] {index}/{len(rows)} episode {row['episode_id']}", flush=True)
            episodes.append(_episode(_replay_path(row), row, student=student))
        corpora[label] = episodes

    result = {
        "objective": "V9 public closed-loop gap versus Rank-1 teacher; no old-agent win-rate selection",
        "episodes": {label: len(episodes) for label, episodes in corpora.items()},
        "trajectory": {label: _trajectories(episodes) for label, episodes in corpora.items()},
        "operations": {label: _operational(episodes) for label, episodes in corpora.items()},
        "v9_prediction_realization": _prediction_realization(corpora["v9"]),
        "v9_lower_tail": _lower_tail(corpora["v9"], teacher_analysis),
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"analysis: {output} ({output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
