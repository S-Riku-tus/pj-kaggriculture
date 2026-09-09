from __future__ import annotations

from scripts.summarize_v113_live_families import (
    HORIZONS,
    MODES,
    _build_cluster_views,
    _gold_correspondence,
    _merge_probe_correspondence,
)


def _episode(episode_id: int, *, full_hash: str) -> dict:
    return {
        "episode_id": episode_id,
        "opponent_submission_id": episode_id + 1_000,
        "opponent_team_name": f"team-{episode_id}",
        "result": "win",
        "margin": 10.0,
        "opponent_initial_rating": 1_500.0,
        "rating_gap_opponent_minus_self": 0.0,
        "generalized_cow_sheep_gate": {"cohort": "A_gate_non_trigger"},
        "town_regime": {"signature": "BAKERY"},
        "opponent_action_fingerprints": {str(horizon): full_hash for horizon in HORIZONS},
        "opponent_seed_robust_fingerprints": {
            mode: {str(horizon): "same-route" for horizon in HORIZONS}
            for mode in MODES
        },
    }


def test_full_trajectory_identity_is_not_counted_as_policy_family() -> None:
    episodes = [_episode(1, full_hash="trajectory-a"), _episode(2, full_hash="trajectory-b")]

    views, _ = _build_cluster_views(episodes)

    assert views["quantity_agnostic_field_route"]["200"]["unique_clusters"] == 1
    assert views["quantity_agnostic_field_route"]["719"]["unique_clusters"] == 1
    assert len({row["opponent_action_fingerprints"]["719"] for row in episodes}) == 2


def test_gold_correspondence_requires_exact_prefix_through_h200() -> None:
    episodes = [_episode(1, full_hash="trajectory-a"), _episode(2, full_hash="trajectory-b")]
    _, cluster_ids = _build_cluster_views(episodes)
    family_id = "gold_family_test"
    probe = {
        "clustering": {
            "exact_families": [
                {
                    "behavior_family_id": family_id,
                    "representative_candidate_id": "executable_test",
                }
            ]
        }
    }
    lineages = {
        "common_probe_correspondence": {
            "matches": [
                {
                    "live_episode_id": 1,
                    "gold_behavior_family_id": family_id,
                    "candidate_id": "executable_test",
                    "exact_matching_checkpoints": [24, 100, 200],
                },
                {
                    "live_episode_id": 2,
                    "gold_behavior_family_id": family_id,
                    "candidate_id": "executable_test",
                    "exact_matching_checkpoints": [24, 100],
                },
            ]
        }
    }

    result = _gold_correspondence(
        lineages,
        probe,
        {int(row["episode_id"]): row for row in episodes},
        cluster_ids,
    )

    assert result["strong_correspondence_episode_count"] == 1
    assert result["strong_correspondence_episodes"][0]["episode_id"] == 1
    assert result["shared_opening_episode_count"] == 1
    assert result["shared_opening_episodes"][0]["episode_id"] == 2


def test_additional_probe_correspondence_is_namespaced_and_hash_only() -> None:
    episode = _episode(1, full_hash="unused")
    episode["opponent_action_fingerprints"] = {
        "24": "a",
        "100": "b",
        "200": "c",
        "400": "d",
        "719": "e",
    }
    probe = {
        "clustering": {
            "exact_families": [
                {
                    "behavior_family_id": "gold_family_01_collision",
                    "representative_candidate_id": "new_exec",
                    "source_members": ["new_exec"],
                }
            ],
            "sources": [
                {
                    "candidate_id": "new_exec",
                    "probe_status": "COMPLETE",
                    "probe_vector": [
                        {
                            "opponent": {
                                "24": "a",
                                "100": "b",
                                "200": "c",
                                "400": "different",
                                "719": "different",
                            }
                        }
                    ],
                }
            ],
        }
    }

    lineages, merged_probe = _merge_probe_correspondence(
        {"common_probe_correspondence": {"matches": []}},
        {"clustering": {"exact_families": []}},
        [("addendum", probe)],
        {1: episode},
    )

    match = lineages["common_probe_correspondence"]["matches"][0]
    assert match["gold_behavior_family_id"] == "addendum:gold_family_01_collision"
    assert match["exact_matching_checkpoints"] == [24, 100, 200]
    assert merged_probe["clustering"]["exact_families"][0][
        "behavior_family_id"
    ] == "addendum:gold_family_01_collision"


def test_cross_probe_identical_action_family_is_collapsed() -> None:
    episode = _episode(1, full_hash="unused")
    episode["opponent_action_fingerprints"]["24"] = "matching-prefix"
    primary = {
        "clustering": {
            "exact_families": [
                {
                    "behavior_family_id": "gold_primary",
                    "family_signature": "same-complete-probe-vector",
                    "representative_candidate_id": "primary_source",
                    "source_members": ["primary_source"],
                    "source_ancestry_ids": ["primary_ancestry"],
                }
            ]
        }
    }
    additional = {
        "clustering": {
            "exact_families": [
                {
                    "behavior_family_id": "gold_additional",
                    "family_signature": "same-complete-probe-vector",
                    "representative_candidate_id": "additional_source",
                    "source_members": ["additional_source"],
                    "source_ancestry_ids": ["additional_ancestry"],
                }
            ],
            "sources": [
                {
                    "candidate_id": "additional_source",
                    "probe_status": "COMPLETE",
                    "probe_vector": [
                        {"opponent": {"24": "matching-prefix"}}
                    ],
                }
            ],
        }
    }

    lineages, merged_probe = _merge_probe_correspondence(
        {"common_probe_correspondence": {"matches": []}},
        primary,
        [("addendum", additional)],
        {1: episode},
    )

    families = merged_probe["clustering"]["exact_families"]
    assert len(families) == 1
    assert families[0]["behavior_family_id"] == "gold_primary"
    assert families[0]["source_members"] == ["additional_source", "primary_source"]
    assert lineages["common_probe_correspondence"]["matches"][0][
        "gold_behavior_family_id"
    ] == "gold_primary"
