"""Closed-loop safety and state-coverage diagnostics for V113."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import evaluate_v111_diagnostics as common  # noqa: E402

v113 = common._import_module(ROOT / "agents/v113/main.py")
common.v111 = v113


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--opponent", action="append", default=[])
    parser.add_argument("--pairs", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260901)
    parser.add_argument(
        "--generalized-gate", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--premium-first", action=argparse.BooleanOptionalAction, default=False
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v113_closed_loop_diagnostics.json"),
    )
    args = parser.parse_args()
    v113.ENABLE_GENERALIZED_ANIMAL_GATE = args.generalized_gate
    v113.ENABLE_PREMIUM_FIRST = args.premium_first
    opponents = args.opponent or ["starter", "agents/v14/main.py", "agents/v111/main.py"]
    results = {}
    for opponent_value in opponents:
        opponent = common._resolve(opponent_value)
        games = [
            common._run_game(opponent, args.seed + offset, seat)
            for offset in range(args.pairs)
            for seat in (0, 1)
        ]
        label = opponent.parent.name if isinstance(opponent, Path) else str(opponent)
        results[label] = {
            "opponent": str(opponent),
            "summary": common._summary(games),
            "games": games,
        }
    payload = {
        "format": "kaggriculture-v113-closed-loop-diagnostics-v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "purpose": "mechanical safety and state coverage; wins are debug-only",
        "configuration": {
            "pairs": args.pairs,
            "seed": args.seed,
            "both_seats": True,
            "generalized_gate": args.generalized_gate,
            "premium_first": args.premium_first,
        },
        "results": results,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {key: value["summary"] for key, value in results.items()},
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"result: {output}")


if __name__ == "__main__":
    main()
