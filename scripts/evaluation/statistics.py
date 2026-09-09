"""Lineage-aware paired statistics and diagnostic Bradley-Terry fit."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Callable
from statistics import mean
from typing import Any


def _average(values: list[float]) -> float:
    return mean(values) if values else 0.0


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _outcome(row: dict[str, Any], arm: str) -> float:
    return float(row[arm]["score"])


def _strict_win(row: dict[str, Any], arm: str) -> float:
    return float(row[arm]["result"] == "win")


def _seed_groups(rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        result[int(row["seed"])].append(row)
    return dict(result)


def _lineage_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_wins = sum(row["control"]["result"] == "win" for row in rows)
    candidate_wins = sum(row["treatment"]["result"] == "win" for row in rows)
    loss_to_win = sum(
        row["control"]["result"] == "loss" and row["treatment"]["result"] == "win"
        for row in rows
    )
    win_to_loss = sum(
        row["control"]["result"] == "win" and row["treatment"]["result"] == "loss"
        for row in rows
    )
    return {
        "pairs": len(rows),
        "independent_seeds": len({int(row["seed"]) for row in rows}),
        "baseline": {
            "wins": baseline_wins,
            "draws": sum(row["control"]["result"] == "draw" for row in rows),
            "losses": sum(row["control"]["result"] == "loss" for row in rows),
            "win_rate": baseline_wins / len(rows) if rows else 0.0,
            "win_score": _average([_outcome(row, "control") for row in rows]),
        },
        "candidate": {
            "wins": candidate_wins,
            "draws": sum(row["treatment"]["result"] == "draw" for row in rows),
            "losses": sum(row["treatment"]["result"] == "loss" for row in rows),
            "win_rate": candidate_wins / len(rows) if rows else 0.0,
            "win_score": _average([_outcome(row, "treatment") for row in rows]),
        },
        "delta_win_rate": _average(
            [_strict_win(row, "treatment") - _strict_win(row, "control") for row in rows]
        ),
        "delta_win_score": _average(
            [_outcome(row, "treatment") - _outcome(row, "control") for row in rows]
        ),
        "loss_to_win": loss_to_win,
        "win_to_loss": win_to_loss,
        "discordant_net": loss_to_win - win_to_loss,
        "score_improved": sum(_outcome(row, "treatment") > _outcome(row, "control") for row in rows),
        "score_worsened": sum(_outcome(row, "treatment") < _outcome(row, "control") for row in rows),
        "both_draw": sum(
            row["control"]["result"] == "draw" and row["treatment"]["result"] == "draw"
            for row in rows
        ),
        "mean_delta_self_coin": _average([float(row["delta_self_coin"]) for row in rows]),
        "mean_delta_opponent_coin": _average([float(row["delta_opponent_coin"]) for row in rows]),
        "mean_delta_margin": _average([float(row["delta_margin"]) for row in rows]),
        "trigger_requests": sum(bool(row.get("gate_requested")) for row in rows),
        "incremental_treatments": sum(bool(row.get("incremental_treatment")) for row in rows),
    }


def summarize_pairs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Public paired summary used for global and trigger-conditional effects."""
    return _lineage_summary(rows)


def _bootstrap_lineage_ci(
    rows: list[dict[str, Any]],
    metric: Callable[[dict[str, Any]], float],
    repetitions: int,
    rng: random.Random,
) -> dict[str, float | None]:
    seeds = _seed_groups(rows)
    ids = sorted(seeds)
    estimates: list[float] = []
    for _ in range(repetitions):
        sampled = rng.choices(ids, k=len(ids))
        values = [metric(row) for seed in sampled for row in seeds[seed]]
        estimates.append(_average(values))
    return {
        "estimate": _average([metric(row) for row in rows]),
        "low_95": _quantile(estimates, 0.025),
        "high_95": _quantile(estimates, 0.975),
    }


def pairwise_payoff_matrix(
    rows: list[dict[str, Any]], repetitions: int, bootstrap_seed: int
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["lineage_id"])].append(row)
    result = []
    for index, lineage in enumerate(sorted(grouped)):
        selected = grouped[lineage]
        summary = _lineage_summary(selected)
        summary["lineage_id"] = lineage
        summary["meta_weight"] = float(selected[0]["meta_weight"])
        summary["delta_win_score_ci"] = _bootstrap_lineage_ci(
            selected,
            lambda row: _outcome(row, "treatment") - _outcome(row, "control"),
            repetitions,
            random.Random(bootstrap_seed + index * 7919),
        )
        result.append(summary)
    return result


def _hierarchical_draw(
    grouped: dict[str, dict[int, list[dict[str, Any]]]],
    lineage_weights: dict[str, float],
    rng: random.Random,
    metric: Callable[[dict[str, Any]], float],
    *,
    macro: bool,
) -> float:
    lineages = sorted(grouped)
    probabilities = None if macro else [lineage_weights[name] for name in lineages]
    sampled_lineages = rng.choices(lineages, weights=probabilities, k=len(lineages))
    lineage_values = []
    for lineage in sampled_lineages:
        seed_groups = grouped[lineage]
        seed_ids = sorted(seed_groups)
        sampled_seeds = rng.choices(seed_ids, k=len(seed_ids))
        seed_values = [
            _average([metric(row) for row in seed_groups[seed]]) for seed in sampled_seeds
        ]
        lineage_values.append(_average(seed_values))
    return _average(lineage_values)


def hierarchical_bootstrap(
    rows: list[dict[str, Any]],
    lineage_weights: dict[str, float],
    repetitions: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    grouped_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped_rows[str(row["lineage_id"])].append(row)
    grouped = {
        lineage: _seed_groups(selected) for lineage, selected in grouped_rows.items()
    }
    lineage_delta = {
        lineage: _average(
            [_outcome(row, "treatment") - _outcome(row, "control") for row in selected]
        )
        for lineage, selected in grouped_rows.items()
    }
    lineage_control = {
        lineage: _average([_outcome(row, "control") for row in selected])
        for lineage, selected in grouped_rows.items()
    }
    lineage_treatment = {
        lineage: _average([_outcome(row, "treatment") for row in selected])
        for lineage, selected in grouped_rows.items()
    }
    estimates: dict[str, list[float]] = {
        "meta_delta": [],
        "macro_delta": [],
        "meta_control": [],
        "meta_treatment": [],
        "macro_control": [],
        "macro_treatment": [],
    }
    rng = random.Random(bootstrap_seed)
    for _ in range(repetitions):
        for label, metric, macro in (
            ("meta_delta", lambda row: _outcome(row, "treatment") - _outcome(row, "control"), False),
            ("macro_delta", lambda row: _outcome(row, "treatment") - _outcome(row, "control"), True),
            ("meta_control", lambda row: _outcome(row, "control"), False),
            ("meta_treatment", lambda row: _outcome(row, "treatment"), False),
            ("macro_control", lambda row: _outcome(row, "control"), True),
            ("macro_treatment", lambda row: _outcome(row, "treatment"), True),
        ):
            estimates[label].append(
                _hierarchical_draw(grouped, lineage_weights, rng, metric, macro=macro)
            )
    point = {
        "meta_delta": sum(lineage_weights[key] * lineage_delta[key] for key in lineage_delta),
        "macro_delta": _average(list(lineage_delta.values())),
        "meta_control": sum(lineage_weights[key] * lineage_control[key] for key in lineage_control),
        "meta_treatment": sum(lineage_weights[key] * lineage_treatment[key] for key in lineage_treatment),
        "macro_control": _average(list(lineage_control.values())),
        "macro_treatment": _average(list(lineage_treatment.values())),
    }
    return {
        "method": "hierarchical cluster bootstrap: executable lineage -> seed cluster (both seats retained)",
        "independent_lineages": len(grouped),
        "repetitions": repetitions,
        **{
            key: {
                "estimate": point[key],
                "low_95": _quantile(values, 0.025),
                "high_95": _quantile(values, 0.975),
            }
            for key, values in estimates.items()
        },
    }


def meta_scenarios(weights: dict[str, float], radius: float) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = [{"name": "current", "weights": dict(weights)}]
    for lineage in sorted(weights):
        current = weights[lineage]
        for direction, target in (
            ("up", min(1.0, current + radius)),
            ("down", max(0.0, current - radius)),
        ):
            remaining_old = 1.0 - current
            remaining_new = 1.0 - target
            scenario = {}
            for other, value in weights.items():
                if other == lineage:
                    scenario[other] = target
                elif remaining_old > 0:
                    scenario[other] = value * remaining_new / remaining_old
                else:
                    scenario[other] = remaining_new / max(1, len(weights) - 1)
            result.append({"name": f"{lineage}_{direction}_{radius:.3f}", "weights": scenario})
    return result


def robust_meta(
    matrix: list[dict[str, Any]], weights: dict[str, float], radius: float
) -> dict[str, Any]:
    by_lineage = {str(row["lineage_id"]): row for row in matrix}
    rows = []
    for scenario in meta_scenarios(weights, radius):
        scenario_weights = scenario["weights"]
        baseline = sum(
            scenario_weights[key] * float(by_lineage[key]["baseline"]["win_score"])
            for key in scenario_weights
        )
        candidate = sum(
            scenario_weights[key] * float(by_lineage[key]["candidate"]["win_score"])
            for key in scenario_weights
        )
        rows.append(
            {
                "name": scenario["name"],
                "weights": scenario_weights,
                "baseline_win_score": baseline,
                "candidate_win_score": candidate,
                "delta": candidate - baseline,
            }
        )
    worst_delta = min(rows, key=lambda row: float(row["delta"]))
    return {
        "weight_radius": radius,
        "scenarios": rows,
        "robust_baseline_win_score": min(float(row["baseline_win_score"]) for row in rows),
        "robust_candidate_win_score": min(float(row["candidate_win_score"]) for row in rows),
        "worst_delta": float(worst_delta["delta"]),
        "worst_delta_scenario": worst_delta["name"],
    }


def _sigmoid(value: float) -> float:
    if value >= 0:
        decay = math.exp(-value)
        return 1.0 / (1.0 + decay)
    growth = math.exp(value)
    return growth / (1.0 + growth)


def bradley_terry_diagnostic(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Fit Candidate ability and one opponent intercept per lineage.

    Baseline ability is fixed to zero. Draws contribute a half outcome. This is
    intentionally diagnostic: the pairwise matrix remains authoritative.
    """
    lineages = sorted({str(row["lineage_id"]) for row in rows})
    opponent_ability = {lineage: 0.0 for lineage in lineages}
    candidate_ability = 0.0
    ridge = 1e-6
    for _ in range(200):
        old = candidate_ability
        gradient = -ridge * candidate_ability
        curvature = ridge
        for row in rows:
            lineage = str(row["lineage_id"])
            probability = _sigmoid(candidate_ability - opponent_ability[lineage])
            gradient += _outcome(row, "treatment") - probability
            curvature += probability * (1.0 - probability)
        candidate_ability += gradient / max(curvature, 1e-12)
        for lineage in lineages:
            gradient = -ridge * opponent_ability[lineage]
            curvature = ridge
            selected = [row for row in rows if str(row["lineage_id"]) == lineage]
            for row in selected:
                for arm, ability in (("control", 0.0), ("treatment", candidate_ability)):
                    probability = _sigmoid(ability - opponent_ability[lineage])
                    gradient += probability - _outcome(row, arm)
                    curvature += probability * (1.0 - probability)
            opponent_ability[lineage] += gradient / max(curvature, 1e-12)
        if abs(candidate_ability - old) < 1e-10:
            break
    information = ridge + sum(
        (lambda probability: probability * (1.0 - probability))(
            _sigmoid(candidate_ability - opponent_ability[str(row["lineage_id"])])
        )
        for row in rows
    )
    standard_error = math.sqrt(1.0 / information)
    return {
        "model": "Bradley-Terry/logistic with baseline ability fixed at 0 and lineage intercepts",
        "candidate_minus_baseline_ability": candidate_ability,
        "approx_standard_error": standard_error,
        "approx_95_interval": [
            candidate_ability - 1.96 * standard_error,
            candidate_ability + 1.96 * standard_error,
        ],
        "opponent_abilities": opponent_ability,
        "warning": "diagnostic only; non-transitive matchups require the pairwise payoff matrix",
    }
