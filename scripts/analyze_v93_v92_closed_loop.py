"""Explain paired V92 gains and lower-tail behavior over time."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v14 import main as v14  # noqa: E402

DEFAULT_INPUT = ROOT / "data/runs/v92_ablation_starter_20269201.json"
DEFAULT_OUTPUT = ROOT / "data/analysis/v93_v92_closed_loop.json"
base = v14.base


def _state(replay: dict[str, Any], seat: int, step: int) -> dict[str, Any]:
    states = replay.get("steps") or []
    state = states[min(step, len(states) - 1)][seat]
    obs = state.get("observation") or {}
    farms = obs.get("farms") or []
    player = int(obs.get("player", seat))
    own = farms[player] if 0 <= player < len(farms) else {}
    other = farms[1 - player] if len(farms) >= 2 else {}
    summary = base._farm_summary(own)
    other_summary = base._farm_summary(other)
    tiles = [tile for row in (base._get(own, "tiles", []) or []) for tile in row if isinstance(tile, dict)]
    private = obs.get("private") or {}
    inventories = private.get("inventories") or []
    wheat = base._inventory_count(private.get("shed") or {}, "WHEAT") + sum(
        base._inventory_count(inventory, "WHEAT") for inventory in inventories
    )
    return {
        "money": float(base._get(own, "money", 0) or 0),
        "opponent_money": float(base._get(other, "money", 0) or 0),
        "productive": int(summary["productive"]),
        "opponent_productive": int(other_summary["productive"]),
        "hands": len(base._get(own, "hands", []) or []) + 1,
        "unwatered": sum(
            base._get(tile, "kind") == "PLANT" and int(base._get(tile, "consecutive_unwatered", 0) or 0) >= 1
            for tile in tiles
        ),
        "unfed": sum(
            bool(base._get(tile, "animal")) and int(base._get(tile, "consecutive_unfed", 0) or 0) >= 1 for tile in tiles
        ),
        "ready_yield": sum(int(base._get(tile, "yield_units", 0) or 0) for tile in tiles),
        "wheat_available": int(wheat),
        "crops": {key: int(value) for key, value in summary["crops"].items()},
        "animals": {key: int(value) for key, value in summary["animals"].items()},
    }


def _actions(replay: dict[str, Any], seat: int, step: int) -> list[list[Any]]:
    state = (replay.get("steps") or [])[step][seat]
    action = state.get("action") or {}
    return [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]


def _operation_counts(replay: dict[str, Any], seat: int, day: int) -> Counter[str]:
    counts: Counter[str] = Counter()
    for step in range(day * 24, min((day + 1) * 24, len(replay.get("steps") or []))):
        for action in _actions(replay, seat, step):
            counts[str(action[0]) if action else "PASS"] += 1
    return counts


def _pair(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    seat = int(candidate["seat"])
    safe_replay = json.loads((ROOT / baseline["replay"]).read_text(encoding="utf-8"))
    ranker_replay = json.loads((ROOT / candidate["replay"]).read_text(encoding="utf-8"))
    first_divergence = None
    divergent_steps = 0
    step_count = min(len(safe_replay.get("steps") or []), len(ranker_replay.get("steps") or []))
    for step in range(step_count):
        if _actions(safe_replay, seat, step) != _actions(ranker_replay, seat, step):
            divergent_steps += 1
            if first_divergence is None:
                first_divergence = step
    daily = []
    for day in range(30):
        step = min(day * 24, step_count - 1)
        safe = _state(safe_replay, seat, step)
        ranker = _state(ranker_replay, seat, step)
        safe_ops = _operation_counts(safe_replay, seat, day)
        ranker_ops = _operation_counts(ranker_replay, seat, day)
        daily.append(
            {
                "day": day,
                "money_delta": ranker["money"] - safe["money"],
                "margin_state_delta": (ranker["money"] - ranker["opponent_money"])
                - (safe["money"] - safe["opponent_money"]),
                "productive_delta": ranker["productive"] - safe["productive"],
                "opponent_productive_delta": ranker["opponent_productive"] - safe["opponent_productive"],
                "unwatered_delta": ranker["unwatered"] - safe["unwatered"],
                "unfed_delta": ranker["unfed"] - safe["unfed"],
                "ready_yield_delta": ranker["ready_yield"] - safe["ready_yield"],
                "wheat_available_delta": ranker["wheat_available"] - safe["wheat_available"],
                "operation_delta": {
                    operation: ranker_ops[operation] - safe_ops[operation]
                    for operation in sorted(set(safe_ops) | set(ranker_ops))
                    if ranker_ops[operation] != safe_ops[operation]
                },
                "crop_delta": {
                    crop: ranker["crops"][crop] - safe["crops"][crop]
                    for crop in safe["crops"]
                    if ranker["crops"][crop] != safe["crops"][crop]
                },
                "animal_delta": {
                    animal: ranker["animals"][animal] - safe["animals"][animal]
                    for animal in safe["animals"]
                    if ranker["animals"][animal] != safe["animals"][animal]
                },
            }
        )
    return {
        "seed": candidate["seed"],
        "seat": seat,
        "reward_delta": candidate["ours"] - baseline["ours"],
        "margin_delta": candidate["margin"] - baseline["margin"],
        "first_divergence_step": first_divergence,
        "first_divergence_day": (first_divergence // 24 if first_divergence is not None else None),
        "divergent_steps": divergent_steps,
        "daily": daily,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    input_path = args.input if args.input.is_absolute() else ROOT / args.input
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    baseline = {(game["seed"], game["seat"]): game for game in payload["games"] if game["mode"] == "safe-core"}
    pairs = [
        _pair(baseline[(game["seed"], game["seat"])], game)
        for game in payload["games"]
        if game["mode"] == "candidate-ranker"
    ]
    result = {
        "format": "kaggriculture-v93-v92-closed-loop-v1",
        "input": str(input_path.relative_to(ROOT)),
        "pairs": pairs,
        "summary": {
            "all_reward_nonnegative": all(pair["reward_delta"] >= 0 for pair in pairs),
            "negative_margin_pairs": sum(pair["margin_delta"] < 0 for pair in pairs),
            "first_divergence_days": [pair["first_divergence_day"] for pair in pairs],
            "worst_reward_pair": min(pairs, key=lambda pair: pair["reward_delta"])["seed"],
            "worst_margin_pair": min(pairs, key=lambda pair: pair["margin_delta"])["seed"],
        },
        "limits": [
            "starter paired trajectories are regression evidence, not ladder estimates",
            "closed-loop state differences combine direct task effects and later policy reactions",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
