"""Closed-loop, multi-metric safety diagnostics for V111.

Opponent agents are state generators.  Their win rate is reported only as a
debugging observation and is never used to select or tune V111's gates.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _import_module(path: Path):
    spec = importlib.util.spec_from_file_location(
        f"_v111_diagnostic_{path.parent.name}_{abs(hash(path))}", path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import agent: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v111 = _import_module(ROOT / "agents/v111/main.py")

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
                if isinstance(tile, dict):
                    yield tile


def _animals(farm: Any) -> Counter[str]:
    return Counter(
        str(_get(tile, "animal"))
        for tile in _tiles(farm)
        if _get(tile, "animal") in {"GOOSE", "COW", "SHEEP"}
    )


def _active_slots(action: Any) -> int:
    if not isinstance(action, dict):
        return 0
    rows = [action.get("farmer"), *(action.get("hands") or [])]
    return sum(isinstance(row, list) and row and row[0] != "PASS" for row in rows)


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, math.ceil(probability * len(ordered)) - 1)
    return ordered[index]


def _run_game(opponent: str | Path, seed: int, seat: int) -> dict[str, Any]:
    opponent_module = _import_module(opponent) if isinstance(opponent, Path) else None
    if opponent_module is not None and hasattr(opponent_module, "reset_runtime_state"):
        opponent_module.reset_runtime_state()
    opponent_agent = opponent_module.agent if opponent_module is not None else opponent
    v111.reset_runtime_state()
    trace: dict[str, Any] = {
        "active_slots": 0,
        "actor_slots": 0,
        "minimum_cash": float("inf"),
        "previous_animals": None,
        "animal_losses": 0,
        "fallback_steps": 0,
        "ood_steps": 0,
        "strategy_counts": Counter(),
        "maximum_clone_confidence": 0,
        "shops": [],
        "final_animals": {},
    }

    def candidate(obs: Any, configuration: Any = None):
        farm = _farm(obs)
        action = v111.agent(obs, configuration)
        diagnostic = v111.policy_diagnostics(obs)
        animals = _animals(farm)
        animal_count = sum(animals.values())
        previous = trace["previous_animals"]
        if previous is not None and animal_count < int(previous):
            trace["animal_losses"] += int(previous) - animal_count
        trace["previous_animals"] = animal_count
        trace["final_animals"] = dict(animals)
        trace["minimum_cash"] = min(
            float(trace["minimum_cash"]), float(_get(farm, "money", 0.0) or 0.0)
        )
        trace["actor_slots"] += 1 + len(_get(farm, "hands", []) or [])
        trace["active_slots"] += _active_slots(action)
        trace["fallback_steps"] += int(bool(diagnostic.get("fallback_latched", False)))
        trace["ood_steps"] += int(
            diagnostic.get("strategy_fallback_reason") == "strategy-model-ood"
        )
        trace["strategy_counts"] = Counter(diagnostic.get("strategy_decision_counts") or {})
        trace["maximum_clone_confidence"] = max(
            int(trace["maximum_clone_confidence"]),
            int(diagnostic.get("clone_confidence", 0)),
        )
        town = _get(obs, "town", {}) or {}
        trace["shops"] = [str(value) for value in (_get(town, "unlocked_shops", []) or [])]
        return action

    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=True)
    env.run([candidate, opponent_agent] if seat == 0 else [opponent_agent, candidate])
    final = env.steps[-1]
    rewards = [float(state.reward or 0) for state in final]
    ours, theirs = rewards[seat], rewards[1 - seat]
    return {
        "seed": seed,
        "seat": seat,
        "statuses": [state.status for state in final],
        "ours": ours,
        "theirs": theirs,
        "margin_debug_only": ours - theirs,
        "win_debug_only": ours > theirs,
        "minimum_cash": trace["minimum_cash"],
        "action_utilization": float(trace["active_slots"]) / max(1, int(trace["actor_slots"])),
        "animal_losses": trace["animal_losses"],
        "fallback_steps": trace["fallback_steps"],
        "ood_steps": trace["ood_steps"],
        "strategy_counts": dict(trace["strategy_counts"]),
        "maximum_clone_confidence": trace["maximum_clone_confidence"],
        "shops": trace["shops"],
        "final_animals": trace["final_animals"],
    }


def _summary(games: list[dict[str, Any]]) -> dict[str, Any]:
    rewards = [float(game["ours"]) for game in games]
    margins = [float(game["margin_debug_only"]) for game in games]
    counts = sum((Counter(game["strategy_counts"]) for game in games), Counter())
    conversion_games = [
        game for game in games if int(game["strategy_counts"].get("cow-to-sheep-purchase", 0)) > 0
    ]
    complete_conversions = [
        game
        for game in conversion_games
        if int(game["strategy_counts"].get("cow-to-sheep-pickup", 0)) == 2
        and int(game["strategy_counts"].get("cow-to-sheep-place", 0)) == 2
    ]
    return {
        "games": len(games),
        "completed": sum(game["statuses"] == ["DONE", "DONE"] for game in games),
        "wins_debug_only": sum(bool(game["win_debug_only"]) for game in games),
        "reward": {
            "mean": mean(rewards),
            "median": median(rewards),
            "minimum": min(rewards),
            "p10_nearest_rank": _percentile(rewards, 0.10),
        },
        "margin_debug_only": {
            "mean": mean(margins),
            "minimum": min(margins),
            "p10_nearest_rank": _percentile(margins, 0.10),
        },
        "minimum_cash": min(float(game["minimum_cash"]) for game in games),
        "action_utilization": {
            "mean": mean(float(game["action_utilization"]) for game in games),
            "minimum": min(float(game["action_utilization"]) for game in games),
        },
        "animal_losses": sum(int(game["animal_losses"]) for game in games),
        "fallback_games": sum(int(game["fallback_steps"]) > 0 for game in games),
        "ood_games": sum(int(game["ood_steps"]) > 0 for game in games),
        "strategy_counts": dict(counts),
        "conversion_games": len(conversion_games),
        "complete_conversion_games": len(complete_conversions),
        "incomplete_conversion_seeds": [
            [game["seed"], game["seat"]]
            for game in conversion_games
            if game not in complete_conversions
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--opponent", action="append", default=[])
    parser.add_argument("--pairs", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20261110)
    parser.add_argument(
        "--output", type=Path, default=Path("data/analysis/v111_closed_loop_diagnostics.json")
    )
    args = parser.parse_args()
    opponents = args.opponent or ["starter", "agents/v14/main.py", "agents/v110/main.py"]
    results: dict[str, Any] = {}
    for opponent_value in opponents:
        opponent = _resolve(opponent_value)
        games = [
            _run_game(opponent, args.seed + offset, seat)
            for offset in range(args.pairs)
            for seat in (0, 1)
        ]
        label = opponent.parent.name if isinstance(opponent, Path) else str(opponent)
        results[label] = {"opponent": str(opponent), "summary": _summary(games), "games": games}
    payload = {
        "format": "kaggriculture-v111-closed-loop-diagnostics-v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "purpose": "mechanical safety and state coverage; not old-agent promotion by win rate",
        "configuration": {"pairs": args.pairs, "seed": args.seed, "both_seats": True},
        "results": results,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value["summary"] for key, value in results.items()}, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
