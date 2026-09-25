"""Build a hash manifest for the self-contained Round13 directory."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROUND13 = Path(__file__).resolve().parents[1]
EXCLUDED = {"MANIFEST.json"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    files = []
    sensitive_names = []
    for path in sorted(value for value in ROUND13.rglob("*") if value.is_file()):
        relative = path.relative_to(ROUND13).as_posix()
        if relative in EXCLUDED:
            continue
        lower = path.name.lower()
        if lower in {"kaggle.json", ".env", "credentials.json"} or "client_secret" in lower:
            sensitive_names.append(relative)
        files.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256(path)})
    if sensitive_names:
        raise RuntimeError(f"sensitive filenames found: {sensitive_names}")
    manifest = {
        "schema": "round13-manifest-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "root": "round13_strategy_reset_20260925",
        "file_count_excluding_manifest": len(files),
        "total_bytes_excluding_manifest": sum(value["bytes"] for value in files),
        "manifest_self_excluded": True,
        "sensitive_filename_matches": sensitive_names,
        "files": files,
    }
    target = ROUND13 / "MANIFEST.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in manifest.items() if key != "files"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
