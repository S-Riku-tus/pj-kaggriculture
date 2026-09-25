"""Paired Round12 analysis; seed is the resampling cluster."""

from __future__ import annotations

import csv
import gzip
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

ROUND12 = Path(__file__).resolve().parents[1]


def read_rows(relative):
    path = ROUND12 / relative / "games.csv"
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        row["seed"] = int(row["seed"])
        row["seat"] = int(row["seat"])
        for key in ("score", "self_cash", "opponent_cash", "margin"):
            row[key] = float(row[key])
    return rows


def key(row):
    return row["opponent"], row["seed"], row["seat"]


def bootstrap_seed_lower(pairs, draws=20000, alpha=0.10):
    by_seed = defaultdict(list)
    for base, candidate in pairs:
        by_seed[base["seed"]].append(candidate["score"] - base["score"])
    seeds = sorted(by_seed)
    seed_means = {seed: sum(values) / len(values) for seed, values in by_seed.items()}
    rng = random.Random(120260925)
    samples = []
    for _ in range(draws):
        picked = [rng.choice(seeds) for _ in seeds]
        samples.append(sum(seed_means[value] for value in picked) / len(picked))
    samples.sort()
    return samples[int(alpha * (len(samples) - 1))]


def paired(rows, baseline, candidate):
    bases = {key(row): row for row in rows if row["arm"] == baseline}
    candidates = {key(row): row for row in rows if row["arm"] == candidate}
    pairs = [(bases[value], candidates[value]) for value in sorted(bases.keys() & candidates.keys())]
    result = {
        "baseline": baseline,
        "candidate": candidate,
        "games": len(pairs),
        "score_delta": sum(b[1]["score"] - b[0]["score"] for b in pairs),
        "mean_self_cash_delta": sum(b[1]["self_cash"] - b[0]["self_cash"] for b in pairs) / len(pairs),
        "mean_opponent_cash_delta": sum(b[1]["opponent_cash"] - b[0]["opponent_cash"] for b in pairs) / len(pairs),
        "mean_margin_delta": sum(b[1]["margin"] - b[0]["margin"] for b in pairs) / len(pairs),
        "w_to_l": sum(b[0]["result"] == "W" and b[1]["result"] == "L" for b in pairs),
        "l_to_w": sum(b[0]["result"] == "L" and b[1]["result"] == "W" for b in pairs),
        "tie_to_loss": sum(b[0]["result"] == "T" and b[1]["result"] == "L" for b in pairs),
        "one_sided_90_seed_bootstrap_lower": bootstrap_seed_lower(pairs),
        "opponents": {},
    }
    for opponent in sorted({base["opponent"] for base, _ in pairs}):
        subset = [(base, cand) for base, cand in pairs if base["opponent"] == opponent]
        result["opponents"][opponent] = {
            "games": len(subset),
            "score_delta": sum(cand["score"] - base["score"] for base, cand in subset),
            "mean_self_cash_delta": sum(cand["self_cash"] - base["self_cash"] for base, cand in subset) / len(subset),
            "mean_margin_delta": sum(cand["margin"] - base["margin"] for base, cand in subset) / len(subset),
        }
    return result


def load_replay(row):
    with gzip.open(ROUND12 / row["replay"], "rt", encoding="utf-8") as stream:
        return json.load(stream)


def final_difference(rows, baseline, candidate):
    bases = {key(row): row for row in rows if row["arm"] == baseline}
    candidates = {key(row): row for row in rows if row["arm"] == candidate}
    action_differences = actual_fill_differences = future_state_differences = 0
    first_steps = []
    telemetry = Counter()
    terminal_deltas = []
    for value in sorted(bases.keys() & candidates.keys()):
        base_row, candidate_row = bases[value], candidates[value]
        base, candidate_replay = load_replay(base_row), load_replay(candidate_row)
        seat = base_row["seat"]
        game_first = None
        for index, (left, right) in enumerate(zip(base["decisions"], candidate_replay["decisions"])):
            if left["actions"][seat] == right["actions"][seat]:
                continue
            action_differences += 1
            game_first = index if game_first is None else game_first
            if index + 1 < len(base["decisions"]):
                left_next = base["decisions"][index + 1]["observations"][seat]
                right_next = candidate_replay["decisions"][index + 1]["observations"][seat]
            else:
                left_next = base["terminal"]["observations"][seat]
                right_next = candidate_replay["terminal"]["observations"][seat]
            left_private = left_next["private"]
            right_private = right_next["private"]
            left_money = left_next["farms"][seat]["money"]
            right_money = right_next["farms"][seat]["money"]
            if left_money != right_money or left_private.get("shed") != right_private.get("shed"):
                actual_fill_differences += 1
            if left_next != right_next:
                future_state_differences += 1
        if game_first is not None:
            first_steps.append({"opponent": value[0], "seed": value[1], "seat": value[2], "step": game_first})
        terminal_deltas.append(candidate_row["self_cash"] - base_row["self_cash"])
        for name, count in candidate_replay.get("agent_telemetry", {}).items():
            if isinstance(count, int):
                telemetry[name] += count
    return {
        "baseline": baseline,
        "candidate": candidate,
        "proposal_generated": telemetry.get("proposal_generated", 0),
        "candidate_different_from_baseline_final": telemetry.get("candidate_different_from_baseline_final", 0),
        "candidate_survived_finalization": telemetry.get("candidate_survived_finalization", 0),
        "paired_replay_action_differences": action_differences,
        "actual_fill_different": actual_fill_differences,
        "future_state_different": future_state_differences,
        "terminal_value_delta_games": sum(value != 0 for value in terminal_deltas),
        "terminal_self_cash_delta_sum": sum(terminal_deltas),
        "first_difference_by_game": first_steps,
        "reason_counts": {name: telemetry.get(name, 0) for name in (
            "redundant_with_baseline", "overwritten_during_finalization", "guard_not_met",
            "invalid_action", "not_filled", "no_value", "undetermined", "selected_wait", "selected_baseline")},
    }


def oracle(rows, arms, baseline):
    grouped = defaultdict(dict)
    for row in rows:
        if row["arm"] in arms:
            grouped[key(row)][row["arm"]] = row
    base_score = oracle_score = 0.0
    choices = Counter()
    for values in grouped.values():
        base_score += values[baseline]["score"]
        best = max(values.values(), key=lambda row: (row["score"], row["margin"], row["self_cash"]))
        oracle_score += best["score"]
        choices[best["arm"]] += 1
    return {
        "future_looking_diagnostic_only": True,
        "games": len(grouped),
        "baseline_score": base_score,
        "oracle_score": oracle_score,
        "oracle_score_delta": oracle_score - base_score,
        "tie_break": "score_then_margin_then_self_cash",
        "chosen_arms": dict(choices),
    }


def main():
    input_rows = read_rows("metrics/input_repairs_development")
    factorial_rows = read_rows("metrics/factorial_development")
    input_analysis = {
        arm: paired(input_rows, "P0M0_B1", arm)
        for arm in ("P0_ledger_only", "P0_censor_only", "P0_ledger_censor", "P0M1_market")
    }
    factorial_analysis = {
        arm: paired(factorial_rows, "P0M0", arm)
        for arm in ("P0M1", "P1M0", "P1M1")
    }
    factorial_analysis["market_effect_with_P1"] = paired(factorial_rows, "P1M0", "P1M1")
    output = {
        "scope": {
            "input_repairs": "40 reactive C++ games on two disclosed Round11 development seeds; not holdout",
            "factorial": "64 reactive C++ games on two new development seeds; not holdout",
            "bootstrap_cluster": "seed; all opponents and both seats remain together",
        },
        "input_repairs": input_analysis,
        "factorial": factorial_analysis,
        "market_final_difference_input_panel": final_difference(input_rows, "P0M0_B1", "P0M1_market"),
        "oracle": oracle(factorial_rows, ("P0M0", "P0M1", "P1M0", "P1M1"), "P0M0"),
    }
    target = ROUND12 / "metrics/round12_paired_analysis.json"
    target.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
