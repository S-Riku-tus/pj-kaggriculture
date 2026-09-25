"""Statically extract Python agent payloads from Round11 public sources.

No notebook or downloaded Python is executed.  Literal strings are decoded
through the common base64/base85 and zlib/gzip/lzma combinations.  Tar members
are read in memory and emitted only when they parse as Python and define a
top-level function.
"""

from __future__ import annotations

import argparse
import ast
import base64
import gzip
import hashlib
import io
import json
import lzma
import re
import tarfile
import zlib
from pathlib import Path
from typing import Any


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def literal_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, (ast.Tuple, ast.List)):
        parts = [literal_string(item) for item in node.elts]
        return "".join(parts) if all(part is not None for part in parts) else None
    return None


def source_units(path: Path) -> tuple[bytes, list[tuple[str, str]]]:
    raw = path.read_bytes()
    document = json.loads(raw)
    units: list[tuple[str, str]] = []
    if isinstance(document, dict) and isinstance(document.get("cells"), list):
        for index, cell in enumerate(document["cells"]):
            if cell.get("cell_type") == "code":
                units.append((f"cell:{index}", "".join(cell.get("source") or [])))
    elif isinstance(document, dict):
        blob = document.get("blob")
        if isinstance(blob, dict) and isinstance(blob.get("source"), str):
            units.append(("$.blob.source", blob["source"]))
    return raw, units


def literal_candidates(source: str) -> list[tuple[str, str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    rows: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            value = literal_string(node.value)
            if value is not None and len(value) >= 500:
                names = [target.id for target in node.targets if isinstance(target, ast.Name)]
                rows.append((names[0] if names else f"line:{node.lineno}", value))
        elif isinstance(node, ast.Call):
            for argument in node.args:
                value = literal_string(argument)
                if value is not None and len(value) >= 500:
                    rows.append((f"call-line:{node.lineno}", value))
    unique: dict[str, tuple[str, str]] = {}
    for label, value in rows:
        unique.setdefault(sha256(value.encode("utf-8")), (label, value))
    return list(unique.values())


def decoded_variants(value: str) -> list[tuple[str, bytes]]:
    variants: list[tuple[str, bytes]] = [("literal-utf8", value.encode("utf-8"))]
    try:
        raw = value.encode("ascii")
    except UnicodeEncodeError:
        return variants
    for name, decoder in (("base64", base64.b64decode), ("base85", base64.b85decode)):
        try:
            decoded = decoder(raw)
        except (ValueError, TypeError):
            continue
        variants.append((name, decoded))
        for compression, decompress in (
            ("zlib", zlib.decompress),
            ("gzip", gzip.decompress),
            ("lzma", lzma.decompress),
        ):
            try:
                variants.append((f"{name}+{compression}", decompress(decoded)))
            except (OSError, EOFError, lzma.LZMAError, zlib.error):
                pass
    return variants


def python_inventory(data: bytes) -> dict[str, Any] | None:
    try:
        source = data.decode("utf-8")
        tree = ast.parse(source)
    except (UnicodeDecodeError, SyntaxError):
        return None
    functions = [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if not functions:
        return None
    imports = sorted(
        {
            alias.name.split(".")[0]
            for node in tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        | {
            (node.module or "").split(".")[0]
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
        }
    )
    return {
        "bytes": len(data),
        "lines": len(source.splitlines()),
        "sha256": sha256(data),
        "top_level_functions": functions,
        "last_top_level_function": functions[-1],
        "imports": imports,
    }


def tar_python_members(data: bytes) -> list[tuple[str, bytes]]:
    try:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
    except tarfile.TarError:
        return []
    rows: list[tuple[str, bytes]] = []
    with archive:
        for member in archive.getmembers():
            if not member.isfile() or not member.name.lower().endswith(".py"):
                continue
            stream = archive.extractfile(member)
            if stream is not None:
                rows.append((member.name, stream.read()))
    return rows


def extract(path: Path, output_dir: Path) -> dict[str, Any]:
    raw, units = source_units(path)
    expected_hashes = sorted(
        {
            match.lower()
            for _, source in units
            for match in re.findall(r"(?i)\b[0-9a-f]{64}\b", source)
        }
    )
    candidates: list[tuple[str, str, str]] = []
    for unit, source in units:
        for label, value in literal_candidates(source):
            candidates.append((unit, label, value))

    output_dir.mkdir(parents=True, exist_ok=True)
    emitted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for unit, label, value in candidates:
        for encoding, decoded in decoded_variants(value):
            possible = [("", decoded)] + [
                (f"/tar:{member}", member_data)
                for member, member_data in tar_python_members(decoded)
            ]
            for suffix, data in possible:
                inventory = python_inventory(data)
                if inventory is None or inventory["sha256"] in seen:
                    continue
                seen.add(inventory["sha256"])
                filename = f"extracted_agent_{len(emitted) + 1}.py"
                (output_dir / filename).write_bytes(data)
                emitted.append(
                    {
                        "source_unit": unit,
                        "literal": label,
                        "encoding": encoding + suffix,
                        "path": filename,
                        "expected_hash_match": (
                            inventory["sha256"] in expected_hashes if expected_hashes else None
                        ),
                        **inventory,
                    }
                )
    result = {
        "input": path.as_posix(),
        "input_sha256": sha256(raw),
        "source_units": len(units),
        "literal_candidates": len(candidates),
        "expected_source_hashes": expected_hashes,
        "agents": emitted,
    }
    (output_dir / "extraction_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    result = extract(args.input, args.output_dir)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    if not result["agents"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
