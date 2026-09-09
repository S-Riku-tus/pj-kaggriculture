"""Immutable preregistration verification and experiment provenance."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from .schema import file_sha256


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def bundle_sha256(root: Path, paths: list[str]) -> str:
    digest = hashlib.sha256()
    for value in sorted(paths):
        path = _resolve(root, value)
        digest.update(value.replace("\\", "/").encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _git_state(root: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    try:
        return {
            "commit": run("rev-parse", "HEAD"),
            "dirty": bool(run("status", "--porcelain")),
        }
    except (OSError, subprocess.CalledProcessError) as exc:
        return {"commit": None, "dirty": None, "error": str(exc)}


def verify_inputs(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for arm_name, arm in spec["arms"].items():
        path = _resolve(root, str(arm["archive"]))
        actual = file_sha256(path)
        expected = str(arm["sha256"])
        checks.append(
            {
                "kind": "arm_archive",
                "name": arm_name,
                "path": str(path),
                "expected_sha256": expected,
                "actual_sha256": actual,
                "passed": actual == expected,
            }
        )
    for opponent in spec["opponent_pool"]:
        path = _resolve(root, str(opponent["path"]))
        actual = file_sha256(path)
        expected = str(opponent["sha256"])
        checks.append(
            {
                "kind": "opponent",
                "name": opponent["lineage_id"],
                "path": str(path),
                "expected_sha256": expected,
                "actual_sha256": actual,
                "passed": actual == expected,
            }
        )
    evaluator = spec["evaluator"]
    actual_bundle = bundle_sha256(root, list(evaluator["files"]))
    checks.append(
        {
            "kind": "evaluator_bundle",
            "name": evaluator["version"],
            "expected_sha256": evaluator["sha256"],
            "actual_sha256": actual_bundle,
            "passed": actual_bundle == evaluator["sha256"],
        }
    )
    engine = spec["engine"]
    engine_path = _resolve(root, str(engine["source_path"]))
    actual_engine = file_sha256(engine_path)
    checks.append(
        {
            "kind": "engine",
            "name": engine["version"],
            "path": str(engine_path),
            "expected_sha256": engine["sha256"],
            "actual_sha256": actual_engine,
            "passed": actual_engine == engine["sha256"],
        }
    )
    failed = [row for row in checks if not row["passed"]]
    if failed:
        raise ValueError(f"preregistered input hash mismatch: {failed}")
    return {
        "verified_at": datetime.now().astimezone().isoformat(),
        "checks": checks,
        "all_passed": True,
        "git": _git_state(root),
    }


def write_record(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"experiment record already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
