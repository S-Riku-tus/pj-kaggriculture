"""Acquire and inventory a public Kaggle notebook without authentication.

The raw ``kernels/pull`` response is always preserved before extraction.  If
the notebook contains exactly one ``%%writefile main.py`` cell, its contents
are extracted byte-for-byte after removing only the magic line.
"""

from __future__ import annotations

import argparse
import ast
import base64
import gzip
import hashlib
import io
import json
import re
import tarfile
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

KERNEL_RE = re.compile(r"^[A-Za-z0-9_-]+/[A-Za-z0-9_-]+$")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def candidate_payloads(value: Any, path: str = "$") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            found.extend(candidate_payloads(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(candidate_payloads(child, f"{path}[{index}]"))
    elif isinstance(value, str) and '"cells"' in value and '"nbformat"' in value:
        found.append((path, value))
    return found


def extract_main(notebook_text: str) -> tuple[str | None, dict[str, Any]]:
    notebook = json.loads(notebook_text)
    cells = [
        cell
        for cell in notebook.get("cells", [])
        if cell.get("cell_type") == "code"
        and "%%writefile main.py" in "".join(cell.get("source") or [])
    ]
    inventory: dict[str, Any] = {
        "main_cells": len(cells),
        "cell_ids": [cell.get("id") for cell in cells],
    }
    if len(cells) != 1:
        return None, inventory
    cell_source = "".join(cells[0].get("source") or [])
    magic, separator, source = cell_source.partition("\n")
    if magic.strip() != "%%writefile main.py" or not separator:
        inventory["error"] = "main.py magic mismatch"
        return None, inventory
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        inventory["error"] = f"main.py does not parse: {exc}"
        return None, inventory
    inventory.update(
        {
            "source_bytes": len(source.encode("utf-8")),
            "source_sha256": sha256(source.encode("utf-8")),
            "top_level_functions": [
                node.name for node in tree.body if isinstance(node, ast.FunctionDef)
            ],
        }
    )
    return source, inventory


def _python_agent_source(data: bytes) -> str | None:
    try:
        source = data.decode("utf-8")
        tree = ast.parse(source)
    except (UnicodeDecodeError, SyntaxError):
        return None
    if any(isinstance(node, ast.FunctionDef) and node.name == "agent" for node in ast.walk(tree)):
        return source
    return None


def _decoded_variants(data: bytes) -> list[bytes]:
    variants = [data]
    for decoder in (base64.b64decode, base64.b85decode, base64.a85decode):
        try:
            decoded = decoder(data)
        except (ValueError, TypeError):
            continue
        if decoded:
            variants.append(decoded)
    expanded = list(variants)
    for value in variants:
        for decompressor in (zlib.decompress, gzip.decompress):
            try:
                decoded = decompressor(value)
            except (OSError, zlib.error):
                continue
            if decoded:
                expanded.append(decoded)
    return expanded


def decode_embedded_sources(notebook_text: str) -> list[tuple[str, str]]:
    notebook = json.loads(notebook_text)
    found: dict[str, tuple[str, str]] = {}
    for cell_index, cell in enumerate(notebook.get("cells", [])):
        if cell.get("cell_type") != "code":
            continue
        cell_source = "".join(cell.get("source") or [])
        try:
            tree = ast.parse(cell_source)
        except SyntaxError:
            continue
        strings = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and len(node.value) >= 500
        ]
        for string_index, value in enumerate(strings):
            try:
                raw = value.encode("ascii")
            except UnicodeEncodeError:
                raw = value.encode("utf-8")
            for variant in _decoded_variants(raw):
                source = _python_agent_source(variant)
                if source is not None:
                    digest = sha256(source.encode("utf-8"))
                    found[digest] = (f"cell[{cell_index}].string[{string_index}]", source)
                    continue
                try:
                    with tarfile.open(fileobj=io.BytesIO(variant), mode="r:*") as archive:
                        member = next(
                            (item for item in archive.getmembers() if Path(item.name).name == "main.py"),
                            None,
                        )
                        if member is None:
                            continue
                        handle = archive.extractfile(member)
                        source = _python_agent_source(handle.read() if handle else b"")
                except (tarfile.TarError, OSError):
                    continue
                if source is not None:
                    digest = sha256(source.encode("utf-8"))
                    found[digest] = (f"cell[{cell_index}].string[{string_index}].tar", source)
    return list(found.values())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kernel", help="Public owner/slug pair")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args()
    if not KERNEL_RE.fullmatch(args.kernel):
        raise SystemExit("kernel must be an owner/slug pair")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    url = f"https://www.kaggle.com/api/v1/kernels/pull/{args.kernel}"
    response = requests.get(
        url,
        timeout=args.timeout,
        headers={
            "Accept": "application/json",
            "User-Agent": "public-kaggriculture-notebook-acquisition/1.0",
        },
    )
    raw = response.content
    (args.output_dir / "kernels_pull_response.json").write_bytes(raw)
    result: dict[str, Any] = {
        "fetched_at_utc": datetime.now(UTC).isoformat(),
        "kernel": args.kernel,
        "url": url,
        "http_status": response.status_code,
        "content_type": response.headers.get("Content-Type", ""),
        "response_bytes": len(raw),
        "response_sha256": sha256(raw),
        "complete_json": False,
        "payloads": [],
    }
    try:
        payload = response.json()
    except requests.JSONDecodeError as exc:
        result["parse_error"] = str(exc)
    else:
        result["complete_json"] = True
        if isinstance(payload, dict):
            metadata = payload.get("metadata") or {}
            result["metadata"] = {
                key: metadata.get(key)
                for key in ("ref", "title", "author", "slug", "lastRunTime")
            }
        seen: set[str] = set()
        for json_path, text in candidate_payloads(payload):
            payload_hash = sha256(text.encode("utf-8"))
            if payload_hash in seen:
                continue
            seen.add(payload_hash)
            name = f"payload_{len(seen)}.ipynb"
            (args.output_dir / name).write_text(text, encoding="utf-8")
            source, inventory = extract_main(text)
            row = {
                "json_path": json_path,
                "path": name,
                "bytes": len(text.encode("utf-8")),
                "sha256": payload_hash,
                "main": inventory,
            }
            if source is not None:
                main_name = "extracted_main.py"
                (args.output_dir / main_name).write_text(source, encoding="utf-8")
                row["extracted_main"] = main_name
            decoded_sources = decode_embedded_sources(text)
            row["decoded_sources"] = []
            for source_index, (source_path, decoded_source) in enumerate(decoded_sources, start=1):
                decoded_name = f"decoded_main_{source_index}.py"
                (args.output_dir / decoded_name).write_text(decoded_source, encoding="utf-8")
                row["decoded_sources"].append(
                    {
                        "source_path": source_path,
                        "path": decoded_name,
                        "bytes": len(decoded_source.encode("utf-8")),
                        "sha256": sha256(decoded_source.encode("utf-8")),
                    }
                )
            result["payloads"].append(row)

    (args.output_dir / "acquisition_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=True, indent=2))
    if response.status_code != 200 or not result["complete_json"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
