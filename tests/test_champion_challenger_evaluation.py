from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.evaluation.divergence import audit_pair
from scripts.evaluation.lineage import (
    audit_action_lineage_independence,
    collapse_to_action_families,
)
from scripts.evaluation.replay import action, observation
from scripts.evaluation.report import build_evaluation
from scripts.evaluation.safety import classify_candidate_incidents
from scripts.evaluation.schema import DatasetRole, GateStatus, validate_preregistration
from scripts.evaluation.statistics import hierarchical_bootstrap, pairwise_payoff_matrix


def _farm(money: float = 3000.0) -> dict:
    return {
        "money": money,
        "farmer": [0, 0],
        "hands": [],
        "hires_today": 0,
        "unlocked_quadrants": ["NW"],
        "tiles": [[None for _ in range(10)] for _ in range(10)],
    }


def _obs(step: int, money: float = 3000.0) -> dict:
    return {
        "step": step,
        "day": step // 24,
        "hour": step % 24,
        "player": 0,
        "farms": [_farm(money), _farm()],
        "private": {"shed": {}, "seeds": {}, "inventories": [{}]},
        "market": {"inventory": {"MILK": 10, "WOOL": 10}, "prices": {"MILK": 10, "WOOL": 10}},
        "town": {"unlocked_shops": []},
    }


def _replay(actions: list[dict], money_by_state: list[float] | None = None) -> dict:
    money_by_state = money_by_state or [3000.0] * (len(actions) + 1)
    steps = []
    for index in range(len(actions) + 1):
        stored = actions[index - 1] if index else {"farmer": ["PASS"], "hands": [], "market": []}
        obs0 = _obs(index, money_by_state[index])
        obs1 = deepcopy(obs0)
        obs1["player"] = 1
        steps.append(
            [
                {"observation": obs0, "action": deepcopy(stored), "status": "ACTIVE"},
                {
                    "observation": obs1,
                    "action": {"farmer": ["PASS"], "hands": [], "market": []},
                    "status": "ACTIVE",
                },
            ]
        )
    return {"steps": steps}


def test_replay_alignment_uses_observation_t_and_action_t_plus_one() -> None:
    emitted = {"farmer": ["EAST"], "hands": [], "market": []}
    replay = _replay([emitted])
    assert observation(replay, 0, 0)["step"] == 0
    assert action(replay, 0, 0) == emitted


def test_first_divergence_accepts_only_expected_cow_to_sheep_rewrite() -> None:
    pass_action = {"farmer": ["PASS"], "hands": [], "market": []}
    control_action = {
        "farmer": ["PASS"],
        "hands": [],
        "market": [["SELL", "MELON", 6], ["BUY_ANIMAL", "COW", 2]],
    }
    treatment_action = {
        "farmer": ["PASS"],
        "hands": [],
        "market": [["SELL", "MELON", 6], ["BUY_ANIMAL", "SHEEP", 2]],
    }
    control = _replay([pass_action, control_action], [3000, 3000, 2800])
    treatment = _replay([pass_action, treatment_action], [3000, 3000, 2600])
    audit = audit_pair(control, treatment, 0, gate_requested=True, intended_action_step=1)
    assert audit["behavioral_isolation_valid"]
    assert audit["incremental_treatment_emitted"]
    assert audit["first_focal_action"]["step"] == 1
    assert audit["first_self_divergence"] == audit["first_focal_action"]
    assert audit["first_money_divergence"]["step"] == 2
    assert audit["first_state_divergence"]["self_money"]["step"] == 2


def test_pre_intervention_divergence_is_invalid() -> None:
    control = _replay([{"farmer": ["PASS"], "hands": [], "market": []}])
    treatment = _replay([{"farmer": ["EAST"], "hands": [], "market": []}])
    audit = audit_pair(control, treatment, 0, gate_requested=False, intended_action_step=10)
    assert not audit["behavioral_isolation_valid"]
    assert audit["classification"] == "unexpected_or_pre_intervention_divergence"


def test_safe_fallback_is_delivery_failure_not_hard_safety() -> None:
    common = {
        "runtime_failures": [],
        "completed_720": True,
        "minimum_cash": 100.0,
        "animal_loss_total": 0,
        "plant_to_weed": 0,
        "spawned_weeds": 0,
        "ood_steps": 0,
        "engine_action_audit": {},
        "transaction": {"complete": True},
    }
    control = {**common, "fallback_steps": 0}
    treatment = {**common, "fallback_steps": 1}
    incidents = classify_candidate_incidents(control, treatment)
    assert incidents["hard_safety_failures"] == []
    assert incidents["treatment_delivery_failures"] == ["new_fallback_steps"]


def test_incomplete_emitted_transaction_is_hard_safety() -> None:
    common = {
        "runtime_failures": [],
        "completed_720": True,
        "minimum_cash": 100.0,
        "animal_loss_total": 0,
        "plant_to_weed": 0,
        "spawned_weeds": 0,
        "fallback_steps": 0,
        "ood_steps": 0,
        "engine_action_audit": {},
    }
    incidents = classify_candidate_incidents(
        {**common, "transaction": {"complete": True}},
        {**common, "transaction": {"complete": False}},
    )
    assert incidents["hard_safety_failures"] == ["transaction_incomplete"]
    assert incidents["treatment_delivery_failures"] == []


def _pair(lineage: str, seed: int, seat: int, control_score: float, treatment_score: float) -> dict:
    def arm(score: float) -> dict:
        result = "win" if score == 1 else "draw" if score == 0.5 else "loss"
        return {"score": score, "result": result, "ours": 10, "theirs": 9, "margin": 1}

    return {
        "lineage_id": lineage,
        "meta_weight": 0.5,
        "seed": seed,
        "seat": seat,
        "control": arm(control_score),
        "treatment": arm(treatment_score),
        "delta_self_coin": 0,
        "delta_opponent_coin": 0,
        "delta_margin": 0,
        "gate_requested": False,
        "incremental_treatment": False,
        "behavioral_isolation_valid": True,
        "divergence_audit": {"classification": "inactive_exact_identity", "first_focal_action": None},
        "candidate_new_major_regressions": [],
        "safety": {
            "control": {
                "completed_720": True,
                "animal_loss_total": 0,
                "plant_to_weed": 0,
                "transaction": {"complete": True},
            },
            "treatment": {
                "completed_720": True,
                "animal_loss_total": 0,
                "plant_to_weed": 0,
                "transaction": {"complete": True},
            },
        },
        "agent_trace": {"treatment": {"agent_exceptions": []}},
        "executed_lineages": {
            "opponent_control_h200": f"{lineage}-{seed}-{seat}",
        },
    }


def test_payoff_matrix_counts_discordant_pairs_and_hierarchical_bootstrap() -> None:
    rows = [
        _pair("a", 1, 0, 0, 1),
        _pair("a", 1, 1, 1, 0),
        _pair("b", 2, 0, 0.5, 1),
        _pair("b", 2, 1, 0.5, 0.5),
    ]
    matrix = pairwise_payoff_matrix(rows, repetitions=50, bootstrap_seed=7)
    assert matrix[0]["loss_to_win"] == 1
    assert matrix[0]["win_to_loss"] == 1
    uncertainty = hierarchical_bootstrap(rows, {"a": 0.5, "b": 0.5}, 50, 11)
    assert uncertainty["independent_lineages"] == 2
    assert uncertainty["method"].startswith("hierarchical cluster bootstrap")


def test_identical_executable_sources_collapse_to_one_action_family() -> None:
    rows = []
    for lineage, prefix in (("source_a", "same"), ("source_b", "same"), ("source_c", "other")):
        for seat in (0, 1):
            row = _pair(lineage, 7, seat, 0, 1)
            row["executed_lineages"]["opponent_control_h200"] = f"{prefix}-{seat}"
            rows.append(row)
    audit = audit_action_lineage_independence(rows)
    assert audit["declared_source_lineages"] == 3
    assert audit["observed_action_families"] == 2
    assert not audit["independence_claim_valid"]
    assert sorted(row["source_count"] for row in audit["families"]) == [1, 2]
    collapsed = collapse_to_action_families(rows, audit)
    assert len({row["lineage_id"] for row in collapsed}) == 2


def _spec() -> dict:
    return {
        "format": "kaggriculture-experiment-preregistration-v1",
        "hypothesis_id": "test",
        "hypothesis": "test",
        "dataset_roles": {
            "top_366_replays": DatasetRole.DEVELOPMENT.value,
            "fresh_holdout": "reserved",
        },
        "arms": {"control": {}, "treatment": {}},
        "opponent_pool": [
            {"lineage_id": "a", "tier": "Gold", "meta_weight": 0.5},
            {"lineage_id": "b", "tier": "Gold", "meta_weight": 0.5},
        ],
        "seed_manifest": {"fast_screen": [1], "formal_promotion": [2]},
        "seat_configuration": {"seats": [0, 1], "episode_steps": 720},
        "statistics": {"bootstrap_repetitions": 20, "bootstrap_seed": 1},
        "robust_meta": {"weight_radius": 0.1},
        "promotion_criteria": {
            "engine_correctness": {},
            "behavioral_isolation": {},
            "trigger_causal_uplift": {
                "minimum_trigger_requests": 2,
                "minimum_delta_win_score_low_95": 0,
                "harm_reject_delta_win_score": -0.05,
            },
            "diverse_meta_payoff_improvement": {
                "minimum_independent_lineages": 2,
                "major_lineage_minimum_weight": 0.1,
                "major_lineage_delta_floor": -0.1,
                "minimum_meta_delta_low_95": 0,
                "minimum_macro_delta_low_95": 0,
                "harm_reject_meta_delta": -0.05,
            },
            "robustness": {"minimum_worst_scenario_delta": 0, "harm_reject_worst_delta": -0.05},
            "fresh_holdout": {},
        },
    }


def test_ordered_promotion_blocks_meta_when_trigger_evidence_is_insufficient() -> None:
    spec = _spec()
    rows = [_pair("a", 2, 0, 1, 1), _pair("b", 2, 0, 1, 1)]
    evaluation = build_evaluation([], rows, [], spec, {"all_passed": True})
    assert evaluation["ordered_promotion_gates"]["engine_correctness"]["status"] == GateStatus.PASS
    assert (
        evaluation["ordered_promotion_gates"]["trigger_causal_uplift"]["status"]
        == GateStatus.INSUFFICIENT
    )
    assert (
        evaluation["ordered_promotion_gates"]["diverse_meta_payoff_improvement"]["status"]
        == GateStatus.BLOCKED
    )
    assert evaluation["decision"] == "PROMISING_UNPROVEN"


def test_preregistration_rejects_fresh_holdout_mislabel() -> None:
    spec = _spec()
    spec["dataset_roles"]["top_366_replays"] = DatasetRole.FRESH_HOLDOUT.value
    with pytest.raises(ValueError, match="top-366"):
        validate_preregistration(spec)
