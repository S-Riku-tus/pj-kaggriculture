"""Inspect one episode and persist its daily trace under data/analysis/."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from kaggle_environments import make

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AGENT = Path("agents/v1")


def resolve_agent(value: Path) -> Path:
    candidate = value if value.is_absolute() else ROOT / value
    if candidate.is_dir():
        candidate /= "main.py"
    candidate = candidate.resolve()
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def tile_counts(farm: dict) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in farm["tiles"]:
        for tile in row:
            if not isinstance(tile, dict):
                continue
            value = tile.get("animal") or tile.get("crop") or tile.get("kind")
            if value:
                counts[value] += 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", type=Path, default=DEFAULT_AGENT)
    parser.add_argument("--opponent", default="starter")
    parser.add_argument("--seed", type=int, default=20260821)
    parser.add_argument("--seat", type=int, choices=(0, 1), default=0)
    parser.add_argument("--json", type=Path, help="output path; defaults to data/analysis/<timestamp>_*.json")
    args = parser.parse_args()

    agent_path = resolve_agent(args.agent)
    opponent_candidate = ROOT / args.opponent
    opponent = str(opponent_candidate.resolve()) if opponent_candidate.is_file() else args.opponent
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": args.seed}, debug=True)
    agents = [str(agent_path), opponent]
    if args.seat == 1:
        agents.reverse()
    env.run(agents)

    daily: list[dict[str, object]] = []
    seen_days: set[int] = set()
    action_counts: Counter[str] = Counter()
    market_counts: Counter[str] = Counter()
    for step_states in env.steps:
        state = step_states[args.seat]
        observation = state.observation
        action = state.action if isinstance(state.action, dict) else {}
        for unit_action in [action.get("farmer", ["PASS"]), *action.get("hands", [])]:
            if isinstance(unit_action, list) and unit_action:
                action_counts[unit_action[0]] += 1
        for order in action.get("market", []):
            if isinstance(order, list) and order:
                market_counts[order[0]] += 1

        day = int(observation.day)
        if int(observation.hour) != 0 or day in seen_days:
            continue
        seen_days.add(day)
        farm = observation.farms[args.seat]
        private = observation.private
        counts = tile_counts(farm)
        daily.append(
            {
                "day": day,
                "money": round(float(farm["money"]), 1),
                "land": len(farm["unlocked_quadrants"]),
                "wheat": counts["WHEAT"],
                "carrot": counts["CARROT"],
                "strawberry": counts["STRAWBERRY"],
                "tomato": counts["TOMATO"],
                "cow": counts["COW"],
                "sheep": counts["SHEEP"],
                "weed": counts["WEED"],
                "empty_pasture": counts["PASTURE"],
                "shed_total": sum(private["shed"].values()),
                "shed_wheat": private["shed"]["WHEAT"],
            }
        )

    final = env.steps[-1][args.seat]
    created_at = datetime.now().astimezone()
    result = {
        "created_at": created_at.isoformat(),
        "agent": str(agent_path.relative_to(ROOT)),
        "opponent": args.opponent,
        "seed": args.seed,
        "seat": args.seat,
        "reward": final.reward,
        "status": final.status,
        "daily": daily,
        "unit_actions": dict(action_counts.most_common()),
        "market_actions": dict(market_counts.most_common()),
    }
    output = args.json or ROOT / "data" / "analysis" / (
        f"{created_at.strftime('%Y%m%d_%H%M%S_%z')}_{agent_path.parent.name}_seed_{args.seed}_seat_{args.seat}.json"
    )
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"analysis: {output}")


if __name__ == "__main__":
    main()
