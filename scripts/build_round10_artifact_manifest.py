from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments" / "round10_public_learning_20260924"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def entry(path: Path, *, required: bool = True) -> dict[str, object]:
    exists = path.is_file()
    result: dict[str, object] = {
        "path": path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path),
        "exists": exists,
        "required": required,
    }
    if exists:
        result.update({"bytes": path.stat().st_size, "sha256": sha256(path)})
    return result


def audit_evaluation_replays() -> dict[str, object]:
    csv_reports: list[dict[str, object]] = []
    replay_refs: dict[str, str] = {}
    conflicting_claims: list[str] = []
    missing: list[str] = []
    mismatched: list[dict[str, str]] = []
    rows_total = 0
    errors = 0

    replay_csvs = list(EXP.rglob("games.csv")) + list(EXP.rglob("baseline_games.csv"))
    for csv_path in sorted(replay_csvs):
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        rows_total += len(rows)
        errors += sum(bool(row.get("error")) for row in rows)
        for row in rows:
            replay_name = row.get("replay", "")
            claimed = row.get("replay_sha256", "")
            if not replay_name:
                continue
            if replay_name in replay_refs and replay_refs[replay_name] != claimed:
                conflicting_claims.append(replay_name)
            replay_refs[replay_name] = claimed
        csv_reports.append(
            {
                **entry(csv_path),
                "rows": len(rows),
                "rows_with_errors": sum(bool(row.get("error")) for row in rows),
            }
        )

    for replay_name, claimed in sorted(replay_refs.items()):
        replay_path = ROOT / replay_name
        if not replay_path.is_file():
            missing.append(replay_name)
            continue
        actual = sha256(replay_path)
        if actual != claimed:
            mismatched.append({"path": replay_name, "claimed_sha256": claimed, "actual_sha256": actual})

    return {
        "csv_reports": csv_reports,
        "rows": rows_total,
        "unique_replays": len(replay_refs),
        "rows_with_errors": errors,
        "missing_replays": missing,
        "sha256_mismatches": mismatched,
        "conflicting_sha256_claims": sorted(set(conflicting_claims)),
        "passed": not missing and not mismatched and not conflicting_claims and errors == 0,
    }


def audit_task_forks() -> dict[str, object]:
    csv_path = EXP / "training" / "task_labels" / "task_labels.csv"
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    missing: list[str] = []
    mismatched: list[dict[str, str]] = []
    for row in rows:
        for field in ("baseline_replay", "treatment_replay"):
            replay_name = row[field]
            if replay_name and not (ROOT / replay_name).is_file():
                missing.append(replay_name)
        treatment = ROOT / row["treatment_replay"]
        if treatment.is_file() and sha256(treatment) != row["treatment_replay_sha256"]:
            mismatched.append(
                {
                    "path": row["treatment_replay"],
                    "claimed_sha256": row["treatment_replay_sha256"],
                    "actual_sha256": sha256(treatment),
                }
            )
    return {
        **entry(csv_path),
        "rows": len(rows),
        "prefix_matches": sum(int(row["prefix_match"]) for row in rows),
        "execution_established": sum(int(row["execution_established"]) for row in rows),
        "contract_failures": sum(int(row["contract_failures"]) for row in rows),
        "missing_replays": sorted(set(missing)),
        "treatment_sha256_mismatches": mismatched,
        "passed": not missing and not mismatched,
    }


def main() -> None:
    official = (
        ROOT / ".venv" / "Lib" / "site-packages" / "kaggle_environments" / "envs" / "kaggriculture" / "kaggriculture.py"
    )
    cpp = EXP / "engines" / "kaggriculture-cppsim"
    external_inputs = [
        Path(r"C:\Users\shiba\Downloads\Kaggriculture_Public_Research_20260924.zip"),
        Path(r"C:\Users\shiba\Downloads\Round9_Hybrid_Audit_20260923.zip"),
    ]
    baselines = {
        "B0": {
            "identity": "v124 repository source",
            "source": entry(ROOT / "agents" / "v124" / "main.py"),
            "archive": entry(ROOT / "artifacts" / "submissions" / "v124.tar.gz"),
        },
        "retained_v122": {
            "identity": "v122 repository source; retained but not an independent family claim",
            "source": entry(ROOT / "agents" / "v122" / "main.py"),
            "archive": entry(ROOT / "artifacts" / "submissions" / "v122.tar.gz"),
        },
        "B1": {
            "identity": "fetched herd-safe source selected by local interactive comparison",
            "source": entry(EXP / "public_agents" / "herd_safe" / "main.py"),
            "archive": entry(ROOT / "artifacts" / "submissions" / "round10_20260924_b1_herd_safe.tar.gz"),
        },
    }
    core_artifacts = [
        EXP / "source_registry.json",
        EXP / "package_manifest.json",
        EXP / "package_validation" / "archive_loader_results.json",
        EXP / "validation" / "engine_validation.json",
        EXP / "validation" / "official_vs_kagsim_agent.json",
        EXP / "validation" / "task_null_control_exact.json",
        EXP / "validation" / "kaggle_access_probe.json",
        EXP / "analysis" / "opening_funding_stress_summary.json",
        EXP / "analysis" / "opening_candidate_isolation_summary.json",
        EXP / "analysis" / "opening_b2_confirmation_summary.json",
        EXP / "analysis" / "b1_task_opportunities.json",
        EXP / "analysis" / "task_selector_seed_holdout_summary.json",
        EXP / "analysis" / "task_diagnostic_examples.json",
        EXP / "training" / "ranker_training_report.json",
        EXP / "training" / "ranker_predictions.csv",
        ROOT / "agents" / "round10_task_learning_20260924" / "model.json",
        ROOT / "agents" / "round10_task_learning_20260924" / "policy_runtime.py",
        ROOT / "agents" / "round10_opening_b2_20260924" / "main.py",
        EXP / "RESULTS_JA.md",
        EXP / "REPRODUCE.md",
    ]
    scripts = sorted(ROOT.glob("scripts/*round10*.py"))
    evaluation_replays = audit_evaluation_replays()
    task_forks = audit_task_forks()
    payload = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "scope": "Round10 reproducibility and integrity manifest",
        "external_input_archives": [entry(path) for path in external_inputs],
        "baselines": baselines,
        "public_sources": json.loads((EXP / "source_registry.json").read_text(encoding="utf-8")),
        "engines": {
            "official_python": {
                **entry(official),
                "package_version": "1.32.7",
                "reference_official_commit": "302d8e20c83822b8d4572975cdea1180b792b748",
                "commit_correspondence_verified": False,
            },
            "cpp_accelerator": {
                "commit": "f0084b916343c37bbcbdc7de9d833dc96caff78f",
                "source_tree": str(cpp.relative_to(ROOT).as_posix()),
                "extension": entry(cpp / "kagsim.cp312-win_amd64.pyd"),
                "local_setup_patch_record": entry(EXP / "validation" / "engine_validation.json"),
            },
        },
        "core_artifacts": [entry(path) for path in core_artifacts],
        "scripts": [entry(path) for path in scripts],
        "evaluation_replay_audit": evaluation_replays,
        "task_fork_audit": task_forks,
        "integrity_passed": (
            evaluation_replays["passed"]
            and task_forks["passed"]
            and all(item["exists"] for item in [entry(path) for path in core_artifacts])
        ),
        "external_actions": {
            "kaggle_submitted": False,
            "notebook_published": False,
            "champion_replaced": False,
        },
    }
    destination = EXP / "artifact_manifest.json"
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(destination.relative_to(ROOT).as_posix())
    print(f"integrity_passed={payload['integrity_passed']}")


if __name__ == "__main__":
    main()
