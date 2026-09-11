"""Read-only repository inventory and frozen submission identity snapshot."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "experiments/research_20260909"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True)
    return result.stdout.decode("utf-8", "replace")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "initial_repository_audit.json"
    if target.exists():
        raise SystemExit("Initial snapshot already exists; refusing to overwrite")
    tracked = git("ls-files").splitlines()
    tracked_hashes = {}
    for name in tracked:
        path = ROOT / name
        if path.is_file() and path.stat().st_size < 100_000_000:
            tracked_hashes[name] = {"bytes": path.stat().st_size, "sha256": sha(path.read_bytes())}
    identities = {}
    for version in ("v109", "v110", "v111", "v112", "v113"):
        directory = ROOT / "agents" / version
        archive = ROOT / "artifacts/submissions" / f"{version}.tar.gz"
        manifest = json.loads((directory / "submission_manifest.json").read_text())
        local = {row["target"]: sha((directory / row["source"]).read_bytes()) for row in manifest["files"]}
        archived = {}
        if archive.exists():
            with tarfile.open(archive) as bundle:
                for member in bundle.getmembers():
                    if member.isfile():
                        stream = bundle.extractfile(member)
                        assert stream is not None
                        archived[member.name.removeprefix("./")] = sha(stream.read())
        identities[version] = {
            "source_main_sha256": sha((directory / "main.py").read_bytes()),
            "archive_sha256": sha(archive.read_bytes()) if archive.exists() else None,
            "source_members": local,
            "archive_members": archived,
            "exact_member_match": local == archived,
            "mismatches": [
                name for name in sorted(local.keys() | archived.keys()) if local.get(name) != archived.get(name)
            ],
        }
    directory_inventory = {}
    for name in (
        "agents",
        "artifacts/submissions",
        "experiments",
        "data/evaluation",
        "data/analysis",
        "docs",
        "scripts/evaluation",
        "tests",
    ):
        path = ROOT / name
        directory_inventory[name] = sorted(child.name for child in path.iterdir()) if path.exists() else None
    versions = {}
    for name in ("kaggle", "kaggle-environments", "pytest", "ruff", "numpy", "scikit-learn"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    payload = {
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "root": str(ROOT),
        "commit": git("rev-parse", "HEAD").strip(),
        "branch": git("branch", "--show-current").strip(),
        "status_porcelain": git("status", "--porcelain=v1", "--untracked-files=all"),
        "log": git("log", "-15", "--format=%H %cI %s"),
        "remote": git("remote", "-v"),
        "remote_tracking_commit": git("rev-parse", "origin/main").strip(),
        "root_main_exists": (ROOT / "main.py").exists(),
        "head_root_main_tracked": "main.py" in tracked,
        "version_identities": identities,
        "directory_inventory": directory_inventory,
        "installed_packages": versions,
        "tracked_file_hashes": tracked_hashes,
        "note": (
            "First git status before research writes was clean. This audit script is a new research file. "
            "Source/archive comparison uses raw bytes, without importing agents. "
            "Existing research outputs are preserved."
        ),
    }
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / "initial_tracked_diff.patch").write_bytes(
        subprocess.run(["git", "diff", "HEAD", "--binary"], cwd=ROOT, capture_output=True, check=True).stdout
    )
    print(
        json.dumps(
            {
                "path": str(target),
                "tracked_files": len(tracked_hashes),
                "identities": {
                    key: {k: v for k, v in value.items() if k not in ("source_members", "archive_members")}
                    for key, value in identities.items()
                },
                "packages": versions,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
