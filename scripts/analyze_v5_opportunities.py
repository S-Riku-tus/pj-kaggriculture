"""Measure the strategic and mission-level gaps targeted by Kaggriculture V5.

The general replay analyzer focuses on economic outcomes.  This companion
analysis adds exact daily portfolios, adjacent worker-action transitions,
land-fill latency, late planting, final seed waste, and the difference between
V3's learned targets and V4's feasibility projection.
"""

from __future__ import annotations

import argparse
import csv
import gc
import json
import math
import sys
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v4 import main as v4  # noqa: E402

MOVES = {"NORTH", "SOUTH", "EAST", "WEST"}
CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
ANIMALS = ("GOOSE", "COW", "SHEEP")
TARGET_DAYS = (5, 7, 10, 12, 15, 20, 24, 27)
TRANSITIONS = (
    "FEED->CARE",
    "CARE->COLLECT_FERTILIZER",
    "HARVEST->FEED",
    "FEED->MOVE",
    "CARE->MOVE",
)


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _inventory_count(inventory: dict[str, Any], item: str) -> int:
    return max(0, _as_int(inventory.get(item, 0)))


def _farm_state(obs: dict[str, Any], seat: int) -> dict[str, Any]:
    farms = obs.get("farms") or []
    farm = farms[seat] if seat < len(farms) else {}
    private = obs.get("private") or {}
    crops: Counter[str] = Counter()
    animals: Counter[str] = Counter()
    pastures = 0
    weeds = 0
    for row in farm.get("tiles") or []:
        for tile in row:
            if not isinstance(tile, dict):
                continue
            if tile.get("kind") == "PLANT" and tile.get("crop") in CROPS:
                crops[str(tile["crop"])] += 1
            if tile.get("kind") == "PASTURE":
                pastures += 1
            if tile.get("kind") == "WEED":
                weeds += 1
            if tile.get("animal") in ANIMALS:
                animals[str(tile["animal"])] += 1
    unlocked = len(farm.get("unlocked_quadrants") or [])
    productive = sum(crops.values()) + sum(animals.values())
    seeds = private.get("seeds") or {}
    return {
        "money": float(farm.get("money") or 0),
        "unlocked": unlocked,
        "utilization": productive / max(25, unlocked * 25),
        "productive": productive,
        "pastures": pastures,
        "weeds": weeds,
        "crops": {crop: crops[crop] for crop in CROPS},
        "animals": {animal: animals[animal] for animal in ANIMALS},
        "seeds": {crop: _inventory_count(seeds, crop) for crop in CROPS},
        "seed_units": sum(_inventory_count(seeds, crop) for crop in CROPS),
    }


def _target_state(obs: dict[str, Any], seat: int) -> dict[str, Any]:
    farms = obs.get("farms") or []
    if len(farms) < 2:
        return {}
    farm = farms[seat]
    opponent = farms[1 - seat]
    private = obs.get("private") or {}
    raw_animals, raw_crops, raw_hands, raw_land, _raw_weights = v4.v3._strategy_targets(
        obs, farm, opponent, private
    )
    animals, crops, hands, land, _weights, pastures = v4._strategy_targets(
        obs, farm, opponent, private
    )
    return {
        "raw": {
            "animals": raw_animals,
            "crops": raw_crops,
            "hands": raw_hands,
            "land": raw_land,
        },
        "v4": {
            "animals": animals,
            "crops": crops,
            "hands": hands,
            "land": land,
            "pastures": pastures,
        },
    }


def _load_manifest(directory: Path) -> list[dict[str, str]]:
    with (directory / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        return [
            row
            for row in csv.DictReader(handle)
            if row.get("replay_status") in {"downloaded", "skipped_existing"}
        ]


def _replay_path(row: dict[str, str]) -> Path:
    relative = Path(row["replay_path"])
    for candidate in (ROOT / relative, ROOT / "data" / relative):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(relative)


def _is_self_play(row: dict[str, str]) -> bool:
    submission = row.get("submission_id", "")
    opponent = row.get("opponent_submission_id", "")
    same_submission = bool(submission and opponent and submission == opponent)
    own_team = row.get("team_name", "")
    opponent_team = row.get("opponent_team_name", "")
    return same_submission or bool(own_team and own_team == opponent_team)


def _fill_latencies(states: list[dict[str, Any]]) -> dict[str, int | None]:
    result: dict[str, int | None] = {}
    previous_unlocked = states[0]["unlocked"] if states else 0
    for index, state in enumerate(states):
        unlocked = state["unlocked"]
        if unlocked <= previous_unlocked:
            continue
        latency = next(
            (
                later["turn"] - state["turn"]
                for later in states[index:]
                if later["unlocked"] == unlocked and later["utilization"] >= 0.80
            ),
            None,
        )
        result[str(unlocked)] = latency
        previous_unlocked = unlocked
    return result


def analyze_episode(row: dict[str, str], *, include_targets: bool) -> dict[str, Any]:
    path = _replay_path(row)
    replay = json.loads(path.read_text(encoding="utf-8"))
    seat = _as_int(row.get("submission_seat"))
    actions: Counter[str] = Counter()
    plant_crops: Counter[str] = Counter()
    plant_hours: Counter[int] = Counter()
    transitions: Counter[str] = Counter()
    previous_actions: dict[int, str] = {}
    previous_action_day = -1
    previous_observation: dict[str, Any] | None = None
    previous_snapshot_day = -1
    daily: dict[str, dict[str, Any]] = {}
    targets: dict[str, dict[str, Any]] = {}
    turn_states: list[dict[str, Any]] = []
    final_state: dict[str, Any] = {}
    hand_actions = 0
    hand_moves = 0

    for turn, states in enumerate(replay.get("steps") or []):
        if seat >= len(states):
            continue
        state = states[seat]
        obs = state.get("observation") or {}
        farms = obs.get("farms") or []
        if seat >= len(farms):
            continue
        day = _as_int(obs.get("day"))
        snapshot = _farm_state(obs, seat)
        snapshot["turn"] = turn
        turn_states.append(snapshot)
        if day != previous_snapshot_day:
            previous_snapshot_day = day
            if day in TARGET_DAYS:
                daily[str(day)] = snapshot
                if include_targets:
                    targets[str(day)] = _target_state(obs, seat)

        # Replay state t stores the action selected from observation t-1.  The
        # initial state has only a placeholder PASS and must not be counted.
        if previous_observation is None:
            previous_observation = obs
            final_state = snapshot
            continue
        action_day = _as_int(previous_observation.get("day"))
        action_hour = _as_int(previous_observation.get("hour"))
        if action_day != previous_action_day:
            previous_action_day = action_day
            previous_actions = {}
        action = state.get("action") or {}
        unit_actions = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
        next_previous: dict[int, str] = {}
        for unit_index, unit_action in enumerate(unit_actions):
            op = str(unit_action[0]) if unit_action else "PASS"
            actions[op] += 1
            if unit_index > 0:
                hand_actions += 1
                hand_moves += op in MOVES
            previous = previous_actions.get(unit_index)
            if previous is not None:
                transition = f"{previous}->{op if op not in MOVES else 'MOVE'}"
                transitions[transition] += 1
            next_previous[unit_index] = op
            if op == "PLANT":
                crop = str(unit_action[1]) if len(unit_action) > 1 else "UNKNOWN"
                plant_crops[crop] += 1
                plant_hours[action_hour] += 1
        previous_actions = next_previous
        previous_observation = obs
        final_state = snapshot

    result = {
        "episode_id": row.get("episode_id", path.stem.removeprefix("episode_")),
        "result": row.get("result", "unknown"),
        "is_self_play": _is_self_play(row),
        "reward": float(row.get("own_reward") or 0),
        "margin": float(row.get("own_reward") or 0) - float(row.get("opponent_reward") or 0),
        "actions": dict(actions),
        "plant_crops": dict(plant_crops),
        "plant_hours": {str(hour): count for hour, count in plant_hours.items()},
        "transitions": dict(transitions),
        "hand_movement_rate": hand_moves / hand_actions if hand_actions else 0.0,
        "daily": daily,
        "targets": targets,
        "fill_latency": _fill_latencies(turn_states),
        "final_seed_units": final_state.get("seed_units", 0),
    }
    del replay
    gc.collect()
    return result


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = probability * (len(ordered) - 1)
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    fraction = index - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    x_mean = mean(xs)
    y_mean = mean(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True))
    x_ss = sum((x - x_mean) ** 2 for x in xs)
    y_ss = sum((y - y_mean) ** 2 for y in ys)
    if not x_ss or not y_ss:
        return None
    return numerator / math.sqrt(x_ss * y_ss)


def _mean_metric(rows: list[dict[str, Any]], key: str) -> float:
    return mean(float(row.get(key) or 0) for row in rows) if rows else 0.0


def summarize(label: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    public = [row for row in rows if not row["is_self_play"]]
    rewards = [row["reward"] for row in public]
    result: dict[str, Any] = {
        "label": label,
        "episodes_discovered": len(rows),
        "episodes_public": len(public),
        "wins": sum(row["result"] == "win" for row in public),
        "coins": {
            "mean": mean(rewards) if rewards else 0.0,
            "p10": _percentile(rewards, 0.10),
            "minimum": min(rewards, default=0.0),
        },
        "hand_movement_rate": _mean_metric(public, "hand_movement_rate"),
        "final_seed_units": _mean_metric(public, "final_seed_units"),
        "actions": {},
        "transitions": {},
        "transition_rates": {},
        "plant_hours": {},
        "daily": {},
        "day20_animal_profiles": {},
        "fill_latency": {},
        "demand_correlations": {},
        "targets": {},
    }
    action_names = sorted({key for row in public for key in row["actions"]})
    for action in action_names:
        result["actions"][action] = mean(row["actions"].get(action, 0) for row in public)
    transition_names = sorted({key for row in public for key in row["transitions"]})
    for transition in transition_names:
        result["transitions"][transition] = mean(row["transitions"].get(transition, 0) for row in public)
    for transition in TRANSITIONS:
        first = transition.split("->", 1)[0]
        denominator = result["actions"].get(first, 0.0)
        result["transition_rates"][transition] = (
            result["transitions"].get(transition, 0.0) / denominator if denominator else 0.0
        )
    for hour in range(24):
        count = mean(row["plant_hours"].get(str(hour), 0) for row in public) if public else 0.0
        if count:
            result["plant_hours"][str(hour)] = count
    for day in TARGET_DAYS:
        snapshots = [row["daily"].get(str(day)) for row in public]
        snapshots = [snapshot for snapshot in snapshots if snapshot]
        if not snapshots:
            continue
        result["daily"][str(day)] = {
            "utilization": mean(snapshot["utilization"] for snapshot in snapshots),
            "wheat": mean(snapshot["crops"]["WHEAT"] for snapshot in snapshots),
            "strawberry": mean(snapshot["crops"]["STRAWBERRY"] for snapshot in snapshots),
            "melon": mean(snapshot["crops"]["MELON"] for snapshot in snapshots),
            "cow": mean(snapshot["animals"]["COW"] for snapshot in snapshots),
            "sheep": mean(snapshot["animals"]["SHEEP"] for snapshot in snapshots),
        }
    profiles = Counter()
    for row in public:
        snapshot = row["daily"].get("20")
        if snapshot:
            profiles[f'{snapshot["animals"]["COW"]}C+{snapshot["animals"]["SHEEP"]}S'] += 1
    result["day20_animal_profiles"] = dict(profiles.most_common())
    for unlocked in (2, 3):
        values = [row["fill_latency"].get(str(unlocked)) for row in public]
        reached = [value for value in values if value is not None]
        result["fill_latency"][str(unlocked)] = {
            "mean_turns": mean(reached) if reached else None,
            "reached_80_percent": len(reached),
            "events": len(values),
        }

    demand_values = {"MILK": [], "WOOL": [], "STRAWBERRY": []}
    capacity_values = {"MILK": [], "WOOL": [], "STRAWBERRY": []}
    for row in public:
        snapshot = row["daily"].get("20")
        target = row["targets"].get("20")
        if not snapshot or not target:
            continue
        # Demand is already embedded in the target observation; recover it by
        # comparing the source replay's target features through V4's helper is
        # intentionally avoided here. Exact corpus correlations remain in the
        # general analyzer; this section measures target projection instead.
        for item, key in (("MILK", "COW"), ("WOOL", "SHEEP")):
            demand_values[item].append(float(target["raw"]["animals"][key]))
            capacity_values[item].append(float(target["v4"]["animals"][key]))
        demand_values["STRAWBERRY"].append(float(target["raw"]["crops"]["STRAWBERRY"]))
        capacity_values["STRAWBERRY"].append(float(target["v4"]["crops"]["STRAWBERRY"]))
    result["demand_correlations"] = {
        "raw_to_projected_cow": _pearson(demand_values["MILK"], capacity_values["MILK"]),
        "raw_to_projected_sheep": _pearson(demand_values["WOOL"], capacity_values["WOOL"]),
        "raw_to_projected_strawberry": _pearson(
            demand_values["STRAWBERRY"], capacity_values["STRAWBERRY"]
        ),
    }
    for day in TARGET_DAYS:
        samples = [row["targets"].get(str(day)) for row in public]
        samples = [sample for sample in samples if sample]
        if not samples:
            continue
        result["targets"][str(day)] = {
            "raw_cow": mean(sample["raw"]["animals"]["COW"] for sample in samples),
            "raw_sheep": mean(sample["raw"]["animals"]["SHEEP"] for sample in samples),
            "v4_cow": mean(sample["v4"]["animals"]["COW"] for sample in samples),
            "v4_sheep": mean(sample["v4"]["animals"]["SHEEP"] for sample in samples),
            "raw_strawberry": mean(sample["raw"]["crops"]["STRAWBERRY"] for sample in samples),
            "v4_strawberry": mean(sample["v4"]["crops"]["STRAWBERRY"] for sample in samples),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", action="append", required=True, metavar="LABEL=SUBMISSION_DIR")
    parser.add_argument("--output", type=Path, default=Path("data/analysis/v5_opportunities.json"))
    parser.add_argument("--details", type=Path, default=Path("data/analysis/v5_opportunity_episodes.json"))
    args = parser.parse_args()
    summaries = []
    all_details: dict[str, list[dict[str, Any]]] = {}
    for corpus in args.corpus:
        if "=" not in corpus:
            raise ValueError(f"invalid corpus {corpus!r}")
        label, directory = corpus.split("=", 1)
        submission_dir = Path(directory)
        submission_dir = submission_dir if submission_dir.is_absolute() else ROOT / submission_dir
        rows = _load_manifest(submission_dir)
        details = []
        for index, row in enumerate(rows, 1):
            print(f"[{label}] {index}/{len(rows)} episode {row['episode_id']}", flush=True)
            details.append(analyze_episode(row, include_targets=label == "v4"))
        all_details[label] = details
        summaries.append(summarize(label, details))

    output = args.output if args.output.is_absolute() else ROOT / args.output
    details_path = args.details if args.details.is_absolute() else ROOT / args.details
    output.parent.mkdir(parents=True, exist_ok=True)
    details_path.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"corpora": summaries}, ensure_ascii=False, indent=2), encoding="utf-8")
    details_path.write_text(json.dumps(all_details, ensure_ascii=False), encoding="utf-8")
    print(f"summary: {output}")
    print(f"details: {details_path}")


if __name__ == "__main__":
    main()
