"""Build a submission from a versioned agent directory."""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import tarfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AGENT = Path("agents/v1")
SUBMISSION_MANIFEST = "submission_manifest.json"


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
    args = parser.parse_args()

    agent_dir = resolve_agent(args.agent)
    output = args.output or ROOT / "artifacts" / "submissions" / f"{agent_dir.name}.tar.gz"
    output = output if output.is_absolute() else ROOT / output
    files = submission_files(agent_dir)
    source_path = files["main.py"]
    source = source_path.read_bytes()
    tree = ast.parse(source, filename=str(source_path))
    if not any(isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == "agent" for node in tree.body):
        raise SystemExit("main.py does not define a top-level agent function")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as archive:
        for target, path in sorted(files.items(), key=lambda item: (item[0] != "main.py", item[0])):
            content = path.read_bytes()
            info = tarfile.TarInfo(target)
            info.size = len(content)
            info.mtime = 0
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(content))

    with tarfile.open(output, "r:gz") as archive:
        names = archive.getnames()
        expected_names = sorted(files, key=lambda name: (name != "main.py", name))
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
