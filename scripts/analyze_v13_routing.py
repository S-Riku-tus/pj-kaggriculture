"""Audit V13 routing counterfactually on stored complete replays."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v13 import main as v13  # noqa: E402


def _decision_rows(replay: dict[str, Any], seat: int, *, all_hours: bool) -> list[dict[str, Any]]:
    rows = []
    for states in replay.get("steps") or []:
        obs = (states[seat].get("observation") or {}) if seat < len(states) else {}
        if not all_hours and int(obs.get("hour", 0) or 0) != 0:
            continue
        decision = v13.policy_diagnostics(obs).get("v13_relative_critic") or {}
        selected = decision.get("selected") or {}
        context = decision.get("context") or {}
        rows.append(
            {
                "day": int(obs.get("day", 0) or 0),
                "hour": int(obs.get("hour", 0) or 0),
                "active": bool(decision.get("active")),
                "reason": str(decision.get("reason") or "missing"),
                "branch": context.get("key"),
                "expert": selected.get("expert"),
                "utility_improvement": selected.get("utility_improvement"),
                "improvements": selected.get("improvements"),
                "uncertainty": selected.get("uncertainty"),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path, help="A run JSON containing replay paths and seats")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--all-hours", action="store_true")
    args = parser.parse_args()
    # This tool audits the rejected experimental router even though release
    # behavior has it disabled.
    v13.ENABLE_RELATIVE_CRITIC = True
    run_path = args.run if args.run.is_absolute() else ROOT / args.run
    run = json.loads(run_path.read_text(encoding="utf-8"))
    games = []
    reasons: Counter[str] = Counter()
    experts: Counter[str] = Counter()
    branches: dict[str, Counter[str]] = defaultdict(Counter)
    for game in run.get("games") or []:
        replay_path = Path(game["replay"])
        replay_path = replay_path if replay_path.is_absolute() else ROOT / replay_path
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
        rows = _decision_rows(replay, int(game["seat"]), all_hours=args.all_hours)
        for row in rows:
            reasons[row["reason"]] += 1
            if row["active"]:
                experts[str(row["expert"])] += 1
                branches[str(row["branch"])][str(row["expert"])] += 1
        games.append(
            {
                "seed": game["seed"],
                "seat": game["seat"],
                "active_decisions": sum(row["active"] for row in rows),
                "rows": rows,
            }
        )
    result = {
        "source_run": str(run_path.relative_to(ROOT)),
        "all_hours": args.all_hours,
        "critic_forced_enabled": True,
        "games": games,
        "summary": {
            "games": len(games),
            "sample_granularity": "hour" if args.all_hours else "day",
            "active_decisions": sum(game["active_decisions"] for game in games),
            "reasons": dict(reasons),
            "experts": dict(experts),
            "branches": {key: dict(value) for key, value in branches.items()},
        },
    }
    output = args.output or ROOT / "data/analysis" / f"v13_routing_{run_path.stem}.json"
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
