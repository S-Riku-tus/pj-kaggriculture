"""Pure, evidence-driven Round4 artifact evaluation.

No file IO, global verdicts, or report literals are allowed here.  JSON and
Markdown renderers consume the same returned object.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

Verdict = Literal["PASS", "FAIL", "UNKNOWN", "NOT_APPLICABLE"]
AXES = (
    "PACKAGE_VALID",
    "EXECUTION_CORRECT",
    "TRAINING_EXECUTED",
    "MODEL_USED",
    "BEHAVIORAL_FIDELITY",
    "ECONOMIC_EFFECT",
    "ONLINE_EVIDENCE",
    "READY_FOR_DIAGNOSTIC_SUBMISSION",
    "CHAMPION_PROMOTION",
)


def _axis(status: Verdict, reason: str, evidence_ids: list[str] | tuple[str, ...] = ()) -> dict[str, Any]:
    return {"status": status, "reason": reason, "evidence_ids": list(evidence_ids)}


def _evidence(section: Mapping[str, Any]) -> list[str]:
    raw = section.get("evidence_ids") or []
    return [str(value) for value in raw]


def evaluate_artifact(
    metrics: Mapping[str, Any],
    provenance: Mapping[str, Any],
    purpose: str,
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate independent axes from explicit metrics and provenance only."""
    result: dict[str, dict[str, Any]] = {}
    hashes_current = provenance.get("required_hashes_current")
    package = metrics.get("package") or {}
    package_evidence = _evidence(package)
    if hashes_current is False:
        result["PACKAGE_VALID"] = _axis("FAIL", "required evidence hash is stale", package_evidence)
    elif not package.get("tested"):
        result["PACKAGE_VALID"] = _axis("UNKNOWN", "final archive was not tested", package_evidence)
    elif package.get("valid") is True:
        result["PACKAGE_VALID"] = _axis(
            "PASS", "final archive loaded and completed the required episode checks", package_evidence
        )
    else:
        result["PACKAGE_VALID"] = _axis(
            "FAIL", str(package.get("reason") or "final archive validation failed"), package_evidence
        )

    execution = metrics.get("execution") or {}
    execution_evidence = _evidence(execution)
    triggered = int(execution.get("triggered") or 0)
    issued = int(execution.get("primitive_issued") or 0)
    established = int(execution.get("primitive_effect_observed") or 0)
    failed = int(execution.get("primitive_failed") or 0)
    known_bug = bool(execution.get("known_critical_bug"))
    if known_bug or failed > 0 or established < min(triggered, issued):
        result["EXECUTION_CORRECT"] = _axis(
            "FAIL",
            (
                "semantic execution failure: "
                f"triggered={triggered}, issued={issued}, "
                f"established={established}, failed={failed}"
            ),
            execution_evidence,
        )
    elif triggered <= 0:
        result["EXECUTION_CORRECT"] = _axis("NOT_APPLICABLE", "target skill did not activate", execution_evidence)
    elif established > 0:
        result["EXECUTION_CORRECT"] = _axis(
            "PASS", "actor-attributed primitive effects were observed", execution_evidence
        )
    else:
        result["EXECUTION_CORRECT"] = _axis(
            "UNKNOWN", "activation was recorded but semantic effect evidence is missing", execution_evidence
        )

    learned = purpose.lower() == "learned"
    training = metrics.get("training") or {}
    training_evidence = _evidence(training)
    if not learned:
        result["TRAINING_EXECUTED"] = _axis("NOT_APPLICABLE", "explicit-rule artifact", training_evidence)
        result["MODEL_USED"] = _axis("NOT_APPLICABLE", "explicit-rule artifact", training_evidence)
    else:
        updates = int(training.get("optimizer_updates") or 0)
        checkpoint_valid = bool(training.get("checkpoint_valid"))
        if updates > 0 and checkpoint_valid:
            result["TRAINING_EXECUTED"] = _axis(
                "PASS", f"training performed {updates} optimizer updates", training_evidence
            )
        elif updates <= 0:
            result["TRAINING_EXECUTED"] = _axis("FAIL", "no optimizer update was executed", training_evidence)
        else:
            result["TRAINING_EXECUTED"] = _axis("FAIL", "checkpoint is missing or hash-invalid", training_evidence)
        inference = int(training.get("inference_calls") or 0)
        invalid_fallbacks = int(training.get("invalid_fallbacks") or 0)
        loads = int(training.get("model_loads") or 0)
        if inference > 0 and invalid_fallbacks == 0:
            result["MODEL_USED"] = _axis("PASS", f"model inference was used {inference} times", training_evidence)
        elif invalid_fallbacks > 0:
            result["MODEL_USED"] = _axis(
                "FAIL", f"{invalid_fallbacks} invalid or silent fallbacks occurred", training_evidence
            )
        elif loads > 0:
            result["MODEL_USED"] = _axis("FAIL", "model loaded but inference count is zero", training_evidence)
        else:
            result["MODEL_USED"] = _axis("UNKNOWN", "model runtime evidence is missing", training_evidence)

    behavior = metrics.get("behavior") or {}
    behavior_evidence = _evidence(behavior)
    if not behavior.get("evaluated"):
        result["BEHAVIORAL_FIDELITY"] = _axis(
            "UNKNOWN", "unused teacher conditions were not evaluated", behavior_evidence
        )
    else:
        delta = float(behavior.get("skill_macro_accuracy_delta") or 0.0)
        minimum = float(thresholds.get("minimum_skill_delta", 0.0))
        raw_completion = behavior.get("plan_completion_rate")
        completion = float(raw_completion or 0.0)
        minimum_completion = float(thresholds.get("minimum_plan_completion_rate", 0.0))
        if raw_completion is None:
            result["BEHAVIORAL_FIDELITY"] = _axis(
                "UNKNOWN",
                f"held-out decision delta={delta:.6g}, but coherent multi-step plan completion was not measured",
                behavior_evidence,
            )
        elif delta >= minimum and completion >= minimum_completion:
            result["BEHAVIORAL_FIDELITY"] = _axis(
                "PASS", f"skill delta={delta:.6g}, plan completion={completion:.6g}", behavior_evidence
            )
        else:
            result["BEHAVIORAL_FIDELITY"] = _axis(
                "FAIL", f"skill delta={delta:.6g}, plan completion={completion:.6g}", behavior_evidence
            )

    economic = metrics.get("economic") or {}
    economic_evidence = _evidence(economic)
    if not economic.get("evaluated"):
        result["ECONOMIC_EFFECT"] = _axis(
            "UNKNOWN", "economic evaluation was not run for this scope", economic_evidence
        )
    else:
        mean_delta = float(economic.get("mean_margin_delta") or 0.0)
        lower = economic.get("cluster_ci_low")
        tradeoff = bool(economic.get("win_loss_tradeoff"))
        minimum = float(thresholds.get("minimum_mean_margin_delta", 0.0))
        if tradeoff and mean_delta >= minimum:
            result["ECONOMIC_EFFECT"] = _axis(
                "UNKNOWN",
                f"positive mean ({mean_delta:.6g}) has a win/loss tradeoff; scope-specific judgment required",
                economic_evidence,
            )
        elif mean_delta < minimum:
            result["ECONOMIC_EFFECT"] = _axis(
                "FAIL", f"mean margin delta {mean_delta:.6g} is below {minimum:.6g}", economic_evidence
            )
        elif lower is not None and float(lower) >= float(thresholds.get("minimum_cluster_ci_low", 0.0)):
            result["ECONOMIC_EFFECT"] = _axis(
                "PASS", f"mean={mean_delta:.6g}, cluster lower bound={float(lower):.6g}", economic_evidence
            )
        else:
            result["ECONOMIC_EFFECT"] = _axis(
                "UNKNOWN", f"mean={mean_delta:.6g}; uncertainty is not resolved", economic_evidence
            )

    online = metrics.get("online") or {}
    online_evidence = _evidence(online)
    if not online.get("evaluated"):
        result["ONLINE_EVIDENCE"] = _axis("UNKNOWN", "no online result is attached", online_evidence)
    elif int(online.get("games") or 0) <= 0:
        result["ONLINE_EVIDENCE"] = _axis("UNKNOWN", "online record contains no games", online_evidence)
    elif bool(online.get("improved")):
        result["ONLINE_EVIDENCE"] = _axis("PASS", "contemporaneous online control comparison improved", online_evidence)
    else:
        result["ONLINE_EVIDENCE"] = _axis("FAIL", "online comparison did not improve", online_evidence)

    package_ok = result["PACKAGE_VALID"]["status"] == "PASS"
    execution_ok = result["EXECUTION_CORRECT"]["status"] in {"PASS", "NOT_APPLICABLE"}
    hypothesis = bool(metrics.get("diagnostic_hypothesis"))
    diagnostic_block = str(metrics.get("diagnostic_blocked_reason") or "")
    if diagnostic_block:
        result["READY_FOR_DIAGNOSTIC_SUBMISSION"] = _axis(
            "FAIL",
            diagnostic_block,
            sorted(set(package_evidence + execution_evidence + economic_evidence)),
        )
    elif package_ok and execution_ok and hypothesis:
        result["READY_FOR_DIAGNOSTIC_SUBMISSION"] = _axis(
            "PASS",
            "package and execution checks pass and a bounded diagnostic hypothesis is recorded",
            sorted(set(package_evidence + execution_evidence)),
        )
    elif result["PACKAGE_VALID"]["status"] == "FAIL" or result["EXECUTION_CORRECT"]["status"] == "FAIL":
        result["READY_FOR_DIAGNOSTIC_SUBMISSION"] = _axis(
            "FAIL",
            "known package or execution failure blocks diagnostic submission",
            sorted(set(package_evidence + execution_evidence)),
        )
    else:
        result["READY_FOR_DIAGNOSTIC_SUBMISSION"] = _axis("UNKNOWN", "diagnostic readiness evidence is incomplete", [])

    champion_inputs = (
        result["PACKAGE_VALID"]["status"],
        result["EXECUTION_CORRECT"]["status"],
        result["ECONOMIC_EFFECT"]["status"],
        result["ONLINE_EVIDENCE"]["status"],
    )
    if champion_inputs == ("PASS", "PASS", "PASS", "PASS"):
        result["CHAMPION_PROMOTION"] = _axis("PASS", "package, execution, economic, and online evidence all pass", [])
    elif "FAIL" in champion_inputs:
        result["CHAMPION_PROMOTION"] = _axis("FAIL", "at least one required promotion axis failed", [])
    else:
        result["CHAMPION_PROMOTION"] = _axis("UNKNOWN", "promotion evidence is incomplete", [])

    assert tuple(result) == AXES
    return {"version": str(provenance.get("version") or "UNKNOWN"), "purpose": purpose, "axes": result}


def render_markdown(evaluation: Mapping[str, Any]) -> str:
    lines = [
        f"# Artifact evaluation: {evaluation.get('version', 'UNKNOWN')}",
        "",
        "| Axis | Status | Reason | Evidence |",
        "|---|---|---|---|",
    ]
    for name, axis in (evaluation.get("axes") or {}).items():
        evidence = ", ".join(str(value) for value in axis.get("evidence_ids") or []) or "—"
        reason = str(axis.get("reason") or "").replace("|", "\\|")
        lines.append(f"| {name} | {axis.get('status')} | {reason} | {evidence} |")
    return "\n".join(lines) + "\n"


__all__ = ["AXES", "evaluate_artifact", "render_markdown"]
