"""Build final Round11 registries from immutable inputs and executed result files."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "experiments/round11_execution_20260924"
PACKAGE = ROOT / "experiments/Kaggriculture_Round11_Research_Revision_20260924"

SOURCES = {
    "more_wheat": "dmitriigluzdov__kaggriculture-more-wheat-smarter-sales",
    "order_book_v3": "arsgorynich__order-book-v3-response-improvement",
    "moon": "prvsiyan__kaggriculture-frontier-the-moon-counts-melons",
    "v15stack": "wzhengbiao__kaggriculture-v15stack-submit",
    "wonderful": "hanifnoerrofiq__a-wonderful-life",
    "master_hybrid": "haideptry__the-2965-master-hybrid-engine",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def json_file(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    generated = json_file(WORK / "arms/generated_manifest.json")
    static_audit = json_file(WORK / "sources/STATIC_AUDIT.json")
    audit_by_hash = {row["sha256"]: row for row in static_audit["agents"]}
    track_a = {row["arm"]: row for row in csv_rows(WORK / "track_a/screen_kagsim/panel_summary.csv")}
    sources = []
    for arm, slug_dir in SOURCES.items():
        raw_dir = WORK / "sources/raw/kaggle" / slug_dir
        acquisition = json_file(raw_dir / "acquisition_result.json")
        extraction = json_file(WORK / "sources/extracted_static" / arm / "extraction_result.json")
        agent = extraction["agents"][0]
        source_path = WORK / "sources/extracted_static" / arm / agent["path"]
        audit = audit_by_hash[agent["sha256"]]
        result = track_a[arm]
        only_open_branch = (
            len(audit["risky_calls"]) == 1
            and audit["risky_calls"][0]["call"] == "open"
            and "path = None  # Frozen offline build" in source_path.read_text(encoding="utf-8")
            and "if path:" in source_path.read_text(encoding="utf-8")
        )
        literal_execs_safe = all(
            row["call"] == "exec" and row["literal"] and row["literal_parseable_python"]
            for row in audit["dynamic_execution"]
        )
        sources.append(
            {
                "id": arm,
                "kaggle_ref": acquisition["kernel"],
                "original_url": "https://www.kaggle.com/code/" + acquisition["kernel"],
                "api_acquisition_url": acquisition["url"],
                "title": acquisition["metadata"].get("title"),
                "author": acquisition["metadata"].get("author"),
                "original_version": acquisition["metadata"].get("currentVersionNumber"),
                "original_last_run_utc": acquisition["metadata"].get("lastRunTime"),
                "fetched_at_utc": acquisition["fetched_at_utc"],
                "raw_response": {
                    "path": relative(raw_dir / "kernels_pull_response.json"),
                    "sha256": acquisition["response_sha256"],
                    "bytes": acquisition["response_bytes"],
                },
                "payloads": acquisition["payloads"],
                "executed_source": {
                    "path": relative(source_path),
                    "sha256": agent["sha256"],
                    "bytes": agent["bytes"],
                    "last_callable": agent["last_top_level_function"],
                    "expected_notebook_hash_match": agent["expected_hash_match"],
                },
                "license": "Apache-2.0 SPDX found in extracted source; bundle includes package NOTICE and Apache license",
                "execution_safety": {
                    "conservative_static_scanner_pass": audit["static_audit_pass"],
                    "external_io_imports": audit["external_io_imports"],
                    "literal_execs_parseable_and_hashed": literal_execs_safe,
                    "only_flagged_open_is_disabled_path_none_branch": only_open_branch,
                    "reviewed_local_execution_allowed": not audit["external_io_imports"]
                    and literal_execs_safe
                    and only_open_branch,
                },
                "usage": "executed unchanged as loader-selected standalone policy in Track A",
                "local_track_a": {
                    "games": int(result["games"]),
                    "wins": int(result["wins"]),
                    "losses": int(result["losses"]),
                    "ties": int(result["ties"]),
                    "score_rate": float(result["score_rate"]),
                    "mean_margin": float(result["mean_margin"]),
                    "mean_delta_points_vs_b1": float(result["mean_delta_points_vs_b1"]),
                    "mean_delta_margin_vs_b1": float(result["mean_delta_margin_vs_b1"]),
                    "decision": "not promoted",
                },
                "lineage_note": "Farm-route measurements match B1 (strawberry day 5, 33 tiles); names are not counted as independent production families.",
            }
        )

    b1_archive = ROOT / "artifacts/submissions/round10_20260924_b1_herd_safe.tar.gz"
    b1_main = PACKAGE / "inputs/agents/B1.py"
    official_engine = ROOT / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py"
    source_registry = {
        "schema": "round11-source-registry-v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "baseline": {
            "id": "B1",
            "archive_path": relative(b1_archive),
            "archive_sha256": sha256(b1_archive),
            "main_path": relative(b1_main),
            "main_sha256": sha256(b1_main),
            "last_callable": "opening_liquidity_agent",
            "public_submission_id": 56509493,
        },
        "official_reference": {
            "commit": "302d8e20c83822b8d4572975cdea1180b792b748",
            "git_blob": "3c202c7ee921da239356789e266b694635103fc4",
            "installed_path": relative(official_engine),
            "installed_sha256": sha256(official_engine),
            "version": "1.32.7",
        },
        "inherited_raw_inputs": [
            {
                "meaning": "downloaded public submission 56509493 raw ZIP",
                "path": "data/submissions/round10_b1_herd_safe_submission_56509493.zip",
                "sha256": sha256(ROOT / "data/submissions/round10_b1_herd_safe_submission_56509493.zip"),
            },
            {
                "meaning": "original Round10 research bundle",
                "path": "experiments/round10_public_learning_20260924.zip",
                "sha256": sha256(ROOT / "experiments/round10_public_learning_20260924.zip"),
            },
        ],
        "public_sources": sources,
        "notes": [
            "Kaggle CLI help was checked; public API pull was used only after unauthenticated CLI pull could not authenticate.",
            "Raw notebook/script responses, payloads, extracted sources and hashes remain under sources/.",
            "No downloaded notebook builder was executed; extraction was literal/static before reviewed policy execution.",
        ],
    }
    write(WORK / "SOURCE_REGISTRY.json", source_registry)

    panels = {
        "track_a_public_originals": WORK / "track_a/screen_kagsim",
        "track_b_market_2x2": WORK / "track_b/market_kagsim",
        "track_b_conditional_wool": WORK / "track_b/conditional_wool_kagsim",
        "holdout_m20": WORK / "holdout/m20_kagsim",
    }
    coverage_panels = {}
    for panel_id, panel in panels.items():
        rows = csv_rows(panel / "games.csv")
        keys = {(r["arm"], r["opponent_id"], r["seed"], r["seat"]) for r in rows}
        coverage_panels[panel_id] = {
            "path": relative(panel),
            "games": len(rows),
            "unique_cells": len(keys),
            "errors": sum(bool(r.get("error")) for r in rows),
            "engines": sorted({r["engine"] for r in rows}),
            "agent_hashes": sorted({r["agent_sha256"] for r in rows}),
            "opponent_hashes": sorted({r["opponent_sha256"] for r in rows}),
        }
    official_panels = {}
    for panel_id in ("no_change_official", "more_wheat_official_parity", "m20_official_parity"):
        panel = WORK / "phase0" / panel_id
        rows = csv_rows(panel / "games.csv")
        official_panels[panel_id] = {
            "games": len(rows),
            "errors": sum(bool(r.get("error")) for r in rows),
            "path": relative(panel),
        }
    coverage = {
        "schema": "round11-experiment-coverage-v1",
        "new_cppsim_games": sum(row["games"] for row in coverage_panels.values()),
        "new_official_python_games": sum(row["games"] for row in official_panels.values()),
        "panels": coverage_panels,
        "official_panels": official_panels,
        "inherited_revision_panel": {
            "games": 128,
            "unique_complete_games": 128,
            "status": "package verify PASS; treated as development evidence, never reused as holdout",
        },
        "training_runs": 0,
        "kaggle_submissions": 0,
        "notebook_publications": 0,
        "external_pushes": 0,
    }
    write(WORK / "EXPERIMENT_COVERAGE.json", coverage)

    market = {row["arm"]: row for row in csv_rows(WORK / "track_b/market_kagsim/panel_summary.csv")}
    conditional = {
        row["arm"]: row for row in csv_rows(WORK / "track_b/conditional_wool_kagsim/panel_summary.csv")
    }
    holdout = json_file(WORK / "holdout/HOLDOUT_DECISION.json")
    arms = [
        {
            "arm": "B1",
            "sha256": sha256(b1_main),
            "last_callable": "opening_liquidity_agent",
            "status": "retained baseline / final local choice",
            "effective_diff": "none",
        }
    ]
    for variant in generated["variants"]:
        arm = variant["arm"]
        record = {
            **variant,
            "last_callable": variant.pop("last_top_level_function", None),
            "effective_diff": variant["changes"],
            "status": "diagnostic only / not promoted",
        }
        if arm in market:
            record["development"] = {
                key: float(market[arm][key])
                for key in ("score_rate", "mean_delta_points_vs_b1", "mean_delta_margin_vs_b1")
            }
            record["final_action_changed_decisions"] = int(market[arm]["changed_decisions_vs_b1"])
        if arm in conditional:
            record["development"] = {
                key: float(conditional[arm][key])
                for key in ("score_rate", "mean_delta_points_vs_b1", "mean_delta_margin_vs_b1")
            }
            record["final_action_changed_decisions"] = int(conditional[arm]["changed_decisions_vs_b1"])
        if arm == "m20_multi_hypothesis":
            record["holdout"] = holdout
            record["status"] = "REJECT: failed frozen substantive holdout gates"
        elif arm == "cw1_conditional_wool":
            record["status"] = "REJECT: internal reservations fired but final actions remained identical"
        elif arm == "wool_gate_open_control":
            record["status"] = "REJECT: unconditional diagnostic reduced development score"
        arms.append(record)
    arm_registry = {
        "schema": "round11-arm-registry-v1",
        "baseline_sha256": sha256(b1_main),
        "arms": arms,
        "public_original_arms": [
            {
                "arm": arm,
                "sha256": next(s["executed_source"]["sha256"] for s in sources if s["id"] == arm),
                "status": "not promoted",
                "track_a": source["local_track_a"],
            }
            for arm in SOURCES
            for source in sources
            if source["id"] == arm
        ],
    }
    write(WORK / "ARM_REGISTRY.json", arm_registry)

    actual_m20_hashes = sorted(
        {
            row["agent_sha256"]
            for panel in (WORK / "track_b/market_kagsim", WORK / "holdout/m20_kagsim")
            for row in csv_rows(panel / "games.csv")
            if row["arm"] == "m20_multi_hypothesis"
        }
    )
    hash_audit = {
        "schema": "round11-holdout-hash-audit-v1",
        "protocol_declared_hash": json_file(WORK / "holdout/ACCEPTANCE_PROTOCOL.json")["candidate_sha256"],
        "actual_candidate_hashes_in_development_and_holdout": actual_m20_hashes,
        "current_candidate_hash": sha256(WORK / "arms/m20_multi_hypothesis/main.py"),
        "official_parity_candidate_hash": next(
            row["agent_sha256"]
            for row in csv_rows(WORK / "phase0/m20_official_parity/games.csv")
            if row["arm"] == "m20_multi_hypothesis"
        ),
        "finding": "The protocol hash was transcribed incorrectly; the fixed path executed the same actual hash in development, official parity and holdout. Coverage correctly failed. No correction was used to reverse the REJECT decision.",
    }
    write(WORK / "HASH_AUDIT.json", hash_audit)

    model_usage = {
        "schema": "round11-model-usage-v1",
        "training_performed": False,
        "training_updates": 0,
        "saved_weight_files": [],
        "reload_tests": 0,
        "model_inferences": 0,
        "model_candidate_selections": 0,
        "model_final_action_changes": 0,
        "reason": "Executable rule-based interventions were available; prior inherited ranker had zero selections and the selected M20 rule failed holdout, so extending the old imbalanced model was not justified.",
    }
    write(WORK / "MODEL_USAGE.json", model_usage)
    print(json.dumps({"sources": len(sources), "arms": len(arms), "coverage": coverage}, indent=2))


if __name__ == "__main__":
    main()
