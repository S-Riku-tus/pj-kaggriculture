"""Run paired local matches and persist their results under data/."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from statistics import mean

from kaggle_environments import make

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AGENT = Path("agents/v1")


def resolve_agent(value: Path) -> Path:
    candidate = value if value.is_absolute() else ROOT / value
    if candidate.is_dir():
        candidate /= "main.py"
    candidate = candidate.resolve()
    if not candidate.is_file():
        raise FileNotFoundError(f"agent main.py not found: {candidate}")
    return candidate


def resolve_opponent(value: str) -> str:
    candidate = Path(value)
    rooted = candidate if candidate.is_absolute() else ROOT / candidate
    return str(rooted.resolve()) if rooted.is_file() else value


def slug(value: str) -> str:
    label = Path(value).parent.name if value.endswith(".py") else value
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("_") or "opponent"


def run_one(
    agent_path: Path,
    opponent: str,
    seed: int,
    our_seat: int,
    episode_steps: int,
    replay_path: Path | None,
) -> dict[str, object]:
    configuration = {"episodeSteps": episode_steps, "seed": seed}
    env = make("kaggriculture", configuration=configuration, debug=True)
    agents = [str(agent_path), opponent] if our_seat == 0 else [opponent, str(agent_path)]
    env.run(agents)
    final = env.steps[-1]
    rewards = [float(state.reward or 0) for state in final]
    statuses = [state.status for state in final]
    ours = rewards[our_seat]
    theirs = rewards[1 - our_seat]
    if replay_path is not None:
        replay_path.parent.mkdir(parents=True, exist_ok=True)
        replay_path.write_text(json.dumps(env.toJSON(), ensure_ascii=False), encoding="utf-8")
    return {
        "seed": seed,
        "seat": our_seat,
        "ours": ours,
        "theirs": theirs,
        "margin": ours - theirs,
        "win": ours > theirs,
        "tie": ours == theirs,
        "statuses": statuses,
        "replay": str(replay_path.relative_to(ROOT)) if replay_path is not None else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", type=Path, default=DEFAULT_AGENT, help="versioned agent directory or main.py")
    parser.add_argument("--opponent", default="starter", help="built-in name or agent main.py path")
    parser.add_argument("--pairs", type=int, default=2, help="number of seeds; both seats run for each seed")
    parser.add_argument("--seed", type=int, default=20260821)
    parser.add_argument("--episode-steps", type=int, default=720)
    parser.add_argument("--json", type=Path, help="result path; defaults to data/runs/<timestamp>_*.json")
    parser.add_argument("--save-replays", action="store_true", help="write full replay JSON files under data/replays")
    args = parser.parse_args()

    agent_path = resolve_agent(args.agent)
    opponent = resolve_opponent(args.opponent)
    created_at = datetime.now().astimezone()
    run_id = created_at.strftime("%Y%m%d_%H%M%S_%z")
    agent_name = agent_path.parent.name
    opponent_name = slug(opponent)
    replay_dir = ROOT / "data" / "replays" / f"{run_id}_{agent_name}_vs_{opponent_name}"

    results = []
    for offset in range(args.pairs):
        for seat in (0, 1):
            replay_path = replay_dir / f"seed_{args.seed + offset}_seat_{seat}.json" if args.save_replays else None
            results.append(run_one(agent_path, opponent, args.seed + offset, seat, args.episode_steps, replay_path))

    summary = {
        "games": len(results),
        "wins": sum(bool(result["win"]) for result in results),
        "ties": sum(bool(result["tie"]) for result in results),
        "win_rate": mean(float(bool(result["win"])) for result in results),
        "mean_our_reward": mean(float(result["ours"]) for result in results),
        "mean_opponent_reward": mean(float(result["theirs"]) for result in results),
        "mean_margin": mean(float(result["margin"]) for result in results),
        "all_done": all(result["statuses"] == ["DONE", "DONE"] for result in results),
    }
    payload = {
        "created_at": created_at.isoformat(),
        "agent": str(agent_path.relative_to(ROOT)),
        "opponent": args.opponent,
        "configuration": {
            "pairs": args.pairs,
            "seed": args.seed,
            "episode_steps": args.episode_steps,
        },
        "summary": summary,
        "games": results,
    }
    output = args.json or ROOT / "data" / "runs" / f"{run_id}_{agent_name}_vs_{opponent_name}.json"
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"result: {output}")
    if args.save_replays:
        print(f"replays: {replay_dir}")


if __name__ == "__main__":
    main()
