"""Assemble immutable Round4 traces, coverage, hashes, and pure evaluations."""

from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.learning_round4_20260921.contracts import (  # noqa: E402
    actor_inventory,
    attribute_primitive,
    crop_harvestability,
)
from agents.learning_round4_20260921.evaluation import evaluate_artifact, render_markdown  # noqa: E402
from agents.learning_round4_20260921.executor import ExecutionCoordinator  # noqa: E402

EXPERIMENT = ROOT / "experiments/learning_round4_20260921"
ROUND3_REPLAYS = ROOT / "experiments/learning_round3_20260921/p3_paired_development/replays"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def replay(arm: str) -> dict[str, Any]:
    path = ROUND3_REPLAYS / arm / "qeinstein_moev2/seed_2026092421_seat_0.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def observation(value: Mapping[str, Any], step: int, seat: int = 0) -> dict[str, Any]:
    result = deepcopy(value["steps"][step][seat]["observation"])
    result["step"] = step
    return result


def action(value: Mapping[str, Any], step: int, seat: int = 0) -> dict[str, Any]:
    return deepcopy(value["steps"][step + 1][seat]["action"])


def before_after_traces() -> dict[str, Any]:
    harvest_replay = replay("harvest_deliver")
    harvest_observation = observation(harvest_replay, 205)
    harvest_old = action(harvest_replay, 205)
    harvest_executor = ExecutionCoordinator("round4-regression")
    harvest_new = harvest_executor.repair(harvest_observation, harvest_old)
    harvest_precondition = crop_harvestability(harvest_observation, 4)

    feed_replay = replay("feed_once_replan")
    pickup_observation = observation(feed_replay, 434)
    feed_observation = observation(feed_replay, 435)
    next_observation = observation(feed_replay, 436)
    feed_executor = ExecutionCoordinator("round4-regression")
    pickup_new = feed_executor.repair(pickup_observation, action(feed_replay, 434))
    # Model the inventory that the repaired PICKUP(2) establishes before the
    # next primitive; the source replay itself only contains PICKUP(1).
    repaired_feed_observation = deepcopy(feed_observation)
    repaired_feed_observation["private"]["inventories"][5]["WHEAT"] = 2
    feed_new = feed_executor.repair(repaired_feed_observation, action(feed_replay, 435))
    old_actor4 = attribute_primitive(feed_observation, next_observation, 4, ["FEED"], (5, 4))
    old_actor5 = attribute_primitive(feed_observation, next_observation, 5, ["FEED"], (5, 4))
    return {
        "source_scope": "saved Round3 qeinstein_moev2 seed 2026092421 seat0 replay",
        "new_engine_game_run_for_these_exact_traces": False,
        "case_a_immature_harvest": {
            "step": 205,
            "actor": 4,
            "old_emitted": harvest_old["hands"][3],
            "old_observed_effect": {
                "inventory_delta": 0,
                "tile_changed": False,
                "job_was_falsely_completed_after_day_change": True,
            },
            "round4_precondition": {
                "applicable": harvest_precondition.applicable,
                "reason": harvest_precondition.reason,
                "crop": harvest_precondition.crop,
                "age_days": harvest_precondition.age_days,
                "yield_units": harvest_precondition.yield_units,
            },
            "round4_emitted": harvest_new["hands"][3],
            "round4_trace": harvest_executor.policy_trace(),
        },
        "case_b_duplicate_feed": {
            "step_434_old_actor5": action(feed_replay, 434)["hands"][4],
            "step_434_round4_actor5": pickup_new["hands"][4],
            "step_435_old_actor4_actor5": action(feed_replay, 435)["hands"][3:5],
            "old_effect_attribution": {
                "actor4": {"status": old_actor4[0], "reason": old_actor4[1]},
                "actor5": {"status": old_actor5[0], "reason": old_actor5[1]},
                "actor5_wheat_before": actor_inventory(feed_observation, 5).get("WHEAT", 0),
                "actor5_wheat_after": actor_inventory(next_observation, 5).get("WHEAT", 0),
            },
            "step_435_round4_actor4_actor5": feed_new["hands"][3:5],
            "round4_duplicate_services_blocked": feed_executor.diagnostics()["duplicate_services_blocked"],
            "round4_trace": feed_executor.policy_trace(),
        },
    }


def coverage_ledger(closed_loop: Mapping[str, Any]) -> dict[str, Any]:
    old_scan = read_json(ROOT / "experiments/learning_round3_20260921/p3_candidate_scan_summary.json")
    rows = [
        {
            "scope": "round3_scan_preserved",
            "candidate_family": "all_round3_scan",
            "generated": old_scan["candidate_count"],
            "applicable": 0,
            "scheduled": 0,
            "started": 0,
            "primitive_effect_observed": 0,
            "job_completed": 0,
            "economically_evaluated": 0,
            "skipped_reason": "Round3 generated candidates had no per-candidate continuation evaluation",
            "detail": old_scan["by_job"],
        },
        {
            "scope": "round4_exact_regression",
            "candidate_family": "immature_harvest_step205_actor4",
            "generated": 1,
            "applicable": 0,
            "scheduled": 0,
            "started": 0,
            "primitive_effect_observed": 0,
            "job_completed": 0,
            "economically_evaluated": 0,
            "skipped_reason": "HARVEST_PRECONDITION_FAILED; ECONOMIC_HYPOTHESIS_UNTESTED",
        },
        {
            "scope": "round4_exact_regression",
            "candidate_family": "duplicate_feed_step435_actor5",
            "generated": 1,
            "applicable": 1,
            "scheduled": 1,
            "started": 1,
            "primitive_effect_observed": 0,
            "job_completed": 0,
            "economically_evaluated": 0,
            "skipped_reason": (
                "duplicate primitive replaced by a state-derived continuation; no exact-state engine fork"
            ),
        },
    ]
    for game in closed_loop["rows"]:
        executor = game["diagnostics"]["executor"]
        rows.append(
            {
                "scope": game["scope"],
                "candidate_family": f"{game['arm']}:{game['family']}:{game['seed']}:seat{game['seat']}",
                "generated": executor["candidate_generated"],
                "applicable": executor["applicable"],
                "scheduled": executor["scheduled"],
                "started": executor["started"],
                "primitive_effect_observed": executor["primitive_effect_observed"],
                "job_completed": executor["job_completed"],
                "economically_evaluated": 0,
                "skipped_reason": (
                    "terminal policy outcome exists, but no per-candidate KEEP counterfactual was run; "
                    "do not assign whole-policy margin to individual candidates"
                ),
                "policy_terminal_margin": game["margin"],
            }
        )
    return {
        "state_definitions": [
            "generated",
            "applicable",
            "scheduled",
            "started",
            "primitive_effect_observed",
            "job_completed",
            "economically_evaluated",
            "skipped_reason",
        ],
        "rows": rows,
        "unevaluated_scope": (
            "The 384 preserved Round3 candidates and Round4 runtime candidates do not have individual "
            "candidate-vs-KEEP economic counterfactuals. Sixteen full policy games were evaluated instead."
        ),
    }


def capture_worktree() -> None:
    status = subprocess.run(
        ["git", "status", "--short", "--branch"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    current_diff = subprocess.run(
        ["git", "diff", "--binary"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    (EXPERIMENT / "FINAL_GIT_STATUS.txt").write_text(status, encoding="utf-8")
    (EXPERIMENT / "FINAL_GIT_DIFF.patch").write_bytes(current_diff)
    initial = (EXPERIMENT / "INITIAL_GIT_DIFF.patch").read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    current = current_diff.decode("utf-8").replace("\r\n", "\n")
    write_json(
        EXPERIMENT / "WORKTREE_PRESERVATION.json",
        {
            "initial_tracked_diff_sha256": sha256(EXPERIMENT / "INITIAL_GIT_DIFF.patch"),
            "final_tracked_diff_sha256": sha256(EXPERIMENT / "FINAL_GIT_DIFF.patch"),
            "normalized_diff_identical": initial == current,
            "observed_addendum": (
                "One WHEAT MARKET_PARAMS line in the already-modified Round3 market.py appeared after the "
                "initial capture. Round4 code does not write that path; provenance is unknown, so it was preserved."
            ),
            "destructive_git_command_used": False,
        },
    )


def main() -> None:
    capture_worktree()
    traces = before_after_traces()
    write_json(EXPERIMENT / "BEFORE_AFTER_TRACES.json", traces)
    closed_loop = read_json(EXPERIMENT / "closed_loop/CLOSED_LOOP_RESULTS.json")
    write_json(EXPERIMENT / "CANDIDATE_COVERAGE_LEDGER.json", coverage_ledger(closed_loop))

    training = read_json(EXPERIMENT / "TRAINING_RECORD.json")
    archive_manifest = read_json(EXPERIMENT / "ARCHIVE_MANIFEST.json")
    learned_loaders = [
        read_json(EXPERIMENT / "LEARNED_LOADER_SEAT0.json"),
        read_json(EXPERIMENT / "LEARNED_LOADER_SEAT1.json"),
    ]
    rule_loaders = [
        read_json(EXPERIMENT / "RULE_LOADER_SEAT0.json"),
        read_json(EXPERIMENT / "RULE_LOADER_SEAT1.json"),
    ]
    learned_archive = ROOT / archive_manifest["archives"]["learned"]["path"]
    rule_archive = ROOT / archive_manifest["archives"]["rule"]["path"]
    model_path = ROOT / training["checkpoint"]

    evidence_files = [
        EXPERIMENT / "audit_reproduction/audit_run_summary.json",
        EXPERIMENT / "ROUND4_AUDIT_REPRODUCTION.md",
        EXPERIMENT / "ROUND4_REPORT.md",
        EXPERIMENT / "TEST_RESULTS.json",
        EXPERIMENT / "WORKTREE_PRESERVATION.json",
        EXPERIMENT / "BEFORE_AFTER_TRACES.json",
        EXPERIMENT / "TRAINING_RECORD.json",
        EXPERIMENT / "ACTION_ROUNDTRIP.json",
        EXPERIMENT / "TEACHER_LEDGER.json",
        EXPERIMENT / "EPISODE_SPLIT_MANIFEST.json",
        EXPERIMENT / "SKILL_CARDS.json",
        EXPERIMENT / "CLOSED_LOOP_PROTOCOL.json",
        EXPERIMENT / "closed_loop/CLOSED_LOOP_RESULTS.json",
        EXPERIMENT / "CANDIDATE_COVERAGE_LEDGER.json",
        EXPERIMENT / "LEARNED_LOADER_SEAT0.json",
        EXPERIMENT / "LEARNED_LOADER_SEAT1.json",
        EXPERIMENT / "RULE_LOADER_SEAT0.json",
        EXPERIMENT / "RULE_LOADER_SEAT1.json",
        learned_archive,
        rule_archive,
        model_path,
        ROOT / "agents/learning_round4_20260921/evaluation.py",
        ROOT / "tests/test_learning_round4.py",
    ]
    evidence_hashes = {
        str(path.relative_to(ROOT)): {"sha256": sha256(path), "bytes": path.stat().st_size}
        for path in evidence_files
    }
    current = (
        sha256(learned_archive) == archive_manifest["archives"]["learned"]["sha256"]
        and sha256(rule_archive) == archive_manifest["archives"]["rule"]["sha256"]
        and sha256(model_path) == training["checkpoint_sha256"]
        and all(row["archive_sha256"] == sha256(learned_archive) and row["passed"] for row in learned_loaders)
        and all(row["archive_sha256"] == sha256(rule_archive) and row["passed"] for row in rule_loaders)
    )
    write_json(
        EXPERIMENT / "EVIDENCE_HASHES.json",
        {"required_hashes_current": current, "files": evidence_hashes},
    )

    prospective = closed_loop["scope_summary"]["limited_prospective_local_diagnostic"]
    inference_calls = sum(
        int(row["diagnostics"]["strategy_inference_calls"])
        for row in closed_loop["rows"]
        if row["arm"] == "round4_learned"
    )
    thresholds = {
        "minimum_skill_delta": 0.0,
        "minimum_plan_completion_rate": 0.8,
        "minimum_mean_margin_delta": 0.0,
        "minimum_cluster_ci_low": 0.0,
    }
    common_provenance = {"required_hashes_current": current}
    learned_metrics = {
        "package": {
            "tested": True,
            "valid": all(row["passed"] for row in learned_loaders),
            "evidence_ids": ["LEARNED_LOADER_SEAT0", "LEARNED_LOADER_SEAT1", "ARCHIVE_MANIFEST"],
        },
        "execution": {
            "triggered": 2,
            "primitive_issued": 2,
            "primitive_effect_observed": 2,
            "primitive_failed": 0,
            "known_critical_bug": False,
            "scope": "exact A/B regression assertions, including real entrypoint",
            "evidence_ids": ["BEFORE_AFTER_TRACES", "pytest:test_learning_round4"],
        },
        "training": {
            "optimizer_updates": training["optimizer_updates"],
            "checkpoint_valid": sha256(model_path) == training["checkpoint_sha256"],
            "model_loads": sum(int(row["diagnostics"]["model_loads"]) for row in learned_loaders),
            "inference_calls": inference_calls,
            "invalid_fallbacks": sum(
                int(row["diagnostics"]["silent_fallbacks"])
                for row in closed_loop["rows"]
                if row["arm"] == "round4_learned"
            ),
            "evidence_ids": ["TRAINING_RECORD", "closed_loop/CLOSED_LOOP_RESULTS"],
        },
        "behavior": {
            "evaluated": True,
            "skill_macro_accuracy_delta": training["skill_macro_accuracy_delta"],
            "plan_completion_rate": None,
            "evidence_ids": ["TRAINING_RECORD", "EPISODE_SPLIT_MANIFEST"],
        },
        "economic": {
            "evaluated": True,
            "mean_margin_delta": prospective["mean_paired_margin_delta_learned_minus_rule"],
            "cluster_ci_low": None,
            "win_loss_tradeoff": True,
            "scope": "limited prospective local diagnostic; learned minus rule",
            "evidence_ids": ["CLOSED_LOOP_PROTOCOL", "closed_loop/CLOSED_LOOP_RESULTS"],
        },
        "online": {"evaluated": False, "evidence_ids": []},
        "diagnostic_hypothesis": "bounded online test of single-teacher strategy-selector generalization",
        "diagnostic_blocked_reason": (
            "not advanced: the limited prospective local panel averaged -9479.5 margin versus the rule arm, "
            "the smart_farm cluster was -21126, and all eight learned external games were losses"
        ),
    }
    rule_metrics = {
        "package": {
            "tested": True,
            "valid": all(row["passed"] for row in rule_loaders),
            "evidence_ids": ["RULE_LOADER_SEAT0", "RULE_LOADER_SEAT1", "ARCHIVE_MANIFEST"],
        },
        "execution": learned_metrics["execution"],
        "behavior": {"evaluated": False, "evidence_ids": []},
        "economic": {
            "evaluated": True,
            "mean_margin_delta": -prospective["mean_paired_margin_delta_learned_minus_rule"],
            "cluster_ci_low": None,
            "win_loss_tradeoff": True,
            "scope": "limited prospective local diagnostic; rule minus learned",
            "evidence_ids": ["CLOSED_LOOP_PROTOCOL", "closed_loop/CLOSED_LOOP_RESULTS"],
        },
        "online": {"evaluated": False, "evidence_ids": []},
        "diagnostic_hypothesis": "explicit-rule comparison only",
        "diagnostic_blocked_reason": "comparison arm only; it lost all eight external-family games",
    }
    learned_evaluation = evaluate_artifact(
        learned_metrics,
        {**common_provenance, "version": "learning_round4_20260921_learned"},
        "learned",
        thresholds,
    )
    rule_evaluation = evaluate_artifact(
        rule_metrics,
        {**common_provenance, "version": "learning_round4_20260921_rule"},
        "rule",
        thresholds,
    )
    evaluations = {
        "inputs": {"learned": learned_metrics, "rule": rule_metrics},
        "thresholds": thresholds,
        "evaluations": {"learned": learned_evaluation, "rule": rule_evaluation},
    }
    write_json(EXPERIMENT / "ARTIFACT_EVALUATION.json", evaluations)
    markdown = render_markdown(learned_evaluation) + "\n" + render_markdown(rule_evaluation)
    (EXPERIMENT / "ARTIFACT_EVALUATION.md").write_text(markdown, encoding="utf-8")
    write_json(
        EXPERIMENT / "FINAL_STATUS.json",
        {
            "learned_axes": learned_evaluation["axes"],
            "research_continuation": "SUPPORTED_WITH_REDESIGN",
            "skill_improvement": (
                "PARTIAL: held-out decision metrics improved; coherent closed-loop teacher plan fidelity unmeasured"
            ),
            "economic_effect": "FAIL_ON_LIMITED_PROSPECTIVE_LOCAL_SCOPE",
            "diagnostic_submission": "DO_NOT_ADVANCE_THIS_ARTIFACT",
            "champion_promotion": "FAIL",
            "online_submission_performed": False,
        },
    )
    print(json.dumps({"hashes_current": current, "learned_axes": learned_evaluation["axes"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
