from __future__ import annotations

from pathlib import Path

import pytest

from scripts.evaluate_v111_v113_expanded import (
    _family_weakness_summary,
    _validate_checkpoint_rows,
    build_tasks,
    normalize_manifest,
    summarize_pairs,
    summarize_panel,
    validate_panel_selection,
    validate_preregistered_task_count,
)


def _write_agent(path: Path) -> None:
    path.write_text(
        "def agent(obs, configuration=None):\n"
        "    return {'farmer': ['PASS'], 'hands': [], 'market': []}\n",
        encoding="utf-8",
    )


def test_manifest_normalization_and_task_plan_collapse_panel_overlap(
    tmp_path: Path,
) -> None:
    v111 = tmp_path / "v111.py"
    v113 = tmp_path / "v113.py"
    opponent_a = tmp_path / "opponent_a.py"
    opponent_b = tmp_path / "opponent_b.py"
    for path in (v111, v113, opponent_a, opponent_b):
        _write_agent(path)
    raw = {
        "format": "kaggriculture-independent-gold-family-panel-v1",
        "controls": {
            "clean_v111": {"entrypoint": str(v111)},
            "live_benchmark_v113": {"entrypoint": str(v113)},
        },
        "dataset_role": "Development",
        "preregistered_dual_benchmark": {"planned_unique_pairs": 4},
        "families": [
            {
                "behavior_family_id": "family_a",
                "representative_candidate_id": "source_a",
                "entrypoint": str(opponent_a),
                "panels": ["sensitivity", "meta"],
                "meta_weight": 0.75,
            },
            {
                "behavior_family_id": "family_b",
                "representative_candidate_id": "source_b",
                "entrypoint": str(opponent_b),
                "panels": ["sensitivity"],
                "meta_weight": 0.25,
            },
        ],
        "panels": {
            "sensitivity": {
                "family_ids": ["family_a", "family_b"],
                "seeds": [101],
                "both_seats": True,
            },
            "meta": {
                "family_ids": ["family_a"],
                "seeds": [101],
                "both_seats": True,
            },
            "fresh_holdout": {"reserved": True, "family_ids": [], "seeds": []},
        },
    }
    manifest = normalize_manifest(raw)
    selected = validate_panel_selection(
        manifest, ["sensitivity", "meta"], allow_fresh_holdout=False
    )
    tasks = build_tasks(manifest, selected)
    assert len(tasks) == 4
    validate_preregistered_task_count(manifest, tasks)
    assert manifest["dataset_role"] == "Development"
    assert manifest["preregistered_dual_benchmark"]["planned_unique_pairs"] == 4
    family_a = [task for task in tasks if task["behavior_family_id"] == "family_a"]
    assert len(family_a) == 2
    assert all(task["panel_memberships"] == ["meta", "sensitivity"] for task in family_a)
    with pytest.raises(ValueError, match="Fresh Holdout"):
        validate_panel_selection(
            manifest, ["fresh_holdout"], allow_fresh_holdout=False
        )
    manifest["preregistered_dual_benchmark"]["planned_unique_pairs"] = 5
    with pytest.raises(ValueError, match="planned_unique_pairs"):
        validate_preregistered_task_count(manifest, tasks)


def _arm(result: str, ours: float, theirs: float) -> dict:
    score = 1.0 if result == "win" else 0.5 if result == "draw" else 0.0
    return {
        "result": result,
        "score": score,
        "ours": ours,
        "theirs": theirs,
        "margin": ours - theirs,
    }


def _row(
    family: str,
    seed: int,
    seat: int,
    v111_result: str,
    v113_result: str,
) -> dict:
    v111 = _arm(v111_result, 100.0, 100.0)
    v113 = _arm(v113_result, 110.0, 95.0)
    return {
        "behavior_family_id": family,
        "seed": seed,
        "seat": seat,
        "v111": v111,
        "v113": v113,
        "delta_self_coin": 10.0,
        "delta_opponent_coin": -5.0,
        "delta_margin": 15.0,
        "delta_win_score": v113["score"] - v111["score"],
        "delta_win_probability": float(v113_result == "win")
        - float(v111_result == "win"),
        "loss_to_win": v111_result == "loss" and v113_result == "win",
        "win_to_loss": v111_result == "win" and v113_result == "loss",
        "gate_requested": True,
        "actual_treatment": True,
        "action_divergent_pair": True,
        "treatment_delivery_failure": False,
        "safe_baseline_overlap": False,
        "safety_classification": {"hard_safety_failures": []},
        "divergence_audit": {"behavioral_isolation_valid": True},
    }


def test_panel_summary_reports_family_discordance_seats_and_hierarchy() -> None:
    rows = [
        _row("family_a", 1, 0, "loss", "win"),
        _row("family_a", 1, 1, "win", "loss"),
        _row("family_a", 2, 0, "win", "win"),
        _row("family_a", 2, 1, "loss", "loss"),
        _row("family_b", 1, 0, "loss", "win"),
        _row("family_b", 1, 1, "loss", "win"),
        _row("family_b", 2, 0, "loss", "win"),
        _row("family_b", 2, 1, "loss", "win"),
    ]
    summary = summarize_panel(
        rows,
        {"family_a": 0.75, "family_b": 0.25},
        repetitions=100,
        bootstrap_seed=17,
    )
    matrix = {
        row["behavior_family_id"]: row for row in summary["pairwise_payoff_matrix"]
    }
    assert matrix["family_a"]["loss_to_win"] == 1
    assert matrix["family_a"]["win_to_loss"] == 1
    assert matrix["family_a"]["strict_discordant_outcome_pairs"] == 2
    assert matrix["family_b"]["delta_win_probability"] == 1.0
    assert matrix["family_a"]["seed_cluster_uncertainty"]["independent_seeds"] == 2
    uncertainty = summary["hierarchical_uncertainty"]
    assert uncertainty["independent_families"] == 2
    assert uncertainty["meta_weighted"]["delta_win_probability"]["estimate"] == pytest.approx(
        0.25
    )
    assert uncertainty["macro_lineage"]["delta_win_probability"]["estimate"] == pytest.approx(
        0.5
    )
    assert summary["seat_breakdown"]["0"]["total_pairs"] == 4
    assert summary["unweighted_episode_summary_diagnostic"]["actual_treatment_pairs"] == 8


def test_invalid_behavioral_pair_is_not_used_in_causal_effect() -> None:
    valid = _row("family_a", 1, 0, "loss", "win")
    invalid = _row("family_a", 2, 1, "win", "loss")
    invalid["divergence_audit"]["behavioral_isolation_valid"] = False
    summary = summarize_pairs([valid, invalid])
    assert summary["total_pairs"] == 2
    assert summary["causal_valid_pairs"] == 1
    assert summary["causal_invalid_pairs"] == 1
    assert summary["delta_win_probability"] == 1.0
    assert summary["loss_to_win"] == 1
    assert summary["win_to_loss"] == 0
    assert summary["registered_all_pairs_outcome_transition_counts_diagnostic"] == {
        "loss->win": 1,
        "win->loss": 1,
    }


def test_weakness_classification_uses_draw_adjusted_score() -> None:
    rows = [
        _row("calibration", 1, 0, "draw", "draw"),
        _row("calibration", 1, 1, "draw", "draw"),
    ]

    weakness = _family_weakness_summary("calibration", rows)

    assert weakness["strict_win_probability_diagnostic"] == {
        "v111": 0.0,
        "v113": 0.0,
    }
    assert weakness["draw_adjusted_win_score"] == {"v111": 0.5, "v113": 0.5}
    assert weakness["flags"]["v111_below_50"] is False
    assert weakness["flags"]["v113_below_50"] is False
    assert weakness["priority_class"] == "SENSITIVITY_CLOSE_MATCHUP"


def test_resume_checkpoint_metadata_must_match_frozen_task() -> None:
    tasks = [
        {
            "task_key": "family_a|1|0",
            "behavior_family_id": "family_a",
            "seed": 1,
            "seat": 0,
            "panel_memberships": ["meta", "sensitivity"],
        }
    ]
    row = {
        "task_key": "family_a|1|0",
        "behavior_family_id": "family_a",
        "seed": 1,
        "seat": 0,
        "panel_memberships": ["sensitivity", "meta"],
    }
    _validate_checkpoint_rows([row], tasks)
    row["seat"] = 1
    with pytest.raises(ValueError, match="metadata mismatch"):
        _validate_checkpoint_rows([row], tasks)
