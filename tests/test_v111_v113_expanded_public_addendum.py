from __future__ import annotations

from scripts.build_v111_v113_expanded_public_addendum import build


def test_expanded_public_addendum_preserves_parent_and_blocks_empty_panel() -> None:
    payload = build()
    registry = payload["new_discovery_results"]["expanded_registry"]

    assert payload["parent_source_integrity"]["all_valid"] is True
    assert registry["coverage"]["source_labels"] == 100
    assert registry["coverage"]["exact_executed_action_families"] == 63
    assert registry["coverage"]["distinct_source_ancestry_ids"] == 22
    assert registry["sensitivity"]["eligible_opponent_family_count"] == 0
    assert payload["paired_addendum_decision"]["run_started"] is False
    assert payload["paired_addendum_decision"]["reason_code"] == (
        "NO_NEW_SENSITIVITY_FAMILY"
    )


def test_expanded_public_addendum_keeps_v111_and_does_not_create_v114() -> None:
    payload = build()
    decision = payload["current_decision"]
    history = payload["new_discovery_results"]["public_history"]
    external = payload["new_discovery_results"]["public_external_github"]

    assert history["games"] == 100
    assert history["v111_wins"] == 100
    assert external["games"] == 12
    assert external["v111_wins"] == 12
    assert decision["production_champion"] == "V111"
    assert decision["v113_status"] == "LIVE_VIABLE / CAUSAL_UNRESOLVED"
    assert decision["v114_candidate_created"] is False
    assert decision["kaggle_submission_basis"] == "INSUFFICIENT"
