"""Screen interpretable recovery-only joint assignment gates without test tuning."""

from __future__ import annotations

import itertools
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
META_INPUT = ROOT / "data/analysis/joint_assignment_meta_validation_dense.json"
TEST_INPUT = ROOT / "data/analysis/joint_assignment_holdout_dense.json"
OUTPUT = ROOT / "data/analysis/joint_recovery_rule_validation.json"


def _weights(rows: list[dict[str, Any]]) -> list[float]:
    counts = Counter(row["episode_id"] for row in rows)
    return [1.0 / counts[row["episode_id"]] for row in rows]


def _accept(row: dict[str, Any], rule: dict[str, Any]) -> bool:
    meta = row["meta"]
    return bool(
        meta["joint_changed_units"] > 0
        and meta["joint_emergency_displaced"] == 0
        and meta["joint_immediate_displaced"] == 0
        and row["current_money_gap_ratio"] <= rule["maximum_money_gap"]
        and (not rule["require_productive_behind"] or row["current_productive_gap"] <= 0)
        and meta["joint_changed_units"] <= rule["maximum_changed_units"]
        and meta["joint_distance_delta"] <= rule["maximum_distance_delta"]
        and meta["joint_same_operation_rate"] >= rule["minimum_same_operation_rate"]
    )


def _evaluate(rows: list[dict[str, Any]], rule: dict[str, Any]) -> dict[str, Any]:
    if not rows:
        return {"states": 0}
    weights = _weights(rows)
    total = sum(weights)
    accepted = [_accept(row, rule) for row in rows]
    accepted_weight = sum(weight for weight, value in zip(weights, accepted, strict=True) if value)
    deltas = [float(row["meta"]["joint_teacher_exact_delta"]) for row in rows]
    gain = sum(
        weight * delta
        for weight, delta, value in zip(weights, deltas, accepted, strict=True)
        if value
    ) / total
    result: dict[str, Any] = {
        "states": len(rows),
        "episodes": len({row["episode_id"] for row in rows}),
        "accepted_states": sum(accepted),
        "acceptance_coverage": round(accepted_weight / total, 5),
        "positive_precision": (
            round(
                sum(
                    weight
                    for weight, delta, value in zip(weights, deltas, accepted, strict=True)
                    if value and delta > 0
                )
                / accepted_weight,
                5,
            )
            if accepted_weight
            else None
        ),
        "negative_rate": (
            round(
                sum(
                    weight
                    for weight, delta, value in zip(weights, deltas, accepted, strict=True)
                    if value and delta < 0
                )
                / accepted_weight,
                5,
            )
            if accepted_weight
            else None
        ),
        "worker_exact_gain": round(gain, 5),
        "by_source": {},
        "by_future72_money_bin": {},
    }
    for source in ("rank1", "rank2", "rank3"):
        local = [row for row in rows if row["source"] == source]
        if local:
            result["by_source"][source] = _evaluate_basic(local, rule)
    for money_bin in ("lt_-0.25", "-0.25_0", "0_0.25", "ge_0.25"):
        local = [row for row in rows if row["future72_money_bin"] == money_bin]
        if local:
            result["by_future72_money_bin"][money_bin] = _evaluate_basic(local, rule)
    return result


def _evaluate_basic(rows: list[dict[str, Any]], rule: dict[str, Any]) -> dict[str, Any]:
    weights = _weights(rows)
    total = sum(weights)
    accepted = [_accept(row, rule) for row in rows]
    return {
        "states": len(rows),
        "acceptance_coverage": round(
            sum(weight for weight, value in zip(weights, accepted, strict=True) if value) / total,
            5,
        ),
        "worker_exact_gain": round(
            sum(
                weight * float(row["meta"]["joint_teacher_exact_delta"])
                for row, weight, value in zip(rows, weights, accepted, strict=True)
                if value
            )
            / total,
            5,
        ),
    }


def _rules() -> list[dict[str, Any]]:
    return [
        {
            "maximum_money_gap": money,
            "require_productive_behind": productive,
            "maximum_changed_units": changed,
            "maximum_distance_delta": distance,
            "minimum_same_operation_rate": same_operation,
        }
        for money, productive, changed, distance, same_operation in itertools.product(
            (-0.10, -0.20, -0.30, -0.40),
            (False, True),
            (1, 2, 3),
            (0, 2),
            (0.0, 0.5, 1.0),
        )
    ]


def _passes(report: dict[str, Any], *, selection: bool) -> bool:
    return bool(
        report["acceptance_coverage"] >= (0.01 if selection else 0.005)
        and report["worker_exact_gain"] > 0
        and report["negative_rate"] is not None
        and report["negative_rate"] <= 0.05
        and report["positive_precision"] is not None
        and report["positive_precision"] >= (0.40 if selection else 0.60)
        and all(value["worker_exact_gain"] >= 0 for value in report["by_source"].values())
        and (
            selection
            or all(
                value["states"] < 20 or value["worker_exact_gain"] >= 0
                for value in report["by_future72_money_bin"].values()
            )
        )
    )


def main() -> None:
    meta_payload = json.loads(META_INPUT.read_text(encoding="utf-8"))
    validation_rows = [row for row in meta_payload["rows"] if row["split"] == "validation"]
    fit = [row for row in validation_rows if int(row["episode_id"]) % 5 <= 2]
    validation = [row for row in validation_rows if int(row["episode_id"]) % 5 >= 3]
    fit_reports = [(rule, _evaluate(fit, rule)) for rule in _rules()]
    eligible = [(rule, report) for rule, report in fit_reports if _passes(report, selection=True)]
    selected_rule, fit_report = (
        max(
            eligible,
            key=lambda value: (
                value[1]["worker_exact_gain"],
                -value[1]["negative_rate"],
                value[1]["acceptance_coverage"],
            ),
        )
        if eligible
        else (None, None)
    )
    validation_report = _evaluate(validation, selected_rule) if selected_rule else None
    validation_passed = bool(validation_report and _passes(validation_report, selection=False))
    test_report = None
    if validation_passed:
        test_payload = json.loads(TEST_INPUT.read_text(encoding="utf-8"))
        test_rows = [row for row in test_payload["rows"] if row["split"] == "test"]
        test_report = _evaluate(test_rows, selected_rule)
    result = {
        "format": "kaggriculture-joint-recovery-rule-validation-v1",
        "selection": "rule selected on meta-fit only; meta-validation is confirmatory; test read only after pass",
        "candidate_rules": len(fit_reports),
        "fit_eligible_rules": len(eligible),
        "selected_rule": selected_rule,
        "meta_fit": fit_report,
        "meta_validation": validation_report,
        "meta_validation_passed": validation_passed,
        "untouched_test": test_report,
        "promotion_screen_passed": bool(
            validation_passed and test_report and _passes(test_report, selection=False)
        ),
        "limits": [
            "teacher endpoint improvement is not a counterfactual reward label",
            "rules use current observable relative state only; future labels are evaluation strata",
            "any offline pass still requires new-seed and distinct-opponent closed-loop tests",
        ],
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"result: {OUTPUT}")


if __name__ == "__main__":
    main()
