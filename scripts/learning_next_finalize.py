"""Assemble compact top-level manifests from completed learning-next runs."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "learning_next_20260921"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def combine_csv(name: str, evaluations: list[Path]) -> None:
    rows: list[dict[str, Any]] = []
    fields = ["evaluation_id"]
    for evaluation in evaluations:
        path = evaluation / name
        if not path.is_file():
            continue
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                item = {"evaluation_id": evaluation.name, **row}
                rows.append(item)
                for key in item:
                    if key not in fields:
                        fields.append(key)
    if not rows:
        return
    with (EXPERIMENT / name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    evaluations = sorted(
        path
        for path in EXPERIMENT.iterdir()
        if path.is_dir() and (path / "evaluation_manifest.json").is_file()
    )
    write_json(
        EXPERIMENT / "dataset_manifest.json",
        {
            "created_at_utc": datetime.now(UTC).isoformat(),
            "tasks": {
                task: read_json(EXPERIMENT / "datasets" / task / "dataset_manifest.json")
                for task in ("b", "a", "bc")
            },
        },
    )
    write_json(
        EXPERIMENT / "offline_metrics.json",
        {task: read_json(EXPERIMENT / f"offline_metrics_{task}.json") for task in ("b", "a", "bc")},
    )
    evaluation_index = {
        evaluation.name: read_json(evaluation / "evaluation_manifest.json") for evaluation in evaluations
    }
    write_json(EXPERIMENT / "evaluation_manifest.json", {"evaluations": evaluation_index})
    for name in ("model_usage.json", "inference_benchmark.json", "paired_summary.json"):
        write_json(
            EXPERIMENT / name,
            {
                evaluation.name: read_json(evaluation / name)
                for evaluation in evaluations
                if (evaluation / name).is_file()
            },
        )
    combine_csv("paired_results.csv", evaluations)
    combine_csv("payoff_by_family.csv", evaluations)

    critical = [
        "source_manifest.json",
        "dataset_manifest.json",
        "split_manifest.json",
        "feature_schema.json",
        "offline_metrics.json",
        "model_usage.json",
        "paired_results.csv",
        "payoff_by_family.csv",
        "paired_summary.json",
        "evaluation_manifest.json",
        "inference_benchmark.json",
        "archive_manifest.json",
        "package_validation.json",
        "engine_comparison.json",
        "repair_history.json",
        "verification.json",
        "commands.jsonl",
        "RESUME_COMMANDS.md",
        "REPORT_JA.md",
    ]
    files = {}
    for relative in critical:
        path = EXPERIMENT / relative
        if path.is_file():
            files[relative] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    archive_manifest = read_json(EXPERIMENT / "archive_manifest.json")
    final = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "study_id": "learning_next_20260921",
        "c0": archive_manifest["c0"],
        "models": {
            name: {
                "path": str((EXPERIMENT / "models" / name).relative_to(ROOT)),
                "sha256": sha256(EXPERIMENT / "models" / name),
            }
            for name in ("b_model.npz", "a_model.npz", "bc_actor_model.npz", "bc_market_model.npz")
        },
        "archives": archive_manifest["arms"],
        "evaluations": evaluation_index,
        "files": files,
        "kaggle_submission_performed": False,
        "rating_3000_claimed": False,
    }
    write_json(EXPERIMENT / "FINAL_MANIFEST.json", final)


if __name__ == "__main__":
    main()
