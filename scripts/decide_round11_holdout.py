"""Apply the frozen Round11 M20 holdout gates without changing thresholds."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = "m20_multi_hypothesis"


def score(result: str) -> float:
    return 1.0 if result == "W" else 0.5 if result == "T" else 0.0


def flattened_numbers(value: object, prefix: str = "") -> dict[str, float]:
    result: dict[str, float] = {}
    if not isinstance(value, dict):
        return result
    for key, child in value.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(child, dict):
            result.update(flattened_numbers(child, name))
        elif isinstance(child, (int, float)) and not isinstance(child, bool):
            result[name] = float(child)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("panel", type=Path)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--parity", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    panel = args.panel if args.panel.is_absolute() else ROOT / args.panel
    protocol_path = args.protocol if args.protocol.is_absolute() else ROOT / args.protocol
    parity_path = args.parity if args.parity.is_absolute() else ROOT / args.parity
    output_path = args.output if args.output.is_absolute() else ROOT / args.output
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    parity = json.loads(parity_path.read_text(encoding="utf-8"))
    with (panel / "games.csv").open(encoding="utf-8-sig", newline="") as handle:
        games = list(csv.DictReader(handle))
    with (panel / "paired_results.csv").open(encoding="utf-8-sig", newline="") as handle:
        pairs = [row for row in csv.DictReader(handle) if row["arm"] == CANDIDATE]

    expected_games = int(protocol["evaluation"]["planned_cells"])
    candidate_hash = protocol["candidate_sha256"]
    game_keys = {(row["arm"], row["opponent_id"], row["seed"], row["seat"]) for row in games}
    replay_lengths_ok = True
    order_caps_ok = True
    for row in games:
        try:
            with gzip.open(ROOT / row["replay"], "rt", encoding="utf-8") as handle:
                replay = json.load(handle)
            decisions = replay.get("decisions") or []
            replay_lengths_ok &= len(decisions) == 719 and len(replay.get("rewards") or []) == 2
            for decision in decisions:
                for action in decision.get("actions", []):
                    order_caps_ok &= len(action.get("market") or []) <= 10
        except Exception:
            replay_lengths_ok = False

    totals = defaultdict(float)
    for row in games:
        totals[row["arm"]] += score(row["result"])
    primary_delta = totals[CANDIDATE] - totals["B1"]
    by_opponent: dict[str, float] = defaultdict(float)
    by_seed_values: dict[int, list[float]] = defaultdict(list)
    for row in pairs:
        delta = float(row["delta_points"])
        by_opponent[row["opponent_id"]] += delta
        by_seed_values[int(row["seed"])].append(delta)
    cluster_means = [statistics.mean(values) for _, values in sorted(by_seed_values.items())]
    rng = random.Random(20260924)
    bootstrap = []
    for _ in range(100_000):
        bootstrap.append(statistics.mean(rng.choices(cluster_means, k=len(cluster_means))))
    bootstrap.sort()
    lower_90 = bootstrap[int(0.10 * (len(bootstrap) - 1))]

    diagnostics_errors = 0.0
    forecast_fires = 0.0
    frozen_hashes_ok = True
    for row in games:
        if row["arm"] != CANDIDATE:
            continue
        frozen_hashes_ok &= row["agent_sha256"] == candidate_hash
        flat = flattened_numbers(json.loads(row.get("diagnostics_json") or "{}"))
        diagnostics_errors += sum(
            value for key, value in flat.items() if key.endswith("errors") or key.endswith("pred_errors")
        )
        forecast_fires += flat.get("parent.forecast.frontier_fires", 0.0)

    transitions = defaultdict(int)
    for row in pairs:
        transitions[f"{row['baseline_result']}->{row['candidate_result']}"] += 1
    mean_margin_delta = statistics.mean(float(row["delta_margin"]) for row in pairs)
    min_margin_delta = min(float(row["delta_margin"]) for row in pairs)
    changed_actions = sum(int(row["own_action_changed_decisions"]) for row in pairs)

    gates = {
        "coverage": len(games) == expected_games
        and len(game_keys) == expected_games
        and not any(row.get("error") for row in games)
        and replay_lengths_ok
        and order_caps_ok
        and frozen_hashes_ok,
        "primary": primary_delta > 0,
        "cluster_uncertainty": lower_90 >= 0,
        "opponent_guardrail": all(delta >= -1.0 for delta in by_opponent.values()),
        "margin_guardrail": mean_margin_delta > -250,
        "large_regression_guardrail": min_margin_delta > -5000,
        "transition_guardrail": transitions.get("W->L", 0) <= 2,
        "effective_change": changed_actions > 0 and forecast_fires > 0 and diagnostics_errors == 0,
        "official_parity_precondition": parity.get("all_exact") is True,
    }
    result = {
        "schema": "round11-holdout-decision-v1",
        "protocol": protocol_path.relative_to(ROOT).as_posix(),
        "candidate": CANDIDATE,
        "candidate_sha256": candidate_hash,
        "decision": "ACCEPT" if all(gates.values()) else "REJECT",
        "gates": gates,
        "metrics": {
            "games": len(games),
            "paired_candidate_games": len(pairs),
            "seed_clusters": len(cluster_means),
            "baseline_points": totals["B1"],
            "candidate_points": totals[CANDIDATE],
            "candidate_minus_baseline_points": primary_delta,
            "mean_paired_point_delta": statistics.mean(float(row["delta_points"]) for row in pairs),
            "seed_cluster_mean_point_delta": statistics.mean(cluster_means),
            "one_sided_90pct_bootstrap_lower": lower_90,
            "bootstrap_draws": len(bootstrap),
            "paired_points_by_opponent": dict(sorted(by_opponent.items())),
            "mean_paired_margin_delta": mean_margin_delta,
            "minimum_paired_margin_delta": min_margin_delta,
            "transitions": dict(sorted(transitions.items())),
            "changed_final_action_decisions": changed_actions,
            "alternate_forecast_fires": forecast_fires,
            "policy_errors": diagnostics_errors,
            "replay_lengths_ok": replay_lengths_ok,
            "order_caps_ok": order_caps_ok,
            "frozen_hashes_ok": frozen_hashes_ok,
        },
        "limitations": [
            "Opponent families are public-source relatives and are not independent samples.",
            "The interval resamples 24 world-seed clusters, not 192 individual games.",
            "This local result is not a public-rating or 2500/3000 forecast.",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["decision"] != "ACCEPT":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
