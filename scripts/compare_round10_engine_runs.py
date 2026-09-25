"""Compare outcome and Shop sequence fields from official and L1 runs."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict[tuple[str, str, str, str], dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return {
            (row["arm"], row["opponent_id"], row["seed"], row["seat"]): row
            for row in csv.DictReader(stream)
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("official", type=Path)
    parser.add_argument("fast", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    official_path = args.official if args.official.is_absolute() else ROOT / args.official
    fast_path = args.fast if args.fast.is_absolute() else ROOT / args.fast
    official, fast = load(official_path), load(fast_path)
    fields = ("self_final_cash", "opp_final_cash", "margin", "result", "shop_sequence_hash")
    rows = []
    for key in sorted(official):
        comparisons = {field: official[key][field] == fast[key][field] for field in fields}
        rows.append(
            {
                "arm": key[0],
                "opponent_id": key[1],
                "seed": int(key[2]),
                "seat": int(key[3]),
                "fields_equal": comparisons,
                "exact": all(comparisons.values()),
            }
        )
    result = {
        "scope": "terminal cash/result and observed Shop sequence; bundled L1 tests cover full observation lockstep",
        "pairs": len(rows),
        "exact_pairs": sum(row["exact"] for row in rows),
        "all_exact": bool(rows) and all(row["exact"] for row in rows),
        "rows": rows,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if not result["all_exact"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
