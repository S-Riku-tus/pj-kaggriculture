"""Verify every declared payload member of the Round5 handoff ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with zipfile.ZipFile(args.bundle, "r") as stream:
        names = set(stream.namelist())
        manifest_name = "experiments/learning_round5_20260921/BUNDLE_MANIFEST.json"
        manifest = json.loads(stream.read(manifest_name))
        rows = []
        for expected in manifest["files"]:
            path = expected["path"]
            exists = path in names
            content = stream.read(path) if exists else b""
            rows.append({
                "path": path,
                "exists": exists,
                "bytes": len(content) if exists else None,
                "sha256": digest(content) if exists else None,
                "match": exists and len(content) == expected["bytes"] and digest(content) == expected["sha256"],
            })
        declared = {row["path"] for row in manifest["files"]} | {manifest_name}
        undeclared = sorted(names - declared)
    result = {
        "bundle": str(args.bundle.resolve()),
        "bundle_sha256": digest(args.bundle.read_bytes()),
        "bundle_bytes": args.bundle.stat().st_size,
        "declared_payload_files": len(rows),
        "all_declared_exist_and_match": all(row["match"] for row in rows),
        "undeclared_members": undeclared,
        "passed": all(row["match"] for row in rows) and not undeclared,
        "rows": rows,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("bundle_sha256", "bundle_bytes", "declared_payload_files", "all_declared_exist_and_match", "undeclared_members", "passed")}, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
