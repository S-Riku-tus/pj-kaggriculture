"""Build deterministic, unsubmitted Round10 B1/B2/learned archives."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ROUND = ROOT / "experiments/round10_public_learning_20260924"
BASE = ROUND / "public_agents/herd_safe/main.py"
TASK = ROOT / "agents/round10_task_learning_20260924"
B2 = ROOT / "agents/round10_opening_b2_20260924"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def archive_bytes(files: dict[str, bytes]) -> bytes:
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for target, data in sorted(files.items()):
            info = tarfile.TarInfo(target)
            info.size = len(data)
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
    compressed = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode="wb", filename="", mtime=0, compresslevel=9) as stream:
        stream.write(tar_buffer.getvalue())
    return compressed.getvalue()


def learned_main() -> bytes:
    source = '''"""Packaged Round10 learned diagnostic arm."""

from policy_runtime import build_agent

_runtime = build_agent("learned")


def latest_diagnostics(*_args):
    return _runtime.round10_diagnostics()


def agent(observation, configuration=None):
    return _runtime(observation, configuration)
'''
    return source.encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "artifacts/submissions",
    )
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    base = BASE.read_bytes()
    notice = (B2 / "NOTICE.md").read_bytes()
    packages = {
        "B1_herd_safe": {
            "archive": output_dir / "round10_20260924_b1_herd_safe.tar.gz",
            "files": {"main.py": base},
            "status": "selected local baseline; not submitted",
        },
        "B2_buy10_sell5": {
            "archive": output_dir / "round10_20260924_b2_buy10_sell5.tar.gz",
            "files": {"main.py": (B2 / "main.py").read_bytes(), "base_main.py": base, "NOTICE.md": notice},
            "status": "opening stress candidate; not submitted; mixed B1 regression",
        },
        "learned_diagnostic": {
            "archive": output_dir / "round10_20260924_learned_diagnostic.tar.gz",
            "files": {
                "main.py": learned_main(),
                "policy_runtime.py": (TASK / "policy_runtime.py").read_bytes(),
                "model.json": (TASK / "model.json").read_bytes(),
                "base_main.py": base,
                "NOTICE.md": notice,
            },
            "status": "trained diagnostic; learning contribution not established; not submitted",
        },
    }
    records: list[dict[str, Any]] = []
    for name, package in packages.items():
        data = archive_bytes(package["files"])
        package["archive"].write_bytes(data)
        with tarfile.open(package["archive"], mode="r:gz") as archive:
            members = [member.name for member in archive.getmembers()]
            extracted = {member: archive.extractfile(member).read() for member in members}
        if extracted != package["files"]:
            raise RuntimeError(f"archive round-trip mismatch: {name}")
        for target, content in extracted.items():
            if target.endswith(".py"):
                compile(content, f"{name}/{target}", "exec")
        records.append(
            {
                "name": name,
                "archive": package["archive"].relative_to(ROOT).as_posix(),
                "archive_sha256": sha256_bytes(data),
                "archive_bytes": len(data),
                "status": package["status"],
                "files": [
                    {"path": target, "bytes": len(content), "sha256": sha256_bytes(content)}
                    for target, content in sorted(package["files"].items())
                ],
                "round_trip_verified": True,
                "python_compile_verified": True,
            }
        )
    result = {"submitted": False, "published": False, "champion_replaced": False, "packages": records}
    manifest = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
