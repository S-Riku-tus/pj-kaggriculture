"""Run paired V18 intraday herd-gate closed-loop diagnostics."""

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

from agents.v18 import main as v18  # noqa: E402
from scripts import run_v14_ablation as common  # noqa: E402

common.v14 = v18.v14


def _gate_trace(replay: dict[str, Any], seat: int) -> dict[str, float]:
    reasons: Counter[str] = Counter()
    decisions: Counter[str] = Counter()
    changed_steps = 0
    changed_days: set[int] = set()
    for states in replay.get("steps") or []:
        observation = states[seat].get("observation") or {}
        farms = observation.get("farms") or []
        player = int(observation.get("player", seat))
        if len(farms) < 2 or not 0 <= player < len(farms):
            continue
        farm, opponent = farms[player], farms[1 - player]
        gate = v18._herd_gate_prediction(observation, farm, opponent)
        reasons[str(gate.get("reason") or "missing")] += 1
        decisions[str(gate.get("decision") or "fallback")] += 1
        if not gate.get("active") or gate.get("decision") != "freeze-owned":
            continue
        private = observation.get("private") or {}
        baseline = v18._SAFE_STRATEGY_TARGETS(observation, farm, opponent, private)[0]
        owned = {animal: v18.v4._owned_animals(farm, private, animal) for animal in ("COW", "SHEEP")}
        if all(owned[animal] >= baseline[animal] for animal in owned):
            continue
        changed_steps += 1
        changed_days.add(int(observation.get("day", 0) or 0))
    return {
        "herd_gate_active_steps": float(reasons["active"]),
        "herd_gate_freeze_steps": float(decisions["freeze-owned"]),
        "herd_gate_v11_steps": float(decisions["v11-herd"]),
        "herd_gate_changed_steps": float(changed_steps),
        "herd_gate_changed_days": float(len(changed_days)),
        "herd_gate_uncertain_steps": float(reasons["uncertain"]),
        "herd_gate_ood_steps": float(reasons["ood"]),
    }


def _run(seed: int, seat: int, opponent: str, replay_path: Path) -> dict[str, Any]:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=True)
    agents = [v18.agent, opponent] if seat == 0 else [opponent, v18.agent]
    env.run(agents)
    replay = env.toJSON()
    final = env.steps[-1]
    rewards = [float(state.reward or 0) for state in final]
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    replay_path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")
    metrics = common._trace(replay, seat)
    metrics.update(_gate_trace(replay, seat))
    return {
        "seed": seed,
        "seat": seat,
        "ours": rewards[seat],
        "theirs": rewards[1 - seat],
        "margin": rewards[seat] - rewards[1 - seat],
        "statuses": [state.status for state in final],
        "metrics": metrics,
        "replay": str(replay_path.relative_to(ROOT)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("intraday-gate", "safe-core"), required=True)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20262201)
    parser.add_argument("--opponent", default="starter")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    v18.ENABLE_INTRADAY_HERD_GATE = args.mode == "intraday-gate"
    created_at = datetime.now().astimezone()
    run_id = created_at.strftime("%Y%m%d_%H%M%S_%z")
    replay_dir = ROOT / "data/replays" / f"{run_id}_v18_{args.mode}_ablation"
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
        "diagnostics": {metric: mean(float(game["metrics"][metric]) for game in games) for metric in metric_names},
    }
    payload = {
        "created_at": created_at.isoformat(),
        "agent": "agents/v18/main.py",
        "mode": args.mode,
        "opponent": args.opponent,
        "configuration": {"pairs": args.pairs, "seed": args.seed, "episode_steps": 720},
        "summary": summary,
        "games": games,
    }
    output = args.output or ROOT / "data/runs" / f"v18_ablation_{args.mode}_{args.seed}.json"
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"result: {output}")
    print(f"replays: {replay_dir}")


if __name__ == "__main__":
    main()
