"""Verify full official replay identity between B1 and its NO_CHANGE wrapper."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_replay(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def normalized_steps(replay: dict) -> list[list[dict]]:
    fields = ("observation", "action", "reward", "status")
    return [
        [{field: state.get(field) for field in fields} for state in step]
        for step in replay["steps"]
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("panel", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    panel = args.panel if args.panel.is_absolute() else ROOT / args.panel
    with (panel / "games.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    indexed = {
        (row["arm"], row["opponent_id"], row["seed"], row["seat"]): row
        for row in rows
    }
    results = []
    for key, baseline in sorted(indexed.items()):
        if key[0] != "B1":
            continue
        candidate_key = ("NO_CHANGE", *key[1:])
        candidate = indexed[candidate_key]
        left = read_replay(ROOT / baseline["replay"])
        right = read_replay(ROOT / candidate["replay"])
        left_steps = normalized_steps(left)
        right_steps = normalized_steps(right)
        results.append(
            {
                "opponent": key[1],
                "seed": int(key[2]),
                "seat": int(key[3]),
                "states": len(left_steps),
                "decisions": len(left_steps) - 1,
                "full_observation_action_reward_status_identity": left_steps == right_steps,
                "terminal_rewards_equal": [s.get("reward") for s in left["steps"][-1]]
                == [s.get("reward") for s in right["steps"][-1]],
            }
        )
    result = {
        "schema": "round11-no-change-official-identity-v1",
        "pairs": len(results),
        "all_identical": bool(results)
        and all(row["full_observation_action_reward_status_identity"] for row in results),
        "rows": results,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    if not result["all_identical"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
