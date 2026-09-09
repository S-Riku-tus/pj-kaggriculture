"""Probe public Kaggle notebook HTML without storing notebook source.

This is a discovery helper for executable-opponent acquisition.  It records
only HTTP metadata, page hashes, and URL/file markers; it never treats a page
listing or replay as executable Gold evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from urllib.parse import urljoin
from urllib.parse import urlparse

import requests


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update(
        {
            "Accept": "text/html,application/xhtml+xml,application/json",
            "User-Agent": "Mozilla/5.0 public-kaggriculture-opponent-probe/1.0",
        }
    )
    bootstrap = session.get(
        "https://www.kaggle.com/c/kaggriculture/code", timeout=args.timeout
    )
    xsrf = session.cookies.get("XSRF-TOKEN") or session.cookies.get("CSRF-TOKEN")
    if xsrf:
        session.headers["X-XSRF-TOKEN"] = xsrf
    response = session.get(args.url, timeout=args.timeout)
    text = response.text
    decoded = html.unescape(text.replace("\\u002F", "/").replace("\\/", "/"))

    rendered_urls = sorted(
        set(
            re.findall(
                r'"renderedOutputUrl"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"',
                decoded,
            )
        )
    )
    absolute_urls = sorted(
        {
            urljoin(response.url, value)
            for value in re.findall(r'https?://[^"\'<>\\ ]+', decoded)
            if any(
                marker in value.lower()
                for marker in (
                    "submission.tar.gz",
                    "main.py",
                    "my_agent.py",
                    "kaggleusercontent",
                    "databundle",
                    "output",
                )
            )
        }
    )
    script_versions = sorted(
        {int(value) for value in re.findall(r'"scriptVersionId"\s*:\s*(\d+)', decoded)}
    )
    parts = [part for part in urlparse(args.url).path.split("/") if part]
    owner = parts[1] if len(parts) >= 3 and parts[0] == "code" else ""
    slug = parts[2] if len(parts) >= 3 and parts[0] == "code" else ""
    api_probes = []
    if owner and slug:
        for method in ("GetKernel", "ListKernelSessionOutput"):
            api_url = f"https://www.kaggle.com/api/i/kernels.KernelsService/{method}"
            api_response = session.post(
                api_url,
                json={"userName": owner, "kernelSlug": slug},
                timeout=args.timeout,
            )
            try:
                payload = api_response.json()
            except requests.JSONDecodeError:
                payload = None
            files = []
            if isinstance(payload, dict):
                for item in payload.get("files", []) or []:
                    if isinstance(item, dict):
                        files.append(
                            {
                                "file_name": item.get("fileName"),
                                "url": item.get("url"),
                            }
                        )
            api_probes.append(
                {
                    "method": method,
                    "status": api_response.status_code,
                    "bytes": len(api_response.content),
                    "sha256": hashlib.sha256(api_response.content).hexdigest(),
                    "json_keys": sorted(payload) if isinstance(payload, dict) else [],
                    "files": files,
                    "error_preview": (
                        payload.get("error")
                        if isinstance(payload, dict) and "error" in payload
                        else None
                    ),
                }
            )
    output = {
        "requested_url": args.url,
        "bootstrap": {
            "status": bootstrap.status_code,
            "final_url": bootstrap.url,
            "bytes": len(bootstrap.content),
            "cookies": sorted(session.cookies.keys()),
        },
        "page": {
            "status": response.status_code,
            "final_url": response.url,
            "bytes": len(response.content),
            "sha256": hashlib.sha256(response.content).hexdigest(),
            "content_type": response.headers.get("Content-Type", ""),
        },
        "markers": {
            "rendered_output_urls": rendered_urls,
            "candidate_absolute_urls": absolute_urls,
            "script_version_ids": script_versions,
            "mentions_submission_tar_gz": "submission.tar.gz" in decoded,
            "mentions_main_py": "main.py" in decoded,
        },
        "api_probes": api_probes,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
