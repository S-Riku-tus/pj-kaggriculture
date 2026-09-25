"""Build the Round10 public-source ledger from saved API responses and files."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ROUND = ROOT / "experiments/round10_public_learning_20260924"

SOURCES: dict[str, dict[str, Any]] = {
    "ahmed_v56": {
        "directory": "ahmedberatozer__kaggriculture-v56-smarter-seeds-and-fertilizer",
        "url": "https://www.kaggle.com/code/ahmedberatozer/kaggriculture-v56-smarter-seeds-and-fertilizer",
        "title_score_claim": None,
        "base_ancestor": "large shared public lineage; V57 is a later Ahmed variant",
        "main_change": "seed purchases tied to remaining planting opportunities; fertilizer pruning",
    },
    "ahmed_v57": {
        "directory": "ahmedberatozer__kaggriculture-v57-funding-order-invariant",
        "url": "https://www.kaggle.com/code/ahmedberatozer/kaggriculture-v57-funding-order-invariant",
        "title_score_claim": None,
        "base_ancestor": "Ahmed V56/shared public lineage",
        "main_change": "funding-order invariant opening and purchase ordering",
    },
    "order_book": {
        "directory": "shiiin9__your-market-list-is-an-order-book",
        "url": "https://www.kaggle.com/code/shiiin9/your-market-list-is-an-order-book",
        "title_score_claim": None,
        "base_ancestor": "shared public production/runtime lineage",
        "main_change": "ordered market-list and relative price-impact logic",
    },
    "metav4": {
        "directory": "thomastschinkel__the-metav4-farm-submission-v13",
        "url": "https://www.kaggle.com/code/thomastschinkel/the-metav4-farm-submission-v13",
        "title_score_claim": None,
        "base_ancestor": "Metav4 public submission lineage",
        "main_change": "submission-v13 integrated farm policy",
    },
    "herd_safe": {
        "directory": "dmitriigluzdov__kaggriculture-herd-safe-sale-window-lb-2700",
        "url": "https://www.kaggle.com/code/dmitriigluzdov/kaggriculture-herd-safe-sale-window-lb-2700",
        "title_score_claim": 2700,
        "base_ancestor": "public V39 plus Dmitrii Gluzdov v9 layers and shared public lineage",
        "main_change": "herd-safe sale window and opening-liquidity layer",
    },
    "melon_threshold": {
        "directory": "goodpjw2008__kaggriculture-melon-threshold-squeeze-2749",
        "url": "https://www.kaggle.com/code/goodpjw2008/kaggriculture-melon-threshold-squeeze-2749",
        "title_score_claim": 2749,
        "base_ancestor": "Ahmed V45-derived/shared public lineage",
        "main_change": "melon threshold and first-turn squeeze/counter logic",
    },
    "barnyard": {
        "directory": "romanrozen__strong-barnyard-economist",
        "url": "https://www.kaggle.com/code/romanrozen/strong-barnyard-economist/notebook",
        "title_score_claim": None,
        "base_ancestor": "not established from the fetched payload",
        "main_change": "replacement seventh candidate after Harvest Ledger returned 404",
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return sorted(names)


def original_source_hash(acquisition: dict[str, Any]) -> tuple[str | None, str]:
    for payload in acquisition.get("payloads") or []:
        decoded = payload.get("decoded_sources") or []
        if decoded:
            return str(decoded[0].get("sha256")), "decoded archive member before text newline normalization"
        main = payload.get("main") or {}
        if main.get("source_sha256"):
            return str(main["source_sha256"]), "concatenated notebook main cell before text newline normalization"
    return None, "not recorded"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    records = []
    for name, specification in SOURCES.items():
        source_dir = ROUND / "public_sources" / specification["directory"]
        acquisition = json.loads((source_dir / "acquisition_result.json").read_text(encoding="utf-8"))
        response = json.loads((source_dir / "kernels_pull_response.json").read_text(encoding="utf-8"))
        metadata = response.get("metadata") or {}
        agent_path = ROUND / "public_agents" / name / "main.py"
        payloads = acquisition.get("payloads") or []
        notebook_hash = payloads[0].get("sha256") if payloads else None
        original_hash, original_scope = original_source_hash(acquisition)
        text = agent_path.read_text(encoding="utf-8")
        records.append(
            {
                "id": name,
                "author": metadata.get("author"),
                "original_url": specification["url"],
                "kernel_ref": metadata.get("ref"),
                "kernel_id": metadata.get("id"),
                "notebook_current_version_number": metadata.get("currentVersionNumber"),
                "script_version_id": None,
                "script_version_id_note": "not returned by the saved unauthenticated kernels/pull response",
                "acquired_at_utc": acquisition.get("fetched_at_utc"),
                "public_last_run_time": metadata.get("lastRunTime"),
                "public_description_date": None,
                "license": "Apache-2.0" if "Apache License" in text else "not established",
                "notebook_sha256": notebook_hash,
                "api_response_sha256": acquisition.get("response_sha256"),
                "original_embedded_source_sha256": original_hash,
                "original_embedded_source_hash_scope": original_scope,
                "executed_local_agent_sha256": sha256_file(agent_path),
                "executed_local_agent_bytes": agent_path.stat().st_size,
                "executed_local_agent_lines": len(text.splitlines()),
                "imports": imports(agent_path),
                "score_fields": {
                    "title_score_claim": specification["title_score_claim"],
                    "historical_best_score": None,
                    "current_display_score": None,
                    "score_at_match_time": None,
                },
                "base_ancestor": specification["base_ancestor"],
                "main_change": specification["main_change"],
                "unconfirmed": [
                    "current leaderboard strength",
                    "Kaggle deployed submission artifact identity",
                    "exact correspondence between any title score and this fetched source",
                ],
                "acquisition_status": acquisition.get("http_status"),
            }
        )
    failed_dir = ROUND / "public_sources/haodou092__notebookdb6965aa8e"
    failed = json.loads((failed_dir / "acquisition_result.json").read_text(encoding="utf-8"))
    result = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "records": records,
        "failed_acquisitions": [
            {
                "kernel": "haodou092/notebookdb6965aa8e",
                "url": "https://www.kaggle.com/code/haodou092/notebookdb6965aa8e",
                "http_status": failed.get("http_status"),
                "acquired_at_utc": failed.get("fetched_at_utc"),
                "replacement": "romanrozen/strong-barnyard-economist",
            }
        ],
        "score_note": "title, historical best, current display, and score-at-match are deliberately separate",
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"records": len(records), "failed": len(result["failed_acquisitions"])}, indent=2))


if __name__ == "__main__":
    main()
