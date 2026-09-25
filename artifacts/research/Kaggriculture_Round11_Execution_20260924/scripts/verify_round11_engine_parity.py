"""Compare official Python and validated cppsim replays at every decision."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def rows(panel: Path) -> dict[tuple[str, str, str, str], dict[str, str]]:
    with (panel / "games.csv").open(encoding="utf-8-sig", newline="") as stream:
        return {
            (row["arm"], row["opponent_id"], row["seed"], row["seat"]): row
            for row in csv.DictReader(stream)
        }


def replay(path: str) -> dict:
    with gzip.open(ROOT / path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("official", type=Path)
    parser.add_argument("fast", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    official_panel = args.official if args.official.is_absolute() else ROOT / args.official
    fast_panel = args.fast if args.fast.is_absolute() else ROOT / args.fast
    official, fast = rows(official_panel), rows(fast_panel)
    common = sorted(set(official) & set(fast))
    results = []
    for key in common:
        py = replay(official[key]["replay"])
        cpp = replay(fast[key]["replay"])
        decisions = cpp.get("decisions", [])
        steps = py.get("steps", [])
        observation_mismatches = []
        action_mismatches = []
        for index, decision in enumerate(decisions):
            for player in (0, 1):
                official_observation = dict(steps[index][player].get("observation") or {})
                # Raw official seat-1 records omit the shared step field.  It is
                # reconstructed from the containing state index before comparison.
                official_observation.setdefault("step", index)
                if official_observation != decision["observations"][player]:
                    observation_mismatches.append([index, player])
                if steps[index + 1][player].get("action") != decision["actions"][player]:
                    action_mismatches.append([index, player])
        official_rewards = [float(state.get("reward") or 0) for state in steps[-1]]
        fast_rewards = [float(value) for value in cpp.get("rewards", [])]
        statuses = [state.get("status") for state in steps[-1]]
        exact = (
            len(steps) == 720
            and len(decisions) == 719
            and not observation_mismatches
            and not action_mismatches
            and official_rewards == fast_rewards
            and statuses == ["DONE", "DONE"]
        )
        results.append(
            {
                "arm": key[0],
                "opponent": key[1],
                "seed": int(key[2]),
                "seat": int(key[3]),
                "states": len(steps),
                "decisions": len(decisions),
                "observation_mismatches": len(observation_mismatches),
                "first_observation_mismatch": observation_mismatches[:1],
                "action_mismatches": len(action_mismatches),
                "first_action_mismatch": action_mismatches[:1],
                "official_rewards": official_rewards,
                "fast_rewards": fast_rewards,
                "terminal_statuses": statuses,
                "exact": exact,
            }
        )
    result = {
        "schema": "round11-official-cppsim-decision-parity-v1",
        "pairs": len(results),
        "all_exact": bool(results) and all(row["exact"] for row in results),
        "rows": results,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    if not result["all_exact"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
