"""Reconcile the one documented concurrent smoke-resume duplication.

This utility is intentionally scoped to P1/smoke.  It preserves the original
JSONL byte-for-byte, requires exactly two semantically identical copies of
each expected key, and keeps the first copy in the canonical JSONL.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "research_20260914_clean_psr"
PAIRS = EXPERIMENT / "candidates" / "P1_psr_clean" / "pairs" / "smoke.jsonl"
BACKUP = PAIRS.with_name("smoke.concurrent_duplicate_preserved.jsonl")
AUDIT = EXPERIMENT / "duplicate_pair_reconciliation.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pair_key(row: dict) -> tuple:
    return (
        row["candidate_id"],
        row["candidate_source_sha256"],
        row["evaluation_core_sha256"],
        row["lineage_id"],
        int(row["seed"]),
        int(row["seat"]),
    )


def semantic_copy(row: dict) -> dict:
    value = copy.deepcopy(row)
    value.pop("execution_seconds", None)
    value.pop("worker_pid", None)
    return value


def main() -> None:
    if BACKUP.exists() or AUDIT.exists():
        raise RuntimeError("reconciliation artifacts already exist")
    original_sha = sha256(PAIRS)
    rows = [json.loads(line) for line in PAIRS.read_text(encoding="utf-8").splitlines() if line.strip()]
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        groups[pair_key(row)].append(row)
    if len(rows) != 8 or len(groups) != 4:
        raise RuntimeError(f"unexpected duplication shape: rows={len(rows)}, keys={len(groups)}")
    expected_sources = {"qeinstein_moev2", "souvik_v4"}
    expected_seats = {0, 1}
    if {key[3] for key in groups} != expected_sources or {key[5] for key in groups} != expected_seats:
        raise RuntimeError("unexpected source/seat keys")
    retained: list[dict] = []
    details = []
    for key in sorted(groups):
        copies = groups[key]
        if len(copies) != 2 or semantic_copy(copies[0]) != semantic_copy(copies[1]):
            raise RuntimeError(f"copies differ for {key}")
        retained.append(copies[0])
        details.append(
            {
                "key": list(key),
                "copies": 2,
                "same_except_execution_seconds_and_worker_pid": True,
                "retained_worker_pid": copies[0].get("worker_pid"),
                "discarded_worker_pid": copies[1].get("worker_pid"),
            }
        )
    shutil.copy2(PAIRS, BACKUP)
    payload = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in retained)
    PAIRS.write_text(payload, encoding="utf-8")
    audit = {
        "created_at": datetime.now(UTC).isoformat(),
        "scope": "P1_psr_clean smoke only",
        "cause": "two concurrent resume invocations both observed an initially empty JSONL",
        "original_rows": len(rows),
        "unique_keys": len(groups),
        "canonical_rows": len(retained),
        "comparison_exclusions": ["execution_seconds", "worker_pid"],
        "all_duplicates_semantically_identical": True,
        "original_sha256": original_sha,
        "preserved_original": str(BACKUP.relative_to(ROOT)).replace("\\", "/"),
        "preserved_original_sha256": sha256(BACKUP),
        "canonical_sha256": sha256(PAIRS),
        "groups": details,
    }
    AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
