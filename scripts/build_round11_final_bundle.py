"""Assemble the audited Round11 research bundle and representative replays."""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
import argparse
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "experiments/round11_execution_20260924"
PACKAGE = ROOT / "experiments/Kaggriculture_Round11_Research_Revision_20260924"
ARTIFACTS = ROOT / "artifacts/research"
STAGE = ARTIFACTS / "Kaggriculture_Round11_Execution_20260924"
ZIP_PATH = ARTIFACTS / "Kaggriculture_Round11_Execution_20260924.zip"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def copy(source: Path, destination: str, records: list[dict[str, object]], category: str) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    target = STAGE / destination
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    records.append(
        {
            "path": target.relative_to(STAGE).as_posix(),
            "source": source.relative_to(ROOT).as_posix(),
            "category": category,
            "bytes": target.stat().st_size,
            "sha256": sha256(target),
        }
    )


def copy_tree(source: Path, destination: str, records: list[dict[str, object]], category: str) -> None:
    for path in sorted(source.rglob("*")):
        if path.is_file():
            copy(path, str(Path(destination) / path.relative_to(source)), records, category)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="refresh only this script's existing final artifact")
    args = parser.parse_args()
    if (STAGE.exists() or ZIP_PATH.exists()) and not args.refresh:
        raise FileExistsError("final stage or ZIP already exists; preserve it or remove it explicitly before rebuilding")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    STAGE.mkdir(exist_ok=args.refresh)
    records: list[dict[str, object]] = []

    for name in (
        "README.md", "REPORT_JA.md", "FINAL_STATUS.json", "SOURCE_REGISTRY.json",
        "ARM_REGISTRY.json", "EFFECTIVE_DIFFS.md", "EXPERIMENT_COVERAGE.json",
        "MODEL_USAGE.json", "HASH_AUDIT.json", "REPRODUCE.md",
    ):
        copy(WORK / name, name, records, "final-document")

    for name in (
        "README_JA.md", "REPORT_JA.md", "SOURCE_MAP_JA.md", "EXPERIMENT_PLAN_JA.md",
        "CHECKLIST_JA.md", "NOTICE.txt", "THIRD_PARTY_APACHE_2_LICENSE.txt",
    ):
        copy(PACKAGE / name, f"input_revision/{name}", records, "input-revision")
    copy(PACKAGE / "inputs/agent_manifest.json", "input_revision/inputs/agent_manifest.json", records, "input-revision")
    for name in ("B1.py", "v57.py", "order_book.py", "metav4.py"):
        copy(PACKAGE / "inputs/agents" / name, f"input_revision/inputs/agents/{name}", records, "input-agent")
    for name in (
        "EXECUTION_SCOPE.json", "development_protocol.json", "development_summary.json",
        "development_game_results.csv", "development_paired_comparisons.csv",
        "development_panel_summary.csv", "online_extended_summary.json",
        "online_floor_ledger_by_item.csv", "online_floor_cases.csv",
        "case_112752873_cost_decomposition.csv", "case_112752873_revenue_decomposition.csv",
        "case_112752873_growth_and_cash.csv", "land_and_crop_route_check.json",
        "cppsim_raw_parity_3.json",
    ):
        copy(PACKAGE / "evidence" / name, f"input_revision/evidence/{name}", records, "input-evidence")
    for name in ("case_112748339_three_turn_fixed_action_window.json", "case_112748339_prices_and_quantities.csv"):
        copy(PACKAGE / "inputs/prior_audit" / name, f"input_revision/inputs/prior_audit/{name}", records, "input-evidence")

    copy_tree(WORK / "sources/raw", "sources/raw", records, "public-source-raw")
    copy_tree(WORK / "sources/extracted_static", "sources/extracted_static", records, "public-source-extracted")
    copy(WORK / "sources/STATIC_AUDIT.json", "sources/STATIC_AUDIT.json", records, "source-audit")
    copy_tree(WORK / "arms", "arms", records, "experimental-arm")
    copy_tree(WORK / "configs", "configs", records, "experiment-config")

    result_names = (
        "preregistration.json", "games.csv", "summary.csv", "paired_results.csv",
        "panel_summary.csv", "seed_block_summary.csv", "telemetry_summary.csv",
        "telemetry_summary.json", "production_routes_per_game.csv",
        "production_routes_summary.json",
    )
    for source_name, panel in {
        "track_a": WORK / "track_a/screen_kagsim",
        "track_b_market": WORK / "track_b/market_kagsim",
        "track_b_conditional_wool": WORK / "track_b/conditional_wool_kagsim",
        "holdout_m20": WORK / "holdout/m20_kagsim",
    }.items():
        for name in result_names:
            path = panel / name
            if path.is_file():
                copy(path, f"results/{source_name}/{name}", records, "result-table")
    copy(WORK / "holdout/ACCEPTANCE_PROTOCOL.json", "results/holdout_m20/ACCEPTANCE_PROTOCOL.json", records, "protocol")
    copy(WORK / "holdout/HOLDOUT_DECISION.json", "results/holdout_m20/HOLDOUT_DECISION.json", records, "decision")

    copy_tree(WORK / "phase0", "results/phase0", records, "phase0-evidence")

    representative = [
        ("holdout/m20_kagsim/replays/B1/B1/seed_612609250_seat_1.json.gz", "m20_improvement_baseline.json.gz"),
        ("holdout/m20_kagsim/replays/m20_multi_hypothesis/B1/seed_612609250_seat_1.json.gz", "m20_improvement_candidate.json.gz"),
        ("holdout/m20_kagsim/replays/B1/v57/seed_612609254_seat_0.json.gz", "m20_regression_baseline.json.gz"),
        ("holdout/m20_kagsim/replays/m20_multi_hypothesis/v57/seed_612609254_seat_0.json.gz", "m20_regression_candidate.json.gz"),
        ("holdout/m20_kagsim/replays/B1/B1/seed_612609245_seat_0.json.gz", "m20_no_effect_baseline.json.gz"),
        ("holdout/m20_kagsim/replays/m20_multi_hypothesis/B1/seed_612609245_seat_0.json.gz", "m20_no_effect_candidate.json.gz"),
        ("track_b/conditional_wool_kagsim/replays/B1/B1/seed_532609243_seat_0.json.gz", "wool_baseline.json.gz"),
        ("track_b/conditional_wool_kagsim/replays/wool_gate_open_control/B1/seed_532609243_seat_0.json.gz", "wool_unconditional_regression.json.gz"),
        ("track_b/conditional_wool_kagsim/replays/cw1_conditional_wool/B1/seed_532609243_seat_0.json.gz", "wool_conditional_no_final_effect.json.gz"),
        ("track_a/screen_kagsim/replays/B1/B1/seed_512609241_seat_0.json.gz", "production_b1.json.gz"),
        ("track_a/screen_kagsim/replays/wonderful/B1/seed_512609241_seat_0.json.gz", "production_wonderful_rejected.json.gz"),
    ]
    for source, name in representative:
        copy(WORK / source, f"representative_replays/{name}", records, "representative-replay")

    scripts = (
        "acquire_round11_public_sources.py", "extract_round11_public_agents.py",
        "audit_round11_agents.py", "build_round11_variants.py", "evaluate_round10_panel.py",
        "verify_round11_no_change.py", "verify_round11_engine_parity.py",
        "summarize_round11_panel.py", "summarize_round11_telemetry.py",
        "analyze_round11_production_routes.py", "decide_round11_holdout.py",
        "build_round11_registries.py", "build_round11_final_bundle.py",
        "verify_round11_final_bundle.py",
    )
    for name in scripts:
        copy(ROOT / "scripts" / name, f"scripts/{name}", records, "reproduction-script")

    copy(ROOT / "artifacts/submissions/round10_20260924_b1_herd_safe.tar.gz", "retained_baseline/round10_20260924_b1_herd_safe.tar.gz", records, "retained-baseline")
    copy(ROOT / "data/submissions/round10_b1_herd_safe_submission_56509493.zip", "retained_baseline/round10_b1_herd_safe_submission_56509493.zip", records, "public-submission-raw")

    manifest = {
        "schema": "kaggriculture-round11-final-bundle-manifest-v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "decision": "KEEP_B1",
        "new_candidate_archive_included": False,
        "retained_baseline_archive_sha256": "3fff94ec235566fff3416627d2691dec2e502bc80646a9016ee15e6fc2067986",
        "files_excluding_this_manifest": len(records),
        "bytes_excluding_this_manifest": sum(int(row["bytes"]) for row in records),
        "files": sorted(records, key=lambda row: str(row["path"])),
        "replay_scope": "All result tables and hashes; selected raw good/bad/no-effect/production replays. Full 864-game raw replay tree remains in the workspace.",
    }
    manifest_path = STAGE / "BUNDLE_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(STAGE.rglob("*")):
            if path.is_file():
                archive.write(path, Path(STAGE.name) / path.relative_to(STAGE))
    final = {
        "schema": "kaggriculture-round11-final-bundle-v1",
        "stage_path": STAGE.relative_to(ROOT).as_posix(),
        "zip_path": ZIP_PATH.relative_to(ROOT).as_posix(),
        "zip_sha256": sha256(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "bundle_manifest_sha256": sha256(manifest_path),
        "files_including_manifest": len(records) + 1,
    }
    (WORK / "FINAL_BUNDLE.json").write_text(
        json.dumps(final, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(final, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
