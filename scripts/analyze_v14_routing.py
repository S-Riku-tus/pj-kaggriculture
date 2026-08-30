"""Explain V14 recovery target changes on stored complete replays."""

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


def _targets(obs: dict[str, Any]) -> dict[str, Any] | None:
    safe = v14.base._safe_observation(obs)
    if safe is None:
        return None
    farm, opponent, private = safe
    prediction = v14._winner_prediction(obs, farm, opponent)
    baseline = v14.v11._strategy_targets(obs, farm, opponent, private)
    animals, crops = baseline[0], baseline[1]
    projected_animals, projected_crops = animals, crops
    if prediction["active"]:
        projected_animals, projected_crops = v14._project_targets(obs, farm, private, animals, crops, prediction)
    changed = projected_animals != animals or projected_crops != crops
    return {
        "day": int(obs.get("day", 0) or 0),
        "hour": int(obs.get("hour", 0) or 0),
        "active": bool(prediction["active"]),
        "changed": changed,
        "reason": prediction["reason"],
        "money_gap_ratio": prediction.get("money_gap_ratio"),
        "confidence": prediction.get("confidence"),
        "uncertainty": prediction.get("uncertainty"),
        "demand": dict(v14.base._demand_profile(obs)),
        "baseline": {**crops, "COW": animals["COW"], "SHEEP": animals["SHEEP"]},
        "projected": {
            **projected_crops,
            "COW": projected_animals["COW"],
            "SHEEP": projected_animals["SHEEP"],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--seat", type=int, choices=(0, 1))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    run_path = args.run if args.run.is_absolute() else ROOT / args.run
    run = json.loads(run_path.read_text(encoding="utf-8"))
    games = []
    reasons: Counter[str] = Counter()
    active = 0
    changed = 0
    for game in run.get("games") or []:
        if args.seed is not None and int(game["seed"]) != args.seed:
            continue
        if args.seat is not None and int(game["seat"]) != args.seat:
            continue
        replay_path = Path(game["replay"])
        replay_path = replay_path if replay_path.is_absolute() else ROOT / replay_path
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
        rows = []
        for states in replay.get("steps") or []:
            row = _targets(states[int(game["seat"])].get("observation") or {})
            if row is None:
                continue
            reasons[row["reason"]] += 1
            active += int(row["active"])
            changed += int(row["changed"])
            if row["active"] or row["changed"]:
                rows.append(row)
        games.append({"seed": game["seed"], "seat": game["seat"], "rows": rows})
    result = {
        "source_run": str(run_path.relative_to(ROOT)),
        "summary": {
            "games": len(games),
            "active_decisions": active,
            "changed_decisions": changed,
            "reasons": dict(reasons),
        },
        "games": games,
    }
    output = args.output or ROOT / "data/analysis" / f"v14_routing_{run_path.stem}.json"
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
