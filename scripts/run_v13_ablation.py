"""Run paired V13 critic diagnostics in the official environment.

The starter outcome is regression context, not a selection target.  The runner
records lower-tail economy, maintenance failures, logistics, and critic routing.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kaggle_environments import make  # noqa: E402

from agents.v13 import main as v13  # noqa: E402

MOVEMENT = {"NORTH", "SOUTH", "EAST", "WEST"}


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


def _trace(replay: dict[str, Any], seat: int) -> dict[str, float]:
    operations: Counter[str] = Counter()
    expert_days: Counter[str] = Counter()
    pickup_wheat_actions = 0
    pickup_units = 0
    feed_follow: Counter[str] = Counter()
    previous: list[list[Any]] = []
    previous_animals: Counter[str] | None = None
    animal_losses = 0
    unwatered_samples: list[float] = []
    critic_active_days = 0
    for states in replay.get("steps") or []:
        state = states[seat]
        obs = state.get("observation") or {}
        farms = obs.get("farms") or []
        player = int(obs.get("player", seat))
        farm = farms[player] if 0 <= player < len(farms) else {}
        if int(obs.get("hour", 0) or 0) == 0:
            decision = v13.policy_diagnostics(obs).get("v13_relative_critic") or {}
            if decision.get("active"):
                critic_active_days += 1
                expert_days[str(decision["selected"]["expert"])] += 1
            plants = 0
            unwatered = 0
            animals: Counter[str] = Counter()
            for row in farm.get("tiles") or []:
                for tile in row:
                    if not isinstance(tile, dict):
                        continue
                    if tile.get("kind") == "PLANT":
                        plants += 1
                        unwatered += int(tile.get("consecutive_unwatered", 0) or 0) >= 1
                    animal = str(tile.get("animal") or "")
                    if animal:
                        animals[animal] += 1
            if plants:
                unwatered_samples.append(unwatered / plants)
            if previous_animals is not None:
                animal_losses += sum(max(0, previous_animals[item] - animals[item]) for item in previous_animals)
            previous_animals = animals
        action = state.get("action") or {}
        current = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
        for unit, unit_action in enumerate(current):
            op = str(unit_action[0]) if unit_action else "PASS"
            operations[op] += 1
            if op == "PICKUP" and len(unit_action) >= 2 and unit_action[1] == "WHEAT":
                pickup_wheat_actions += 1
                pickup_units += max(0, int(unit_action[2] if len(unit_action) > 2 else 1))
            if unit < len(previous) and previous[unit] and previous[unit][0] == "FEED":
                label = op if op in {"CARE", "COLLECT_FERTILIZER"} else ("MOVE" if op in MOVEMENT else op)
                feed_follow[label] += 1
        previous = [list(value) for value in current]
    return {
        "pickup_wheat_actions": float(pickup_wheat_actions),
        "pickup_wheat_units": float(pickup_units),
        "feed": float(operations["FEED"]),
        "care": float(operations["CARE"]),
        "water": float(operations["WATER"]),
        "harvest": float(operations["HARVEST"]),
        "pass": float(operations["PASS"]),
        "move": float(sum(operations[op] for op in MOVEMENT)),
        "feed_to_care": float(feed_follow["CARE"]),
        "feed_to_move": float(feed_follow["MOVE"]),
        "wheat_units_per_feed": pickup_units / max(1, operations["FEED"]),
        "previous_day_unwatered": mean(unwatered_samples) if unwatered_samples else 0.0,
        "observed_animal_losses": float(animal_losses),
        "critic_active_days": float(critic_active_days),
        "critic_rank1_days": float(expert_days["rank1"]),
        "critic_rank2_days": float(expert_days["rank2"]),
        "critic_rank3_days": float(expert_days["rank3"]),
        "critic_opponent_days": float(expert_days["opponent"]),
    }


def _run(seed: int, seat: int, opponent: str, replay_path: Path) -> dict[str, Any]:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=True)
    agents = [v13.agent, opponent] if seat == 0 else [opponent, v13.agent]
    env.run(agents)
    replay = env.toJSON()
    final = env.steps[-1]
    rewards = [float(state.reward or 0) for state in final]
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    replay_path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")
    return {
        "seed": seed,
        "seat": seat,
        "ours": rewards[seat],
        "theirs": rewards[1 - seat],
        "margin": rewards[seat] - rewards[1 - seat],
        "statuses": [state.status for state in final],
        "metrics": _trace(replay, seat),
        "replay": str(replay_path.relative_to(ROOT)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("critic", "safe-core"), required=True)
    parser.add_argument("--pairs", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20261501)
    parser.add_argument("--opponent", default="starter")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    v13.ENABLE_RELATIVE_CRITIC = args.mode == "critic"
    created_at = datetime.now().astimezone()
    run_id = created_at.strftime("%Y%m%d_%H%M%S_%z")
    replay_dir = ROOT / "data/replays" / f"{run_id}_v13_{args.mode}_ablation"
    games = [
        _run(
            args.seed + offset,
            seat,
            args.opponent,
            replay_dir / f"seed_{args.seed + offset}_seat_{seat}.json",
        )
        for offset in range(args.pairs)
        for seat in (0, 1)
    ]
    metric_names = tuple(games[0]["metrics"])
    summary = {
        "games": len(games),
        "all_done": all(game["statuses"] == ["DONE", "DONE"] for game in games),
        "reward": {
            "mean": mean(game["ours"] for game in games),
            "p10": _percentile([game["ours"] for game in games], 0.10),
            "minimum": min(game["ours"] for game in games),
        },
        "margin": {
            "mean": mean(game["margin"] for game in games),
            "p10": _percentile([game["margin"] for game in games], 0.10),
        },
        "diagnostics": {metric: mean(float(game["metrics"][metric]) for game in games) for metric in metric_names},
    }
    payload = {
        "created_at": created_at.isoformat(),
        "agent": "agents/v13/main.py",
        "mode": args.mode,
        "opponent": args.opponent,
        "configuration": {"pairs": args.pairs, "seed": args.seed, "episode_steps": 720},
        "summary": summary,
        "games": games,
    }
    output = args.output or ROOT / "data/runs" / f"v13_ablation_{args.mode}_{args.seed}.json"
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"result: {output}")
    print(f"replays: {replay_dir}")


if __name__ == "__main__":
    main()
