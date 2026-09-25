"""Require exact state/action/reward equality for B1 and its null wrapper."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("games_csv", type=Path)
    parser.add_argument("--reference", default="B1_original")
    parser.add_argument("--candidate", default="B1_wrapper_null")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    csv_path = args.games_csv if args.games_csv.is_absolute() else ROOT / args.games_csv
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    indexed = {(row["arm"], row["opponent_id"], row["seed"], row["seat"]): row for row in rows}
    comparisons = []
    for key, reference_row in indexed.items():
        if key[0] != args.reference:
            continue
        candidate_key = (args.candidate, *key[1:])
        candidate_row = indexed[candidate_key]
        with gzip.open(ROOT / reference_row["replay"], "rt", encoding="utf-8") as stream:
            reference = json.load(stream)
        with gzip.open(ROOT / candidate_row["replay"], "rt", encoding="utf-8") as stream:
            candidate = json.load(stream)
        fields = ("decisions", "rewards", "telemetry")
        field_hashes = {
            field: {"reference": digest(reference[field]), "candidate": digest(candidate[field])}
            for field in fields
        }
        comparisons.append(
            {
                "opponent_id": key[1],
                "seed": int(key[2]),
                "seat": int(key[3]),
                "exact": all(value["reference"] == value["candidate"] for value in field_hashes.values()),
                "field_hashes": field_hashes,
            }
        )
    result = {
        "pairs": len(comparisons),
        "exact_pairs": sum(row["exact"] for row in comparisons),
        "all_exact": bool(comparisons) and all(row["exact"] for row in comparisons),
        "comparisons": comparisons,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if not result["all_exact"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
