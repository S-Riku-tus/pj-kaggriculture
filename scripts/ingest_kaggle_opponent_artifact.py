"""Safely ingest a manually downloaded public Kaggle opponent artifact.

Anonymous Kaggle API access can return HTTP 403 even for a public notebook.
This tool bridges the browser-download path to the existing executable Gold
probe without executing untrusted code during ingestion.  It preserves the
raw artifact, safely expands archives (including nested submission archives),
recovers ``%%writefile`` files from notebooks, statically locates ``agent``
entrypoints, and emits a one-candidate manifest accepted by
``scripts/build_independent_gold_pool.py``.

An ingested artifact remains an acquisition lead until its common-seed,
both-seat closed-loop probe completes.  Ingestion never promotes it to Gold.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shutil
import stat
import tarfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = ROOT / "artifacts/opponent_pool/manual_kaggle_downloads"
MAX_MEMBERS = 10_000
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_NESTED_ARCHIVE_DEPTH = 3
ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{1,79}\Z")
WRITEFILE_PATTERN = re.compile(r"^\s*%%writefile\s+(.+?)\s*$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_member_path(name: str) -> Path:
    normalized = name.replace("\\", "/")
    value = PurePosixPath(normalized)
    if not normalized or value.is_absolute() or ".." in value.parts:
        raise ValueError(f"unsafe archive member path: {name!r}")
    if value.parts and re.fullmatch(r"[A-Za-z]:", value.parts[0]):
        raise ValueError(f"unsafe archive drive path: {name!r}")
    useful = [part for part in value.parts if part not in ("", ".")]
    if not useful:
        raise ValueError(f"empty archive member path: {name!r}")
    return Path(*useful)


def _prepare_member_target(root: Path, relative: Path) -> Path:
    target = root.joinpath(relative)
    resolved_root = root.resolve()
    resolved_target = target.resolve()
    if resolved_target != resolved_root and resolved_root not in resolved_target.parents:
        raise ValueError(f"archive member escapes extraction root: {relative}")
    if target.exists():
        raise FileExistsError(f"duplicate archive member target: {target}")
    return target


def _extract_zip(source: Path, target: Path) -> list[Path]:
    extracted: list[Path] = []
    total = 0
    with zipfile.ZipFile(source) as archive:
        members = archive.infolist()
        if len(members) > MAX_MEMBERS:
            raise ValueError(f"zip member limit exceeded: {len(members)}")
        for member in members:
            relative = _safe_member_path(member.filename)
            mode = (member.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise ValueError(f"zip symlink is not allowed: {member.filename!r}")
            output = target / relative
            if member.is_dir():
                output.mkdir(parents=True, exist_ok=True)
                continue
            total += int(member.file_size)
            if total > MAX_TOTAL_BYTES:
                raise ValueError("zip expanded-byte limit exceeded")
            output = _prepare_member_target(target, relative)
            output.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as incoming, output.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
            extracted.append(output)
    return extracted


def _extract_tar(source: Path, target: Path) -> list[Path]:
    extracted: list[Path] = []
    total = 0
    with tarfile.open(source, "r:*") as archive:
        members = archive.getmembers()
        if len(members) > MAX_MEMBERS:
            raise ValueError(f"tar member limit exceeded: {len(members)}")
        for member in members:
            relative = _safe_member_path(member.name)
            output = target / relative
            if member.isdir():
                output.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise ValueError(
                    f"tar links/devices are not allowed: {member.name!r} ({member.type!r})"
                )
            total += int(member.size)
            if total > MAX_TOTAL_BYTES:
                raise ValueError("tar expanded-byte limit exceeded")
            output = _prepare_member_target(target, relative)
            output.parent.mkdir(parents=True, exist_ok=True)
            incoming = archive.extractfile(member)
            if incoming is None:
                raise ValueError(f"cannot read tar member: {member.name!r}")
            with incoming, output.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
            extracted.append(output)
    return extracted


def _is_archive(path: Path) -> bool:
    try:
        return zipfile.is_zipfile(path) or tarfile.is_tarfile(path)
    except OSError:
        return False


def _archive_output_name(path: Path) -> str:
    name = path.name
    for suffix in (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".zip"):
        if name.lower().endswith(suffix):
            return name[: -len(suffix)] + "_extracted"
    return name + "_extracted"


def extract_archives(payload_root: Path, initial: Path) -> list[dict[str, Any]]:
    queue: list[tuple[Path, int]] = [(initial, 0)]
    records: list[dict[str, Any]] = []
    seen: set[Path] = set()
    while queue:
        source, depth = queue.pop(0)
        source = source.resolve()
        if source in seen or not source.is_file() or not _is_archive(source):
            continue
        seen.add(source)
        if depth > MAX_NESTED_ARCHIVE_DEPTH:
            raise ValueError(f"nested archive depth exceeded: {source}")
        if source == initial.resolve():
            target = payload_root
        else:
            target = source.parent / _archive_output_name(source)
            if target.exists():
                raise FileExistsError(f"nested archive target already exists: {target}")
            target.mkdir(parents=True)
        if zipfile.is_zipfile(source):
            extracted = _extract_zip(source, target)
            kind = "zip"
        else:
            extracted = _extract_tar(source, target)
            kind = "tar"
        records.append(
            {
                "archive": str(source),
                "archive_sha256": sha256_file(source),
                "kind": kind,
                "depth": depth,
                "target": str(target.resolve()),
                "extracted_files": len(extracted),
            }
        )
        queue.extend((path, depth + 1) for path in extracted if _is_archive(path))
    return records


def _writefile_target(raw_name: str) -> Path:
    name = raw_name.strip().strip("'\"")
    normalized = name.replace("\\", "/")
    if normalized.startswith("/kaggle/working/"):
        normalized = normalized.removeprefix("/kaggle/working/")
    elif normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized):
        normalized = PurePosixPath(normalized).name
    return _safe_member_path(normalized)


def recover_notebook_writefiles(payload_root: Path) -> list[dict[str, Any]]:
    recovered: list[dict[str, Any]] = []
    notebooks = sorted(payload_root.rglob("*.ipynb"))
    for notebook in notebooks:
        try:
            document = json.loads(notebook.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            recovered.append(
                {"notebook": str(notebook), "status": "INVALID_NOTEBOOK", "error": str(exc)}
            )
            continue
        output_root = notebook.parent / f"{notebook.stem}_writefiles"
        for index, cell in enumerate(document.get("cells") or []):
            if not isinstance(cell, dict) or cell.get("cell_type") != "code":
                continue
            source_value = cell.get("source") or []
            text = "".join(source_value) if isinstance(source_value, list) else str(source_value)
            lines = text.splitlines(keepends=True)
            if not lines:
                continue
            match = WRITEFILE_PATTERN.match(lines[0].rstrip("\r\n"))
            if not match:
                continue
            relative = _writefile_target(match.group(1))
            output = _prepare_member_target(output_root, relative)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("".join(lines[1:]), encoding="utf-8")
            recovered.append(
                {
                    "notebook": str(notebook),
                    "cell": index,
                    "status": "RECOVERED",
                    "output": str(output.resolve()),
                    "sha256": sha256_file(output),
                }
            )
    return recovered


def inspect_python_entrypoints(payload_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(payload_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(text, filename=str(path))
            top_level = {
                node.name
                for node in tree.body
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            }
            syntax_error = None
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            top_level = set()
            syntax_error = str(exc)
        relative = path.relative_to(payload_root).as_posix()
        rows.append(
            {
                "path": str(path.resolve()),
                "relative_path": relative,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "syntax_ok": syntax_error is None,
                "syntax_error": syntax_error,
                "top_level_agent": "agent" in top_level,
                "basename_priority": (
                    0 if path.name.lower() == "main.py" else 1 if path.name.lower() == "submission.py" else 2
                ),
            }
        )
    return rows


def select_entrypoint(
    candidates: list[dict[str, Any]], requested: str | None
) -> tuple[dict[str, Any] | None, str]:
    eligible = [row for row in candidates if row["syntax_ok"] and row["top_level_agent"]]
    if requested:
        normalized = requested.replace("\\", "/").lstrip("./")
        matches = [
            row
            for row in eligible
            if row["relative_path"] == normalized or Path(row["path"]).name == normalized
        ]
        if len(matches) != 1:
            raise ValueError(
                f"--entrypoint must identify exactly one valid agent file; matches={len(matches)}"
            )
        return matches[0], "explicit"
    main_files = [row for row in eligible if row["basename_priority"] == 0]
    if len(main_files) == 1:
        return main_files[0], "unique_main_py"
    if len(eligible) == 1:
        return eligible[0], "unique_agent_function"
    return None, "ambiguous" if eligible else "no_static_agent_entrypoint"


def _relative_to_root(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _all_file_records(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name not in {"acquisition_manifest.json", "candidate_sources.json"}
    ]


def ingest(
    *,
    artifact: Path,
    candidate_id: str,
    source_url: str,
    script_version_id: str | None,
    output_root: Path,
    expected_sha256: str | None = None,
    requested_entrypoint: str | None = None,
    exact_public_output: bool = False,
    source_ancestry_id: str | None = None,
) -> dict[str, Any]:
    if not ID_PATTERN.fullmatch(candidate_id):
        raise ValueError("candidate id must use 2-80 lowercase letters, digits, '_' or '-'")
    artifact = artifact.expanduser().resolve()
    if not artifact.is_file():
        raise FileNotFoundError(f"artifact does not exist: {artifact}")
    artifact_sha = sha256_file(artifact)
    if expected_sha256 and artifact_sha.lower() != expected_sha256.lower():
        raise ValueError(
            f"artifact SHA-256 mismatch: expected={expected_sha256}, actual={artifact_sha}"
        )
    target = output_root.expanduser().resolve() / candidate_id
    if target.exists():
        raise FileExistsError(f"candidate target already exists; use a new immutable id: {target}")
    raw_root = target / "raw"
    payload_root = target / "payload"
    raw_root.mkdir(parents=True)
    payload_root.mkdir(parents=True)
    raw_copy = raw_root / artifact.name
    shutil.copy2(artifact, raw_copy)

    if _is_archive(raw_copy):
        archives = extract_archives(payload_root, raw_copy)
    else:
        copied = payload_root / artifact.name
        shutil.copy2(raw_copy, copied)
        archives = []
    notebook_recovery = recover_notebook_writefiles(payload_root)
    python_candidates = inspect_python_entrypoints(payload_root)
    selected, selection_reason = select_entrypoint(python_candidates, requested_entrypoint)
    status = "READY_FOR_COMMON_PROBE" if selected else "NEEDS_ENTRYPOINT_SELECTION"
    candidate_manifest_path = target / "candidate_sources.json"
    candidate_record = None
    if selected:
        selected_path = Path(selected["path"])
        candidate_record = {
            "candidate_id": candidate_id,
            "kind": "python",
            "entrypoint": _relative_to_root(selected_path),
            "provenance": (
                f"manual browser download from {source_url}"
                + (f" scriptVersionId={script_version_id}" if script_version_id else "")
                + f"; raw sha256={artifact_sha}"
            ),
            "source_ancestry_id": source_ancestry_id or f"kaggle_{candidate_id}",
            "exact_submitted_or_public_artifact": bool(exact_public_output),
            "artifact_scope": (
                "exact manually downloaded public notebook output; not yet verified as exact live submission bytes"
                if exact_public_output
                else "manual public notebook download; artifact/output identity not asserted"
            ),
            "acquisition_manifest": _relative_to_root(target / "acquisition_manifest.json"),
        }
        compatible = {
            "format": "kaggriculture-manual-kaggle-candidate-sources-v1",
            "frozen_before_probe": datetime.now().astimezone().isoformat(),
            "dataset_role": "Discovery/Development; never Fresh Holdout",
            "candidates": [candidate_record],
        }
        candidate_manifest_path.write_text(
            json.dumps(compatible, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    probe_output = target / "common_probe.json"
    probe_report = target / "common_probe.md"
    probe_command = None
    if selected:
        probe_command = (
            ".\\.venv\\Scripts\\python.exe scripts\\build_independent_gold_pool.py "
            f"--candidate-manifest \"{_relative_to_root(candidate_manifest_path)}\" "
            "--seed 29114001 --seed 29114002 --workers 4 "
            f"--output \"{_relative_to_root(probe_output)}\" "
            f"--report \"{_relative_to_root(probe_report)}\""
        )
    manifest = {
        "format": "kaggriculture-manual-kaggle-opponent-acquisition-v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "status": status,
        "evidence_status": "ACQUISITION_LEAD_NOT_GOLD",
        "dataset_role": "Discovery/Development; permanently excluded from Fresh Holdout",
        "candidate_id": candidate_id,
        "source": {
            "url": source_url,
            "script_version_id": script_version_id,
            "manual_download_required_because": "anonymous Kaggle API returned HTTP 403",
        },
        "raw_artifact": {
            "original_path": str(artifact),
            "preserved_path": _relative_to_root(raw_copy),
            "bytes": raw_copy.stat().st_size,
            "sha256": artifact_sha,
            "expected_sha256_verified": bool(expected_sha256),
        },
        "archive_extractions": archives,
        "notebook_writefile_recovery": notebook_recovery,
        "python_entrypoint_candidates": python_candidates,
        "selected_entrypoint": selected,
        "entrypoint_selection_reason": selection_reason,
        "candidate_record": candidate_record,
        "next_actions": {
            "review_entrypoint": (
                _relative_to_root(Path(selected["path"])) if selected else "rerun with --entrypoint"
            ),
            "common_probe_command": probe_command,
            "gold_boundary": (
                "Do not call this Gold until all common-seed, both-seat games complete. "
                "Then collapse by executed action fingerprints before any family-level claim."
            ),
        },
    }
    manifest["files"] = _all_file_records(target)
    acquisition_manifest = target / "acquisition_manifest.json"
    acquisition_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "status": status,
        "target": str(target),
        "raw_sha256": artifact_sha,
        "selected_entrypoint": selected["relative_path"] if selected else None,
        "acquisition_manifest": str(acquisition_manifest),
        "candidate_manifest": str(candidate_manifest_path) if selected else None,
        "common_probe_command": probe_command,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--script-version-id")
    parser.add_argument("--expected-sha256")
    parser.add_argument("--entrypoint")
    parser.add_argument("--source-ancestry-id")
    parser.add_argument("--exact-public-output", action="store_true")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    result = ingest(
        artifact=args.artifact,
        candidate_id=args.candidate_id,
        source_url=args.source_url,
        script_version_id=args.script_version_id,
        output_root=args.output_root,
        expected_sha256=args.expected_sha256,
        requested_entrypoint=args.entrypoint,
        exact_public_output=args.exact_public_output,
        source_ancestry_id=args.source_ancestry_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
