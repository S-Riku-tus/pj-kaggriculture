"""Package trained Round8 spatial BC checkpoints as standalone archives."""

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
EXPERIMENT = ROOT / "experiments" / "round8_execution_reset_20260922"
OUTPUT = ROOT / "artifacts" / "submissions"
MAINS = {"pure": SOURCE / "main_spatial_pure.py", "hybrid": SOURCE / "main_spatial_hybrid.py"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def package(seed: int, arm: str) -> dict[str, Any]:
    models = EXPERIMENT / "phase_c_spatial" / "models_v5" / f"seed_{seed}"
    archive = OUTPUT / f"round8_spatial_bc_20260922_seed{seed}_{arm}_v6.tar.gz"
    if archive.exists():
        raise FileExistsError(f"refusing to overwrite {archive}")
    members = [
        (MAINS[arm], "main.py"),
        (SOURCE / "spatial_policy.py", "policy.py"),
        (SOURCE / "spatial.py", "spatial.py"),
        (SOURCE / "common.py", "common.py"),
        (SOURCE / "model_compat.py", "model_compat.py"),
        (SOURCE / "runtime.py", "runtime.py"),
    ]
    for model in ("actor_token", "market_token", "actor_quantity", "market_quantity"):
        members.extend(((models / f"{model}.npz", f"{model}.npz"), (models / f"{model}.json", f"{model}.json")))
    missing = [str(path) for path, _name in members if not path.is_file()]
    if missing:
        raise FileNotFoundError(missing)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz") as stream:
        for path, name in members:
            stream.add(path, arcname=name)
    inventory = []
    with tarfile.open(archive, "r:gz") as stream:
        for member in sorted(stream.getmembers(), key=lambda value: value.name):
            extracted = stream.extractfile(member)
            content = extracted.read() if extracted is not None else b""
            inventory.append(
                {"name": member.name, "bytes": member.size, "sha256": hashlib.sha256(content).hexdigest()}
            )
    return {
        "arm": f"spatial_{arm}",
        "classification": "independent_bc" if arm == "pure" else "hybrid_bc_plus_handwritten_livestock_plan",
        "seed": seed,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "archive": str(archive.relative_to(ROOT)),
        "archive_sha256": sha256(archive),
        "training_summary": str((models / "training_summary.json").relative_to(ROOT)),
        "training_summary_sha256": sha256(models / "training_summary.json"),
        "members": inventory,
        "standalone_external_weight_dependency": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260922)
    args = parser.parse_args()
    rows = [package(args.seed, arm) for arm in MAINS]
    target = EXPERIMENT / "phase_c_spatial" / f"archive_manifest_seed_{args.seed}_v6.json"
    write_json(target, rows)
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
