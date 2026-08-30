"""Episode-split, multi-metric safety diagnostics for V109.

This script is intentionally not a promotion-by-win-rate harness.  It records
completion, lower-tail reward/margin, actor utilization, cash floor, animal
losses, land progression, route-fallback activation, demand regime, and farm
state checkpoints.  Opponents are perturbation sources for exercising states.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CHECKPOINTS = {24, 72, 168, 264, 480, 648, 719}


def _import_module(path: Path):
    spec = importlib.util.spec_from_file_location(
        f"_v109_diagnostic_{path.parent.name}_{abs(hash(path))}", path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import agent: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Import the candidate before kaggle-environments, whose optional Lux loader
# may temporarily use the generic top-level name ``agents``.
v109 = _import_module(ROOT / "agents" / "v109" / "main.py")

from kaggle_environments import make  # noqa: E402


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    getter = getattr(obj, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except (AttributeError, TypeError):
            pass
    return getattr(obj, key, default)


def _resolve(value: str) -> str | Path:
    candidate = Path(value)
    rooted = candidate if candidate.is_absolute() else ROOT / candidate
    if rooted.is_dir():
        rooted /= "main.py"
    return rooted.resolve() if rooted.is_file() else value


def _farm(obs: Any) -> Any:
    farms = list(_get(obs, "farms", []) or [])
    seat = 1 if int(_get(obs, "player", 0) or 0) == 1 else 0
    return farms[seat] if seat < len(farms) else {}


def _tiles(farm: Any):
    for row in _get(farm, "tiles", []) or []:
        if isinstance(row, dict):
            yield row
        else:
            for tile in row or []:
                if tile is not None:
                    yield tile


def _farm_vector(obs: Any) -> dict[str, Any]:
    farm = _farm(obs)
    crops: Counter[str] = Counter()
    animals: Counter[str] = Counter()
    weeds = 0
    max_unfed = 0
    productive = 0
    for tile in _tiles(farm):
        crop = _get(tile, "crop")
        animal = _get(tile, "animal")
        kind = _get(tile, "kind")
        if crop:
            crops[str(crop)] += 1
            productive += 1
        if animal:
            animals[str(animal)] += 1
            productive += 1
            max_unfed = max(max_unfed, int(_get(tile, "consecutive_unfed", 0) or 0))
        if kind == "WEED":
            weeds += 1
    unlocked = len(set(_get(farm, "unlocked_quadrants", []) or []))
    capacity = max(25, 25 * unlocked)
    return {
        "money": float(_get(farm, "money", 0) or 0),
        "hands": len(_get(farm, "hands", []) or []),
        "land": unlocked,
        "productive_tiles": productive,
        "utilization": productive / capacity,
        "weeds": weeds,
        "max_consecutive_unfed": max_unfed,
        "crops": dict(sorted(crops.items())),
        "animals": dict(sorted(animals.items())),
    }


def _active_slots(action: Any) -> int:
    if not isinstance(action, dict):
        return 0
    rows = [action.get("farmer")] + list(action.get("hands") or [])
    return sum(bool(row) and str(row[0]) != "PASS" for row in rows)


def _nearest_rank(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def _summary(games: list[dict[str, Any]]) -> dict[str, Any]:
    rewards = [float(game["ours"]) for game in games]
    margins = [float(game["margin"]) for game in games]
    utilizations = [float(game["action_utilization"]) for game in games]
    by_demand: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for game in games:
        by_demand["+".join(game["shops"]) or "NO_SHOP"].append(game)
    return {
        "games": len(games),
        "completed": sum(game["statuses"] == ["DONE", "DONE"] for game in games),
        "wins_diagnostic_only": sum(bool(game["win"]) for game in games),
        "reward": {
            "mean": mean(rewards),
            "median": median(rewards),
            "minimum": min(rewards),
            "p10_nearest_rank": _nearest_rank(rewards, 0.10),
        },
        "margin": {
            "mean": mean(margins),
            "median": median(margins),
            "minimum": min(margins),
            "p10_nearest_rank": _nearest_rank(margins, 0.10),
        },
        "action_utilization": {
            "mean": mean(utilizations),
            "minimum": min(utilizations),
        },
        "minimum_cash": min(float(game["minimum_cash"]) for game in games),
        "animal_losses": sum(int(game["animal_losses"]) for game in games),
        "fallback_games": sum(game["fallback_first_step"] is not None for game in games),
        "fallback_steps": sum(int(game["fallback_steps"]) for game in games),
        "demand_groups": {
            key: {
                "games": len(group),
                "mean_reward": mean(float(game["ours"]) for game in group),
                "minimum_reward": min(float(game["ours"]) for game in group),
                "mean_margin": mean(float(game["margin"]) for game in group),
            }
            for key, group in sorted(by_demand.items())
        },
    }


def _run_game(
    opponent: str | Path,
    seed: int,
    seat: int,
    force_fallback_step: int | None = None,
) -> dict[str, Any]:
    opponent_module = _import_module(opponent) if isinstance(opponent, Path) else None
    if opponent_module is not None and hasattr(opponent_module, "reset_runtime_state"):
        opponent_module.reset_runtime_state()
    opponent_agent = opponent_module.agent if opponent_module is not None else opponent
    v109.reset_runtime_state()
    trace: dict[str, Any] = {
        "actor_slots": 0,
        "active_slots": 0,
        "minimum_cash": float("inf"),
        "animal_losses": 0,
        "previous_animals": None,
        "fallback_steps": 0,
        "fallback_first_step": None,
        "fallback_reason": None,
        "checkpoints": {},
        "shops": [],
    }

    def candidate(obs: Any, configuration: Any = None):
        vector = _farm_vector(obs)
        step = int(_get(obs, "step", 24 * int(_get(obs, "day", 0) or 0) + int(_get(obs, "hour", 0) or 0)) or 0)
        if force_fallback_step is not None and step >= force_fallback_step:
            normalized = v109._normalize_observation(obs)
            state = v109._state_for(normalized)
            if not state["latched"]:
                state.update(
                    latched=True,
                    reason="diagnostic-forced-fallback",
                    fallback_step=step,
                )
        action = v109.agent(obs, configuration)
        diagnostic = v109.policy_diagnostics(obs)
        actor_slots = 1 + int(vector["hands"])
        trace["actor_slots"] += actor_slots
        trace["active_slots"] += _active_slots(action)
        trace["minimum_cash"] = min(float(trace["minimum_cash"]), float(vector["money"]))
        animal_count = sum(int(value) for value in vector["animals"].values())
        previous = trace["previous_animals"]
        if previous is not None and animal_count < int(previous):
            trace["animal_losses"] += int(previous) - animal_count
        trace["previous_animals"] = animal_count
        if diagnostic["fallback_latched"]:
            trace["fallback_steps"] += 1
            if trace["fallback_first_step"] is None:
                trace["fallback_first_step"] = step
                trace["fallback_reason"] = diagnostic["fallback_reason"]
        if step in CHECKPOINTS:
            trace["checkpoints"][str(step)] = vector
        town = _get(obs, "town", {}) or {}
        trace["shops"] = sorted(str(shop) for shop in (_get(town, "unlocked_shops", []) or []))
        return action

    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=True)
    env.run([candidate, opponent_agent] if seat == 0 else [opponent_agent, candidate])
    final = env.steps[-1]
    rewards = [float(state.reward or 0) for state in final]
    ours, theirs = rewards[seat], rewards[1 - seat]
    return {
        "seed": seed,
        "seat": seat,
        "ours": ours,
        "theirs": theirs,
        "margin": ours - theirs,
        "win": ours > theirs,
        "statuses": [state.status for state in final],
        "action_utilization": float(trace["active_slots"]) / max(1, int(trace["actor_slots"])),
        "minimum_cash": trace["minimum_cash"],
        "animal_losses": trace["animal_losses"],
        "fallback_steps": trace["fallback_steps"],
        "fallback_first_step": trace["fallback_first_step"],
        "fallback_reason": trace["fallback_reason"],
        "shops": trace["shops"],
        "checkpoints": trace["checkpoints"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--opponent",
        action="append",
        default=[],
        help="built-in opponent or repository agent; repeatable",
    )
    parser.add_argument("--pairs", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260830)
    parser.add_argument(
        "--force-fallback-step",
        type=int,
        help="diagnostic only: latch the rule fallback at this observation step",
    )
    parser.add_argument("--output", type=Path, default=Path("data/analysis/v109_diagnostics.json"))
    args = parser.parse_args()
    opponents = args.opponent or ["starter", "agents/v14/main.py", "agents/v108/main.py"]
    results: dict[str, Any] = {}
    for opponent_value in opponents:
        opponent = _resolve(opponent_value)
        games = [
            _run_game(opponent, args.seed + offset, seat, args.force_fallback_step)
            for offset in range(args.pairs)
            for seat in (0, 1)
        ]
        label = opponent.parent.name if isinstance(opponent, Path) else str(opponent)
        results[label] = {"opponent": str(opponent), "summary": _summary(games), "games": games}
    payload = {
        "created_at": datetime.now().astimezone().isoformat(),
        "purpose": "safety/state-coverage diagnostics; not a promotion-by-old-agent-win-rate test",
        "configuration": {
            "pairs": args.pairs,
            "seed": args.seed,
            "both_seats": True,
            "force_fallback_step": args.force_fallback_step,
        },
        "results": results,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value["summary"] for key, value in results.items()}, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
