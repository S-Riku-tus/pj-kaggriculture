"""Safely extract embedded Python agents from acquired public notebooks.

The extractor never executes notebook cells.  It evaluates only literal string
assignments and the common ``''.join((...))`` wrapper, then tries documented
base64/base85 plus zlib encodings.  Every emitted file must parse as Python and
define at least one top-level function.
"""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import zlib
from pathlib import Path
from typing import Any


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def literal_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Tuple | ast.List):
        parts = [literal_string(item) for item in node.elts]
        return "".join(parts) if all(part is not None for part in parts) else None
    if (
        isinstance(node, ast.Call)
        and not node.keywords
        and len(node.args) == 1
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
    ):
        separator = literal_string(node.func.value)
        values = literal_string(node.args[0])
        if separator is not None and values is not None:
            # All observed notebooks use an empty separator.  Reject other
            # separators because tuple boundaries are intentionally discarded.
            return values if separator == "" else None
    return None


def assignment_strings(tree: ast.Module) -> dict[str, str]:
    values: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        value = literal_string(node.value)
        if value is not None:
            values[target.id] = value
    return values


def decoded_variants(value: str) -> list[tuple[str, bytes]]:
    raw = value.encode("ascii", errors="strict")
    variants: list[tuple[str, bytes]] = []
    for name, decoder in (("base64", base64.b64decode), ("base85", base64.b85decode)):
        try:
            decoded = decoder(raw)
        except (ValueError, TypeError):
            continue
        variants.append((name, decoded))
        try:
            variants.append((f"{name}+zlib", zlib.decompress(decoded)))
        except zlib.error:
            pass
    return variants


def python_inventory(data: bytes) -> dict[str, Any] | None:
    try:
        source = data.decode("utf-8")
        tree = ast.parse(source)
    except (UnicodeDecodeError, SyntaxError):
        return None
    functions = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
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
        "imports": imports,
    }


def extract_notebook(path: Path, output_dir: Path) -> dict[str, Any]:
    notebook_bytes = path.read_bytes()
    notebook = json.loads(notebook_bytes)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    expected_hashes: set[str] = set()
    candidates: list[tuple[int, str, str]] = []

    for cell_index, cell in enumerate(notebook.get("cells", [])):
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell.get("source") or [])
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for name, value in assignment_strings(tree).items():
            if "SHA256" in name.upper() and len(value) == 64:
                expected_hashes.add(value.lower())
            if len(value) >= 500:
                candidates.append((cell_index, name, value))

    output_dir.mkdir(parents=True, exist_ok=True)
    for cell_index, name, value in candidates:
        for encoding, data in decoded_variants(value):
            inventory = python_inventory(data)
            if inventory is None or inventory["sha256"] in seen:
                continue
            seen.add(inventory["sha256"])
            filename = f"extracted_agent_{len(rows) + 1}.py"
            (output_dir / filename).write_bytes(data)
            rows.append(
                {
                    "cell": cell_index,
                    "assignment": name,
                    "encoding": encoding,
                    "path": filename,
                    "expected_hash_match": (
                        inventory["sha256"] in expected_hashes if expected_hashes else None
                    ),
                    **inventory,
                }
            )

    result = {
        "notebook": path.as_posix(),
        "notebook_sha256": sha256(notebook_bytes),
        "expected_source_hashes": sorted(expected_hashes),
        "agents": rows,
    }
    (output_dir / "extraction_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("notebook", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    result = extract_notebook(args.notebook, args.output_dir)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    if not result["agents"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
