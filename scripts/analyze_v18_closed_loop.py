"""Explain paired V18 closed-loop changes at the strategy and market layers."""

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

from agents.v18 import main as v18  # noqa: E402


def _herd(farm: dict[str, Any]) -> Counter[str]:
    result: Counter[str] = Counter()
    for row in farm.get("tiles") or []:
        for tile in row:
            if isinstance(tile, dict) and tile.get("animal"):
                result[str(tile["animal"])] += 1
    return result


def _trace(replay: dict[str, Any], seat: int) -> dict[str, Any]:
    animal_buys: Counter[str] = Counter()
    effective: list[dict[str, Any]] = []
    snapshots: dict[str, Any] = {}
    max_herd: Counter[str] = Counter()
    final_herd: Counter[str] = Counter()
    final_money = 0.0
    for states in replay.get("steps") or []:
        state = states[seat]
        observation = state.get("observation") or {}
        farms = observation.get("farms") or []
        player = int(observation.get("player", seat))
        if len(farms) < 2 or not 0 <= player < len(farms):
            continue
        farm, opponent = farms[player], farms[1 - player]
        herd = _herd(farm)
        for animal in ("COW", "SHEEP"):
            max_herd[animal] = max(max_herd[animal], herd[animal])
        final_herd = herd
        final_money = float(farm.get("money", 0) or 0)
        action = state.get("action") or {}
        for order in action.get("market") or []:
            if len(order) >= 3 and order[0] == "BUY_ANIMAL":
                animal_buys[str(order[1])] += int(order[2])
        day = int(observation.get("day", 0) or 0)
        hour = int(observation.get("hour", 0) or 0)
        if hour == 0 and day in (7, 9, 10, 12, 14, 19):
            snapshots[str(day)] = {
                "money": final_money,
                "cow": herd["COW"],
                "sheep": herd["SHEEP"],
                "productive": v18.base._farm_summary(farm)["productive"],
            }
        gate = v18._herd_gate_prediction(observation, farm, opponent)
        if not gate.get("active") or gate.get("decision") != "freeze-owned":
            continue
        private = observation.get("private") or {}
        baseline = v18._SAFE_STRATEGY_TARGETS(observation, farm, opponent, private)[0]
        owned = {animal: v18.v4._owned_animals(farm, private, animal) for animal in ("COW", "SHEEP")}
        if all(owned[animal] >= baseline[animal] for animal in owned):
            continue
        effective.append(
            {
                "day": day,
                "hour": hour,
                "money": final_money,
                "opponent_money": float(opponent.get("money", 0) or 0),
                "baseline": {animal: int(baseline[animal]) for animal in owned},
                "owned": owned,
                "advantage": gate.get("advantage"),
                "uncertainty": gate.get("uncertainty"),
                "market": action.get("market") or [],
            }
        )
    return {
        "animal_buys": dict(animal_buys),
        "max_herd": {animal: max_herd[animal] for animal in ("COW", "SHEEP")},
        "final_herd": {animal: final_herd[animal] for animal in ("COW", "SHEEP")},
        "final_money": final_money,
        "snapshots": snapshots,
        "effective_changes": effective,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("safe_run", type=Path)
    parser.add_argument("gate_run", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v18_closed_loop_pairs.json"),
    )
    args = parser.parse_args()
    safe_path = args.safe_run if args.safe_run.is_absolute() else ROOT / args.safe_run
    gate_path = args.gate_run if args.gate_run.is_absolute() else ROOT / args.gate_run
    safe = json.loads(safe_path.read_text(encoding="utf-8"))
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    safe_games = {(int(game["seed"]), int(game["seat"])): game for game in safe["games"]}
    pairs: list[dict[str, Any]] = []
    for gate_game in gate["games"]:
        key = (int(gate_game["seed"]), int(gate_game["seat"]))
        safe_game = safe_games[key]
        safe_replay = json.loads((ROOT / safe_game["replay"]).read_text(encoding="utf-8"))
        gate_replay = json.loads((ROOT / gate_game["replay"]).read_text(encoding="utf-8"))
        pairs.append(
            {
                "seed": key[0],
                "seat": key[1],
                "safe_reward": safe_game["ours"],
                "gate_reward": gate_game["ours"],
                "reward_delta": gate_game["ours"] - safe_game["ours"],
                "safe": _trace(safe_replay, key[1]),
                "gate": _trace(gate_replay, key[1]),
            }
        )
    payload = {
        "safe_run": str(safe_path.relative_to(ROOT)),
        "gate_run": str(gate_path.relative_to(ROOT)),
        "pairs": pairs,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
