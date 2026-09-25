"""Fetch Round11 public Kaggle notebook payloads without executing them.

Uses Kaggle's public kernels/pull endpoint, stores the raw response and any
embedded notebook payload, and records hashes and public metadata.  The script
does not read credentials and has no submit or publish operation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


TARGETS = [
    "dmitriigluzdov/kaggriculture-more-wheat-smarter-sales",
    "arsgorynich/order-book-v3-response-improvement",
    "prvsiyan/kaggriculture-frontier-the-moon-counts-melons",
    "wzhengbiao/kaggriculture-v15stack-submit",
    "hanifnoerrofiq/a-wonderful-life",
    "haideptry/the-2965-master-hybrid-engine",
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(ref: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "__", ref)


def find_notebooks(value: Any, json_path: str = "$") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            found.extend(find_notebooks(child, f"{json_path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(find_notebooks(child, f"{json_path}[{index}]"))
    elif isinstance(value, str):
        try:
            candidate = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return found
        if isinstance(candidate, dict) and isinstance(candidate.get("cells"), list):
            found.append((json_path, value))
    return found


def fetch(ref: str, output_root: Path, overwrite: bool) -> dict[str, Any]:
    destination = output_root / safe_name(ref)
    if destination.exists() and any(destination.iterdir()) and not overwrite:
        raise FileExistsError(f"refusing to overwrite {destination}; pass --overwrite")
    destination.mkdir(parents=True, exist_ok=True)
    url = f"https://www.kaggle.com/api/v1/kernels/pull/{ref}"
    request = urllib.request.Request(url, headers={"User-Agent": "round11-public-audit/1"})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            raw = response.read()
            status = response.status
            content_type = response.headers.get("Content-Type")
    except urllib.error.HTTPError as error:
        raw = error.read()
        status = error.code
        content_type = error.headers.get("Content-Type")

    (destination / "kernels_pull_response.json").write_bytes(raw)
    result: dict[str, Any] = {
        "fetched_at_utc": datetime.now(UTC).isoformat(),
        "kernel": ref,
        "url": url,
        "http_status": status,
        "content_type": content_type,
        "response_bytes": len(raw),
        "response_sha256": sha256(raw),
        "complete_json": False,
        "payloads": [],
    }
    try:
        document = json.loads(raw)
        result["complete_json"] = True
    except json.JSONDecodeError:
        document = None
    if isinstance(document, dict):
        metadata = document.get("metadata")
        if isinstance(metadata, dict):
            result["metadata"] = {
                key: metadata.get(key)
                for key in (
                    "ref",
                    "title",
                    "author",
                    "slug",
                    "lastRunTime",
                    "currentVersionNumber",
                )
            }
        for index, (json_path, notebook) in enumerate(find_notebooks(document), start=1):
            data = notebook.encode("utf-8")
            path = destination / f"payload_{index}.ipynb"
            path.write_bytes(data)
            result["payloads"].append(
                {
                    "json_path": json_path,
                    "path": path.name,
                    "bytes": len(data),
                    "sha256": sha256(data),
                }
            )
    (destination / "acquisition_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    outcomes = [fetch(ref, args.output_root, args.overwrite) for ref in TARGETS]
    for outcome in outcomes:
        print(
            outcome["kernel"],
            outcome["http_status"],
            outcome["response_sha256"],
            len(outcome["payloads"]),
        )


if __name__ == "__main__":
    main()
