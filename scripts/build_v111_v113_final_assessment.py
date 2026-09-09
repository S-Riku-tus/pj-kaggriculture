"""Build the non-destructive final V111/V113 research assessment.

The builder reads completed immutable experiments and post-hoc analysis files.
It never rewrites those sources and does not create an Agent candidate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

FORMAL_RESULT = Path(
    "data/evaluation/v113_cow_sheep_gate_e3e4_20260901_2024/experiment_result.json"
)
FORENSICS = Path(
    "data/evaluation/v113_cow_sheep_gate_e3e4_20260901_2024/"
    "posthoc_e6_interpretation_and_forensics_v1.json"
)
LIVE_ANALYSIS = Path("data/evaluation/v113_live_e6_55933145/analysis.json")
LIVE_RAW_MANIFEST = Path(
    "data/evaluation/v113_live_e6_55933145/immutable_raw_manifest.json"
)
LIVE_FAMILY_SUMMARY = Path(
    "data/evaluation/v113_live_e6_55933145/live_family_summary.json"
)
CONTINUATION = Path("data/analysis/v113_continuation_package_bronze_v2.json")
GOLD_REGISTRY = Path(
    "experiments/independent_gold_pool/consolidated_gold_family_registry.json"
)

EXPANDED_DIR = Path("data/evaluation/v111_v113_expanded_20260902")
PUBLIC_DIR = Path("data/evaluation/v111_v113_public_gold_addendum_20260902")

EXPECTED_IMMUTABLE_HASHES = {
    FORMAL_RESULT: "70f4e3ebd86b77686247f82ff253300d5374040cc70bc96ba6d3fbdc181597d5",
    LIVE_RAW_MANIFEST: "ec5394577555ba7a114bd1729df033e9403812b162e339862fe10cade5ff8f1b",
    EXPANDED_DIR
    / "experiment_result.json": "07be500829e444d113aa186d19c40ba907d9ae09e0db6ca7691f5cd6182e8b06",
    PUBLIC_DIR
    / "experiment_result.json": "a53b89b013ef845e010bcf5e3ea7460942b428f3299e4d73d51bc5dec137df2b",
}


def _absolute(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def _sha(path: Path) -> str:
    return hashlib.sha256(_absolute(path).read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(_absolute(path).read_text(encoding="utf-8"))


def _source(path: Path) -> dict[str, Any]:
    absolute = _absolute(path)
    return {
        "path": str(path).replace("\\", "/"),
        "sha256": _sha(absolute),
        "bytes": absolute.stat().st_size,
    }


def _validate_immutable_sources() -> dict[str, Any]:
    checks = []
    for path, expected in EXPECTED_IMMUTABLE_HASHES.items():
        actual = _sha(path)
        checks.append(
            {
                "path": str(path).replace("\\", "/"),
                "expected_sha256": expected,
                "actual_sha256": actual,
                "valid": actual == expected,
            }
        )
    for directory in (EXPANDED_DIR, PUBLIC_DIR):
        manifest_path = directory / "immutable_result_manifest.json"
        manifest = _load(manifest_path)
        actual = _sha(directory / "experiment_result.json")
        checks.append(
            {
                "path": str(manifest_path).replace("\\", "/"),
                "declared_result_sha256": manifest["result_sha256"],
                "actual_result_sha256": actual,
                "valid": actual == manifest["result_sha256"],
            }
        )
    if not all(check["valid"] for check in checks):
        invalid = [check for check in checks if not check["valid"]]
        raise ValueError(f"immutable source validation failed: {invalid}")
    return {
        "all_valid": True,
        "sources_modified_by_builder": False,
        "checks": checks,
    }


def _arm_summary(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    outcomes = Counter(str(row[arm]["result"]) for row in rows)
    total = len(rows)
    return {
        "wins": outcomes["win"],
        "draws": outcomes["draw"],
        "losses": outcomes["loss"],
        "strict_win_probability": outcomes["win"] / total,
        "win_score": (outcomes["win"] + 0.5 * outcomes["draw"]) / total,
        "mean_self_coin": mean(float(row[arm]["ours"]) for row in rows),
        "mean_opponent_coin": mean(float(row[arm]["theirs"]) for row in rows),
        "mean_margin": mean(float(row[arm]["margin"]) for row in rows),
    }


def _combined_pair_diagnostic(
    expanded: dict[str, Any], public: dict[str, Any]
) -> dict[str, Any]:
    rows = list(expanded["pairs"]) + list(public["pairs"])
    transitions = Counter(
        f"{row['v111']['result']}->{row['v113']['result']}" for row in rows
    )
    return {
        "scope": (
            "Diagnostic aggregation of two non-overlapping Development runs; not one "
            "pre-registered Meta estimate."
        ),
        "total_pairs": len(rows),
        "v111": _arm_summary(rows, "v111"),
        "v113": _arm_summary(rows, "v113"),
        "outcome_transition_counts": dict(sorted(transitions.items())),
        "loss_to_win": sum(bool(row["loss_to_win"]) for row in rows),
        "win_to_loss": sum(bool(row["win_to_loss"]) for row in rows),
        "any_outcome_changed_pairs": sum(
            row["v111"]["result"] != row["v113"]["result"] for row in rows
        ),
        "trigger_pairs": sum(bool(row["gate_requested"]) for row in rows),
        "actual_treatment_pairs": sum(bool(row["actual_treatment"]) for row in rows),
        "action_divergent_pairs": sum(
            bool(row["action_divergent_pair"]) for row in rows
        ),
        "treatment_delivery_failures": sum(
            bool(row["treatment_delivery_failure"]) for row in rows
        ),
        "safe_baseline_overlaps": sum(
            bool(row["safe_baseline_overlap"]) for row in rows
        ),
        "hard_safety_failure_pairs": sum(
            bool(row["safety_classification"]["hard_safety_failures"])
            for row in rows
        ),
        "mean_delta_self_coin": mean(float(row["delta_self_coin"]) for row in rows),
        "mean_delta_opponent_coin": mean(
            float(row["delta_opponent_coin"]) for row in rows
        ),
        "mean_delta_margin": mean(float(row["delta_margin"]) for row in rows),
        "interpretation": (
            "The only two outcome changes were Draw->Win against the V110/V111 "
            "calibration family. No baseline loss became a candidate win, and no "
            "baseline win became a candidate loss."
        ),
    }


def _panel_extract(result: dict[str, Any], panel: str) -> dict[str, Any]:
    value = result["panels"][panel]
    summary = value["unweighted_episode_summary_diagnostic"]
    uncertainty = value["hierarchical_uncertainty"]
    return {
        "registered_pairs": value["validity_gate"]["registered_pairs"],
        "independent_families": uncertainty["independent_families"],
        "v111": summary["v111"],
        "v113": summary["v113"],
        "loss_to_win": summary["loss_to_win"],
        "win_to_loss": summary["win_to_loss"],
        "trigger_pairs": summary["trigger_pairs"],
        "actual_treatment_pairs": summary["actual_treatment_pairs"],
        "hard_safety_failure_pairs": summary["hard_safety_failure_pairs"],
        "validity_gate": value["validity_gate"],
        "meta_weighted_delta_win_probability": uncertainty["meta_weighted"][
            "delta_win_probability"
        ],
        "macro_lineage_delta_win_probability": uncertainty["macro_lineage"][
            "delta_win_probability"
        ],
        "meta_weighted_delta_win_score": uncertainty["meta_weighted"][
            "delta_win_score"
        ],
        "macro_lineage_delta_win_score": uncertainty["macro_lineage"][
            "delta_win_score"
        ],
    }


def _compact_loss_case(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "seed": case["seed"],
        "seat": case["seat"],
        "margin": case["margin"],
        "day_cash_margins": case["day_cash_margins"],
        "terminal_shop_regime": case["terminal_shop_regime"],
        "terminal_own_animals": case["terminal_own_portfolio"]["animals"],
        "terminal_opponent_animals": case["terminal_opponent_portfolio"]["animals"],
        "focal_premium_sell_quantity": case["focal_premium_market_behavior"][
            "premium_sell_quantity"
        ],
        "opponent_premium_sell_quantity": case["opponent_premium_market_behavior"][
            "premium_sell_quantity"
        ],
    }


def _compact_loss_families(*maps: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for weakness_map in maps:
        for family in weakness_map["families"]:
            if not family["v111"]["losses"] and not family["v113"]["losses"]:
                continue
            sources = family["source_members"]
            calibration = any(
                source in {"local_v110", "v111_self_calibration"}
                for source in sources
            )
            result.append(
                {
                    "behavior_family_id": family["behavior_family_id"],
                    "source_members": sources,
                    "calibration_or_self_lineage": calibration,
                    "classification_basis": family["classification_basis"],
                    "priority_class": family["priority_class"],
                    "v111_strict_win_probability": family[
                        "strict_win_probability_diagnostic"
                    ]["v111"],
                    "v113_strict_win_probability": family[
                        "strict_win_probability_diagnostic"
                    ]["v113"],
                    "v111_win_score": family["draw_adjusted_win_score"]["v111"],
                    "v113_win_score": family["draw_adjusted_win_score"]["v113"],
                    "v111_diagnostic_loss_signals": family["v111"][
                        "diagnostic_loss_signals"
                    ],
                    "v113_diagnostic_loss_signals": family["v113"][
                        "diagnostic_loss_signals"
                    ],
                    "v111_lead_to_loss": family["v111"][
                        "lead_to_loss_any_major_checkpoint"
                    ],
                    "v113_lead_to_loss": family["v113"][
                        "lead_to_loss_any_major_checkpoint"
                    ],
                    "v111_loss_cases": [
                        _compact_loss_case(case)
                        for case in family["v111"]["loss_cases"]
                    ],
                    "v113_loss_cases": [
                        _compact_loss_case(case)
                        for case in family["v113"]["loss_cases"]
                    ],
                    "pairwise_v111_to_v113": family["pairwise_v111_to_v113"],
                }
            )
    return sorted(result, key=lambda row: row["behavior_family_id"])


def _shared_public_loss_regime(
    public: dict[str, Any], public_weakness: dict[str, Any]
) -> dict[str, Any]:
    rows = [
        row
        for row in public["pairs"]
        if row["v111"]["result"] == "loss" or row["v113"]["result"] == "loss"
    ]
    opponent_prefixes = {
        horizon: {
            row["executed_action_fingerprints"]["v111_arm"]["opponent"][horizon]
            for row in rows
        }
        for horizon in ("24", "100", "200", "400", "719")
    }
    compact = _compact_loss_families(public_weakness)
    cases = [case for family in compact for case in family["v111_loss_cases"]]
    shops = {tuple(case["terminal_shop_regime"]) for case in cases}
    return {
        "hypothesis_id": "H_WEAK_LATE_PREMIUM_REVERSAL_001",
        "status": "DEVELOPMENT_HYPOTHESIS_NOT_YET_A_BEST_RESPONSE",
        "loss_pairs": len(rows),
        "independent_seeds": sorted({int(row["seed"]) for row in rows}),
        "seats": sorted({int(row["seat"]) for row in rows}),
        "continuation_families": sorted(
            {str(row["behavior_family_id"]) for row in rows}
        ),
        "shared_opponent_prefix_family_count": {
            horizon: len(values) for horizon, values in opponent_prefixes.items()
        },
        "shared_through_step200": len(opponent_prefixes["200"]) == 1,
        "distinct_continuations_by_step400": len(opponent_prefixes["400"]),
        "distinct_terminal_trajectories": len(opponent_prefixes["719"]),
        "terminal_shop_regimes": [list(value) for value in sorted(shops)],
        "gate_requested_pairs": sum(bool(row["gate_requested"]) for row in rows),
        "actual_treatment_pairs": sum(bool(row["actual_treatment"]) for row in rows),
        "v111_v113_action_identical_pairs": sum(
            not bool(row["action_divergent_pair"]) for row in rows
        ),
        "day12_cash_margin": sorted(
            {case["day_cash_margins"]["288"] for case in cases}
        ),
        "day20_cash_margin_range": [
            min(case["day_cash_margins"]["480"] for case in cases),
            max(case["day_cash_margins"]["480"] for case in cases),
        ],
        "terminal_margin_range": [
            min(float(row["v111"]["margin"]) for row in rows),
            max(float(row["v111"]["margin"]) for row in rows),
        ],
        "focal_premium_sell_quantity": sorted(
            {case["focal_premium_sell_quantity"] for case in cases}
        ),
        "opponent_premium_sell_quantity_range": [
            min(case["opponent_premium_sell_quantity"] for case in cases),
            max(case["opponent_premium_sell_quantity"] for case in cases),
        ],
        "taxonomy": (
            "Late premium/residual-demand cash reversal after a shared opening. "
            "V111 leads by +1308 at Day12 in every loss, then is behind by Day20."
        ),
        "dependence_guardrail": (
            "Six seat-level losses are one seed/Town regime and share the exact opponent "
            "action prefix through step200. They cannot be counted as six independent "
            "weakness confirmations."
        ),
        "next_valid_test": (
            "Acquire executable independent descendants or synthesize pre-registered "
            "Targeted Efficacy seeds with the same regime before selecting a continuation."
        ),
    }


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    integrity = _validate_immutable_sources()
    forensics = _load(FORENSICS)
    live = _load(LIVE_ANALYSIS)
    live_family = _load(LIVE_FAMILY_SUMMARY)
    continuation = _load(CONTINUATION)
    registry = _load(GOLD_REGISTRY)
    expanded = _load(EXPANDED_DIR / "experiment_result.json")
    public = _load(PUBLIC_DIR / "experiment_result.json")
    expanded_weakness = _load(
        EXPANDED_DIR / "weakness_map_draw_adjusted_addendum.json"
    )
    public_weakness = _load(
        PUBLIC_DIR / "weakness_map_draw_adjusted_addendum.json"
    )

    c03 = next(
        row
        for row in live_family["cluster_views"]["quantity_agnostic_field_route"][
            "200"
        ]["clusters"]
        if row["cluster_id"] == "live_field_route_h200_c03"
    )
    actual_live = [
        {
            "episode_id": row["episode_id"],
            "opponent_submission_id": row["opponent_submission_id"],
            "opponent_team_name": row["opponent_team_name"],
            "seat": row["seat"],
            "result": row["result"],
            "margin": row["margin"],
            "self_initial_rating": row["self_initial_rating"],
            "opponent_initial_rating": row["opponent_initial_rating"],
            "rating_gap_opponent_minus_self": row[
                "rating_gap_opponent_minus_self"
            ],
            "town_regime_signature": row["town_regime_signature"],
            "h200_field_route_cluster": row["behavioral_prefix_clusters"][
                "quantity_agnostic_field_route"
            ]["200"],
        }
        for row in live_family["episode_summaries"]
        if row["gate_cohort"] == "C_actual_incremental_conversion"
    ]
    hard_safety_families = sorted(
        {
            row["behavior_family_id"]
            for row in expanded["pairs"]
            if row["safety_classification"]["hard_safety_failures"]
        }
    )
    improved_outcome_families = sorted(
        {
            row["behavior_family_id"]
            for row in expanded["pairs"] + public["pairs"]
            if row["v111"]["result"] != row["v113"]["result"]
        }
    )
    worsened_outcome_families = sorted(
        {
            row["behavior_family_id"]
            for row in expanded["pairs"] + public["pairs"]
            if row["win_to_loss"]
        }
    )
    loss_taxonomy = {
        "format": "kaggriculture-v111-v113-loss-taxonomy-v1",
        "dataset_role": "Development",
        "classification_basis": "draw-adjusted win score; strict WR retained as diagnostic",
        "executable_loss_families": _compact_loss_families(
            expanded_weakness, public_weakness
        ),
        "largest_experimentable_signal": _shared_public_loss_regime(
            public, public_weakness
        ),
        "live_bronze_acquisition_priority": {
            "cluster_id": c03["cluster_id"],
            "episodes": c03["performance"]["episodes"],
            "wins": c03["performance"]["wins"],
            "losses": c03["performance"]["losses"],
            "win_rate": c03["performance"]["win_rate"],
            "mean_margin": c03["performance"]["mean_margin"],
            "executable_status": "UNIDENTIFIED_BRONZE",
            "best_response_eligible": False,
            "reason": (
                "Recorded trajectory similarity is not executable policy identity and "
                "cannot support a counterfactual."
            ),
        },
        "weakness_conclusions": {
            "v111": (
                "No broad 30-70% independent executable family weakness was found. The "
                "largest Development signal is a one-seed shared-opening late premium "
                "cash reversal, which is a target for further opponent acquisition."
            ),
            "v113": (
                "Outcome weaknesses match V111 in every executable loss. Its additional "
                "verified weakness is a treatment-linked hard Safety regression: one "
                "extra spawned weed in four pairs."
            ),
        },
    }

    combined = _combined_pair_diagnostic(expanded, public)
    trigger = forensics["trigger_funnel"]
    mediator = forensics["v14_mediator_analysis"]
    correspondence = live_family["local_gold_correspondence"]
    report = {
        "format": "kaggriculture-v111-v113-final-research-assessment-v1",
        "source_snapshot_date": "2026-09-02",
        "immutable_preservation": integrity,
        "status": {
            "preregistered_experiment_verdict": "REJECTED_SAFETY",
            "preregistered_verdict_frozen": True,
            "current_research_interpretation": "LIVE_VIABLE / CAUSAL_UNRESOLVED",
            "live_ladder_evidence": "E6_OBSERVATIONAL",
            "clean_causal_control": "V111",
            "production_champion": "V111",
            "live_validated_field_benchmark": "V113 submission 55933145",
            "v113_artifact_status": "FROZEN_PROMISING_UNPROVEN",
            "v113_discarded": False,
            "v113_v114_base_eligible": False,
        },
        "source_records": {
            "formal_result": _source(FORMAL_RESULT),
            "posthoc_forensics": _source(FORENSICS),
            "live_raw_manifest": _source(LIVE_RAW_MANIFEST),
            "live_analysis": _source(LIVE_ANALYSIS),
            "live_family_summary": _source(LIVE_FAMILY_SUMMARY),
            "top_continuation": _source(CONTINUATION),
            "gold_registry": _source(GOLD_REGISTRY),
            "expanded_result": _source(EXPANDED_DIR / "experiment_result.json"),
            "public_addendum_result": _source(
                PUBLIC_DIR / "experiment_result.json"
            ),
        },
        "why_formal_and_live_coexist": {
            "formal_60_pair": {
                "v111": "58W 0D 2L",
                "v113": "58W 0D 2L",
                "loss_to_win": 0,
                "win_to_loss": 0,
                "independent_action_families": 3,
                "sensitivity_problem": (
                    "V111 already won 96.7%; at most two losses could be rescued."
                ),
            },
            "live_e6": {
                "episodes": live["live_public_performance"]["episodes"],
                "wins": live["live_public_performance"]["wins"],
                "draws": live["live_public_performance"]["draws"],
                "losses": live["live_public_performance"]["losses"],
                "win_rate": live["live_public_performance"]["win_rate"],
                "mean_margin": live["live_public_performance"]["mean_margin"],
                "initial_rating": live["rating_trajectory"][
                    "initial_public_rating"
                ],
                "final_rating": live["rating_trajectory"]["final_rating"],
                "rating_confidence_available": live["coverage"][
                    "rating_confidence_available"
                ],
                "rating_gap_bands": live["rating_gap_bands"],
            },
            "conclusion": (
                "The formal run estimates a narrow gate effect in an easy local panel; "
                "the ladder observes the whole Agent under changing matchmaking. Different "
                "opponent/Town support, rating dynamics, and scarce local loss headroom make "
                "the results compatible without making the gate causal."
            ),
        },
        "gold_pool": {
            "coverage": registry["coverage"],
            "identity_rule": registry["identity_rule"],
            "sensitivity": registry["sensitivity"],
            "fresh_holdout_status": registry["fresh_holdout_status"],
            "live_correspondence": {
                "strong_h200_or_later_episodes": correspondence[
                    "strong_correspondence_episode_count"
                ],
                "shared_opening_only_episodes": correspondence[
                    "shared_opening_episode_count"
                ],
                "no_strong_correspondence_episodes": correspondence[
                    "no_strong_gold_correspondence_episode_count"
                ],
                "h200_route_clusters": correspondence[
                    "h200_field_route_cluster_count"
                ],
                "h200_clusters_without_strong_gold": correspondence[
                    "h200_field_route_clusters_without_strong_gold_correspondence_count"
                ],
                "evidence_boundary": correspondence["interpretation"],
            },
        },
        "expanded_v111_v113": {
            "first_expanded_run": {
                "sensitivity": _panel_extract(expanded, "sensitivity"),
                "meta": _panel_extract(expanded, "meta"),
                "regression": _panel_extract(expanded, "regression"),
                "sensitivity_adequacy": expanded["selection"][
                    "sensitivity_adequacy"
                ],
            },
            "public_gold_addendum": {
                "sensitivity": _panel_extract(public, "sensitivity"),
                "meta": _panel_extract(public, "meta"),
                "regression": _panel_extract(public, "regression"),
            },
            "combined_development_diagnostic": combined,
            "family_level_findings": {
                "outcome_improved_families": improved_outcome_families,
                "outcome_improvement_scope": (
                    "Two Draw->Win pairs in gold_family_22_f835f763, the V110/V111 "
                    "calibration family; no Loss->Win."
                ),
                "outcome_worsened_families": worsened_outcome_families,
                "candidate_new_hard_safety_families": hard_safety_families,
                "public_addendum_outcome_delta": (
                    "Zero in all 14 families, including the three 10W2L families."
                ),
            },
            "strength_interpretation": (
                "Strength is statistically unresolved. V113 shows no Loss->Win rescue and "
                "no Win->Loss regression; its two Draw->Win changes are confined to the "
                "V110/V111 calibration family. Public Gold outcomes are exactly equal."
            ),
            "safety_interpretation": (
                "Pairing and Behavioral Isolation pass, but four candidate-new spawned-weed "
                "pairs close the hard Safety gate. The later public addendum Safety pass does "
                "not erase the earlier failure."
            ),
        },
        "live_gate_use": {
            "cohorts": live["gate_reconstruction"]["cohorts"],
            "transaction_complete_conversions": live["gate_reconstruction"][
                "transaction_complete_conversions"
            ],
            "actual_conversion_episodes": actual_live,
            "actual_conversion_seat_observation": (
                "All three observed conversions occurred from seat0; this is descriptive "
                "coverage, not evidence of a causal seat effect."
            ),
            "live_field_priority_sets": {
                name: {
                    "episodes": value["episodes"],
                    "h200_field_route_cluster_count": len(
                        value["h200_field_route_clusters"]
                    ),
                }
                for name, value in live_family["priority_sets"].items()
            },
            "causal_limit": live["causal_limit"],
        },
        "formal_trigger_funnel": {
            "formal_pairs": trigger["formal_pairs"],
            "gate_requests": trigger["gate_requests"],
            "reason_counts": trigger["reason_counts"],
            "accounting_identity": trigger["accounting_identity"],
            "all_requests_classified": trigger["all_requests_classified"],
            "future_taxonomy": forensics["future_safety_taxonomy"],
            "controller": forensics["transaction_controller_design"],
        },
        "v14_opponent_response": {
            "timeline": mediator["timeline"],
            "first_response_action": mediator["opponent_first_response_action"],
            "observation_before_response": mediator[
                "observation_immediately_before_response"
            ],
            "conclusion": mediator["mediator_conclusion"],
        },
        "top_continuation_package": {
            "evidence_level": continuation["evidence_level"],
            "coverage": continuation["coverage"],
            "animal_movement": continuation["animal_movement_characterization"],
            "archetype_partition": continuation["archetype_partition"],
            "production_eligible": continuation["production_eligible"],
            "interpretation": (
                "The material replay signal is Sheep expansion with Cow delta zero, plus "
                "FEED/CARE, hand-utilization, crop, sell-timing, and market-exposure "
                "co-movement. It is not evidence for isolated Cow removal."
            ),
        },
        "weakness_map": loss_taxonomy,
        "v114_decision": {
            "best_response_selected": False,
            "candidate_implemented": False,
            "causal_win_uplift": "NOT_ESTIMATED",
            "research_target": "H_WEAK_LATE_PREMIUM_REVERSAL_001",
            "reason": (
                "The only repeatable executable loss pattern is one Development seed/Town "
                "regime shared through step200, while the genuine 30-70% Sensitivity count "
                "is zero. Selecting implementation details now would be post-hoc overfit."
            ),
            "next_gate": (
                "Promote executable live-loss candidates or independent variants into a "
                "pre-registered Targeted Efficacy Panel, then measure actual-treatment "
                "Loss->Win and Win->Loss before creating V114."
            ),
        },
        "evidence_levels": {
            "E0": "ACHIEVED for engine/evaluator mechanics and tests",
            "E1": "ACHIEVED for Top continuation-package descriptive analysis",
            "E2": (
                "ACHIEVED for the previously frozen animal-direction predictive model; "
                "NOT ACHIEVED for the newly extracted continuation package and not causal "
                "policy-strength evidence"
            ),
            "E3": (
                "ACHIEVED as executable paired diagnosis for V111 versus V113; promotion "
                "fails hard Safety and shows no Loss->Win rescue"
            ),
            "E4": (
                "NOT ACHIEVED: Sensitivity has zero genuine 30-70% opponents and Meta "
                "weights are not a validated diverse current-field population"
            ),
            "E5": "NOT ACHIEVED: no Fresh Holdout was consumed or relabeled",
            "E6": (
                "ACHIEVED observationally for V113 submission 55933145; not a gate-level "
                "causal effect"
            ),
        },
        "final_decision": {
            "v111_remains_champion": True,
            "v113_retained_as_live_benchmark": True,
            "v113_strength_vs_v111": "INCONCLUSIVE",
            "v113_promotion": "NO",
            "v114_created": False,
            "v114_kaggle_submission_basis": "INSUFFICIENT",
            "fresh_holdout_used": False,
            "decision_rationale": (
                "Strength non-separation alone would justify retaining both research "
                "candidates, but the hard Safety regression keeps V111 as the sole production "
                "Champion. V113 remains a non-discarded live-validated field benchmark."
            ),
        },
    }
    return report, loss_taxonomy


def _pct(value: float) -> str:
    return f"{100.0 * value:.1f}%"


def _render(report: dict[str, Any]) -> str:
    live = report["why_formal_and_live_coexist"]["live_e6"]
    combined = report["expanded_v111_v113"]["combined_development_diagnostic"]
    c = report["live_gate_use"]["cohorts"]
    funnel = report["formal_trigger_funnel"]
    weakness = report["weakness_map"]["largest_experimentable_signal"]
    return "\n".join(
        [
            "# V111/V113 Live and Expanded Final Assessment",
            "",
            "## Decision",
            "",
            "V111 remains the production Champion and clean causal control. V113 is not "
            "discarded: it remains a frozen live-validated benchmark with current research "
            "status `LIVE_VIABLE / CAUSAL_UNRESOLVED`. No V114 strategy was created, and "
            "there is not yet a Kaggle-submission basis.",
            "",
            "The preregistered 60-pair verdict remains `REJECTED_SAFETY`; none of its "
            "immutable files were rewritten.",
            "",
            "## 1. Why local formal evaluation and Live 1675 coexist",
            "",
            "The local panel collapsed to three action families and V111 was already "
            "58W2L (96.7%), leaving only two possible Loss-to-Win rescues. The live run asks "
            "a different, Agent-level observational question in a changing field. Its 58 "
            f"public episodes were {live['wins']}W/{live['draws']}D/{live['losses']}L "
            f"({_pct(live['win_rate'])}), and the reconstructed rating moved from "
            f"{live['initial_rating']:.0f} to {live['final_rating']:.2f}. Matchmaking, Town "
            "support, field composition, and unavailable rating confidence prevent a gate "
            "causal claim.",
            "",
            "## 2. V113 versus V111 by executable family",
            "",
            f"Across two distinct Development runs, the diagnostic total is "
            f"{combined['total_pairs']} pairs: V111 "
            f"{combined['v111']['wins']}W/{combined['v111']['draws']}D/"
            f"{combined['v111']['losses']}L and V113 "
            f"{combined['v113']['wins']}W/{combined['v113']['draws']}D/"
            f"{combined['v113']['losses']}L. Loss-to-Win={combined['loss_to_win']}, "
            f"Win-to-Loss={combined['win_to_loss']}. The only outcome changes were two "
            "Draw-to-Win results against the V110/V111 calibration family. Public Gold "
            "outcomes were exactly equal. No major independent opponent family establishes "
            "V113 superiority or inferiority in strength.",
            "",
            "The only apparent stronger family was `gold_family_22_f835f763`, where two "
            "draws became wins; that family is V110/V111 calibration, not an independent "
            "field weakness. There was no outcome-weaker family. Four actual-treatment "
            "pairs in families 14/16/19/20 produced one extra spawned weed under V113. This "
            "is a hard Safety regression and keeps V111 as Champion even though strength is "
            "statistically unresolved.",
            "",
            "## 3. Live Cow/Sheep gate use",
            "",
            f"A/non-trigger: {c['A_gate_non_trigger']['episodes']} episodes; "
            f"B/trigger without incremental conversion: "
            f"{c['B_trigger_but_no_incremental_conversion']['episodes']}; "
            f"C/actual conversion: {c['C_actual_incremental_conversion']['episodes']} "
            f"({c['C_actual_incremental_conversion']['wins']}W/"
            f"{c['C_actual_incremental_conversion']['losses']}L). All three emitted "
            "transactions completed, all from seat0, against three different opponent/Town "
            "trajectories. Their margins were +44531, -13143, and +1363. These selected "
            "cohorts are descriptive E6 evidence, not a treatment-effect estimate.",
            "",
            "## 4. Formal Trigger Funnel",
            "",
            f"All {funnel['gate_requests']} requests are classified: 13 actual incremental "
            "transactions, 8 baseline-route overlaps, and 8 purchase-slot-absent safe "
            "cancels. The legacy fallback eight are Treatment Delivery Failures, not "
            "catastrophic Hard Safety failures; the other eight were already satisfied by "
            "the baseline route.",
            "",
            "The future controller lifecycle is `ARM -> REVALIDATE -> COMMIT / SAFE_CANCEL`.",
            "",
            "## 5. V14 opponent-response channel",
            "",
            "At step270, V14 changed only `BUY_SEED STRAWBERRY 2` to quantity 1. Restoring "
            "our money did not restore the action; restoring the two public Cow/Sheep pasture "
            "tiles did. The supported one-pair channel is: our step248 animal change -> "
            "public portfolio -> V14 seed-buy response -> opponent money -> market inventory "
            "-> price. Opponent-response lag is 22 turns.",
            "",
            "## 6. Weakness map",
            "",
            "V111 has no genuine independent 30-70% executable family in the current Gold "
            "registry. The largest experimentable signal is late premium/residual-demand "
            f"reversal: {weakness['loss_pairs']} seat-level losses in one seed/Town regime, "
            "across three continuations that share an identical opponent action prefix "
            "through step200. V111 led +1308 at Day12, was behind by Day20, and sold 1018 "
            "premium units versus opponents' 1905-2253. This is one dependent regime, not "
            "six independent confirmations.",
            "",
            "V113 has the same executable outcome losses and adds the verified spawned-weed "
            "Safety weakness. Live cluster `live_field_route_h200_c03` is 1W4L with mean "
            "margin -3220, but remains unidentified Bronze and is acquisition priority only.",
            "",
            "## 7. V114 Best Response",
            "",
            "No Best Response was selected or implemented, so causal win uplift is "
            "`NOT_ESTIMATED`. The late-premium reversal is frozen as research hypothesis "
            "`H_WEAK_LATE_PREMIUM_REVERSAL_001`. A pre-registered Targeted Efficacy Panel "
            "with independent executable continuations must precede implementation.",
            "",
            "## 8. Evidence levels",
            "",
            "E0 and E1 are achieved. E2 was reached for the earlier animal-direction "
            "predictive model, but not for the newly extracted continuation package and not "
            "for policy strength. E3 paired diagnosis is complete, while V113 fails its hard "
            "Safety gate and shows no Loss-to-Win rescue. Diverse/current-field E4 and Fresh "
            "Holdout E5 are not achieved. E6 is achieved only as whole-Agent live "
            "observational evidence.",
            "",
            "## 9. Kaggle submission decision",
            "",
            "Insufficient. There is no V114 artifact, no causal uplift, no passed E4/E5, and "
            "no passed hard-Safety chain. V113 remains useful as a live field benchmark, not "
            "as proof that the generalized gate should become the next base.",
            "",
        ]
    )


def _render_loss_taxonomy(payload: dict[str, Any]) -> str:
    signal = payload["largest_experimentable_signal"]
    lines = [
        "# V111/V113 Weakness Map and Loss Taxonomy",
        "",
        "All rows are Development evidence. Draw-adjusted win score is the classification "
        "basis; strict win probability remains diagnostic.",
        "",
        "| Family | Sources | V111 WR / score | V113 WR / score | L->W | W->L | Signal |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for family in payload["executable_loss_families"]:
        pairwise = family["pairwise_v111_to_v113"]
        lines.append(
            "| {family} | {sources} | {v111_wr:.1%} / {v111_score:.1%} | "
            "{v113_wr:.1%} / {v113_score:.1%} | {l2w} | {w2l} | {signal} |".format(
                family=family["behavior_family_id"],
                sources=", ".join(family["source_members"]),
                v111_wr=family["v111_strict_win_probability"],
                v111_score=family["v111_win_score"],
                v113_wr=family["v113_strict_win_probability"],
                v113_score=family["v113_win_score"],
                l2w=pairwise["loss_to_win"],
                w2l=pairwise["win_to_loss"],
                signal=", ".join(family["v111_diagnostic_loss_signals"]) or "none",
            )
        )
    lines.extend(
        [
            "",
            "## Largest experimentable signal",
            "",
            f"`{signal['hypothesis_id']}` is a Development hypothesis, not a selected Best "
            "Response. Its six losses use one seed and one Town regime, both seats, and "
            "three opponent continuations with a shared action prefix through step200. "
            "Independent-seed confirmation is absent.",
            "",
            "The next valid action is opponent acquisition / targeted scenario construction, "
            "not V114 implementation.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--assessment-json",
        type=Path,
        default=Path("data/evaluation/v111_v113_final_assessment_20260902.json"),
    )
    parser.add_argument(
        "--assessment-report",
        type=Path,
        default=Path("docs/v111_v113_live_and_expanded_final_assessment.md"),
    )
    parser.add_argument(
        "--weakness-json",
        type=Path,
        default=Path(
            "data/evaluation/v111_v113_weakness_map_loss_taxonomy_20260902.json"
        ),
    )
    parser.add_argument(
        "--weakness-report",
        type=Path,
        default=Path("docs/v111_v113_weakness_map_loss_taxonomy.md"),
    )
    args = parser.parse_args()

    report, weakness = build()
    outputs = {
        _absolute(args.assessment_json): json.dumps(
            report, ensure_ascii=False, indent=2
        )
        + "\n",
        _absolute(args.assessment_report): _render(report),
        _absolute(args.weakness_json): json.dumps(
            weakness, ensure_ascii=False, indent=2
        )
        + "\n",
        _absolute(args.weakness_report): _render_loss_taxonomy(weakness),
    }
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    print(
        json.dumps(
            [
                {
                    "path": str(path),
                    "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    "bytes": len(content.encode("utf-8")),
                }
                for path, content in outputs.items()
            ],
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
