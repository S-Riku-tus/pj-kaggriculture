#!/usr/bin/env python3
"""Summarize paired V126 four-arm results against the common control."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "experiments/research_20260920_v126/four_arm_development"
ARMS = ("control", "service", "fertilizer", "joint")


def main() -> None:
    with (EVAL / "games.csv").open("r", encoding="utf-8-sig", newline="") as stream:
        games = list(csv.DictReader(stream))
    keyed = {
        (row["arm"], row["opponent_family"], int(row["seed"]), int(row["seat"])): row
        for row in games
    }
    direct = []
    for arm in ARMS:
        if arm == "control":
            continue
        pairs = []
        for key, control in keyed.items():
            if key[0] != "control":
                continue
            other = keyed[(arm, *key[1:])]
            control_win = bool(int(control["win"]))
            other_win = bool(int(other["win"]))
            pairs.append(
                {
                    "opponent": key[1],
                    "seed": key[2],
                    "seat": key[3],
                    "margin_delta": float(other["margin"]) - float(control["margin"]),
                    "control_win": control_win,
                    "candidate_win": other_win,
                }
            )
        deltas = [row["margin_delta"] for row in pairs]
        direct.append(
            {
                "arm": arm,
                "paired_games": len(pairs),
                "wins": sum(row["candidate_win"] for row in pairs),
                "loss_to_win": sum(not row["control_win"] and row["candidate_win"] for row in pairs),
                "win_to_loss": sum(row["control_win"] and not row["candidate_win"] for row in pairs),
                "mean_margin_delta": mean(deltas),
                "median_margin_delta": median(deltas),
                "lower_margin_delta": min(deltas),
                "upper_margin_delta": max(deltas),
                "by_opponent": {
                    opponent: {
                        "games": len(selected),
                        "wins": sum(row["candidate_win"] for row in selected),
                        "mean_margin_delta": mean(row["margin_delta"] for row in selected),
                        "win_to_loss": sum(
                            row["control_win"] and not row["candidate_win"] for row in selected
                        ),
                    }
                    for opponent in sorted({row["opponent"] for row in pairs})
                    if (selected := [row for row in pairs if row["opponent"] == opponent])
                },
            }
        )

    terminal_triggers: dict[tuple[str, str, int, int], dict[str, int]] = {}
    with (EVAL / "decision_log.jsonl").open("r", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if "trigger_counts" not in row:
                continue
            key = (row["arm"], row["opponent"], int(row["seed"]), int(row["seat"]))
            terminal_triggers[key] = {
                name: int(value) for name, value in (row.get("trigger_counts") or {}).items()
            }
    trigger_totals: dict[str, dict[str, int]] = {}
    for arm in ARMS:
        total: Counter[str] = Counter()
        for key, counts in terminal_triggers.items():
            if key[0] == arm:
                total.update(counts)
        trigger_totals[arm] = dict(total)

    shop_hashes: dict[tuple[str, int, int], set[str]] = {}
    for row in games:
        replay_path = ROOT / row["replay"]
        with gzip.open(replay_path, "rt", encoding="utf-8") as stream:
            replay = json.load(stream)
        shops = [
            state[0]["observation"]["town"].get("unlocked_shops") or []
            for state in replay["steps"]
        ]
        encoded = json.dumps(shops, separators=(",", ":"), sort_keys=True).encode()
        key = (row["opponent_family"], int(row["seed"]), int(row["seat"]))
        shop_hashes.setdefault(key, set()).add(hashlib.sha256(encoded).hexdigest())

    aggregate = {}
    for arm in ARMS:
        selected = [row for row in games if row["arm"] == arm]
        losses = [float(row["margin"]) for row in selected if not int(row["win"])]
        aggregate[arm] = {
            "games": len(selected),
            "wins": sum(int(row["win"]) for row in selected),
            "mean_margin": mean(float(row["margin"]) for row in selected),
            "lower_margin": min(float(row["margin"]) for row in selected),
            "mean_loss_margin": mean(losses) if losses else 0.0,
            "mean_feed": mean(float(row["successful_feed"]) for row in selected),
            "mean_care": mean(float(row["successful_care"]) for row in selected),
            "mean_animal_exits": mean(float(row["animal_exits"]) for row in selected),
            "mean_unplaced_animals": mean(float(row["unplaced_animals"]) for row in selected),
            "mean_wheat_fertilize": mean(float(row["fertilize_wheat"]) for row in selected),
            "mean_discarded": mean(float(row["discarded_units"]) for row in selected),
        }

    output = {
        "classification": "development panel; reacting public proxy opponents; not final holdout",
        "games": len(games),
        "seeds": sorted({int(row["seed"]) for row in games}),
        "shop_sequences_identical_across_arms": all(len(values) == 1 for values in shop_hashes.values()),
        "aggregate": aggregate,
        "direct_vs_control": direct,
        "trigger_totals": trigger_totals,
    }
    destination = EVAL / "paired_analysis.json"
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
