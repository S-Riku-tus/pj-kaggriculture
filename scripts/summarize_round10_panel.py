"""Summarize strict outcomes and paired arm transitions without rate conversion."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def numeric(row: dict[str, str], key: str) -> float:
    return float(row.get(key, 0) or 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("games_csv", type=Path)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--paired-csv", type=Path, required=True)
    args = parser.parse_args()
    games_path = args.games_csv if args.games_csv.is_absolute() else ROOT / args.games_csv
    with games_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    index = {
        (row["arm"], row["opponent_id"], row["seed"], row["seat"]): row
        for row in rows
    }
    grouped: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[(row["arm"], row["opponent_family"], row["opponent_id"])].append(row)
    groups = []
    for (arm, family, opponent), values in sorted(grouped.items()):
        outcomes = Counter(row["result"] for row in values)
        groups.append(
            {
                "arm": arm,
                "opponent_family": family,
                "opponent_id": opponent,
                "games": len(values),
                "wins": outcomes["W"],
                "losses": outcomes["L"],
                "ties": outcomes["T"],
                "score_rate": (outcomes["W"] + 0.5 * outcomes["T"]) / len(values),
                "mean_self_cash": mean(numeric(row, "self_final_cash") for row in values),
                "mean_opp_cash": mean(numeric(row, "opp_final_cash") for row in values),
                "mean_margin": mean(numeric(row, "margin") for row in values),
                "model_loaded_games": sum(int(numeric(row, "model_loaded")) for row in values),
                "model_calls": sum(int(numeric(row, "model_calls")) for row in values),
                "model_selected_tasks": sum(int(numeric(row, "model_selected_tasks")) for row in values),
                "model_changed_final_actions": sum(
                    int(numeric(row, "model_changed_final_actions")) for row in values
                ),
                "rule_overrides": sum(int(numeric(row, "rule_overrides")) for row in values),
                "contract_failures": sum(int(numeric(row, "contract_failures")) for row in values),
                "distinct_shop_sequences": len({row["shop_sequence_hash"] for row in values}),
            }
        )
    paired_rows: list[dict[str, Any]] = []
    for row in rows:
        if row["arm"] == args.reference:
            continue
        reference = index.get((args.reference, row["opponent_id"], row["seed"], row["seat"]))
        if reference is None:
            continue
        paired_rows.append(
            {
                "arm": row["arm"],
                "opponent_family": row["opponent_family"],
                "opponent_id": row["opponent_id"],
                "seed": int(row["seed"]),
                "seat": int(row["seat"]),
                "reference_result": reference["result"],
                "candidate_result": row["result"],
                "transition": f"{reference['result']}->{row['result']}",
                "reference_margin": numeric(reference, "margin"),
                "candidate_margin": numeric(row, "margin"),
                "margin_delta": numeric(row, "margin") - numeric(reference, "margin"),
                "self_cash_delta": numeric(row, "self_final_cash") - numeric(reference, "self_final_cash"),
                "opp_cash_delta": numeric(row, "opp_final_cash") - numeric(reference, "opp_final_cash"),
            }
        )
    paired_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in paired_rows:
        paired_groups[(str(row["arm"]), str(row["opponent_id"]))].append(row)
    paired = []
    for (arm, opponent), values in sorted(paired_groups.items()):
        transitions = Counter(row["transition"] for row in values)
        paired.append(
            {
                "arm": arm,
                "opponent_id": opponent,
                "pairs": len(values),
                "mean_margin_delta": mean(row["margin_delta"] for row in values),
                "mean_self_cash_delta": mean(row["self_cash_delta"] for row in values),
                "mean_opp_cash_delta": mean(row["opp_cash_delta"] for row in values),
                "transitions": dict(sorted(transitions.items())),
            }
        )
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "games": len(rows),
        "reference": args.reference,
        "sampling_note": (
            "seat pairs and candidate forks sharing a seed are reported, "
            "not treated as independent samples"
        ),
        "groups": groups,
        "paired_vs_reference": paired,
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    paired_path = args.paired_csv if args.paired_csv.is_absolute() else ROOT / args.paired_csv
    paired_path.parent.mkdir(parents=True, exist_ok=True)
    if paired_rows:
        with paired_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(paired_rows[0]))
            writer.writeheader()
            writer.writerows(paired_rows)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
