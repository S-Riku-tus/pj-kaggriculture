from __future__ import annotations

import gzip
import json
from copy import deepcopy
from pathlib import Path

import pytest

from agents.learning_round4_20260921 import rule_main
from agents.learning_round4_20260921.action_codec import decode_action, encode_action
from agents.learning_round4_20260921.contracts import (
    actor_inventory,
    attribute_primitive,
    capture_rejoin_snapshot,
    crop_harvestability,
    make_harvest_plan,
    prove_rejoin,
)
from agents.learning_round4_20260921.evaluation import AXES, evaluate_artifact, render_markdown
from agents.learning_round4_20260921.executor import ExecutionCoordinator

ROOT = Path(__file__).resolve().parents[1]
ROUND3_REPLAYS = ROOT / "experiments/learning_round3_20260921/p3_paired_development/replays"


def _replay(arm: str) -> dict:
    path = ROUND3_REPLAYS / arm / "qeinstein_moev2/seed_2026092421_seat_0.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def _observation(replay: dict, step: int, seat: int = 0) -> dict:
    value = deepcopy(replay["steps"][step][seat]["observation"])
    value["step"] = step
    return value


def _action(replay: dict, step: int, seat: int = 0) -> dict:
    return deepcopy(replay["steps"][step + 1][seat]["action"])


def test_immature_harvest_is_blocked_by_typed_plan_and_real_entrypoint() -> None:
    replay = _replay("harvest_deliver")
    observation = _observation(replay, 205)
    old_action = _action(replay, 205)
    assert old_action["hands"][3] == ["HARVEST"]
    precondition = crop_harvestability(observation, 4)
    assert not precondition.applicable
    assert precondition.reason == "HARVEST_PRECONDITION_FAILED:IMMATURE"
    assert (precondition.crop, precondition.age_days, precondition.yield_units) == ("WHEAT", 1, 1)
    plan, same_precondition = make_harvest_plan(observation, 4)
    assert plan is None and same_precondition == precondition

    coordinator = ExecutionCoordinator("regression")
    repaired = coordinator.repair(observation, old_action)
    assert repaired["hands"][3] == ["PASS"]
    blocked = [row for row in coordinator.policy_trace() if row["event"] == "harvest_blocked"]
    assert blocked[0]["audit_addendum"] == ["HARVEST_PRECONDITION_FAILED", "ECONOMIC_HYPOTHESIS_UNTESTED"]

    # Actual submission-style entrypoint, not a helper-only assertion.
    rule_main.reset_runtime_state()
    emitted = rule_main.agent(observation)
    assert emitted["hands"][3] != ["HARVEST"]


def test_feed_is_attributed_to_consuming_actor_not_target_flag() -> None:
    replay = _replay("feed_once_replan")
    before = _observation(replay, 435)
    after = _observation(replay, 436)
    assert _action(replay, 435)["hands"][3:5] == [["FEED"], ["FEED"]]
    status4, _ = attribute_primitive(before, after, 4, ["FEED"], (5, 4))
    status5, reason5 = attribute_primitive(before, after, 5, ["FEED"], (5, 4))
    assert status4 == "ESTABLISHED"
    assert status5 == "FAILED"
    assert reason5 == "FEED_TARGET_CHANGED_BY_OTHER_ACTOR"
    assert actor_inventory(before, 5).get("WHEAT") == actor_inventory(after, 5).get("WHEAT") == 1


def test_real_entrypoint_reserves_duplicate_feed_and_preserves_pickup_obligation() -> None:
    replay = _replay("feed_once_replan")
    coordinator = ExecutionCoordinator("regression")

    pickup_observation = _observation(replay, 434)
    pickup = coordinator.repair(pickup_observation, _action(replay, 434))
    assert pickup["hands"][4] == ["PICKUP", "WHEAT", 2]

    feed_observation = _observation(replay, 435)
    feed_observation["private"]["inventories"][5]["WHEAT"] = 2
    feed = coordinator.repair(feed_observation, _action(replay, 435))
    assert feed["hands"][3] == ["FEED"]
    assert feed["hands"][4] != ["FEED"]
    assert coordinator.diagnostics()["duplicate_services_blocked"] == 1

    rule_main.reset_runtime_state()
    entrypoint = rule_main.agent(feed_observation)
    units = [entrypoint["farmer"], *entrypoint["hands"]]
    duplicate_target_feeds = [units[index] for index in (4, 5) if units[index] == ["FEED"]]
    assert len(duplicate_target_feeds) == 1
    assert rule_main.policy_diagnostics()["executor"]["duplicate_services_blocked"] == 1


def test_rejoin_requires_time_inventory_reservations_and_policy_state() -> None:
    replay = _replay("feed_once_replan")
    observation = _observation(replay, 435)
    snapshot = capture_rejoin_snapshot(observation, 5, {"WHEAT": 2}, "policy-state-a")
    assert prove_rejoin(observation, snapshot, {"WHEAT": 2}, "policy-state-a") == (True, [])
    changed = deepcopy(observation)
    changed["step"] = 436
    changed["hour"] = 4
    changed["private"]["inventories"][5]["WHEAT"] = 0
    proven, reasons = prove_rejoin(changed, snapshot, {"WHEAT": 1}, "policy-state-b")
    assert not proven
    assert {
        "REJOIN_INVENTORY_MISMATCH",
        "REJOIN_TIME_MISMATCH",
        "REJOIN_RESERVATION_MISMATCH",
        "REJOIN_POLICY_STATE_MISMATCH",
    }.issubset(reasons)


def test_typed_harvest_contract_and_primitive_share_one_plan() -> None:
    replay = _replay("c0")
    # Find a genuinely mature harvest issued by C0.
    for step in range(719):
        observation = _observation(replay, step)
        action = _action(replay, step)
        units = [action["farmer"], *action["hands"]]
        actors = [index for index, unit in enumerate(units) if unit == ["HARVEST"]]
        matches = [(actor, make_harvest_plan(observation, actor)) for actor in actors]
        matches = [(actor, pair) for actor, pair in matches if pair[0] is not None]
        if matches:
            _actor, (plan, precondition) = matches[0]
            assert precondition.applicable and plan is not None
            assert plan.contract()["continuation"] == plan.primitives == [["HARVEST"]]
            assert not any(primitive[0] in {"DROP", "PLACE"} for primitive in plan.primitives)
            return
    raise AssertionError("no mature C0 harvest found")


def test_lossless_action_roundtrip_preserves_quantities_and_order() -> None:
    action = {
        "farmer": ["PICKUP", "WHEAT", 17],
        "hands": [["PLACE", "MELON", 6], ["PLANT", "STRAWBERRY"]],
        "market": [["SELL", "MELON", 12], ["SELL", "FERTILIZER", 13], ["HIRE"]],
    }
    assert decode_action(encode_action(action)) == action


def _metrics() -> dict:
    return {
        "package": {"tested": True, "valid": True, "evidence_ids": ["package"]},
        "execution": {
            "triggered": 2,
            "primitive_issued": 2,
            "primitive_effect_observed": 2,
            "primitive_failed": 0,
            "evidence_ids": ["trace"],
        },
        "training": {
            "optimizer_updates": 10,
            "checkpoint_valid": True,
            "model_loads": 1,
            "inference_calls": 3,
            "invalid_fallbacks": 0,
            "evidence_ids": ["training"],
        },
        "behavior": {
            "evaluated": True,
            "skill_macro_accuracy_delta": 0.1,
            "plan_completion_rate": 1.0,
            "evidence_ids": ["holdout"],
        },
        "economic": {
            "evaluated": True,
            "mean_margin_delta": 10.0,
            "cluster_ci_low": 1.0,
            "win_loss_tradeoff": False,
            "evidence_ids": ["paired"],
        },
        "online": {"evaluated": True, "games": 4, "improved": True, "evidence_ids": ["online"]},
        "diagnostic_hypothesis": "bounded test",
    }


def _evaluate(metrics: dict, purpose: str = "learned", current: bool = True) -> dict:
    return evaluate_artifact(
        metrics,
        {"version": "round4-test", "required_hashes_current": current},
        purpose,
        {
            "minimum_skill_delta": 0.0,
            "minimum_plan_completion_rate": 0.8,
            "minimum_mean_margin_delta": 0.0,
            "minimum_cluster_ci_low": 0.0,
        },
    )


def test_evaluator_positive_negative_no_activation_failure_and_missing() -> None:
    positive = _evaluate(_metrics())
    assert all(name in positive["axes"] for name in AXES)
    assert positive["axes"]["CHAMPION_PROMOTION"]["status"] == "PASS"

    negative_metrics = _metrics()
    negative_metrics["economic"]["mean_margin_delta"] = -1
    negative = _evaluate(negative_metrics)
    assert negative["axes"]["ECONOMIC_EFFECT"]["status"] == "FAIL"

    no_activation_metrics = _metrics()
    no_activation_metrics["execution"].update({"triggered": 0, "primitive_issued": 0, "primitive_effect_observed": 0})
    no_activation = _evaluate(no_activation_metrics)
    assert no_activation["axes"]["EXECUTION_CORRECT"]["status"] == "NOT_APPLICABLE"

    failed_metrics = _metrics()
    failed_metrics["execution"].update({"primitive_effect_observed": 1, "primitive_failed": 1})
    failed = _evaluate(failed_metrics)
    assert failed["axes"]["EXECUTION_CORRECT"]["status"] == "FAIL"
    assert failed["axes"]["READY_FOR_DIAGNOSTIC_SUBMISSION"]["status"] == "FAIL"

    missing_metrics = _metrics()
    missing_metrics["economic"] = {}
    missing = _evaluate(missing_metrics)
    assert missing["axes"]["ECONOMIC_EFFECT"]["status"] == "UNKNOWN"


def test_evaluator_stale_hash_rule_load_only_invalid_fallback_and_skill_only() -> None:
    stale = _evaluate(_metrics(), current=False)
    assert stale["axes"]["PACKAGE_VALID"]["status"] == "FAIL"

    rule = _evaluate(_metrics(), purpose="rule")
    assert rule["axes"]["TRAINING_EXECUTED"]["status"] == "NOT_APPLICABLE"
    assert rule["axes"]["MODEL_USED"]["status"] == "NOT_APPLICABLE"

    load_only_metrics = _metrics()
    load_only_metrics["training"]["inference_calls"] = 0
    load_only = _evaluate(load_only_metrics)
    assert load_only["axes"]["MODEL_USED"]["status"] == "FAIL"

    fallback_metrics = _metrics()
    fallback_metrics["training"]["invalid_fallbacks"] = 1
    fallback = _evaluate(fallback_metrics)
    assert fallback["axes"]["MODEL_USED"]["status"] == "FAIL"

    skill_only_metrics = _metrics()
    skill_only_metrics["economic"] = {"evaluated": False}
    skill_only_metrics["online"] = {"evaluated": False}
    skill_only = _evaluate(skill_only_metrics)
    assert skill_only["axes"]["BEHAVIORAL_FIDELITY"]["status"] == "PASS"
    assert skill_only["axes"]["ECONOMIC_EFFECT"]["status"] == "UNKNOWN"
    assert skill_only["axes"]["READY_FOR_DIAGNOSTIC_SUBMISSION"]["status"] == "PASS"
    assert skill_only["axes"]["CHAMPION_PROMOTION"]["status"] == "UNKNOWN"


def test_evaluator_win_loss_tradeoff_is_not_permanent_rejection_and_renderer_is_consistent() -> None:
    metrics = _metrics()
    metrics["economic"].update({"mean_margin_delta": 50, "cluster_ci_low": -10, "win_loss_tradeoff": True})
    evaluation = _evaluate(metrics)
    assert evaluation["axes"]["ECONOMIC_EFFECT"]["status"] == "UNKNOWN"
    markdown = render_markdown(evaluation)
    for axis, row in evaluation["axes"].items():
        assert f"| {axis} | {row['status']} |" in markdown


def test_evaluator_missing_plan_completion_and_explicit_diagnostic_block() -> None:
    metrics = _metrics()
    metrics["behavior"]["plan_completion_rate"] = None
    metrics["diagnostic_blocked_reason"] = "bounded local panel found a material adverse cluster"
    evaluation = _evaluate(metrics)
    assert evaluation["axes"]["BEHAVIORAL_FIDELITY"]["status"] == "UNKNOWN"
    assert evaluation["axes"]["READY_FOR_DIAGNOSTIC_SUBMISSION"]["status"] == "FAIL"


@pytest.mark.parametrize("field", ["optimizer_updates", "checkpoint_valid"])
def test_training_evidence_cannot_be_filled_true_without_runtime_proof(field: str) -> None:
    metrics = _metrics()
    metrics["training"][field] = 0 if field == "optimizer_updates" else False
    evaluation = _evaluate(metrics)
    assert evaluation["axes"]["TRAINING_EXECUTED"]["status"] == "FAIL"
