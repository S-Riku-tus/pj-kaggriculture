"""Paired score analysis for a completed reactive Round13 panel."""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter, defaultdict
from pathlib import Path


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def normalized_execution(row: dict) -> tuple[bool, str]:
    telemetry = json.loads(row["telemetry_json"])
    metrics = json.loads(row["route_metrics_json"])
    arm = row["arm"]
    if arm == "D0_B1":
        return True, "BASELINE_COMPLETE"
    if arm == "M1_deadline_market":
        created = int(telemetry.get("market_reservations_created", 0))
        filled = int(telemetry.get("market_reservations_filled", 0))
        if created == 0:
            return True, "NOT_TRIGGERED"
        return created == filled, "DEADLINES_FILLED" if created == filled else "DEADLINE_UNFILLED"
    if arm == "P_EARLY4":
        started = int(telemetry.get("early_started", 0))
        if started == 0:
            return False, "START_PRECONDITION_FAILED"
        first = metrics.get("first_plant_day", {}).get("STRAWBERRY")
        sold = int(metrics.get("sold_units", {}).get("STRAWBERRY", 0)) > 0
        complete = int(telemetry.get("early_plants", 0)) >= 4 and first is not None and int(first) <= 3 and sold
        return complete, "EARLY4_SOLD" if complete else "EARLY4_INCOMPLETE"
    if arm == "P_ROTATE2":
        started = int(telemetry.get("rotate_started", 0))
        if started == 0:
            return True, "NOT_TRIGGERED"
        converted = int(telemetry.get("rotate_digs", 0)) >= 2 and int(telemetry.get("rotate_plants", 0)) >= 2
        return converted, "ROTATE2_CONVERTED" if converted else "ROTATE2_INCOMPLETE"
    return False, "UNKNOWN_ARM"


def bootstrap_seed_ci(pairs: list[dict], draws: int = 10000) -> list[float]:
    by_seed: dict[int, list[float]] = defaultdict(list)
    for row in pairs:
        by_seed[int(row["seed"])].append(float(row["delta_score"]))
    seed_means = [mean(values) for _seed, values in sorted(by_seed.items())]
    rng = random.Random(130925)
    estimates = []
    for _ in range(draws):
        sample = [rng.choice(seed_means) for _ in seed_means]
        estimates.append(mean(sample))
    return [percentile(estimates, 0.025), percentile(estimates, 0.975)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("games", type=Path)
    parser.add_argument("--baseline", default="D0_B1")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.games.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    config = json.loads((args.games.parent / "config.json").read_text(encoding="utf-8"))
    thresholds = config["promotion_thresholds_preregistered"]
    keyed = {(row["arm"], row["opponent"], int(row["seed"]), int(row["seat"])): row for row in rows}
    baseline = {
        (row["opponent"], int(row["seed"]), int(row["seat"])): row
        for row in rows
        if row["arm"] == args.baseline
    }
    pairs = []
    for row in rows:
        if row["arm"] == args.baseline:
            continue
        key = (row["opponent"], int(row["seed"]), int(row["seat"]))
        base = baseline[key]
        candidate_result, baseline_result = row["result"], base["result"]
        valid, completion = normalized_execution(row)
        pairs.append(
            {
                "arm": row["arm"],
                "opponent": row["opponent"],
                "family": row["family"],
                "seed": int(row["seed"]),
                "seat": int(row["seat"]),
                "baseline_result": baseline_result,
                "candidate_result": candidate_result,
                "baseline_score": float(base["score"]),
                "candidate_score": float(row["score"]),
                "baseline_self_cash": float(base["self_cash"]),
                "candidate_self_cash": float(row["self_cash"]),
                "baseline_opp_cash": float(base["opponent_cash"]),
                "candidate_opp_cash": float(row["opponent_cash"]),
                "delta_score": float(row["score"]) - float(base["score"]),
                "delta_self": float(row["self_cash"]) - float(base["self_cash"]),
                "delta_opp": float(row["opponent_cash"]) - float(base["opponent_cash"]),
                "delta_margin": float(row["margin"]) - float(base["margin"]),
                "execution_valid": valid,
                "completion_status": completion,
                "fullgame_followup": True,
                "transition": f"{baseline_result}->{candidate_result}",
                "candidate_replay": row["replay"],
                "baseline_replay": base["replay"],
            }
        )
    summaries = []
    for arm in config["arms"]:
        if arm == args.baseline:
            continue
        selected = [row for row in pairs if row["arm"] == arm]
        family_rows: dict[str, list[dict]] = defaultdict(list)
        for row in selected:
            family_rows[row["family"]].append(row)
        family = {
            name: {
                "games": len(values),
                "condition_weight": len(values) / len(selected),
                "mean_delta_score": mean([float(row["delta_score"]) for row in values]),
                "mean_delta_self": mean([float(row["delta_self"]) for row in values]),
                "mean_delta_opp": mean([float(row["delta_opp"]) for row in values]),
                "mean_delta_margin": mean([float(row["delta_margin"]) for row in values]),
            }
            for name, values in sorted(family_rows.items())
        }
        overall = mean([float(row["delta_score"]) for row in selected])
        triggered = [row for row in selected if row["completion_status"] != "NOT_TRIGGERED"]
        family_minimum = min(value["mean_delta_score"] for value in family.values())
        all_valid = all(bool(row["execution_valid"]) for row in selected)
        clears = (
            overall >= float(thresholds["practical_minimum_paired_score_gain"])
            and family_minimum >= float(thresholds["allowed_major_family_score_degradation"])
            and all_valid
        )
        summaries.append(
            {
                "arm": arm,
                "games": len(selected),
                "baseline_wdl": dict(sorted(Counter(row["baseline_result"] for row in selected).items())),
                "candidate_wdl": dict(sorted(Counter(row["candidate_result"] for row in selected).items())),
                "baseline_mean_score": mean([float(row["baseline_score"]) for row in selected]),
                "candidate_mean_score": mean([float(row["candidate_score"]) for row in selected]),
                "paired_score_delta": overall,
                "equal_family_weighted_score_delta": mean(
                    [float(value["mean_delta_score"]) for value in family.values()]
                ),
                "seed_bootstrap_95pct": bootstrap_seed_ci(selected),
                "baseline_mean_self_cash": mean([float(row["baseline_self_cash"]) for row in selected]),
                "candidate_mean_self_cash": mean([float(row["candidate_self_cash"]) for row in selected]),
                "baseline_mean_opp_cash": mean([float(row["baseline_opp_cash"]) for row in selected]),
                "candidate_mean_opp_cash": mean([float(row["candidate_opp_cash"]) for row in selected]),
                "mean_delta_self": mean([float(row["delta_self"]) for row in selected]),
                "mean_delta_opp": mean([float(row["delta_opp"]) for row in selected]),
                "mean_delta_margin": mean([float(row["delta_margin"]) for row in selected]),
                "transitions": dict(sorted(Counter(row["transition"] for row in selected).items())),
                "execution_valid_games": sum(bool(row["execution_valid"]) for row in selected),
                "completion_statuses": dict(sorted(Counter(row["completion_status"] for row in selected).items())),
                "triggered_games": len(triggered),
                "triggered_mean_delta_score": mean([float(row["delta_score"]) for row in triggered]),
                "triggered_mean_delta_self": mean([float(row["delta_self"]) for row in triggered]),
                "triggered_mean_delta_opp": mean([float(row["delta_opp"]) for row in triggered]),
                "triggered_mean_delta_margin": mean([float(row["delta_margin"]) for row in triggered]),
                "families": family,
                "development_gate_pass": clears,
                "status": "HOLDOUT_ELIGIBLE" if clears else "RESEARCH_ONLY",
            }
        )
    output = {
        "evaluation_mode": config["evaluation_mode"],
        "baseline": args.baseline,
        "games": len(rows),
        "paired_rows": len(pairs),
        "thresholds_preregistered": thresholds,
        "summaries": summaries,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paired_path = args.output.with_name("paired_rows.csv")
    with paired_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(pairs[0]))
        writer.writeheader()
        writer.writerows(pairs)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
