"""Run paired V20 multi-horizon Cow-gate diagnostics."""

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

from agents.v20 import main as v20  # noqa: E402
from scripts import run_v14_ablation as common  # noqa: E402

common.v14 = v20.v14


def _gate_trace(replay: dict[str, Any], seat: int) -> dict[str, float]:
    reasons: Counter[str] = Counter()
    decisions: Counter[str] = Counter()
    supported: Counter[str] = Counter()
    changed_steps = 0
    changed_days: set[int] = set()
    for states in replay.get("steps") or []:
        observation = states[seat].get("observation") or {}
        farms = observation.get("farms") or []
        player = int(observation.get("player", seat))
        if len(farms) < 2 or not 0 <= player < len(farms):
            continue
        farm, opponent = farms[player], farms[1 - player]
        gate = v20._cow_gate_prediction(observation, farm, opponent)
        reasons[str(gate.get("reason") or "missing")] += 1
        if not gate.get("active"):
            continue
        decisions[str(gate.get("decision") or "missing")] += 1
        for horizon, details in gate.get("horizons", {}).items():
            supported[horizon] += bool(details.get("supported"))
        if gate.get("decision") != "freeze-owned":
            continue
        private = observation.get("private") or {}
        baseline = v20._SAFE_STRATEGY_TARGETS(observation, farm, opponent, private)[0]
        owned = v20.v4._owned_animals(farm, private, "COW")
        if owned < baseline["COW"]:
            changed_steps += 1
            changed_days.add(int(observation.get("day", 0) or 0))
    return {
        "cow_gate_active_steps": float(reasons["active"]),
        "cow_gate_freeze_steps": float(decisions["freeze-owned"]),
        "cow_gate_v11_steps": float(decisions["v11-herd"]),
        "cow_gate_h24_supported_steps": float(supported["h24"]),
        "cow_gate_h72_supported_steps": float(supported["h72"]),
        "cow_gate_changed_steps": float(changed_steps),
        "cow_gate_changed_days": float(len(changed_days)),
        "cow_gate_ood_steps": float(reasons["ood"]),
    }


def _run(seed: int, seat: int, opponent: str, replay_path: Path) -> dict[str, Any]:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=True)
    agents = [v20.agent, opponent] if seat == 0 else [opponent, v20.agent]
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
    parser.add_argument("--mode", choices=("multihorizon-cow", "safe-core"), required=True)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20262601)
    parser.add_argument("--opponent", default="starter")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    v20.ENABLE_MULTIHORIZON_COW_GATE = args.mode == "multihorizon-cow"
    created_at = datetime.now().astimezone()
    run_id = created_at.strftime("%Y%m%d_%H%M%S_%z")
    replay_dir = ROOT / "data/replays" / f"{run_id}_v20_{args.mode}_ablation"
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
        "agent": "agents/v20/main.py",
        "mode": args.mode,
        "opponent": args.opponent,
        "configuration": {"pairs": args.pairs, "seed": args.seed, "episode_steps": 720},
        "summary": summary,
        "games": games,
    }
    output = args.output or ROOT / "data/runs" / f"v20_ablation_{args.mode}_{args.seed}.json"
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"result: {output}")
    print(f"replays: {replay_dir}")


if __name__ == "__main__":
    main()
