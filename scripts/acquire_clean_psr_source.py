"""Read-only acquisition of the preregistered public PSR Kaggle notebook.

The public ``kernels/pull`` endpoint is fetched without authentication.  The raw
response is frozen before any extraction so a failed or partial extraction can
never be replaced by guesses from the notebook title or score.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

URL = "https://www.kaggle.com/api/v1/kernels/pull/thomastschinkel/kaggriculture-93-8-win-rate-public-state-router"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def string_inventory(value: Any, path: str = "$") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            rows.extend(string_inventory(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            rows.extend(string_inventory(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        rows.append(
            {
                "path": path,
                "characters": len(value),
                "sha256_utf8": sha256(value.encode("utf-8")),
                "markers": {
                    "ipynb": '"cells"' in value and '"nbformat"' in value,
                    "agent": "def agent" in value,
                    "main_py": "main.py" in value,
                    "apache": "Apache" in value,
                },
            }
        )
    return rows


def candidate_payloads(value: Any, path: str = "$") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            found.extend(candidate_payloads(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(candidate_payloads(child, f"{path}[{index}]"))
    elif isinstance(value, str) and (('"cells"' in value and '"nbformat"' in value) or "def agent" in value):
        found.append((path, value))
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    fetched_at = datetime.now(UTC).isoformat()
    response = requests.get(
        URL,
        timeout=args.timeout,
        headers={
            "Accept": "application/json",
            "User-Agent": "public-kaggriculture-psr-acquisition/1.0",
        },
    )
    raw = response.content
    (args.output_dir / "kernels_pull_response.json").write_bytes(raw)
    result: dict[str, Any] = {
        "fetched_at": fetched_at,
        "url": URL,
        "http_status": response.status_code,
        "content_type": response.headers.get("Content-Type", ""),
        "bytes": len(raw),
        "sha256": sha256(raw),
        "complete_json": False,
        "extracted": [],
    }
    try:
        payload = response.json()
    except requests.JSONDecodeError as exc:
        result["parse_error"] = str(exc)
    else:
        result["complete_json"] = True
        result["top_level_keys"] = sorted(payload) if isinstance(payload, dict) else []
        result["string_inventory"] = string_inventory(payload)
        for index, (json_path, text) in enumerate(candidate_payloads(payload), start=1):
            suffix = ".ipynb" if '"cells"' in text and '"nbformat"' in text else ".py"
            name = f"payload_{index}{suffix}"
            data = text.encode("utf-8")
            (args.output_dir / name).write_bytes(data)
            result["extracted"].append(
                {
                    "json_path": json_path,
                    "path": name,
                    "bytes": len(data),
                    "sha256": sha256(data),
                }
            )
    (args.output_dir / "acquisition_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if response.status_code != 200 or not result["complete_json"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
