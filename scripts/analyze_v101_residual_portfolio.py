"""Select and test a bounded opponent-congestion crop branch for V101.

The candidate never changes live assets or herd decisions.  It only lowers a
future Strawberry replenishment target in the midgame when public evidence
indicates weak residual demand, then transfers the released target capacity to
Wheat.  Parameters are selected on the episode-disjoint validation split; the
test split is report-only.

This is a future-state fidelity screen, not a causal rating estimate.  Closed
loop diagnostics remain mandatory before runtime promotion.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v3.feature_schema import FEATURE_NAMES  # noqa: E402
from agents.v14 import main as v14  # noqa: E402
from scripts.train_v12_relative_policy import CACHE_FORMAT, PORTFOLIO  # noqa: E402

FORMAT = "kaggriculture-v101-residual-portfolio-screen-v1"
CROPS = PORTFOLIO[:5]
SCALES = {"WHEAT": 30.0, "STRAWBERRY": 30.0}
IMPORTANCE = {"WHEAT": 1.0, "STRAWBERRY": 1.6}


def _feature(row: dict[str, Any], name: str, scale: float = 1.0) -> float:
    return float(row["features"][FEATURE_NAMES.index(name)]) * scale


def _demand(row: dict[str, Any], item: str) -> int:
    return int(round(_feature(row, f"demand_{item}", 8.0)))


def _v14_targets(row: dict[str, Any]) -> dict[str, float]:
    """Reconstruct V14's logged-state target closely enough for screening."""
    baseline = {item: float(row["baseline"][item]) for item in PORTFOLIO}
    day = int(row["day"])
    if not 6 <= day <= 27 or float(row["money_gap_ratio"]) >= 0:
        return baseline

    features = [float(value) for value in row["features"]]
    manifold_confidence, _distance = v14._distance_confidence(features, day)
    if manifold_confidence <= 0.0 or v14.WINNER_MODEL is None:
        return baseline
    means, deviations = v14._predict_forest(v14.WINNER_MODEL["forests"]["h72"], features)
    scales = [max(1.0, float(value)) for value in v14.WINNER_MODEL["target_scales"]]
    uncertainty = sum(
        deviation / scale for deviation, scale in zip(deviations, scales, strict=True)
    ) / len(scales)
    reference = max(0.05, float(v14.WINNER_MODEL["uncertainty_p90"]["h72"]))
    model_confidence = min(1.0, max(0.0, 1.15 - 0.50 * uncertainty / reference))
    confidence = manifold_confidence * model_confidence
    if uncertainty > reference or confidence < v14.MIN_CONFIDENCE:
        return baseline

    blend = min(v14.MAX_BLEND, 0.15 + 0.20 * confidence)
    current = {item: float(row["current"][item]) for item in PORTFOLIO}
    target = dict(baseline)
    for index, crop in enumerate(CROPS):
        mixed = round((1.0 - blend) * baseline[crop] + blend * means[index])
        limit = v14.CROP_CHANGE_LIMIT[crop]
        limited = min(baseline[crop] + limit, max(baseline[crop] - limit, mixed))
        target[crop] = max(current[crop], float(limited))

    feed_floor = math.ceil((baseline["COW"] + baseline["SHEEP"]) * 1.2)
    target["WHEAT"] = max(target["WHEAT"], float(feed_floor))
    floors = {item: current[item] for item in PORTFOLIO}
    floors["WHEAT"] = max(floors["WHEAT"], float(feed_floor))
    budget = max(sum(baseline.values()), sum(floors.values()))
    item_demand = {
        crop: _demand(row, v14.ITEM_DEMAND[crop])
        for crop in CROPS
    }
    while sum(target.values()) > budget + 1e-9:
        reducible = [crop for crop in CROPS if target[crop] > floors[crop]]
        if not reducible:
            break
        crop = min(
            reducible,
            key=lambda value: (
                item_demand[value],
                int(v14.base.BASE_PRICE[v14.ITEM_DEMAND[value]]),
                -(target[value] - floors[value]),
                PORTFOLIO.index(value),
            ),
        )
        target[crop] -= 1.0
    if sum(target.values()) < budget:
        target["WHEAT"] += budget - sum(target.values())
    return target


def _candidate_targets(
    row: dict[str, Any],
    baseline: dict[str, float],
    parameters: dict[str, float | int],
) -> tuple[dict[str, float], bool, float]:
    target = dict(baseline)
    day = int(row["day"])
    berry_demand = _demand(row, "STRAWBERRY")
    opponent_berry = _feature(row, "opp_crop_STRAWBERRY", 50.0)
    price_ratio = _feature(row, "price_STRAWBERRY")
    active = bool(
        int(parameters["day_start"]) <= day <= int(parameters["day_end"])
        and berry_demand <= int(parameters["max_demand"])
        and opponent_berry >= float(parameters["opponent_threshold"])
        and price_ratio <= float(parameters["price_cap"])
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
    target["WHEAT"] = float(baseline["WHEAT"]) + released
    return target, released > 0.0, cap


def _quantile(values: list[float], probability: float) -> float:
    return float(np.quantile(np.asarray(values, dtype=np.float64), probability)) if values else 0.0


def _report(
    rows: list[dict[str, Any]],
    parameters: dict[str, float | int] | None,
) -> dict[str, Any]:
    base_errors: list[float] = []
    candidate_errors: list[float] = []
    base_item_errors: dict[str, list[float]] = {item: [] for item in SCALES}
    candidate_item_errors: dict[str, list[float]] = {item: [] for item in SCALES}
    changes: list[float] = []
    changed_rows = 0
    changed_episodes: set[str] = set()
    by_source: dict[str, list[float]] = {}
    for row in rows:
        baseline = row.get("_v14_target") or _v14_targets(row)
        candidate, changed, _cap = (
            _candidate_targets(row, baseline, parameters)
            if parameters is not None
            else (baseline, False, baseline["STRAWBERRY"])
        )
        actual = row["h72"]
        base_vector = []
        candidate_vector = []
        for item in SCALES:
            base_error = abs(float(baseline[item]) - float(actual[item]))
            candidate_error = abs(float(candidate[item]) - float(actual[item]))
            base_item_errors[item].append(base_error)
            candidate_item_errors[item].append(candidate_error)
            base_vector.append(base_error / SCALES[item] * IMPORTANCE[item])
            candidate_vector.append(candidate_error / SCALES[item] * IMPORTANCE[item])
        base_errors.append(sum(base_vector) / len(base_vector))
        candidate_errors.append(sum(candidate_vector) / len(candidate_vector))
        if changed:
            changed_rows += 1
            changed_episodes.add(str(row["episode_id"]))
            changes.append(float(baseline["STRAWBERRY"]) - float(candidate["STRAWBERRY"]))
        by_source.setdefault(str(row["source"]), []).append(candidate_errors[-1] - base_errors[-1])

    improvement = [base - candidate for base, candidate in zip(base_errors, candidate_errors, strict=True)]
    return {
        "rows": len(rows),
        "episodes": len({str(row["episode_id"]) for row in rows}),
        "changed_rows": changed_rows,
        "changed_episodes": len(changed_episodes),
        "coverage": changed_rows / len(rows) if rows else 0.0,
        "mean_target_reduction": float(np.mean(changes)) if changes else 0.0,
        "base_normalized_mae": float(np.mean(base_errors)) if base_errors else 0.0,
        "candidate_normalized_mae": float(np.mean(candidate_errors)) if candidate_errors else 0.0,
        "mean_improvement": float(np.mean(improvement)) if improvement else 0.0,
        "p10_improvement": _quantile(improvement, 0.10),
        "p50_improvement": _quantile(improvement, 0.50),
        "p90_error_base": _quantile(base_errors, 0.90),
        "p90_error_candidate": _quantile(candidate_errors, 0.90),
        "item_mae": {
            item: {
                "base": float(np.mean(base_item_errors[item])) if rows else 0.0,
                "candidate": float(np.mean(candidate_item_errors[item])) if rows else 0.0,
            }
            for item in SCALES
        },
        "mean_delta_by_source": {
            source: float(np.mean(values)) for source, values in sorted(by_source.items())
        },
    }


def _objective(report: dict[str, Any]) -> tuple[float, float, float]:
    # Prefer mean fidelity, then the lower tail and sparse interventions.
    return (
        float(report["mean_improvement"]),
        float(report["p10_improvement"]),
        -float(report["coverage"]),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rows", type=Path, default=Path("data/training/v12_relative_rows.json")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v101_residual_portfolio_screen.json"),
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
        and 12 <= int(row["day"]) <= 20
    ]
    for row in rows:
        row["_v14_target"] = _v14_targets(row)
    split_rows = {
        split: [row for row in rows if row["split"] == split]
        for split in ("train", "validation", "test")
    }

    candidates: list[dict[str, float | int]] = []
    for values in itertools.product(
        (12, 14),  # day_start
        (18, 20),  # day_end
        (1, 2, 3),  # max_demand
        (24.0, 28.0, 32.0, 36.0),  # opponent_threshold
        (0.85, 1.0, 1.15),  # price_cap as ratio to base
        (14.0, 16.0, 18.0),  # intercept
        (4.0, 5.0, 6.0),  # demand_slope
        (0.1, 0.2, 0.3, 0.4),  # opponent_slope
    ):
        parameters = dict(
            zip(
                (
                    "day_start",
                    "day_end",
                    "max_demand",
                    "opponent_threshold",
                    "price_cap",
                    "intercept",
                    "demand_slope",
                    "opponent_slope",
                ),
                values,
                strict=True,
            )
        )
        candidates.append(parameters)

    scored: list[tuple[tuple[float, float, float], dict[str, float | int], dict[str, Any], dict[str, Any]]] = []
    for index, parameters in enumerate(candidates, start=1):
        train_report = _report(split_rows["train"], parameters)
        validation_report = _report(split_rows["validation"], parameters)
        # Selection may use train and validation, never test.  Require a real,
        # non-single-episode branch and no negative mean on either split.
        if (
            train_report["changed_episodes"] < 8
            or validation_report["changed_episodes"] < 3
            or train_report["mean_improvement"] <= 0
            or validation_report["mean_improvement"] <= 0
        ):
            continue
        scored.append((_objective(validation_report), parameters, train_report, validation_report))
        if index % 1000 == 0:
            print(f"screened {index}/{len(candidates)}", flush=True)

    if not scored:
        raise RuntimeError("no residual-demand branch passed train/validation support")
    scored.sort(key=lambda item: item[0], reverse=True)
    _score, selected, train_report, validation_report = scored[0]
    # Test is evaluated exactly once after the validation choice is fixed.
    test_report = _report(split_rows["test"], selected)

    source_test = {
        source: _report(
            [row for row in split_rows["test"] if row["source"] == source],
            selected,
        )
        for source in ("rank1", "rank2", "rank3")
    }
    demand_test = {
        str(demand): _report(
            [row for row in split_rows["test"] if _demand(row, "STRAWBERRY") == demand],
            selected,
        )
        for demand in range(7)
        if any(_demand(row, "STRAWBERRY") == demand for row in split_rows["test"])
    }
    result = {
        "format": FORMAT,
        "objective": (
            "Bound V14 Strawberry replenishment under weak residual demand while preserving "
            "herd and deterministic execution"
        ),
        "row_source": str(rows_path.relative_to(ROOT)),
        "split_discipline": (
            "parameters selected by train+validation support and validation objective; "
            "test evaluated once after selection"
        ),
        "candidate_count": len(candidates),
        "supported_candidate_count": len(scored),
        "selected": selected,
        "reports": {
            "train": train_report,
            "validation": validation_report,
            "test": test_report,
            "test_by_source": source_test,
            "test_by_berry_demand": demand_test,
        },
        "promotion_screen": {
            "validation_mean_improves": validation_report["mean_improvement"] > 0,
            "validation_p90_not_worse": (
                validation_report["p90_error_candidate"] <= validation_report["p90_error_base"]
            ),
            "test_mean_confirms": test_report["mean_improvement"] > 0,
            "test_p90_not_worse": test_report["p90_error_candidate"] <= test_report["p90_error_base"],
            "all_test_sources_nonnegative_mean": all(
                report["mean_improvement"] >= -1e-12 for report in source_test.values()
            ),
        },
        "interpretation": {
            "fact": (
                "all rows from an episode remain in one split; live assets and animal targets are unchanged"
            ),
            "inference": (
                "a confirmed result supports a bounded replenishment branch, not immediate crop removal"
            ),
            "unverified": (
                "logged future-state fidelity is not a causal score or leaderboard-rating estimate"
            ),
        },
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
                "test": test_report,
                "promotion_screen": result["promotion_screen"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"result: {output}")


if __name__ == "__main__":
    main()
