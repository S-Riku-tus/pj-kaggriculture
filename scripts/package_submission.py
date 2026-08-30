"""Build a submission from a versioned agent directory."""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import re
import tarfile
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AGENT = Path("agents/v1")
SUBMISSION_MANIFEST = "submission_manifest.json"


def parse_boolean_overrides(values: list[str]) -> dict[str, bool]:
    """Parse explicit, reproducible top-level boolean source overrides."""
    overrides: dict[str, bool] = {}
    for value in values:
        name, separator, raw = value.partition("=")
        if not separator or not name.isidentifier() or raw.lower() not in {"true", "false"}:
            raise ValueError(f"expected NAME=true or NAME=false, got {value!r}")
        overrides[name] = raw.lower() == "true"
    return overrides


def apply_boolean_overrides(source: bytes, overrides: dict[str, bool]) -> bytes:
    """Override only an existing simple top-level bool assignment in main.py."""
    text = source.decode("utf-8")
    for name, enabled in overrides.items():
        pattern = re.compile(rf"(?m)^{re.escape(name)}\s*=\s*(?:True|False)\s*$")
        text, count = pattern.subn(f"{name} = {enabled}", text)
        if count != 1:
            raise ValueError(f"expected one top-level boolean assignment for {name}, found {count}")
    return text.encode("utf-8")


def resolve_agent(value: Path) -> Path:
    candidate = value if value.is_absolute() else ROOT / value
    if candidate.is_file() and candidate.name == "main.py":
        candidate = candidate.parent
    candidate = candidate.resolve()
    if not (candidate / "main.py").is_file():
        raise FileNotFoundError(f"versioned agent main.py not found: {candidate}")
    return candidate


def submission_files(agent_dir: Path) -> dict[str, Path]:
    manifest_path = agent_dir / SUBMISSION_MANIFEST
    if not manifest_path.is_file():
        return {"main.py": agent_dir / "main.py"}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    files: dict[str, Path] = {}
    for entry in payload.get("files", []):
        target = str(entry["target"]).replace("\\", "/")
        target_path = Path(target)
        if target_path.is_absolute() or ".." in target_path.parts or target in {"", "."}:
            raise ValueError(f"unsafe archive target: {target!r}")
        source = (agent_dir / str(entry["source"])).resolve()
        if not source.is_relative_to(ROOT) or not source.is_file():
            raise FileNotFoundError(f"submission source not found under repository: {source}")
        if target in files:
            raise ValueError(f"duplicate archive target: {target}")
        files[target] = source
    if "main.py" not in files:
        raise ValueError(f"{SUBMISSION_MANIFEST} must include main.py")
    return files


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", type=Path, default=DEFAULT_AGENT, help="versioned agent directory")
    parser.add_argument("--output", type=Path, help="defaults to artifacts/submissions/<agent>.tar.gz")
    parser.add_argument(
        "--set-bool",
        action="append",
        default=[],
        metavar="NAME=true|false",
        help="override an existing top-level boolean in the archived main.py",
    )
    args = parser.parse_args()

    agent_dir = resolve_agent(args.agent)
    output = args.output or ROOT / "artifacts" / "submissions" / f"{agent_dir.name}.tar.gz"
    output = output if output.is_absolute() else ROOT / output
    files = submission_files(agent_dir)
    source_path = files["main.py"]
    overrides = parse_boolean_overrides(args.set_bool)
    contents = {target: path.read_bytes() for target, path in files.items()}
    contents["main.py"] = apply_boolean_overrides(contents["main.py"], overrides)
    source = contents["main.py"]
    tree = ast.parse(source, filename=str(source_path))
    if not any(isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == "agent" for node in tree.body):
        raise SystemExit("main.py does not define a top-level agent function")

    output.parent.mkdir(parents=True, exist_ok=True)
    expected_names = sorted(files, key=lambda name: (name != "main.py", name))
    if output.suffix.lower() == ".zip":
        archive_format = "zip"
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for target in expected_names:
                info = zipfile.ZipInfo(target, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, contents[target], compresslevel=9)
        with zipfile.ZipFile(output, "r") as archive:
            names = archive.namelist()
    else:
        archive_format = "tar.gz"
        with tarfile.open(output, "w:gz") as archive:
            for target in expected_names:
                content = contents[target]
                info = tarfile.TarInfo(target)
                info.size = len(content)
                info.mtime = 0
                info.mode = 0o644
                archive.addfile(info, io.BytesIO(content))
        with tarfile.open(output, "r:gz") as archive:
            names = archive.getnames()
    if names != expected_names:
        raise SystemExit(f"unexpected archive layout: {names}")

    created_at = datetime.now().astimezone()
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    manifest = {
        "created_at": created_at.isoformat(),
        "agent": str(agent_dir.relative_to(ROOT)),
        "artifact": str(output.relative_to(ROOT)),
        "size": output.stat().st_size,
        "sha256": digest,
        "archive_format": archive_format,
        "boolean_overrides": overrides,
        "archive_entries": names,
    }
    manifest_dir = ROOT / "data" / "submissions" / "builds"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{created_at.strftime('%Y%m%d_%H%M%S_%z')}_{agent_dir.name}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"artifact: {output}")
    print(f"manifest: {manifest_path}")
    print(f"sha256: {digest}")


if __name__ == "__main__":
    main()
