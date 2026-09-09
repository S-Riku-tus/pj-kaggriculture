"""Ordered promotion gates and human-readable report rendering."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .lineage import audit_action_lineage_independence, collapse_to_action_families
from .safety import classify_candidate_incidents
from .schema import PROMOTION_GATE_ORDER, EvidenceLevel, GateStatus
from .statistics import (
    bradley_terry_diagnostic,
    hierarchical_bootstrap,
    pairwise_payoff_matrix,
    robust_meta,
    summarize_pairs,
)


def _weights(spec: dict[str, Any], present: set[str] | None = None) -> dict[str, float]:
    values = {
        str(row["lineage_id"]): float(row["meta_weight"])
        for row in spec["opponent_pool"]
        if present is None or str(row["lineage_id"]) in present
    }
    total = sum(values.values())
    return {key: value / total for key, value in values.items()} if total else {}


def _row_weights(rows: list[dict[str, Any]]) -> dict[str, float]:
    values: dict[str, float] = {}
    for row in rows:
        values[str(row["lineage_id"])] = float(row["meta_weight"])
    total = sum(values.values())
    return {key: value / total for key, value in values.items()} if total else {}


def _effect_statistics(
    rows: list[dict[str, Any]], spec: dict[str, Any], bootstrap_seed: int
) -> dict[str, Any] | None:
    if not rows:
        return None
    weights = _row_weights(rows)
    repetitions = int(spec["statistics"]["bootstrap_repetitions"])
    return {
        "paired": summarize_pairs(rows),
        "uncertainty": hierarchical_bootstrap(
            rows,
            weights,
            repetitions,
            bootstrap_seed,
        ),
    }


def _engine_gate(
    rows: list[dict[str, Any]], provenance: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    classifications = [
        row.get("candidate_incident_classification")
        or classify_candidate_incidents(row["safety"]["control"], row["safety"]["treatment"])
        for row in rows
    ]
    regressions = [
        {
            "lineage_id": row["lineage_id"],
            "seed": row["seed"],
            "seat": row["seat"],
            "failures": classification["hard_safety_failures"],
        }
        for row, classification in zip(rows, classifications, strict=True)
        if classification["hard_safety_failures"]
    ]
    delivery_failures = [
        {
            "lineage_id": row["lineage_id"],
            "seed": row["seed"],
            "seat": row["seat"],
            "failures": classification["treatment_delivery_failures"],
        }
        for row, classification in zip(rows, classifications, strict=True)
        if classification["treatment_delivery_failures"]
    ]
    incomplete = sum(not row["safety"]["treatment"]["completed_720"] for row in rows)
    details = {
        "archive_inputs_verified": bool(provenance.get("all_passed")),
        "pairs": len(rows),
        "treatment_incomplete_720": incomplete,
        "candidate_new_major_regressions": regressions,
        "hard_safety_failure_pairs": len(regressions),
        "treatment_delivery_failures": delivery_failures,
        "treatment_delivery_failure_pairs": len(delivery_failures),
        "runtime_exceptions": sum(
            bool(row["agent_trace"]["treatment"].get("agent_exceptions")) for row in rows
        ),
        "animal_losses": sum(row["safety"]["treatment"]["animal_loss_total"] for row in rows),
        "plant_to_weed": sum(row["safety"]["treatment"]["plant_to_weed"] for row in rows),
        "transaction_incomplete": sum(
            not row["safety"]["treatment"]["transaction"]["complete"] for row in rows
        ),
        "seat_counts": dict(Counter(str(row["seat"]) for row in rows)),
    }
    passed = provenance.get("all_passed") and not regressions and not incomplete
    return (GateStatus.PASS.value if passed else GateStatus.FAIL.value), details


def _behavior_gate(rows: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    invalid = [
        {
            "lineage_id": row["lineage_id"],
            "seed": row["seed"],
            "seat": row["seat"],
            "classification": row["divergence_audit"]["classification"],
            "first_focal_action": row["divergence_audit"]["first_focal_action"],
        }
        for row in rows
        if not row["behavioral_isolation_valid"]
    ]
    inactive = [row for row in rows if not row["gate_requested"]]
    inactive_not_identical = [
        row for row in inactive if row["divergence_audit"]["classification"] != "inactive_exact_identity"
    ]
    details = {
        "pairs": len(rows),
        "valid_pairs": len(rows) - len(invalid),
        "invalid_pairs": invalid,
        "inactive_pairs": len(inactive),
        "inactive_non_identity_pairs": len(inactive_not_identical),
        "gate_requested_pairs": sum(bool(row["gate_requested"]) for row in rows),
        "incremental_treatment_pairs": sum(bool(row["incremental_treatment"]) for row in rows),
        "rule": "pre-step248 identity; first action difference must be the single Cow2-to-Sheep2 market rewrite",
    }
    passed = not invalid and not inactive_not_identical
    return (GateStatus.PASS.value if passed else GateStatus.FAIL.value), details


def _causal_gate(
    rows: list[dict[str, Any]], spec: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    requested = [row for row in rows if row["gate_requested"]]
    incremental = [row for row in rows if row["incremental_treatment"]]
    requested_stats = _effect_statistics(requested, spec, int(spec["statistics"]["bootstrap_seed"]) + 101)
    incremental_stats = _effect_statistics(
        incremental, spec, int(spec["statistics"]["bootstrap_seed"]) + 202
    )
    criterion = spec["promotion_criteria"]["trigger_causal_uplift"]
    details = {
        "all_games": len(rows),
        "trigger_requests": len(requested),
        "trigger_frequency": len(requested) / len(rows) if rows else 0.0,
        "incremental_treatments": len(incremental),
        "conditional_on_pre_action_request": requested_stats,
        "conditional_on_emitted_incremental_transaction": incremental_stats,
        "global_policy_effect": _effect_statistics(
            rows, spec, int(spec["statistics"]["bootstrap_seed"]) + 303
        ),
        "warning": (
            "The request cohort is the preregistered pre-action trigger analysis. "
            "The emitted-transaction cohort is a complier diagnostic and not a replacement for global impact."
        ),
    }
    if len(requested) < int(criterion["minimum_trigger_requests"]):
        return GateStatus.INSUFFICIENT.value, details
    assert requested_stats is not None
    interval = requested_stats["uncertainty"]["meta_delta"]
    paired = requested_stats["paired"]
    if (
        float(interval["low_95"]) > float(criterion["minimum_delta_win_score_low_95"])
        and int(paired["loss_to_win"]) > int(paired["win_to_loss"])
    ):
        return GateStatus.PASS.value, details
    if float(interval["high_95"]) < float(criterion["harm_reject_delta_win_score"]):
        return GateStatus.FAIL.value, details
    return GateStatus.INSUFFICIENT.value, details


def _meta_gate(
    rows: list[dict[str, Any]], matrix: list[dict[str, Any]], uncertainty: dict[str, Any], spec: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    criterion = spec["promotion_criteria"]["diverse_meta_payoff_improvement"]
    major_harm = [
        {
            "lineage_id": row["lineage_id"],
            "delta_win_score": row["delta_win_score"],
        }
        for row in matrix
        if float(row["meta_weight"]) >= float(criterion["major_lineage_minimum_weight"])
        and float(row["delta_win_score"]) < float(criterion["major_lineage_delta_floor"])
    ]
    details = {
        "independent_executable_lineages": len(matrix),
        "pairs": len(rows),
        "meta_weighted": {
            "baseline": uncertainty["meta_control"],
            "candidate": uncertainty["meta_treatment"],
            "delta": uncertainty["meta_delta"],
        },
        "macro_lineage": {
            "baseline": uncertainty["macro_control"],
            "candidate": uncertainty["macro_treatment"],
            "delta": uncertainty["macro_delta"],
        },
        "major_lineage_harm": major_harm,
    }
    enough = len(matrix) >= int(criterion["minimum_independent_lineages"])
    positive = (
        float(uncertainty["meta_delta"]["low_95"]) > float(criterion["minimum_meta_delta_low_95"])
        and float(uncertainty["macro_delta"]["low_95"]) > float(criterion["minimum_macro_delta_low_95"])
        and not major_harm
    )
    if enough and positive:
        return GateStatus.PASS.value, details
    clearly_harmful = (
        float(uncertainty["meta_delta"]["high_95"]) < float(criterion["harm_reject_meta_delta"])
        or bool(major_harm)
    )
    return (GateStatus.FAIL.value if clearly_harmful else GateStatus.INSUFFICIENT.value), details


def build_evaluation(
    fast_rows: list[dict[str, Any]],
    formal_rows: list[dict[str, Any]],
    diagnostic_rows: list[dict[str, Any]],
    spec: dict[str, Any],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    repetitions = int(spec["statistics"]["bootstrap_repetitions"])
    bootstrap_seed = int(spec["statistics"]["bootstrap_seed"])
    valid_source_rows = [row for row in formal_rows if row["behavioral_isolation_valid"]]
    lineage_audit = audit_action_lineage_independence(valid_source_rows)
    valid_strength_rows = collapse_to_action_families(valid_source_rows, lineage_audit)
    weights = _row_weights(valid_strength_rows)
    matrix = pairwise_payoff_matrix(valid_strength_rows, repetitions, bootstrap_seed)
    family_sources = {
        str(row["family_id"]): list(row["source_lineages"])
        for row in lineage_audit["families"]
    }
    for row in matrix:
        row["source_lineages"] = family_sources[str(row["lineage_id"])]
    source_matrix = pairwise_payoff_matrix(valid_source_rows, repetitions, bootstrap_seed)
    uncertainty = hierarchical_bootstrap(
        valid_strength_rows,
        weights,
        repetitions,
        bootstrap_seed,
    )
    robust = robust_meta(matrix, weights, float(spec["robust_meta"]["weight_radius"]))
    gates: dict[str, dict[str, Any]] = {}
    engine_status, engine_details = _engine_gate(formal_rows, provenance)
    gates["engine_correctness"] = {"status": engine_status, "details": engine_details}
    behavior_status, behavior_details = _behavior_gate(formal_rows)
    gates["behavioral_isolation"] = {"status": behavior_status, "details": behavior_details}
    causal_status, causal_details = _causal_gate(valid_strength_rows, spec)
    gates["trigger_causal_uplift"] = {"status": causal_status, "details": causal_details}
    meta_status, meta_details = _meta_gate(
        valid_strength_rows, matrix, uncertainty, spec
    )
    gates["diverse_meta_payoff_improvement"] = {"status": meta_status, "details": meta_details}
    robust_status = (
        GateStatus.PASS.value
        if float(robust["worst_delta"])
        > float(spec["promotion_criteria"]["robustness"]["minimum_worst_scenario_delta"])
        else GateStatus.FAIL.value
        if float(robust["worst_delta"])
        < float(spec["promotion_criteria"]["robustness"]["harm_reject_worst_delta"])
        else GateStatus.INSUFFICIENT.value
    )
    gates["robustness"] = {"status": robust_status, "details": robust}
    gates["fresh_holdout"] = {
        "status": GateStatus.NOT_RUN.value,
        "details": {
            "dataset": spec["dataset_roles"].get("fresh_holdout"),
            "reason": "No post-freeze unused executable lineage/episode cohort is available in this run.",
        },
    }

    blocked = False
    for name in PROMOTION_GATE_ORDER:
        if blocked:
            gates[name]["diagnostic_status_before_ordering"] = gates[name]["status"]
            gates[name]["status"] = GateStatus.BLOCKED.value
        elif gates[name]["status"] != GateStatus.PASS.value:
            blocked = True
    if engine_status == GateStatus.FAIL.value:
        decision = "REJECTED_SAFETY"
    elif behavior_status == GateStatus.FAIL.value:
        decision = "INVALID_EVALUATION"
    elif all(gates[name]["status"] == GateStatus.PASS.value for name in PROMOTION_GATE_ORDER):
        decision = "PROMOTE"
    else:
        decision = "PROMISING_UNPROVEN"
    evidence = [EvidenceLevel.E0.value, EvidenceLevel.E1.value, EvidenceLevel.E2.value]
    if causal_status == GateStatus.PASS.value and engine_status == behavior_status == GateStatus.PASS.value:
        evidence.append(EvidenceLevel.E3.value)
    if meta_status == GateStatus.PASS.value and EvidenceLevel.E3.value in evidence:
        evidence.append(EvidenceLevel.E4.value)
    return {
        "decision": decision,
        "promotion_allowed": decision == "PROMOTE",
        "highest_supported_evidence": evidence[-1],
        "supported_evidence_levels": evidence,
        "ordered_promotion_gates": gates,
        "fast_screen": {
            "purpose": "negative-only early harm screen; a positive result is not strength evidence",
            "pairs": len(fast_rows),
            "summary": summarize_pairs(fast_rows) if fast_rows else None,
            "major_regression_pairs": sum(
                bool(
                    (
                        row.get("candidate_incident_classification")
                        or classify_candidate_incidents(
                            row["safety"]["control"], row["safety"]["treatment"]
                        )
                    )["hard_safety_failures"]
                )
                for row in fast_rows
            ),
            "treatment_delivery_failure_pairs": sum(
                bool(
                    (
                        row.get("candidate_incident_classification")
                        or classify_candidate_incidents(
                            row["safety"]["control"], row["safety"]["treatment"]
                        )
                    )["treatment_delivery_failures"]
                )
                for row in fast_rows
            ),
        },
        "formal_promotion": {
            "pairs": len(formal_rows),
            "lineage_independence_audit": lineage_audit,
            "pairwise_payoff_matrix": matrix,
            "source_variant_payoff_matrix_diagnostic": source_matrix,
            "hierarchical_uncertainty": uncertainty,
            "robust_meta": robust,
            "bradley_terry_diagnostic": bradley_terry_diagnostic(valid_strength_rows),
        },
        "first_divergence_reproduction": diagnostic_rows,
        "causal_interpretation": (
            "Replay prediction and Top imitation are E1/E2 hypothesis evidence only. "
            "Only paired closed-loop executable-opponent outcomes contribute to E3/E4."
        ),
    }


def markdown_report(payload: dict[str, Any]) -> str:
    evaluation = payload["evaluation"]
    formal = evaluation["formal_promotion"]
    lines = [
        "# V113 generalized Cow→Sheep Champion/Challenger evaluation",
        "",
        f"- Decision: **{evaluation['decision']}**",
        f"- Highest supported evidence: **{evaluation['highest_supported_evidence']}**",
        f"- Formal pairs: {formal['pairs']}",
        (
            "- Independent action families: "
            f"{formal['lineage_independence_audit']['observed_action_families']} "
            f"from {formal['lineage_independence_audit']['declared_source_lineages']} "
            "declared executable sources"
        ),
        "- Champion/Control: v113 wrapper with generalized gate disabled (v111-equivalent)",
        "- Challenger/Treatment: identical archive except generalized gate enabled at tilt >= 1.5",
        "",
        "## Ordered promotion gates",
        "",
        "| Gate | Status |",
        "|---|---|",
    ]
    for name in PROMOTION_GATE_ORDER:
        lines.append(f"| {name} | {evaluation['ordered_promotion_gates'][name]['status']} |")
    lines.extend(
        [
            "",
            "## Pairwise payoff matrix",
            "",
            (
                "| Gold executable lineage | Pairs | Baseline WR | Candidate WR | ΔWR | "
                "L→W | W→L | Δself | Δopp | Δmargin |"
            ),
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in formal["pairwise_payoff_matrix"]:
        lineage_label = f"{row['lineage_id']} ({', '.join(row.get('source_lineages', []))})"
        lines.append(
            (
                "| {lineage_id} | {pairs} | {b:.1%} | {c:.1%} | {d:+.1%} | "
                "{lw} | {wl} | {ds:+.1f} | {do:+.1f} | {dm:+.1f} |"
            ).format(
                lineage_id=lineage_label,
                pairs=row["pairs"],
                b=row["baseline"]["win_rate"],
                c=row["candidate"]["win_rate"],
                d=row["delta_win_rate"],
                lw=row["loss_to_win"],
                wl=row["win_to_loss"],
                ds=row["mean_delta_self_coin"],
                do=row["mean_delta_opponent_coin"],
                dm=row["mean_delta_margin"],
            )
        )
    uncertainty = formal["hierarchical_uncertainty"]
    lines.extend(
        [
            "",
            "## Primary strength estimates",
            "",
            (
                f"- Meta-weighted Δ win score: {uncertainty['meta_delta']['estimate']:+.3%} "
                f"(95% hierarchical CI {uncertainty['meta_delta']['low_95']:+.3%} to "
                f"{uncertainty['meta_delta']['high_95']:+.3%})"
            ),
            (
                f"- Macro-lineage Δ win score: {uncertainty['macro_delta']['estimate']:+.3%} "
                f"(95% hierarchical CI {uncertainty['macro_delta']['low_95']:+.3%} to "
                f"{uncertainty['macro_delta']['high_95']:+.3%})"
            ),
            f"- Robust worst-scenario Δ: {formal['robust_meta']['worst_delta']:+.3%}",
            "",
            (
                "Diagnostics such as coin, margin, Top imitation, and actual tilt do not override "
                "an earlier failed or insufficient gate."
            ),
        ]
    )
    return "\n".join(lines) + "\n"
