"""Finalize and verify the V117 experiment artifact set."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments/research_20260916_v117_live_trial"
ARCHIVE = ROOT / "artifacts/submissions/v117.tar.gz"
SOURCE = ROOT / "agents/v117/main.py"
EXPECTED_SOURCE = "2772e5fa31476db3dc4f015d4a8cf11bf7c48d75ab617a9bd782bb4c7aa696a8"
EXPECTED_ARCHIVE = "8f2c7e8446ce1295fe519cf9f29b87b01a0816863b952d94f1db80ed1432dbfa"


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def jsonl(path: Path) -> list[dict[str, Any]]:
    result = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"partial JSONL record {path}:{line_number}") from exc
    return result


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def git_attribute(path: Path, attribute: str) -> str:
    completed = subprocess.run(
        ["git", "check-attr", attribute, "--", relative(path)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=True,
    )
    return completed.stdout.strip().rsplit(": ", 1)[-1]


def ignored(path: Path) -> bool:
    completed = subprocess.run(
        ["git", "check-ignore", "-q", "--", relative(path)], cwd=ROOT, check=False
    )
    return completed.returncode == 0


def artifact_paths() -> list[Path]:
    paths = [
        ROOT / ".gitattributes",
        ROOT / "docs/research_20260916_v117_live_trial_preregistration.md",
        ROOT / "docs/research_20260916_v117_live_trial_report.md",
        ROOT / "docs/agent_status_registry_20260916.json",
        ROOT / "scripts/package_submission.py",
        ROOT / "scripts/research_20260916_v117_live_trial.py",
        ROOT / "scripts/analyze_20260916_v117_live_trial.py",
        ROOT / "scripts/validate_v117_package_runtime.py",
        Path(__file__),
        ARCHIVE,
    ]
    paths.extend(path for path in (ROOT / "agents/v117").rglob("*") if path.is_file())
    paths.extend(
        path
        for path in EXP.rglob("*")
        if path.is_file()
        and path.name not in {"final_artifact_manifest.json", "final_artifact_verification.json"}
    )
    return sorted(set(paths), key=relative)


def main() -> None:
    manifest_path = EXP / "manifest.json"
    manifest = load(manifest_path)
    manifest.update(
        {
            "status": "COMPLETE_LOCAL_SLOT_APPROVAL_REQUIRED",
            "phase": "finalized",
            "updated_at": now(),
            "evaluation_pid": None,
            "candidate_source_sha256": EXPECTED_SOURCE,
            "qualification_package_sha256": manifest.get("candidate_package_sha256"),
            "candidate_package_sha256": EXPECTED_ARCHIVE,
            "trial_gate_passed": True,
            "submission_attempts": 0,
            "submission_id": None,
            "slot_change_performed": False,
            "kernel_push_performed": False,
            "production_champion": "V111",
            "final_decision": "LIVE_TRIAL_CANDIDATE_NOT_SUBMITTED_SLOT_APPROVAL_REQUIRED",
        }
    )
    save(manifest_path, manifest)

    required = [
        "manifest.json",
        "initial_audit.json",
        "seed_ledger.json",
        "input_artifact_verification.json",
        "candidate_contract.json",
        "candidate_integrity.json",
        "trial_gate.json",
        "fallback_decision.json",
        "source_and_license_inventory.json",
        "package_manifest.json",
        "package_verification.json",
        "package_runtime_validation.json",
        "aa_results.json",
        "smoke_results.json",
        "pairs.jsonl",
        "runs.jsonl",
        "summary.json",
        "safety_and_delivery.json",
        "mechanism_attribution.json",
        "mechanism_details.json",
        "remote_identity_and_slots.json",
        "submission_decision.json",
        "live_observation.json",
        "v112_fallback_audit.json",
        "reproduction_commands.json",
        "final_decision.json",
    ]
    required_checks = {name: (EXP / name).is_file() for name in required}
    records = jsonl(EXP / "pairs.jsonl")
    expected_by_phase = {
        "aa_v111": 2,
        "aa_v117": 2,
        "smoke_nontrigger": 2,
        "smoke_commit": 4,
        "old_spent": 32,
        "confirmation": 32,
    }
    counts = Counter(record["phase"] for record in records)
    keys = {
        (
            record["phase"],
            record["candidate"],
            record["candidate_source_sha256"],
            record["evaluation_core_sha256"],
            record["lineage_id"],
            int(record["seed"]),
            int(record["seat"]),
        )
        for record in records
    }
    replay_paths = [
        Path(record["replay_artifacts"][arm])
        for record in records
        for arm in ("control", "treatment")
    ]
    entries = []
    for path in artifact_paths():
        entries.append(
            {
                "path": relative(path),
                "size": path.stat().st_size,
                "sha256": sha(path),
                "git_ignored": ignored(path),
                "git_lfs_filter": git_attribute(path, "filter"),
            }
        )
    final_manifest = {
        "created_at": now(),
        "scope": (
            "All required V117 source, documentation, local experiment payload, replays, "
            "scripts, and exact archive."
        ),
        "entries": entries,
        "entry_count": len(entries),
        "total_bytes": sum(entry["size"] for entry in entries),
        "control_artifacts_excluded_from_self_hashing": [
            relative(EXP / "final_artifact_manifest.json"),
            relative(EXP / "final_artifact_verification.json"),
        ],
        "github_save_policy": {
            "replay_lfs_pattern": "experiments/research_20260916_v117_live_trial/replays/**/*.json.gz",
            "archive_ignored": ignored(ARCHIVE),
            "archive_preservation": "release asset or explicit force-add; reproducible from command and expected hash",
        },
    }
    final_manifest_path = EXP / "final_artifact_manifest.json"
    save(final_manifest_path, final_manifest)
    checks = {
        "required_artifacts_present": all(required_checks.values()),
        "candidate_source_hash": sha(SOURCE) == EXPECTED_SOURCE,
        "final_archive_hash": sha(ARCHIVE) == EXPECTED_ARCHIVE,
        "trial_gate_passed": load(EXP / "trial_gate.json")["result"]["passed"] is True,
        "final_package_runtime_passed": load(EXP / "package_runtime_validation.json")["passed"] is True,
        "pair_count": len(records) == sum(expected_by_phase.values()),
        "pair_phase_counts": dict(counts) == expected_by_phase,
        "pair_keys_unique": len(keys) == len(records),
        "all_pairs_complete_720": all(
            record["safety"][arm]["completed_720"]
            for record in records
            for arm in ("control", "treatment")
        ),
        "all_replays_present": all(path.is_file() for path in replay_paths),
        "replay_count": len(replay_paths) == 2 * len(records),
        "submission_attempts_zero": load(EXP / "submission_decision.json")["upload_attempts"] == 0,
        "kernel_push_false": load(EXP / "submission_decision.json")["kernel_push_performed"] is False,
        "production_champion_v111": load(EXP / "final_decision.json")["production_champion"] == "V111",
    }
    verification = {
        "verified_at": now(),
        "passed": all(checks.values()),
        "checks": checks,
        "required_artifacts": required_checks,
        "phase_counts": dict(counts),
        "total_pairs": len(records),
        "unique_pair_keys": len(keys),
        "replay_paths": len(replay_paths),
        "final_artifact_manifest_sha256": sha(final_manifest_path),
        "candidate_source_sha256": sha(SOURCE),
        "archive_sha256": sha(ARCHIVE),
    }
    save(EXP / "final_artifact_verification.json", verification)
    print(json.dumps(verification, ensure_ascii=False))
    if not verification["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
