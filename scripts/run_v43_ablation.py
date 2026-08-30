"""Run paired V43 NE-core reservation diagnostics in the official environment."""

from __future__ import annotations

import argparse
import json
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

from agents.v43 import main as v43  # noqa: E402
from scripts import run_v14_ablation as common  # noqa: E402

common.v14 = v43.v14


def _farm(obs: dict[str, Any], seat: int) -> dict[str, Any]:
    farms = obs.get("farms") or []
    player = int(obs.get("player", seat))
    return farms[player] if 0 <= player < len(farms) else {}


def _kind(tile: Any) -> str:
    if tile is None:
        return "EMPTY"
    if not isinstance(tile, dict):
        return str(tile)
    if tile.get("animal") in {"COW", "SHEEP"}:
        return "ANIMAL"
    if tile.get("kind") == "PASTURE":
        return "EMPTY_PASTURE"
    if tile.get("kind") == "PLANT":
        return "CROP"
    return str(tile.get("kind") or "OTHER")


def _ne_core(farm: dict[str, Any], count: int = 8) -> list[tuple[int, int]]:
    tiles = farm.get("tiles") or []
    size = len(tiles) or 10
    half = size // 2
    shed = v43.base._shed_tiles(size)
    positions = [(x, y) for y in range(half) for x in range(half, size)]
    positions.sort(
        key=lambda position: (
            min(v43.base._manhattan(position, value) for value in shed),
            position[1],
            position[0],
        )
    )
    return positions[:count]


def _trace(replay: dict[str, Any], seat: int) -> dict[str, float]:
    metrics = common._trace(replay, seat)
    snapshots: dict[int, Counter[str]] = {}
    protected_plants = 0
    for states in replay.get("steps") or []:
        state = states[seat]
        obs = state.get("observation") or {}
        day = int(obs.get("day", 0) or 0)
        hour = int(obs.get("hour", 0) or 0)
        farm = _farm(obs, seat)
        if hour == 0 and day in {6, 9, 11}:
            tiles = farm.get("tiles") or []
            snapshots[day] = Counter(
                _kind(tiles[y][x]) for x, y in _ne_core(farm)
            )
        if day not in v43.RESERVATION_DAYS:
            continue
        size = len(farm.get("tiles") or []) or 10
        protected = v43._protected_ne_positions(size)
        action = state.get("action") or {}
        actions = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
        positions = [tuple(farm.get("farmer") or [0, 0])]
        positions.extend(tuple(value) for value in (farm.get("hands") or []))
        protected_plants += sum(
            unit < len(positions)
            and unit_action
            and unit_action[0] == "PLANT"
            and positions[unit] in protected
            for unit, unit_action in enumerate(actions)
        )
    metrics["protected_plant_actions"] = float(protected_plants)
    for day in (6, 9, 11):
        for kind in ("ANIMAL", "EMPTY_PASTURE", "CROP", "EMPTY"):
            metrics[f"day{day}_ne8_{kind.lower()}"] = float(
                snapshots.get(day, Counter())[kind]
            )
    return metrics


def _run(seed: int, seat: int, opponent: str, replay_path: Path) -> dict[str, Any]:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=True)
    agents = [v43.agent, opponent] if seat == 0 else [opponent, v43.agent]
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
    parser.add_argument("--mode", choices=("ne-core", "safe-core"), required=True)
    parser.add_argument("--pairs", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20264301)
    parser.add_argument("--opponent", default="starter")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    v43.ENABLE_NE_CORE_RESERVATION = args.mode == "ne-core"
    created_at = datetime.now().astimezone()
    run_id = created_at.strftime("%Y%m%d_%H%M%S_%z")
    replay_dir = ROOT / "data/replays" / f"{run_id}_v43_{args.mode}_ablation"
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
            "p10": common._percentile([game["ours"] for game in games], 0.10),
            "minimum": min(game["ours"] for game in games),
        },
        "margin": {
            "mean": mean(game["margin"] for game in games),
            "p10": common._percentile([game["margin"] for game in games], 0.10),
        },
        "diagnostics": {
            metric: mean(float(game["metrics"][metric]) for game in games)
            for metric in metric_names
        },
    }
    payload = {
        "created_at": created_at.isoformat(),
        "agent": "agents/v43/main.py",
        "mode": args.mode,
        "opponent": args.opponent,
        "configuration": {"pairs": args.pairs, "seed": args.seed, "episode_steps": 720},
        "summary": summary,
        "games": games,
    }
    output = args.output or ROOT / "data/runs" / f"v43_ablation_{args.mode}_{args.seed}.json"
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"result: {output}")
    print(f"replays: {replay_dir}")


if __name__ == "__main__":
    main()
