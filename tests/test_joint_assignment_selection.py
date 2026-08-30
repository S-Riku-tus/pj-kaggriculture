from __future__ import annotations

import json
from pathlib import Path

from scripts import screen_joint_recovery_rules as recovery

ROOT = Path(__file__).resolve().parents[1]


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "episode_id": "10",
        "source": "rank1",
        "current_money_gap_ratio": -0.3,
        "current_productive_gap": -1.0,
        "future72_money_bin": "lt_-0.25",
        "meta": {
            "joint_changed_units": 1,
            "joint_emergency_displaced": 0,
            "joint_immediate_displaced": 0,
            "joint_distance_delta": 0,
            "joint_same_operation_rate": 1.0,
            "joint_teacher_exact_delta": 0.5,
        },
    }
    row.update(overrides)
    return row


def test_recovery_rule_grid_uses_only_observable_current_state() -> None:
    rules = recovery._rules()
    assert len(rules) == 144
    assert all(not any("future" in key for key in rule) for rule in rules)

    rule = rules[0]
    first = _row(future72_money_bin="lt_-0.25")
    second = _row(future72_money_bin="ge_0.25")
    assert recovery._accept(first, rule) == recovery._accept(second, rule)


def test_recovery_screen_keeps_episode_partitions_disjoint() -> None:
    payload = json.loads(recovery.META_INPUT.read_text(encoding="utf-8"))
    rows = [row for row in payload["rows"] if row["split"] == "validation"]
    fit_ids = {row["episode_id"] for row in rows if int(row["episode_id"]) % 5 <= 2}
    validation_ids = {row["episode_id"] for row in rows if int(row["episode_id"]) % 5 >= 3}
    assert fit_ids
    assert validation_ids
    assert fit_ids.isdisjoint(validation_ids)


def test_recovery_screen_has_no_eligible_fit_rule_or_test_tuning() -> None:
    payload = json.loads(recovery.META_INPUT.read_text(encoding="utf-8"))
    rows = [
        row
        for row in payload["rows"]
        if row["split"] == "validation" and int(row["episode_id"]) % 5 <= 2
    ]
    eligible = [
        rule
        for rule in recovery._rules()
        if recovery._passes(recovery._evaluate(rows, rule), selection=True)
    ]
    assert eligible == []

    result = json.loads(recovery.OUTPUT.read_text(encoding="utf-8"))
    assert result["selected_rule"] is None
    assert result["meta_validation"] is None
    assert result["untouched_test"] is None
    assert result["promotion_screen_passed"] is False


def test_confirmation_gate_rejects_a_negative_future_stratum() -> None:
    report = {
        "acceptance_coverage": 0.02,
        "worker_exact_gain": 0.01,
        "negative_rate": 0.0,
        "positive_precision": 0.8,
        "by_source": {"rank1": {"worker_exact_gain": 0.0}},
        "by_future72_money_bin": {
            "0_0.25": {"states": 100, "worker_exact_gain": -0.001}
        },
    }
    assert recovery._passes(report, selection=False) is False
