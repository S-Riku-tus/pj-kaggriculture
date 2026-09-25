"""Package Round8 execution-repair arms without touching frozen artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "agents" / "round8_execution_reset_20260922"
MODELS = ROOT / "experiments" / "learning_round7_20260922" / "models" / "arm_b_capacity"
OUTPUT = ROOT / "artifacts" / "submissions"
EXPERIMENT = ROOT / "experiments" / "round8_execution_reset_20260922"
SPECS = {
    "f1_harvest": SOURCE / "main_f1.py",
    "f2_consistent": SOURCE / "main_f2.py",
    "f2_no_plan": SOURCE / "main_f2_no_plan.py",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def package(name: str) -> dict[str, Any]:
    archive = OUTPUT / f"round8_execution_reset_20260922_{name}_v4.tar.gz"
    if archive.exists():
        raise FileExistsError(f"refusing to overwrite {archive}")
    members = [
        (SPECS[name], "main.py"),
        (SOURCE / "policy.py", "policy.py"),
        (SOURCE / "common.py", "common.py"),
        (SOURCE / "model_compat.py", "model_compat.py"),
        (SOURCE / "runtime.py", "runtime.py"),
    ]
    for model in ("actor_token", "market_token", "actor_quantity", "market_quantity"):
        members.extend(((MODELS / f"{model}.npz", f"{model}.npz"), (MODELS / f"{model}.json", f"{model}.json")))
    missing = [str(path) for path, _arcname in members if not path.is_file()]
    if missing:
        raise FileNotFoundError(missing)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz") as stream:
        for path, arcname in members:
            stream.add(path, arcname=arcname)
    inventory = []
    with tarfile.open(archive, "r:gz") as stream:
        for member in sorted(stream.getmembers(), key=lambda value: value.name):
            extracted = stream.extractfile(member)
            content = extracted.read() if extracted is not None else b""
            inventory.append({"name": member.name, "bytes": member.size, "sha256": hashlib.sha256(content).hexdigest()})
    return {
        "arm": name,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "archive": str(archive.relative_to(ROOT)),
        "archive_sha256": sha256(archive),
        "members": inventory,
        "frozen_checkpoint_source": str(MODELS.relative_to(ROOT)),
        "checkpoint_files_unchanged": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("arms", nargs="*", choices=tuple(SPECS))
    args = parser.parse_args()
    rows = [package(name) for name in (args.arms or list(SPECS))]
    target = EXPERIMENT / "phase_b_archive_manifest_v4.json"
    if target.exists():
        raise FileExistsError(f"refusing to overwrite {target}")
    write_json(target, rows)
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
