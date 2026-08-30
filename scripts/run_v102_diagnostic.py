"""Run paired V102/V11 trajectory diagnostics against an independent V14.

The opponent match is a state-coverage and safety instrument.  Win rate is
never a promotion objective.  Candidate and safe core use identical
seed/seat/opponent tuples, and intermediate runtime failures remain failures
even when Kaggle later writes final DONE states.
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

from agents.v14 import main as opponent_v14  # noqa: E402
from agents.v102 import main as v102  # noqa: E402

CHECKPOINTS = {8, 10, 12, 15, 20, 24, 29}
ANIMALS = ("COW", "SHEEP", "GOOSE")
CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")


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


def _reset(module: Any) -> None:
    module.v9._MISSION_LAST_STEP = -1
    module.v9._MISSION_PREVIOUS_ACTIONS = []


def _snapshot(obs: dict[str, Any], seat: int) -> dict[str, Any]:
    farm = obs["farms"][seat]
    crops: Counter[str] = Counter()
    animals: Counter[str] = Counter()
    unwatered = 0
    unfed = 0
    weeds = 0
    for row in farm.get("tiles") or []:
        for tile in row:
            if not isinstance(tile, dict):
                continue
            if tile.get("kind") == "PLANT":
                crops[str(tile.get("crop"))] += 1
                unwatered += int(tile.get("consecutive_unwatered", 0) or 0) > 0
            animal = str(tile.get("animal") or "")
            if animal:
                animals[animal] += 1
                unfed += int(tile.get("consecutive_unfed", 0) or 0) > 0
            weeds += tile.get("kind") == "WEED"
    productive = sum(crops.values()) + sum(animals.values())
    unlocked = len(farm.get("unlocked_quadrants") or [])
    return {
        "money": float(farm.get("money", 0) or 0),
        "crops": {crop: int(crops[crop]) for crop in CROPS},
        "animals": {animal: int(animals[animal]) for animal in ANIMALS},
        "productive": productive,
        "utilization": productive / max(25, unlocked * 25),
        "unwatered": unwatered,
        "unfed": unfed,
        "weeds": weeds,
    }


def _trace(replay: dict[str, Any], seat: int) -> dict[str, Any]:
    reasons: Counter[str] = Counter()
    active_steps = 0
    changed_steps = 0
    changes: list[float] = []
    checkpoints: dict[str, dict[str, Any]] = {}
    previous_animals: Counter[str] | None = None
    animal_losses: Counter[str] = Counter()
    minimum_money = math.inf
    max_unfed = 0
    max_unwatered = 0
    minimum_productive = math.inf
    seen_days: set[int] = set()
    for states in replay.get("steps") or []:
        state = states[seat]
        obs = state.get("observation") or {}
        if not obs.get("farms"):
            continue
        day = int(obs.get("day", 0) or 0)
        if v102.v14._phase(day) in v102.ELIGIBLE_PHASES:
            safe = v102.base._safe_observation(obs)
            if safe is not None:
                decision = v102._gate_decision(obs, *safe)
                reasons[str(decision.get("reason") or "missing")] += 1
                active_steps += bool(decision.get("active"))
                changed_steps += bool(decision.get("changed"))
                if decision.get("active"):
                    changes.append(float(decision.get("normalized_change", 0) or 0))
        if day in seen_days:
            continue
        seen_days.add(day)
        snapshot = _snapshot(obs, seat)
        minimum_money = min(minimum_money, snapshot["money"])
        max_unfed = max(max_unfed, snapshot["unfed"])
        max_unwatered = max(max_unwatered, snapshot["unwatered"])
        if day >= 6:
            minimum_productive = min(minimum_productive, snapshot["productive"])
        if day in CHECKPOINTS:
            checkpoints[str(day)] = snapshot
        current_animals = Counter(snapshot["animals"])
        if previous_animals is not None:
            for animal in ANIMALS:
                animal_losses[animal] += max(0, previous_animals[animal] - current_animals[animal])
        previous_animals = current_animals
    return {
        "active_steps": active_steps,
        "changed_steps": changed_steps,
        "mean_normalized_change": mean(changes) if changes else 0.0,
        "reasons": dict(reasons),
        "checkpoints": checkpoints,
        "safety": {
            "animal_losses": dict(animal_losses),
            "minimum_day_start_money": 0.0 if minimum_money == math.inf else minimum_money,
            "minimum_day6_plus_productive": (
                0 if minimum_productive == math.inf else minimum_productive
            ),
            "max_unfed_at_day_start": max_unfed,
            "max_unwatered_at_day_start": max_unwatered,
        },
    }


def _runtime_failures(replay: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "step": step,
            "player": player,
            "status": str(state.get("status")),
            "remaining_overage_time": (state.get("observation") or {}).get(
                "remainingOverageTime"
            ),
        }
        for step, states in enumerate(replay.get("steps") or [])
        for player, state in enumerate(states)
        if state.get("status") not in {"ACTIVE", "DONE"}
    ]


def _run(seed: int, seat: int, enabled: bool, replay_path: Path) -> dict[str, Any]:
    _reset(v102)
    _reset(opponent_v14)
    v102.ENABLE_RECOVERY_META_GATE = enabled
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=True)
    agents = [v102.agent, opponent_v14.agent] if seat == 0 else [opponent_v14.agent, v102.agent]
    env.run(agents)
    replay = env.toJSON()
    rewards = [float(value or 0) for value in replay.get("rewards") or (0, 0)]
    failures = _runtime_failures(replay)
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    replay_path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")
    final = replay["steps"][-1]
    return {
        "seed": seed,
        "resolved_seed": int(replay["info"]["seed"]),
        "seat": seat,
        "mode": "candidate" if enabled else "safe-core",
        "ours": rewards[seat],
        "theirs": rewards[1 - seat],
        "margin": rewards[seat] - rewards[1 - seat],
        "statuses": [str(state["status"]) for state in final],
        "runtime_failures": failures,
        "trace": _trace(replay, seat),
        "replay": str(replay_path.relative_to(ROOT)),
    }


def _mode_summary(games: list[dict[str, Any]]) -> dict[str, Any]:
    rewards = [float(game["ours"]) for game in games]
    margins = [float(game["margin"]) for game in games]
    return {
        "games": len(games),
        "all_clean": all(
            game["statuses"] == ["DONE", "DONE"] and not game["runtime_failures"]
            for game in games
        ),
        "games_with_runtime_failure": sum(bool(game["runtime_failures"]) for game in games),
        "reward_context": {
            "mean": mean(rewards),
            "p10": _percentile(rewards, 0.10),
            "minimum": min(rewards),
        },
        "margin_context": {
            "mean": mean(margins),
            "p10": _percentile(margins, 0.10),
            "minimum": min(margins),
        },
        "branch": {
            "games_changed": sum(int(game["trace"]["changed_steps"] > 0) for game in games),
            "mean_active_steps": mean(float(game["trace"]["active_steps"]) for game in games),
            "mean_changed_steps": mean(float(game["trace"]["changed_steps"]) for game in games),
            "mean_normalized_change": mean(
                float(game["trace"]["mean_normalized_change"]) for game in games
            ),
        },
        "safety": {
            "games_with_animal_loss": sum(
                any(int(value) > 0 for value in game["trace"]["safety"]["animal_losses"].values())
                for game in games
            ),
            "animal_losses": {
                animal: sum(
                    int(game["trace"]["safety"]["animal_losses"].get(animal, 0))
                    for game in games
                )
                for animal in ANIMALS
            },
            "minimum_day_start_money": min(
                float(game["trace"]["safety"]["minimum_day_start_money"]) for game in games
            ),
            "minimum_day6_plus_productive": min(
                int(game["trace"]["safety"]["minimum_day6_plus_productive"]) for game in games
            ),
            "max_unfed_at_day_start": max(
                int(game["trace"]["safety"]["max_unfed_at_day_start"]) for game in games
            ),
            "max_unwatered_at_day_start": max(
                int(game["trace"]["safety"]["max_unwatered_at_day_start"]) for game in games
            ),
        },
        "checkpoint_means": {
            str(day): {
                "strawberry": mean(
                    float(game["trace"]["checkpoints"][str(day)]["crops"]["STRAWBERRY"])
                    for game in games
                ),
                "wheat": mean(
                    float(game["trace"]["checkpoints"][str(day)]["crops"]["WHEAT"])
                    for game in games
                ),
                "productive": mean(
                    float(game["trace"]["checkpoints"][str(day)]["productive"])
                    for game in games
                ),
                "money": mean(
                    float(game["trace"]["checkpoints"][str(day)]["money"])
                    for game in games
                ),
            }
            for day in sorted(CHECKPOINTS)
            if all(str(day) in game["trace"]["checkpoints"] for game in games)
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20261201)
    parser.add_argument("--label", default="calibration")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    replay_dir = ROOT / "data/replays" / f"v102_{args.label}_{args.seed}"
    games = [
        _run(
            args.seed + offset,
            seat,
            enabled,
            replay_dir
            / f"{'candidate' if enabled else 'safe'}_seed_{args.seed + offset}_seat_{seat}.json",
        )
        for offset in range(args.pairs)
        for seat in (0, 1)
        for enabled in (False, True)
    ]
    summary = {
        mode: _mode_summary([game for game in games if game["mode"] == mode])
        for mode in ("safe-core", "candidate")
    }
    paired = []
    for seed in range(args.seed, args.seed + args.pairs):
        for seat in (0, 1):
            safe = next(
                game
                for game in games
                if game["seed"] == seed and game["seat"] == seat and game["mode"] == "safe-core"
            )
            candidate = next(
                game
                for game in games
                if game["seed"] == seed and game["seat"] == seat and game["mode"] == "candidate"
            )
            paired.append(
                {
                    "seed": seed,
                    "seat": seat,
                    "reward_delta_context": candidate["ours"] - safe["ours"],
                    "margin_delta_context": candidate["margin"] - safe["margin"],
                    "day15_productive_delta": (
                        candidate["trace"]["checkpoints"]["15"]["productive"]
                        - safe["trace"]["checkpoints"]["15"]["productive"]
                    ),
                    "day20_productive_delta": (
                        candidate["trace"]["checkpoints"]["20"]["productive"]
                        - safe["trace"]["checkpoints"]["20"]["productive"]
                    ),
                    "changed_steps": candidate["trace"]["changed_steps"],
                }
            )
    result = {
        "created_at": datetime.now().astimezone().isoformat(),
        "agent": "agents/v102/main.py",
        "safe_core": "V102 with recovery meta-gate disabled (V11 targets)",
        "opponent": "independent agents/v14/main.py",
        "purpose": "trajectory and safety diagnostic; old-agent win rate is not a selection KPI",
        "configuration": {"pairs": args.pairs, "seed": args.seed, "label": args.label},
        "summary": summary,
        "paired_diagnostics": paired,
        "games": games,
    }
    output = args.output or ROOT / "data/runs" / f"v102_{args.label}_{args.seed}.json"
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": summary, "paired": paired}, ensure_ascii=False, indent=2))
    print(f"result: {output}")
    print(f"replays: {replay_dir}")


if __name__ == "__main__":
    main()
