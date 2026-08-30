"""Screen an early, expert-gated Strawberry commitment branch for V101.

This follow-up addresses the support failure of the Day-12+ replenishment
screen.  It intervenes only while Strawberry capacity is still being built,
uses V3's already-trained expert gate to avoid flattening Rank-3 regimes, and
preserves the total productive target by transferring any reduction to Wheat.

The historical test split has already been reported by the preceding screen,
so it is explicitly treated as a confirmation set rather than pristine test.
Runtime promotion still requires new-seed closed-loop diagnostics.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v3 import main as v3  # noqa: E402
from scripts.analyze_v101_residual_portfolio import (  # noqa: E402
    _demand,
    _feature,
    _objective,
    _report,
    _v14_targets,
)
from scripts.train_v12_relative_policy import CACHE_FORMAT  # noqa: E402

FORMAT = "kaggriculture-v101-early-commitment-screen-v1"


def _expert_weights(row: dict[str, Any]) -> dict[str, float]:
    prior = {"rank1": 0.50, "rank2": 0.30, "rank3": 0.20}
    day = int(row["day"])
    if v3.MODEL is None or day < 3:
        return prior
    milk = float(_demand(row, "MILK"))
    wool = float(_demand(row, "WOOL"))
    berry = float(_demand(row, "STRAWBERRY"))
    features = [1.0, day / 29.0, milk / 8.0, wool / 8.0, berry / 8.0, (wool - milk) / 8.0]
    scores = {expert: math.log(weight) for expert, weight in prior.items()}
    for pair_model in (v3.MODEL.get("gate") or {}).get("pair_models", {}).values():
        first = pair_model.get("first")
        second = pair_model.get("second")
        coefficients = pair_model.get("coefficients", [])
        episodes = int(pair_model.get("episodes", 0))
        if first not in scores or second not in scores or len(coefficients) != len(features) or not episodes:
            continue
        value = sum(
            float(coefficient) * feature
            for coefficient, feature in zip(coefficients, features, strict=True)
        )
        probability = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, value))))
        evidence = min(1.0, episodes / 12.0)
        scores[first] += evidence * (probability - 0.5) * 2.0
        scores[second] += evidence * (0.5 - probability) * 2.0
    information = min(1.0, max(0.0, (day - 3) / 7.0))
    maximum = max(scores.values())
    learned = {expert: math.exp((score - maximum) / 0.42) for expert, score in scores.items()}
    total = sum(learned.values())
    learned = {expert: value / total for expert, value in learned.items()}
    mixed = {
        expert: (1.0 - information) * prior[expert] + information * learned[expert]
        for expert in prior
    }
    normalizer = sum(mixed.values())
    return {expert: value / normalizer for expert, value in mixed.items()}


def _candidate_targets(
    row: dict[str, Any],
    baseline: dict[str, float],
    parameters: dict[str, float | int],
) -> tuple[dict[str, float], bool, float]:
    target = dict(baseline)
    day = int(row["day"])
    berry_demand = _demand(row, "STRAWBERRY")
    opponent_berry = _feature(row, "opp_crop_STRAWBERRY", 50.0)
    weights = row.get("_expert_weights") or _expert_weights(row)
    active = bool(
        int(parameters["day_start"]) <= day <= int(parameters["day_end"])
        and berry_demand <= int(parameters["max_demand"])
        and opponent_berry >= float(parameters["opponent_threshold"])
        and float(weights["rank3"]) <= float(parameters["rank3_weight_cap"])
    )
    if not active:
        return target, False, float(baseline["STRAWBERRY"])
    cap = (
        float(parameters["intercept"])
        + float(parameters["demand_slope"]) * berry_demand
        - float(parameters["opponent_slope"])
        * max(0.0, opponent_berry - float(parameters["opponent_threshold"]))
    )
    current = float(row["current"]["STRAWBERRY"])
    selected = max(current, min(float(baseline["STRAWBERRY"]), round(cap)))
    released = max(0.0, float(baseline["STRAWBERRY"]) - selected)
    target["STRAWBERRY"] = selected
    target["WHEAT"] = float(baseline["WHEAT"]) + released * float(
        parameters.get("wheat_transfer", 1.0)
    )
    return target, released > 0.0, cap


def _candidate_report(
    rows: list[dict[str, Any]], parameters: dict[str, float | int]
) -> dict[str, Any]:
    # Reuse the common metric implementation while swapping its candidate
    # function in a narrow, explicit scope.
    from scripts import analyze_v101_residual_portfolio as common

    original = common._candidate_targets
    common._candidate_targets = _candidate_targets
    try:
        return _report(rows, parameters)
    finally:
        common._candidate_targets = original


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rows", type=Path, default=Path("data/training/v12_relative_rows.json")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v101_early_commitment_screen.json"),
    )
    args = parser.parse_args()
    rows_path = args.rows if args.rows.is_absolute() else ROOT / args.rows
    payload = json.loads(rows_path.read_text(encoding="utf-8"))
    if payload.get("format") != CACHE_FORMAT:
        raise ValueError("rebuild the V12 row cache before screening V101")
    rows = [
        row
        for row in payload["rows"]
        if row["winner"]
        and row["source"] in {"rank1", "rank2", "rank3"}
        and 8 <= int(row["day"]) <= 15
    ]
    for row in rows:
        row["_v14_target"] = _v14_targets(row)
        row["_expert_weights"] = _expert_weights(row)
    split_rows = {
        split: [row for row in rows if row["split"] == split]
        for split in ("train", "validation", "test")
    }

    candidates: list[dict[str, float | int]] = []
    for values in itertools.product(
        (8, 9, 10),
        (13, 14, 15),
        (1, 2),
        (16.0, 20.0, 24.0, 28.0),
        (0.25, 0.40, 0.60),
        (14.0, 16.0, 18.0),
        (4.0, 5.0, 6.0),
        (0.0, 0.1, 0.2),
    ):
        candidates.append(
            dict(
                zip(
                    (
                        "day_start",
                        "day_end",
                        "max_demand",
                        "opponent_threshold",
                        "rank3_weight_cap",
                        "intercept",
                        "demand_slope",
                        "opponent_slope",
                    ),
                    values,
                    strict=True,
                )
            )
        )

    scored: list[tuple[tuple[float, float, float], dict[str, float | int], dict[str, Any], dict[str, Any]]] = []
    for parameters in candidates:
        train_report = _candidate_report(split_rows["train"], parameters)
        validation_report = _candidate_report(split_rows["validation"], parameters)
        if (
            train_report["changed_episodes"] < 40
            or validation_report["changed_episodes"] < 12
            or train_report["mean_improvement"] <= 0
            or validation_report["mean_improvement"] <= 0
            or validation_report["p90_error_candidate"] > validation_report["p90_error_base"]
        ):
            continue
        scored.append((_objective(validation_report), parameters, train_report, validation_report))
    if not scored:
        raise RuntimeError("no early commitment branch passed the predeclared support screen")
    scored.sort(key=lambda item: item[0], reverse=True)
    _score, structural_selected, _train_report, _validation_report = scored[0]
    transfer_candidates = []
    for wheat_transfer in (0.0, 0.25, 0.5, 0.75, 1.0):
        parameters = {**structural_selected, "wheat_transfer": wheat_transfer}
        local_train = _candidate_report(split_rows["train"], parameters)
        local_validation = _candidate_report(split_rows["validation"], parameters)
        if local_train["mean_improvement"] > 0 and local_validation["mean_improvement"] > 0:
            transfer_candidates.append(
                (_objective(local_validation), parameters, local_train, local_validation)
            )
    if not transfer_candidates:
        raise RuntimeError("no Wheat transfer fraction retained train/validation support")
    transfer_candidates.sort(key=lambda item: item[0], reverse=True)
    _transfer_score, selected, train_report, validation_report = transfer_candidates[0]
    confirmation_report = _candidate_report(split_rows["test"], selected)
    confirmation_by_source = {
        source: _candidate_report(
            [row for row in split_rows["test"] if row["source"] == source], selected
        )
        for source in ("rank1", "rank2", "rank3")
    }
    result = {
        "format": FORMAT,
        "objective": "Reduce early Strawberry over-commitment without averaging away Rank-3 regimes",
        "row_source": str(rows_path.relative_to(ROOT)),
        "split_discipline": {
            "selection": "train support plus validation mean/lower-tail objective",
            "confirmation": (
                "historical test split, already observed by the preceding distinct screen; "
                "not claimed as pristine"
            ),
            "remaining_required": "new-seed closed-loop and submitted-log domain checks",
        },
        "candidate_count": len(candidates),
        "supported_candidate_count": len(scored),
        "selected": selected,
        "reports": {
            "train": train_report,
            "validation": validation_report,
            "confirmation": confirmation_report,
            "confirmation_by_source": confirmation_by_source,
        },
        "promotion_screen": {
            "validation_mean_improves": validation_report["mean_improvement"] > 0,
            "validation_p90_not_worse": (
                validation_report["p90_error_candidate"] <= validation_report["p90_error_base"]
            ),
            "confirmation_mean_improves": confirmation_report["mean_improvement"] > 0,
            "confirmation_p90_not_worse": (
                confirmation_report["p90_error_candidate"] <= confirmation_report["p90_error_base"]
            ),
            "all_confirmation_sources_nonnegative": all(
                report["mean_improvement"] >= -1e-12 for report in confirmation_by_source.values()
            ),
        },
        "limits": [
            "future-state target fidelity is not a causal reward estimate",
            "the historical test split is no longer pristine after the preceding screen",
            "the V3 expert gate was trained previously and is not refit here",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "selected": selected,
                "train": train_report,
                "validation": validation_report,
                "confirmation": confirmation_report,
                "confirmation_by_source": confirmation_by_source,
                "promotion_screen": result["promotion_screen"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"result: {output}")


if __name__ == "__main__":
    main()
