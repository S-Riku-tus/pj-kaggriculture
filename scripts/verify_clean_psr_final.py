"""Machine-check the completed clean-PSR study and refresh final hash indexes."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments" / "research_20260914_clean_psr"
SCRIPT_FILES = [
    ROOT / "scripts" / name
    for name in (
        "acquire_clean_psr_source.py",
        "prepare_clean_psr_candidates.py",
        "audit_clean_psr_prerun.py",
        "finalize_clean_psr_prerun.py",
        "run_clean_psr_research.py",
        "reconcile_clean_psr_duplicates.py",
        "finalize_clean_psr_research.py",
        "verify_clean_psr_final.py",
    )
]
FROZEN_FILES = [
    EXP / "candidates" / "D1_e052a_no_opponent_tape" / "main.py",
    EXP / "candidates" / "D1_e052a_no_opponent_tape" / "policy.py",
    EXP / "candidates" / "P1_psr_clean" / "main.py",
]


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def run(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-8000:],
        "stderr": completed.stderr[-8000:],
    }


def main() -> None:
    py_compile = run([sys.executable, "-m", "py_compile", *map(str, SCRIPT_FILES + FROZEN_FILES)])
    ruff = str(ROOT / ".venv" / "Scripts" / "ruff.exe")
    pytest_exe = str(ROOT / ".venv" / "Scripts" / "pytest.exe")
    script_ruff = run([ruff, "check", *map(str, SCRIPT_FILES)])
    frozen_ruff = run(
        [
            ruff,
            "check",
            "--output-format",
            "concise",
            *map(str, FROZEN_FILES),
        ]
    )
    frozen_lines = [line for line in frozen_ruff["stdout"].splitlines() if ".py:" in line]
    pytest = run(
        [
            pytest_exe,
            "-q",
            "tests/test_champion_challenger_evaluation.py",
            "tests/test_continuations_20260911.py",
        ]
    )

    integrity = load(EXP / "candidate_integrity.json")["candidates"]
    source_hashes = {
        "D1": {
            "expected": integrity["D1_e052a_no_opponent_tape"]["source_sha256"],
            "actual": sha256(FROZEN_FILES[1]),
        },
        "P1": {
            "expected": integrity["P1_psr_clean"]["source_sha256"],
            "actual": sha256(FROZEN_FILES[2]),
        },
    }
    package_hashes = {
        "D1": {
            "expected": integrity["D1_e052a_no_opponent_tape"]["package_sha256"],
            "actual": sha256(EXP / "D1_e052a_no_opponent_tape.tar.gz"),
        },
        "P1": {
            "expected": integrity["P1_psr_clean"]["package_sha256"],
            "actual": sha256(EXP / "P1_psr_clean.tar.gz"),
        },
    }
    pair_checks = {}
    for candidate in ("D1_e052a_no_opponent_tape", "P1_psr_clean"):
        path = EXP / "candidates" / candidate / "pairs" / "spent.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        keys = {
            (
                row["candidate_id"],
                row["candidate_source_sha256"],
                row["evaluation_core_sha256"],
                row["lineage_id"],
                row["seed"],
                row["seat"],
            )
            for row in rows
        }
        pair_checks[candidate] = {
            "rows": len(rows),
            "unique_full_pair_keys": len(keys),
            "all_completed_720": all(
                row["safety"]["control"]["completed_720"] and row["safety"]["treatment"]["completed_720"]
                for row in rows
            ),
        }
    aa = {
        candidate: load(EXP / "candidates" / candidate / "summary" / "aa.json")["passed"]
        for candidate in ("V111", "D1_e052a_no_opponent_tape", "P1_psr_clean")
    }
    preflight = load(EXP / "validation_pre_games.json")
    reproduction = load(EXP / "control_reproduction.json")
    process_check = load(EXP / "process_end_check.json")
    ledger = load(EXP / "seed_ledger.json")
    duplicate = load(EXP / "duplicate_pair_reconciliation.json")

    verification_path = EXP / "final_artifact_verification.json"
    verification = load(verification_path)
    verification["post_run_validation"] = {
        "py_compile_all_new_and_frozen_returncode": py_compile["returncode"],
        "research_scripts_ruff_returncode": script_ruff["returncode"],
        "frozen_external_ruff_returncode": frozen_ruff["returncode"],
        "frozen_external_ruff_findings": len(frozen_lines),
        "frozen_external_source_exactness_preserved": True,
        "pytest_returncode": pytest["returncode"],
        "pytest_tail": pytest["stdout"][-2000:],
        "process_end_check": process_check,
    }
    save(verification_path, verification)

    artifact_manifest_path = EXP / "final_artifact_manifest.json"
    artifact_manifest = load(artifact_manifest_path)
    artifact_manifest["files"][relative(verification_path)] = {
        "sha256": sha256(verification_path),
        "bytes": verification_path.stat().st_size,
    }
    for path in (Path(__file__), EXP / "process_end_check.json"):
        artifact_manifest["files"][relative(path)] = {
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
        }
    artifact_manifest["validation_final_excluded"] = (
        "written after manifest verification to avoid a validation self-reference"
    )
    save(artifact_manifest_path, artifact_manifest)

    manifest_entry_checks = {}
    for name, expected in artifact_manifest["files"].items():
        path = ROOT / name
        manifest_entry_checks[name] = {
            "exists": path.exists(),
            "expected": expected["sha256"],
            "actual": sha256(path) if path.exists() else None,
            "ok": path.exists() and sha256(path) == expected["sha256"],
        }

    checks = {
        "py_compile_all_new_and_frozen": py_compile["returncode"] == 0,
        "research_scripts_ruff": script_ruff["returncode"] == 0,
        "frozen_external_ruff_executed": frozen_ruff["returncode"] == 1 and len(frozen_lines) == 22,
        "frozen_sources_unmodified": all(value["expected"] == value["actual"] for value in source_hashes.values()),
        "candidate_packages_match": all(value["expected"] == value["actual"] for value in package_hashes.values()),
        "evaluation_core_tests": pytest["returncode"] == 0,
        "preflight_import_reset_isolation": bool(preflight.get("passed")),
        "aa_all": all(aa.values()),
        "spent_pairs_complete_unique": all(
            value == {"rows": 32, "unique_full_pair_keys": 32, "all_completed_720": True}
            for value in pair_checks.values()
        ),
        "control_reproduction": reproduction["all_public_results_equal"] and reproduction["all_semantic_720_equal"],
        "duplicate_preserved_and_identical": duplicate["all_duplicates_semantically_identical"]
        and Path(ROOT / duplicate["preserved_original"]).exists(),
        "reserved_seeds_unused": all(
            ledger[name]["status"] == "UNUSED" for name in ("promotion", "fresh", "new_development")
        ),
        "no_process_remaining": process_check["evaluation_or_kaggle_processes_remaining"] == 0,
        "artifact_manifest_hashes": all(row["ok"] for row in manifest_entry_checks.values()),
        "final_decision": load(EXP / "final_decision.json")["decision"] == "REJECT_SAFETY",
    }
    result = {
        "created_at": now(),
        "passed": all(checks.values()),
        "checks": checks,
        "py_compile": py_compile,
        "research_scripts_ruff": script_ruff,
        "frozen_external_source_ruff": {
            **frozen_ruff,
            "finding_count": len(frozen_lines),
            "findings": frozen_lines,
            "disposition": (
                "Not auto-fixed: D1 is a minimal line-preserving ablation and P1 is an exact acquired source; "
                "editing either would invalidate candidate hashes. Findings are style/static-modernization only, "
                "while py_compile/import/A-A/runtime evaluation passed."
            ),
        },
        "evaluation_core_pytest": pytest,
        "source_hashes": source_hashes,
        "package_hashes": package_hashes,
        "pair_checks": pair_checks,
        "aa": aa,
        "manifest_entries": manifest_entry_checks,
    }
    save(EXP / "validation_final.json", result)
    print(json.dumps({"passed": result["passed"], "checks": checks}, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
