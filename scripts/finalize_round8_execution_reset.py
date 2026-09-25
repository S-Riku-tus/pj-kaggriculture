"""Finalize the Round8 registry, manifest, deliverable ZIP, and extraction audit."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "round8_execution_reset_20260922"
PHASE_C = EXPERIMENT / "phase_c_spatial"
OUTPUT = ROOT / "artifacts" / "submissions"
REGISTRY = EXPERIMENT / "EXPERIMENT_REGISTRY.json"
MANIFEST = EXPERIMENT / "ARTIFACT_MANIFEST.json"
DELIVERABLE = Path(r"C:\Users\shiba\Kaggle\Kaggriculture_Round8_execution_reset_results_20260922.zip")
VERIFY_ROOT = Path(r"C:\Users\shiba\Kaggle\Kaggriculture_Round8_execution_reset_results_20260922_verify")
INPUT_ZIP = Path(r"C:\Users\shiba\Downloads\Kaggriculture_Round7_Online_Reanalysis_and_Round8_20260922.zip")
AUDIT_ROOT = Path(r"C:\Users\shiba\Kaggle\round8_reanalysis_input_20260922\round7_online_reanalysis")
ENGINE_DIR = ROOT / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture"
LOADER = ROOT / ".venv/Lib/site-packages/kaggle_environments/agent.py"

ARCHIVES = {
    "round1_b_reference": OUTPUT / "learning_next_20260921_b_learned_fixed_v3.tar.gz",
    "round5_reference": OUTPUT / "learning_round5_20260921_learned.tar.gz",
    "f0_round7_original": OUTPUT / "learning_round7_20260922_arm_b_plan_v3.tar.gz",
    "f1_harvest": OUTPUT / "round8_execution_reset_20260922_f1_harvest_v4.tar.gz",
    "f2_consistent": OUTPUT / "round8_execution_reset_20260922_f2_consistent_v4.tar.gz",
    "f2_no_plan": OUTPUT / "round8_execution_reset_20260922_f2_no_plan_v4.tar.gz",
    "spatial_pure_v6": OUTPUT / "round8_spatial_bc_20260922_seed20260922_pure_v6.tar.gz",
    "spatial_hybrid_v6": OUTPUT / "round8_spatial_bc_20260922_seed20260922_hybrid_v6.tar.gz",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_new(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def file_record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        label = str(path.relative_to(ROOT))
    except ValueError:
        label = str(path)
    return {"path": label, "bytes": path.stat().st_size, "sha256": sha256(path)}


def evaluation_result(directory: Path) -> dict[str, Any]:
    summary_path = directory / "summary.json"
    summary = load(summary_path)
    return {
        "summary": file_record(summary_path),
        "games": summary["completed_games"],
        "wins_draws_losses": summary["wins_draws_losses"],
        "mean_our_cash": summary["mean_our_cash"],
        "mean_margin": summary["mean_margin"],
        "failures": len(summary["failures"]),
        "sealed_seeds_opened": summary["sealed_seeds_opened"],
    }


def main() -> None:
    if DELIVERABLE.exists() or VERIFY_ROOT.exists():
        raise FileExistsError(f"refusing to overwrite {DELIVERABLE} or {VERIFY_ROOT}")
    required = [*ARCHIVES.values(), INPUT_ZIP, EXPERIMENT / "REPORT_JA.md"]
    required.extend(
        AUDIT_ROOT / name
        for name in (
            "REPORT_JA.md",
            "evidence/findings.json",
            "evidence/focused_checks.json",
            "evidence/artifact_identity.json",
        )
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(missing)

    reaggregation_path = EXPERIMENT / "independent_closed_loop_reaggregation_v1.json"
    reaggregation = load(reaggregation_path)
    engine = ENGINE_DIR / "kaggriculture.py"
    opponents = {
        "v122": file_record(OUTPUT / "v122.tar.gz"),
        "v124": file_record(OUTPUT / "v124.tar.gz"),
    }
    phase_b_dirs = {
        "f0_round7_original": EXPERIMENT / "phase_b_f0",
        "f1_harvest": EXPERIMENT / "phase_b_f1",
        "f2_consistent": EXPERIMENT / "phase_b_f2",
        "f2_no_plan": EXPERIMENT / "phase_b_f2_no_plan",
    }
    phase_c_dirs = {
        "spatial_pure_v6": PHASE_C / "pilot_pure_v6",
        "spatial_hybrid_v6": PHASE_C / "pilot_hybrid_v6",
    }
    hypotheses = {
        "f0_round7_original": "frozen Round7 behavior reference; no code or weight change",
        "f1_harvest": "animal harvest inclusion plus mature-crop contract alone repairs lost yield opportunities",
        "f2_consistent": "post-plan sequential resolution removes over-reservation and no-effect final actions",
        "f2_no_plan": "separates repaired learned decoder from the handwritten livestock plan",
        "spatial_pure_v6": (
            "position-sensitive inputs plus target-task day-0 recovery can sustain an independent BC economy"
        ),
        "spatial_hybrid_v6": (
            "same learned checkpoints with explicit handwritten livestock plan quantifies hybrid rescue"
        ),
    }
    scopes = {
        "f0_round7_original": "none",
        "f1_harvest": "legality contract only; frozen Round7 checkpoints",
        "f2_consistent": "full contract, plan-endgame, sequential final resolver; frozen Round7 checkpoints",
        "f2_no_plan": "F2 resolver with plan disabled; frozen Round7 checkpoints",
        "spatial_pure_v6": "new encoder, four newly trained heads, F2 decoder, plan disabled",
        "spatial_hybrid_v6": "spatial pure plus handwritten livestock plan",
    }
    arms = []
    for name, directory in {**phase_b_dirs, **phase_c_dirs}.items():
        independent_name = {
            "f0_round7_original": "phase_b_f0",
            "f1_harvest": "phase_b_f1",
            "f2_consistent": "phase_b_f2",
            "f2_no_plan": "phase_b_f2_no_plan",
        }.get(name, name)
        independent = reaggregation["summaries"][independent_name]
        arms.append(
            {
                "arm": name,
                "hypothesis": hypotheses[name],
                "change_scope": scopes[name],
                "archive": file_record(ARCHIVES[name]),
                "engine": file_record(engine),
                "opponents": opponents,
                "seeds": [2026102201, 2026102202],
                "seats": [0, 1],
                "evaluation": evaluation_result(directory),
                "independent_reaggregation": independent,
                "promotion_eligible": False,
            }
        )
    model_runs = {}
    for seed in (20260922, 20260923):
        path = PHASE_C / "models_v5" / f"seed_{seed}" / "training_summary.json"
        value = load(path)
        model_runs[str(seed)] = {
            "summary": file_record(path),
            "models": {
                name: {
                    "checkpoint_sha256": model["sha256"],
                    "architecture": model["architecture"],
                    "optimizer_steps_total": model["optimizer_steps_total"],
                    "optimizer_steps_at_checkpoint": model["optimizer_steps_at_checkpoint"],
                    "best_epoch": model["best_epoch"],
                    "validation_accuracy": model["validation"]["accuracy"],
                    "test_accuracy": model["test"]["accuracy"],
                }
                for name, model in value["models"].items()
            },
            "reload_and_inference": value["reload_and_inference"],
        }
    excluded_archives = sorted(
        [
            path
            for path in OUTPUT.glob("round8_execution_reset_20260922_*.tar.gz")
            if path not in ARCHIVES.values()
        ]
        + [path for path in OUTPUT.glob("round8_spatial_bc_20260922_*.tar.gz") if path not in ARCHIVES.values()]
    )
    registry = {
        "experiment": "round8_execution_reset_20260922",
        "created_at_utc": utc_now(),
        "objective": (
            "repair concrete execution defects, actually train a position-sensitive independent BC, "
            "and evaluate closed loop"
        ),
        "safeguards": {
            "kaggle_submissions_created": 0,
            "sealed_seed_range_used": False,
            "existing_success_archives_overwritten": False,
            "existing_checkpoints_overwritten": False,
            "dirty_changes_discarded": False,
        },
        "input_audit": {
            "zip": file_record(INPUT_ZIP),
            "report": file_record(AUDIT_ROOT / "REPORT_JA.md"),
            "findings": file_record(AUDIT_ROOT / "evidence/findings.json"),
            "focused_checks": file_record(AUDIT_ROOT / "evidence/focused_checks.json"),
            "artifact_identity": file_record(AUDIT_ROOT / "evidence/artifact_identity.json"),
        },
        "frozen_references": {name: file_record(path) for name, path in ARCHIVES.items() if "reference" in name},
        "fixed_engine": {
            "version": "1.32.7",
            "engine": file_record(engine),
            "loader": file_record(LOADER),
            "config": file_record(ENGINE_DIR / "kaggriculture.json"),
            "copied_engine": file_record(EXPERIMENT / "fixed_engine/kaggriculture.py"),
        },
        "criteria": {
            "development": "v122/v124 x 2 seeds x both seats = 8 games per arm",
            "promotion_to_32": "only candidates improved on development; none qualified",
            "win_rate_language": "8 games are a diagnostic, not a statistically significant estimate",
            "economic_and_win_promotion_separated": True,
        },
        "contract_fixtures": file_record(EXPERIMENT / "fixtures/engine_contracts_v2.json"),
        "arms": arms,
        "spatial_training": {
            "teacher_submission": 56216119,
            "teacher_family_count": 1,
            "dataset": file_record(PHASE_C / "dataset_v2/dataset_manifest.json"),
            "split": {"train_episodes": 12, "validation_episodes": 4, "test_episodes": 4},
            "overfit_v1_failed": file_record(PHASE_C / "overfit_probe/result.json"),
            "overfit_v2_passed": file_record(PHASE_C / "overfit_probe_v2/result.json"),
            "model_runs": model_runs,
            "selected_archive_version": "v6",
            "classification": {
                "spatial_pure_v6": "independent BC plus execution-safety decoder",
                "spatial_hybrid_v6": "hybrid; handwritten livestock plan materially controls actions",
            },
        },
        "change_history": [
            {"version": "spatial v1/v2", "result": "market trained only on even steps; step-1 HIRE omitted"},
            {"version": "spatial v3", "result": "all market steps, weighted token loss; extra initial animal orders"},
            {"version": "spatial v4", "result": "unweighted market token; HIRE repeated seven times"},
            {"version": "spatial v5", "result": "day-0 market recovery; actor diverged at record 2"},
            {"version": "spatial v6", "result": "day-0 actor+market recovery; selected development artifact"},
        ],
        "excluded_non_candidates": [file_record(path) for path in excluded_archives],
        "final_decisions": {
            "implementation_success": True,
            "learning_updates_performed": True,
            "execution_consistency_improved": True,
            "research_economic_improvement": "hybrid-only versus spatial pure; not versus F0",
            "stronger_than_baseline": False,
            "submission_ready": False,
        },
    }
    write_new(REGISTRY, registry)

    package_sources: dict[str, Path] = {}

    def add(path: Path, archive_name: str | None = None) -> None:
        if not path.is_file():
            raise FileNotFoundError(path)
        name = archive_name or str(path.relative_to(ROOT)).replace("\\", "/")
        if name in package_sources and package_sources[name] != path:
            raise RuntimeError(f"duplicate package name {name}")
        package_sources[name] = path

    for path in EXPERIMENT.rglob("*"):
        if path.is_file() and path != MANIFEST:
            add(path)
    for path in (ROOT / "agents/round8_execution_reset_20260922").glob("*.py"):
        add(path)
    for name in (
        "package_round8_execution_reset.py",
        "run_round8_contract_fixtures.py",
        "train_round8_spatial_bc.py",
        "package_round8_spatial_bc.py",
        "evaluate_round8_spatial_horizons.py",
        "audit_round8_closed_loop.py",
        "finalize_round8_execution_reset.py",
    ):
        add(ROOT / "scripts" / name)
    add(ROOT / "tests/test_round8_execution_reset.py")
    for path in ARCHIVES.values():
        add(path)
    for path in excluded_archives:
        add(path)
    add(ROOT / "experiments/learning_next_20260921/source_manifest.json")
    add(ROOT / "experiments/learning_next_20260921/split_manifest.json")
    add(INPUT_ZIP, "external/input/Kaggriculture_Round7_Online_Reanalysis_and_Round8_20260922.zip")
    for path in (
        AUDIT_ROOT / "REPORT_JA.md",
        AUDIT_ROOT / "evidence/findings.json",
        AUDIT_ROOT / "evidence/focused_checks.json",
        AUDIT_ROOT / "evidence/artifact_identity.json",
    ):
        add(path, f"external/reanalysis/{path.relative_to(AUDIT_ROOT).as_posix()}")
    for name in ("kaggriculture.py", "kaggriculture.json"):
        add(ENGINE_DIR / name, f"external/installed_engine/{name}")
    add(LOADER, "external/installed_engine/agent.py")

    records = [
        {
            "archive_path": name,
            "source_path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for name, path in sorted(package_sources.items())
    ]
    manifest = {
        "created_at_utc": utc_now(),
        "scope": "every file listed is included in the deliverable ZIP and verified after extraction",
        "files": records,
        "raw_teacher_replays": {
            "packaged": False,
            "reason": (
                "the existing raw corpus is 17+ GB; selected replay hashes and paths are frozen in "
                "dataset_v2/dataset_manifest.json"
            ),
            "existence_and_hash_verified_during_dataset_build": True,
        },
        "manifest_self": (
            "included as experiments/round8_execution_reset_20260922/ARTIFACT_MANIFEST.json; "
            "excluded from its own hash list"
        ),
    }
    write_new(MANIFEST, manifest)
    add(MANIFEST)

    DELIVERABLE.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        DELIVERABLE, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True
    ) as stream:
        for name, path in sorted(package_sources.items()):
            stream.write(path, arcname=name)
    VERIFY_ROOT.mkdir(parents=True)
    with zipfile.ZipFile(DELIVERABLE, "r") as stream:
        stream.extractall(VERIFY_ROOT)
    failures = []
    for record in records:
        extracted = VERIFY_ROOT / record["archive_path"]
        if not extracted.is_file():
            failures.append({"path": record["archive_path"], "reason": "missing"})
        elif extracted.stat().st_size != record["bytes"] or sha256(extracted) != record["sha256"]:
            failures.append({"path": record["archive_path"], "reason": "size_or_hash_mismatch"})
    verification = {
        "created_at_utc": utc_now(),
        "deliverable": file_record(DELIVERABLE),
        "extracted_outside_repository": str(VERIFY_ROOT),
        "listed_files": len(records),
        "verified_files": len(records) - len(failures),
        "failures": failures,
        "all_manifest_targets_present_and_matching": not failures,
    }
    verification_path = EXPERIMENT / "DELIVERABLE_VERIFICATION.json"
    write_new(verification_path, verification)
    print(json.dumps(verification, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
