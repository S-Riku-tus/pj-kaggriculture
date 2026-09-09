from __future__ import annotations

from scripts.build_v111_v113_final_assessment import build


def test_final_assessment_preserves_sources_and_combines_completed_runs() -> None:
    report, _ = build()
    combined = report["expanded_v111_v113"]["combined_development_diagnostic"]

    assert report["immutable_preservation"]["all_valid"] is True
    assert report["immutable_preservation"]["sources_modified_by_builder"] is False
    assert combined["total_pairs"] == 348
    assert combined["v111"]["wins"] == 329
    assert combined["v111"]["draws"] == 10
    assert combined["v111"]["losses"] == 9
    assert combined["v113"]["wins"] == 331
    assert combined["v113"]["draws"] == 8
    assert combined["v113"]["losses"] == 9
    assert combined["loss_to_win"] == 0
    assert combined["win_to_loss"] == 0
    assert combined["actual_treatment_pairs"] == 31
    assert combined["hard_safety_failure_pairs"] == 4


def test_final_assessment_does_not_authorize_v114() -> None:
    report, weakness = build()
    signal = weakness["largest_experimentable_signal"]

    assert report["gold_pool"]["coverage"]["exact_executed_action_families"] == 37
    assert report["gold_pool"]["sensitivity"]["eligible_opponent_family_count"] == 0
    assert signal["loss_pairs"] == 6
    assert signal["independent_seeds"] == [29117001]
    assert signal["shared_through_step200"] is True
    assert signal["distinct_continuations_by_step400"] == 3
    assert report["v114_decision"]["best_response_selected"] is False
    assert report["v114_decision"]["candidate_implemented"] is False
    assert report["final_decision"]["v111_remains_champion"] is True
    assert report["final_decision"]["v113_retained_as_live_benchmark"] is True
    assert report["final_decision"]["v114_kaggle_submission_basis"] == "INSUFFICIENT"
