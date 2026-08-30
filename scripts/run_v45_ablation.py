"""Run paired V45 staged-expansion diagnostics in the official environment."""

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

from agents.v45 import main as v45  # noqa: E402
from scripts import run_v14_ablation as common  # noqa: E402

common.v14 = v45.v14


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
    sheds = v45.base._shed_tiles(size)
    positions = [(x, y) for y in range(half) for x in range(half, size)]
    positions.sort(
        key=lambda position: (
            min(v45.base._manhattan(position, shed) for shed in sheds),
            position[1],
            position[0],
        )
    )
    return positions[:count]


def _trace(replay: dict[str, Any], seat: int) -> dict[str, float]:
    metrics = common._trace(replay, seat)
    snapshots: dict[int, Counter[str]] = {}
    for states in replay.get("steps") or []:
        obs = states[seat].get("observation") or {}
        day = int(obs.get("day", 0) or 0)
        hour = int(obs.get("hour", 0) or 0)
        if hour != 0 or day not in {6, 7, 8, 9, 11}:
            continue
        farm = _farm(obs, seat)
        tiles = farm.get("tiles") or []
        snapshots[day] = Counter(_kind(tiles[y][x]) for x, y in _ne_core(farm))
    for day in (6, 7, 8, 9, 11):
        for kind in ("ANIMAL", "EMPTY_PASTURE", "CROP", "EMPTY"):
            metrics[f"day{day}_ne8_{kind.lower()}"] = float(
                snapshots.get(day, Counter())[kind]
            )
    return metrics


def _run(seed: int, seat: int, opponent: str, path: Path) -> dict[str, Any]:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=True)
    env.run([v45.agent, opponent] if seat == 0 else [opponent, v45.agent])
    replay = env.toJSON()
    final = env.steps[-1]
    rewards = [float(state.reward or 0) for state in final]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")
    return {
        "seed": seed,
        "seat": seat,
        "ours": rewards[seat],
        "theirs": rewards[1 - seat],
        "margin": rewards[seat] - rewards[1 - seat],
        "statuses": [state.status for state in final],
        "metrics": _trace(replay, seat),
        "replay": str(path.relative_to(ROOT)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("staged", "safe-core"), required=True)
    parser.add_argument("--pairs", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20264501)
    parser.add_argument("--opponent", default="starter")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    v45.ENABLE_STAGED_EXPANSION = args.mode == "staged"
    created_at = datetime.now().astimezone()
    run_id = created_at.strftime("%Y%m%d_%H%M%S_%z")
    replay_dir = ROOT / "data/replays" / f"{run_id}_v45_{args.mode}_ablation"
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
    metrics = tuple(games[0]["metrics"])
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
            for metric in metrics
        },
    }
    payload = {
        "created_at": created_at.isoformat(),
        "agent": "agents/v45/main.py",
        "mode": args.mode,
        "opponent": args.opponent,
        "configuration": {
            "pairs": args.pairs,
            "seed": args.seed,
            "episode_steps": 720,
        },
        "summary": summary,
        "games": games,
    }
    output = args.output or ROOT / "data/runs" / f"v45_ablation_{args.mode}_{args.seed}.json"
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"result: {output}")
    print(f"replays: {replay_dir}")


if __name__ == "__main__":
    main()
