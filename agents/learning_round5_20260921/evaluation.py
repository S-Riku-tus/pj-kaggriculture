"""Pure evidence evaluation for Round5; no IO or embedded experiment result."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

Verdict = Literal["PASS", "FAIL", "UNKNOWN", "NOT_APPLICABLE"]
AXES = (
    "PACKAGE_VALID",
    "EXECUTION_CORRECT",
    "TRAINING_EXECUTED",
    "MODEL_USED",
    "SKILL_COMPLETION",
    "LOCAL_ECONOMIC_EFFECT",
    "EXTERNAL_ECONOMIC_EFFECT",
    "ONLINE_EVIDENCE",
    "READY_FOR_LIMITED_SUBMISSION",
    "CHAMPION_PROMOTION",
)


def _axis(status: Verdict, reason: str, evidence: Any = (), scope: str = "") -> dict[str, Any]:
    return {"status": status, "reason": reason, "scope": scope, "evidence_ids": [str(value) for value in evidence or ()]}


def _economic(section: Mapping[str, Any], threshold: float, scope: str) -> dict[str, Any]:
    evidence = section.get("evidence_ids") or []
    if not section.get("evaluated"):
        return _axis("UNKNOWN", "economic evaluation was not run", evidence, scope)
    clusters = int(section.get("clusters") or 0)
    mean_self = float(section.get("mean_delta_self") or 0.0)
    mean_opp = float(section.get("mean_delta_opponent") or 0.0)
    mean_margin = float(section.get("mean_delta_margin") or 0.0)
    if clusters <= 0:
        return _axis("UNKNOWN", "no family×seed cluster is present", evidence, scope)
    if mean_margin < threshold:
        return _axis("FAIL", f"delta self={mean_self:.6g}, opponent={mean_opp:.6g}, margin={mean_margin:.6g}", evidence, scope)
    lower = section.get("cluster_ci_low")
    if lower is not None and float(lower) >= threshold:
        return _axis("PASS", f"delta margin={mean_margin:.6g}, cluster lower={float(lower):.6g}", evidence, scope)
    return _axis("UNKNOWN", f"non-negative point estimate but uncertainty unresolved: self={mean_self:.6g}, opponent={mean_opp:.6g}, margin={mean_margin:.6g}", evidence, scope)


def evaluate_artifact(
    metrics: Mapping[str, Any], provenance: Mapping[str, Any], purpose: str, thresholds: Mapping[str, Any]
) -> dict[str, Any]:
    result: dict[str, dict[str, Any]] = {}
    package = metrics.get("package") or {}
    if provenance.get("required_hashes_current") is False:
        result["PACKAGE_VALID"] = _axis("FAIL", "required evidence hash is stale", package.get("evidence_ids"), "final archive")
    elif not package.get("tested"):
        result["PACKAGE_VALID"] = _axis("UNKNOWN", "final archive itself was not tested", package.get("evidence_ids"), "final archive")
    elif package.get("valid") is True and package.get("last_callable") == "agent" and int(package.get("full_episodes") or 0) >= 2:
        result["PACKAGE_VALID"] = _axis("PASS", "archive passed loader and full-episode checks", package.get("evidence_ids"), "final archive")
    else:
        result["PACKAGE_VALID"] = _axis("FAIL", str(package.get("reason") or "archive contract failed"), package.get("evidence_ids"), "final archive")

    execution = metrics.get("execution") or {}
    contracts = list(execution.get("required_contracts") or [])
    contract_statuses = [str(row.get("status") or "UNKNOWN") for row in contracts if isinstance(row, Mapping)]
    if execution.get("known_critical_bug") or "FAIL" in contract_statuses:
        result["EXECUTION_CORRECT"] = _axis("FAIL", "at least one required semantic contract failed", execution.get("evidence_ids"), str(execution.get("scope") or "declared contracts"))
    elif not contracts:
        result["EXECUTION_CORRECT"] = _axis("UNKNOWN", "no required semantic contracts were declared", execution.get("evidence_ids"), str(execution.get("scope") or ""))
    elif all(status == "PASS" for status in contract_statuses):
        result["EXECUTION_CORRECT"] = _axis("PASS", f"all {len(contracts)} required contracts passed", execution.get("evidence_ids"), str(execution.get("scope") or "declared contracts"))
    elif all(status == "NOT_APPLICABLE" for status in contract_statuses):
        result["EXECUTION_CORRECT"] = _axis("NOT_APPLICABLE", "none of the declared contracts activated", execution.get("evidence_ids"), str(execution.get("scope") or "declared contracts"))
    else:
        result["EXECUTION_CORRECT"] = _axis("UNKNOWN", "required contract evidence contains UNKNOWN or pending results", execution.get("evidence_ids"), str(execution.get("scope") or "declared contracts"))

    learned = purpose.lower() == "learned"
    training = metrics.get("training") or {}
    model = metrics.get("model") or training
    if not learned:
        result["TRAINING_EXECUTED"] = _axis("NOT_APPLICABLE", "non-learned arm", training.get("evidence_ids"), purpose)
        result["MODEL_USED"] = _axis("NOT_APPLICABLE", "non-learned arm", model.get("evidence_ids"), purpose)
    else:
        updates = int(training.get("optimizer_updates") or 0)
        changed = float(training.get("parameter_change_l2") or 0.0)
        if updates > 0 and changed > 0 and training.get("checkpoint_valid") is True:
            result["TRAINING_EXECUTED"] = _axis("PASS", f"{updates} optimizer updates; parameter delta={changed:.6g}", training.get("evidence_ids"), "Round5 training run")
        else:
            result["TRAINING_EXECUTED"] = _axis("FAIL", "updates, parameter change, or checkpoint validation is missing", training.get("evidence_ids"), "Round5 training run")
        calls = int(model.get("inference_calls") or 0)
        fallbacks = int(model.get("invalid_fallbacks") or 0)
        if calls > 0 and fallbacks == 0 and model.get("reloaded") is True:
            result["MODEL_USED"] = _axis("PASS", f"reloaded model executed {calls} runtime inferences", model.get("evidence_ids"), "runtime")
        elif fallbacks > 0:
            result["MODEL_USED"] = _axis("FAIL", f"{fallbacks} invalid/silent fallbacks", model.get("evidence_ids"), "runtime")
        elif int(model.get("model_loads") or 0) > 0:
            result["MODEL_USED"] = _axis("FAIL", "model loaded but inference was not observed", model.get("evidence_ids"), "runtime")
        else:
            result["MODEL_USED"] = _axis("UNKNOWN", "runtime inference evidence is absent", model.get("evidence_ids"), "runtime")

    skill = metrics.get("skill") or {}
    if not skill.get("evaluated"):
        result["SKILL_COMPLETION"] = _axis("UNKNOWN", "continuous skill completion was not evaluated", skill.get("evidence_ids"), str(skill.get("scope") or ""))
    elif int(skill.get("completed") or 0) >= int(skill.get("required") or 1) and int(skill.get("failed") or 0) == 0 and int(skill.get("unknown") or 0) == 0:
        result["SKILL_COMPLETION"] = _axis("PASS", f"completed={int(skill.get('completed') or 0)} with no failed/unknown required skill", skill.get("evidence_ids"), str(skill.get("scope") or ""))
    elif int(skill.get("failed") or 0) > 0:
        result["SKILL_COMPLETION"] = _axis("FAIL", f"failed={int(skill.get('failed') or 0)}", skill.get("evidence_ids"), str(skill.get("scope") or ""))
    else:
        result["SKILL_COMPLETION"] = _axis("UNKNOWN", "required sequence did not complete or ended pending", skill.get("evidence_ids"), str(skill.get("scope") or ""))

    minimum = float(thresholds.get("minimum_mean_margin_delta", 0.0))
    result["LOCAL_ECONOMIC_EFFECT"] = _economic(metrics.get("local_economic") or {}, minimum, "local skill/economic scenarios")
    result["EXTERNAL_ECONOMIC_EFFECT"] = _economic(metrics.get("external_economic") or {}, minimum, "fixed external proxy panel")
    online = metrics.get("online") or {}
    if not online.get("evaluated"):
        result["ONLINE_EVIDENCE"] = _axis("UNKNOWN", "no Round5 online submission/result", online.get("evidence_ids"), "Kaggle online")
    elif int(online.get("games") or 0) <= 0:
        result["ONLINE_EVIDENCE"] = _axis("UNKNOWN", "online record has no games", online.get("evidence_ids"), "Kaggle online")
    elif online.get("improved") is True:
        result["ONLINE_EVIDENCE"] = _axis("PASS", "contemporaneous online comparison improved", online.get("evidence_ids"), "Kaggle online")
    else:
        result["ONLINE_EVIDENCE"] = _axis("FAIL", "online comparison did not improve", online.get("evidence_ids"), "Kaggle online")

    package_ok = result["PACKAGE_VALID"]["status"] == "PASS"
    execution_ok = result["EXECUTION_CORRECT"]["status"] == "PASS"
    skill_ok = result["SKILL_COMPLETION"]["status"] == "PASS"
    hypothesis = bool(metrics.get("diagnostic_hypothesis"))
    if str(metrics.get("limited_submission_decision") or "").upper() == "DEFER":
        result["READY_FOR_LIMITED_SUBMISSION"] = _axis(
            "NOT_APPLICABLE",
            str(metrics.get("limited_submission_reason") or "researcher deferred a limited submission"),
            (),
            "limited diagnostic submission only",
        )
    elif package_ok and execution_ok and skill_ok and hypothesis:
        result["READY_FOR_LIMITED_SUBMISSION"] = _axis("PASS", "package, semantic execution, required skill, and bounded hypothesis are present", (), "limited diagnostic submission only")
    elif "FAIL" in {result["PACKAGE_VALID"]["status"], result["EXECUTION_CORRECT"]["status"], result["SKILL_COMPLETION"]["status"]}:
        result["READY_FOR_LIMITED_SUBMISSION"] = _axis("FAIL", "known package/execution/skill failure blocks submission", (), "limited diagnostic submission only")
    else:
        result["READY_FOR_LIMITED_SUBMISSION"] = _axis("UNKNOWN", "limited-submission evidence is incomplete", (), "limited diagnostic submission only")

    promotion_required = ("PACKAGE_VALID", "EXECUTION_CORRECT", "SKILL_COMPLETION", "EXTERNAL_ECONOMIC_EFFECT", "ONLINE_EVIDENCE")
    statuses = [result[name]["status"] for name in promotion_required]
    if all(status == "PASS" for status in statuses):
        result["CHAMPION_PROMOTION"] = _axis("PASS", "all promotion axes pass", (), "champion replacement")
    elif "FAIL" in statuses:
        result["CHAMPION_PROMOTION"] = _axis("FAIL", "at least one promotion axis failed", (), "champion replacement")
    else:
        result["CHAMPION_PROMOTION"] = _axis("UNKNOWN", "promotion evidence is incomplete", (), "champion replacement")
    assert tuple(result) == AXES
    return {"version": str(provenance.get("version") or "UNKNOWN"), "purpose": purpose, "axes": result}


def render_markdown(evaluation: Mapping[str, Any]) -> str:
    lines = ["# Artifact evaluation", "", "| Axis | Status | Scope | Reason |", "|---|---|---|---|"]
    for name, axis in (evaluation.get("axes") or {}).items():
        lines.append(f"| {name} | {axis.get('status')} | {str(axis.get('scope') or '').replace('|', '/') } | {str(axis.get('reason') or '').replace('|', '/') } |")
    return "\n".join(lines) + "\n"


__all__ = ["AXES", "evaluate_artifact", "render_markdown"]
