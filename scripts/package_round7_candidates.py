"""Package Round7 candidates without modifying any frozen Round6 artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "learning_round7_20260922"
ARCHIVES = ROOT / "artifacts" / "submissions"
POLICY = ROOT / "agents" / "learning_round6_20260922_v1" / "main.py"
COMMON = ROOT / "agents" / "learning_next_20260921" / "common.py"
RUNTIME = ROOT / "agents" / "learning_round7_20260922_plan" / "runtime.py"
MODEL_COMPAT = ROOT / "agents" / "learning_round7_20260922_capacity" / "model_compat.py"
ROUND6_MODELS = ROOT / "experiments" / "learning_round6_20260922" / "models" / "sequence_bc_v1"
SPECS = {
    "r6_loaderfix": {
        "main": ROOT / "agents" / "learning_round7_20260922_r6_loaderfix" / "main.py",
        "runtime": False,
    },
    "ledger": {
        "main": ROOT / "agents" / "learning_round7_20260922_ledger" / "main.py",
        "runtime": True,
    },
    "plan": {
        "main": ROOT / "agents" / "learning_round7_20260922_plan" / "main.py",
        "runtime": True,
    },
    "ledger_v1": {
        "main": ROOT / "agents" / "learning_round7_20260922_ledger" / "main.py",
        "runtime": True,
    },
    "plan_v1": {
        "main": ROOT / "agents" / "learning_round7_20260922_plan" / "main.py",
        "runtime": True,
    },
    "arm_a_extended_v1": {
        "main": ROOT / "agents" / "learning_round7_20260922_r6_loaderfix" / "main.py",
        "runtime": False,
        "model_dir": ROOT / "experiments" / "learning_round7_20260922" / "models" / "arm_a_extended_v1",
    },
    "arm_a_ledger_v1": {
        "main": ROOT / "agents" / "learning_round7_20260922_ledger" / "main.py",
        "runtime": True,
        "model_dir": ROOT / "experiments" / "learning_round7_20260922" / "models" / "arm_a_extended_v1",
    },
    "arm_a_plan_v1": {
        "main": ROOT / "agents" / "learning_round7_20260922_plan" / "main.py",
        "runtime": True,
        "model_dir": ROOT / "experiments" / "learning_round7_20260922" / "models" / "arm_a_extended_v1",
    },
    "arm_b_capacity_v1": {
        "main": ROOT / "agents" / "learning_round7_20260922_capacity" / "main.py",
        "runtime": False,
        "compat": True,
        "model_dir": ROOT / "experiments" / "learning_round7_20260922" / "models" / "arm_b_capacity",
    },
    "arm_b_ledger_v1": {
        "main": ROOT / "agents" / "learning_round7_20260922_capacity" / "main_ledger.py",
        "runtime": True,
        "compat": True,
        "model_dir": ROOT / "experiments" / "learning_round7_20260922" / "models" / "arm_b_capacity",
    },
    "arm_b_plan_v1": {
        "main": ROOT / "agents" / "learning_round7_20260922_capacity" / "main_plan.py",
        "runtime": True,
        "compat": True,
        "model_dir": ROOT / "experiments" / "learning_round7_20260922" / "models" / "arm_b_capacity",
    },
    "arm_b_plan_v2": {
        "main": ROOT / "agents" / "learning_round7_20260922_capacity" / "main_plan.py",
        "runtime": True,
        "compat": True,
        "model_dir": ROOT / "experiments" / "learning_round7_20260922" / "models" / "arm_b_capacity",
    },
    "arm_b_plan_v3": {
        "main": ROOT / "agents" / "learning_round7_20260922_capacity" / "main_plan.py",
        "runtime": True,
        "compat": True,
        "model_dir": ROOT / "experiments" / "learning_round7_20260922" / "models" / "arm_b_capacity",
    },
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
    spec = SPECS[name]
    model_dir = spec.get("model_dir", ROUND6_MODELS)
    archive = ARCHIVES / f"learning_round7_20260922_{name}.tar.gz"
    if archive.exists():
        raise FileExistsError(f"refusing to overwrite {archive}")
    required = [(spec["main"], "main.py"), (POLICY, "policy.py"), (COMMON, "common.py")]
    if spec.get("compat"):
        required.append((MODEL_COMPAT, "model_compat.py"))
    if spec["runtime"]:
        required.append((RUNTIME, "runtime.py"))
    for model in ("actor_token", "market_token", "actor_quantity", "market_quantity"):
        required.extend(
            (
                (model_dir / f"{model}.npz", f"{model}.npz"),
                (model_dir / f"{model}.json", f"{model}.json"),
            )
        )
    missing = [str(path) for path, _arcname in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(missing)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz") as stream:
        for path, arcname in required:
            stream.add(path, arcname=arcname)
    members = []
    with tarfile.open(archive, "r:gz") as stream:
        for member in sorted(stream.getmembers(), key=lambda value: value.name):
            extracted = stream.extractfile(member)
            content = extracted.read() if extracted is not None else b""
            members.append({"name": member.name, "bytes": member.size, "sha256": hashlib.sha256(content).hexdigest()})
    return {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "candidate": name,
        "archive": str(archive.relative_to(ROOT)),
        "archive_sha256": sha256(archive),
        "members": members,
        "round6_weights_unchanged": model_dir == ROUND6_MODELS,
        "model_source": str(model_dir.relative_to(ROOT)),
        "online_operations": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("names", nargs="*", choices=tuple(SPECS))
    args = parser.parse_args()
    names = args.names or list(SPECS)
    manifests = [package(name) for name in names]
    write_json(EXPERIMENT / "candidate_archive_manifests.json", manifests)
    print(json.dumps(manifests, indent=2))


if __name__ == "__main__":
    main()
