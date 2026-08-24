"""Run reproducible V9 component ablations in the official environment.

These runs are diagnostic: they attribute trajectory changes to a component;
they are not a win-rate model-selection loop.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kaggle_environments import make  # noqa: E402

from agents.v9 import main as v9  # noqa: E402

MODES = {
    "all": (True, True, True),
    "strategy-market": (True, True, False),
    "option-market": (True, True, False),
    "wait-market": (True, True, False),
    "land-market": (True, True, False),
    "crop-market": (True, True, False),
    "decision": (True, False, False),
    "market": (False, True, False),
    "mission": (False, False, True),
    "safe-core": (False, False, False),
}
INTENT_LIMITS = {
    "option-market": frozenset({"WAIT_ANIMAL_12", "BUY_LAND_24"}),
    "wait-market": frozenset({"WAIT_ANIMAL_12"}),
    "land-market": frozenset({"BUY_LAND_24"}),
    "crop-market": frozenset(
        {"BUILD_PASTURE_12", "PLANT_STRAWBERRY_12", "PLANT_WHEAT_12"}
    ),
}


def _configure(mode: str) -> None:
    decision, market, mission = MODES[mode]
    v9.ENABLE_DECISION_POLICY = decision
    v9.ENABLE_MARKET_POLICY = market
    v9.ENABLE_MISSION_CONTINUITY = mission
    v9.ACTIVE_INTENT_CONTROLS = INTENT_LIMITS.get(mode)


def _run(seed: int, seat: int, opponent: str, replay_path: Path) -> dict[str, Any]:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=True)
    agents = [v9.agent, opponent] if seat == 0 else [opponent, v9.agent]
    env.run(agents)
    final = env.steps[-1]
    rewards = [float(state.reward or 0) for state in final]
    statuses = [state.status for state in final]
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    replay_path.write_text(json.dumps(env.toJSON(), ensure_ascii=False), encoding="utf-8")
    return {
        "seed": seed,
        "seat": seat,
        "ours": rewards[seat],
        "theirs": rewards[1 - seat],
        "margin": rewards[seat] - rewards[1 - seat],
        "win": rewards[seat] > rewards[1 - seat],
        "tie": rewards[seat] == rewards[1 - seat],
        "statuses": statuses,
        "replay": str(replay_path.relative_to(ROOT)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=tuple(MODES), required=True)
    parser.add_argument("--pairs", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20269001)
    parser.add_argument("--opponent", default="starter")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    _configure(args.mode)
    created_at = datetime.now().astimezone()
    run_id = created_at.strftime("%Y%m%d_%H%M%S_%z")
    replay_dir = ROOT / "data" / "replays" / f"{run_id}_v9_{args.mode}_ablation"
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
    summary = {
        "games": len(games),
        "wins": sum(bool(game["win"]) for game in games),
        "ties": sum(bool(game["tie"]) for game in games),
        "win_rate": mean(float(bool(game["win"])) for game in games),
        "mean_our_reward": mean(float(game["ours"]) for game in games),
        "mean_opponent_reward": mean(float(game["theirs"]) for game in games),
        "mean_margin": mean(float(game["margin"]) for game in games),
        "all_done": all(game["statuses"] == ["DONE", "DONE"] for game in games),
    }
    payload = {
        "created_at": created_at.isoformat(),
        "agent": "agents/v9/main.py",
        "mode": args.mode,
        "components": dict(zip(("decision", "market", "mission"), MODES[args.mode], strict=True)),
        "opponent": args.opponent,
        "configuration": {"pairs": args.pairs, "seed": args.seed, "episode_steps": 720},
        "summary": summary,
        "games": games,
    }
    output = args.output or ROOT / "data" / "runs" / f"v9_ablation_{args.mode}_{args.seed}.json"
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"result: {output}")
    print(f"replays: {replay_dir}")


if __name__ == "__main__":
    main()
