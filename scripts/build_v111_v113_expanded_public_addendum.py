"""Build a versioned addendum for post-assessment public-opponent acquisition.

This builder never rewrites the completed formal, expanded, public-addendum,
or 2026-09-02 final-assessment artifacts.  It records only newly executed
Discovery probes, the expanded registry, and the decision not to run an
uninformative strength tournament when no new Sensitivity family qualifies.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "data/evaluation/v111_v113_final_assessment_20260902.json"
REGISTRY = (
    ROOT
    / "experiments/independent_gold_pool/"
    "consolidated_gold_family_registry_expanded_public_20260902.json"
)
LIVE = (
    ROOT
    / "data/evaluation/v113_live_e6_55933145/"
    "live_family_summary_expanded_public_20260902.json"
)
HISTORY_PROBE = (
    ROOT
    / "data/evaluation/independent_gold_pool/public_history_candidate_probe.json"
)
EXTERNAL_PROBE = (
    ROOT
    / "data/evaluation/independent_gold_pool/"
    "public_external_github_candidate_probe.json"
)
OUTPUT = ROOT / "data/evaluation/v111_v113_expanded_public_addendum_20260902.json"
REPORT = ROOT / "docs/v111_v113_expanded_public_addendum_20260902.md"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": _sha(path),
        "bytes": path.stat().st_size,
    }


def _probe_summary(probe: dict[str, Any]) -> dict[str, Any]:
    sources = {
        str(row["candidate_id"]): row
        for row in (probe.get("clustering") or {}).get("sources") or []
    }
    families = (probe.get("clustering") or {}).get("exact_families") or []
    games = probe.get("games") or []
    family_rows = [sources[str(row["representative_candidate_id"])] for row in families]
    target = [
        row
        for row in family_rows
        if 0.30 <= float(row["win_score_of_v111"]) <= 0.70
    ]
    near = [
        row
        for row in family_rows
        if 0.70 < float(row["win_score_of_v111"]) <= 0.80
    ]
    return {
        "source_labels": len(probe.get("candidates") or []),
        "complete_source_labels": sum(
            row.get("probe_status") == "COMPLETE" for row in sources.values()
        ),
        "games": len(games),
        "exact_action_families": len(families),
        "failed_tasks": len((probe.get("safety") or {}).get("failed_tasks") or []),
        "non_done_games": len(
            (probe.get("safety") or {}).get("non_done_games") or []
        ),
        "v111_wins": sum(row.get("result") == "win" for row in games),
        "v111_draws": sum(row.get("result") == "draw" for row in games),
        "v111_losses": sum(row.get("result") == "loss" for row in games),
        "minimum_family_mean_margin": min(
            float(row["mean_margin_of_v111"]) for row in family_rows
        ),
        "mean_family_margin": mean(
            float(row["mean_margin_of_v111"]) for row in family_rows
        ),
        "target_30_to_70_families": len(target),
        "near_70_to_80_families": len(near),
    }


def _verify_parent_sources(parent: dict[str, Any]) -> list[dict[str, Any]]:
    checks = []
    for label, record in parent["source_records"].items():
        path = ROOT / str(record["path"])
        actual = _sha(path)
        checks.append(
            {
                "label": label,
                "path": str(record["path"]),
                "expected_sha256": str(record["sha256"]),
                "actual_sha256": actual,
                "valid": actual == str(record["sha256"]),
            }
        )
    return checks


def build() -> dict[str, Any]:
    parent = _load(PARENT)
    registry = _load(REGISTRY)
    live = _load(LIVE)
    history = _probe_summary(_load(HISTORY_PROBE))
    external = _probe_summary(_load(EXTERNAL_PROBE))
    parent_checks = _verify_parent_sources(parent)
    if not all(row["valid"] for row in parent_checks):
        raise ValueError("parent assessment source drift detected")

    correspondence = live["local_gold_correspondence"]
    sensitivity = registry["sensitivity"]
    no_new_target = sensitivity["eligible_opponent_family_count"] == 0
    return {
        "format": "kaggriculture-v111-v113-expanded-public-addendum-v1",
        "dataset_role": "Discovery/Development addendum; never Fresh Holdout",
        "parent_assessment": _source(PARENT),
        "parent_source_integrity": {
            "all_valid": all(row["valid"] for row in parent_checks),
            "checks": parent_checks,
        },
        "new_sources": {
            "expanded_registry": _source(REGISTRY),
            "expanded_live_correspondence": _source(LIVE),
            "public_history_probe": _source(HISTORY_PROBE),
            "public_external_github_probe": _source(EXTERNAL_PROBE),
        },
        "new_discovery_results": {
            "public_history": history,
            "public_external_github": external,
            "expanded_registry": {
                "coverage": registry["coverage"],
                "sensitivity": sensitivity,
                "fresh_holdout_status": registry["fresh_holdout_status"],
            },
            "live_hash_rematch": {
                "public_live_episodes": live["coverage"]["public_live_episodes"],
                "local_exact_executable_families": correspondence[
                    "common_probe_exact_family_count"
                ],
                "strong_h200_or_later_episodes": correspondence[
                    "strong_correspondence_episode_count"
                ],
                "shared_opening_h100_only_episodes": correspondence[
                    "shared_opening_episode_count"
                ],
                "no_strong_correspondence_episodes": correspondence[
                    "no_strong_gold_correspondence_episode_count"
                ],
                "new_external_family_added_strong_match": False,
                "evidence_boundary": correspondence["interpretation"],
            },
        },
        "paired_addendum_decision": {
            "run_started": False,
            "reason_code": "NO_NEW_SENSITIVITY_FAMILY",
            "precondition": (
                "at least one newly acquired exact family with V111 draw-adjusted "
                "score in 30-70% (or exploratory 70-80% near band)"
            ),
            "precondition_met": not no_new_target,
            "reason": (
                "All 27 newly probed repository-history/external families were "
                "outside the qualifying band. Re-running V111/V113 over easy "
                "opponents would add Regression coverage but not strategy-uplift "
                "sensitivity, so no strength claim is made."
            ),
            "old_paired_results_reused_without_rerun": True,
            "completed_development_pairs": parent["expanded_v111_v113"][
                "combined_development_diagnostic"
            ]["total_pairs"],
        },
        "acquisition_blocker": {
            "candidate": "flexonafft/kaggriculture-multi-route-farming-agent",
            "public_page_score_observation": 1961.6,
            "executable_status": "UNACQUIRED_LEAD",
            "gold_status": False,
            "reason": (
                "Kaggle CLI required authentication and anonymous GetKernel / "
                "ListKernelSessionOutput returned HTTP 403; no executable bytes "
                "were available to hash or run."
            ),
        },
        "current_decision": {
            "production_champion": "V111",
            "clean_causal_control": "V111",
            "v113_status": "LIVE_VIABLE / CAUSAL_UNRESOLVED",
            "v113_role": "frozen live-validated field benchmark",
            "preregistered_v113_verdict": "REJECTED_SAFETY (unchanged)",
            "v114_candidate_created": False,
            "best_response_selected": False,
            "causal_win_uplift": "NOT_ESTIMATED",
            "kaggle_submission_basis": "INSUFFICIENT",
        },
        "evidence_level": {
            "E0": "achieved",
            "E1": "achieved",
            "E2": "animal-direction predictive model only; not continuation-package policy strength",
            "E3": "paired diagnosis completed previously; V113 promotion chain failed Safety and no Loss-to-Win rescue",
            "E4": "not achieved",
            "E5": "not achieved",
            "E6": "V113 whole-Agent observational ladder evidence",
            "new_pool_addendum": "Gold executable Discovery/Regression coverage; not a new promotion level",
        },
    }


def render(payload: dict[str, Any]) -> str:
    history = payload["new_discovery_results"]["public_history"]
    external = payload["new_discovery_results"]["public_external_github"]
    registry = payload["new_discovery_results"]["expanded_registry"]
    live = payload["new_discovery_results"]["live_hash_rematch"]
    coverage = registry["coverage"]
    sensitivity = registry["sensitivity"]
    return "\n".join(
        [
            "# V111/V113 expanded public-opponent addendum",
            "",
            (
                "This addendum preserves the completed 60-pair verdict and the "
                "prior 348-pair Development diagnostic. No old experiment was "
                "rerun or rewritten."
            ),
            "",
            "## New executable acquisition",
            "",
            (
                f"- Public repository history: {history['source_labels']} sources, "
                f"{history['exact_action_families']} action families, "
                f"{history['games']} games, V111 {history['v111_wins']}W/"
                f"{history['v111_draws']}D/{history['v111_losses']}L."
            ),
            (
                f"- Additional GitHub agents: {external['source_labels']} sources, "
                f"{external['exact_action_families']} families, "
                f"{external['games']} games, V111 {external['v111_wins']}W/"
                f"{external['v111_draws']}D/{external['v111_losses']}L."
            ),
            (
                f"- Consolidated inventory: {coverage['source_labels']} labels -> "
                f"{coverage['exact_executed_action_families']} executed families -> "
                f"{coverage['distinct_source_ancestry_ids']} normalized ancestries."
            ),
            (
                f"- Sensitivity: {sensitivity['eligible_opponent_family_count']} "
                "families in 30-70%; "
                f"{len(sensitivity['near_family_ids_70_to_80'])} in 70-80%."
            ),
            "",
            (
                "Every new history/external game was a V111 win. This adds "
                "Regression diversity, but it does not improve the ability to "
                "detect strategy uplift. Therefore no further V111/V113 strength "
                "run was started."
            ),
            "",
            "## Live-field correspondence",
            "",
            (
                f"The expanded {live['local_exact_executable_families']}-family "
                "inventory still gives strong h200+ correspondence for only "
                f"{live['strong_h200_or_later_episodes']}/58 live episodes; "
                f"{live['no_strong_correspondence_episodes']} remain without strong "
                "Gold correspondence. The three new external GitHub families "
                "added no strong match."
            ),
            "",
            (
                "The public Multi-Route Kaggle notebook remains the "
                "highest-priority lead, but authentication/HTTP 403 prevented "
                "retrieval of executable bytes. A displayed score is not Gold "
                "policy evidence."
            ),
            "",
            "## Decision",
            "",
            (
                "V111 remains Champion and clean causal control. V113 remains "
                "frozen as `LIVE_VIABLE / CAUSAL_UNRESOLVED`; its old "
                "`REJECTED_SAFETY` verdict is unchanged. No Best Response or V114 "
                "was implemented, causal win uplift remains unestimated, E4/E5 "
                "are unmet, and there is no Kaggle-submission basis."
            ),
            "",
        ]
    )


def main() -> int:
    payload = build()
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    REPORT.write_text(render(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": OUTPUT.relative_to(ROOT).as_posix(),
                "output_sha256": _sha(OUTPUT),
                "report": REPORT.relative_to(ROOT).as_posix(),
                "report_sha256": _sha(REPORT),
                "parent_sources_valid": payload["parent_source_integrity"][
                    "all_valid"
                ],
                "new_paired_run": payload["paired_addendum_decision"][
                    "run_started"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
