#!/usr/bin/env python3
"""Build v120's runtime-only case model from the dominant live opponent cohort."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FORENSICS = ROOT / "experiments/research_20260918_v120/live_forensics.json"
DEFAULT_AGENT = ROOT / "agents/v120/main.py"
DEFAULT_MODEL = ROOT / "agents/v120/model.json.gz"
DEFAULT_METADATA = ROOT / "agents/v120/model_metadata.json"
DEFAULT_REPORT = ROOT / "experiments/research_20260918_v120/imitation_validation.json"
TARGET_HASH = "8d1581ebb81f920f"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--forensics", type=Path, default=DEFAULT_FORENSICS)
    parser.add_argument("--agent", type=Path, default=DEFAULT_AGENT)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--target-hash", default=TARGET_HASH)
    parser.add_argument(
        "--include-source-id",
        action="store_true",
        help="append an opaque, per-teacher route id to each row",
    )
    return parser.parse_args()


def load_policy(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("v120_policy", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def normalized_action(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, Mapping) else {}
    return {
        "farmer": list(raw.get("farmer") or ["PASS"]),
        "hands": list(raw.get("hands") or []),
        "market": list(raw.get("market") or []),
    }


def replay_path_for(row: Mapping[str, Any]) -> Path:
    return (
        ROOT
        / "data"
        / "replays"
        / f"v119_submission_{int(row['submission_id'])}"
        / f"episode_{row['episode_id']}.json"
    )


def main() -> int:
    args = parse_args()
    policy = load_policy(args.agent.resolve())
    forensics = read_json(args.forensics.resolve())
    records = [
        row
        for row in forensics.get("records", [])
        if row.get("opponent_field_h48") == args.target_hash
    ]
    train_rows = [row for row in records if row.get("result") == "loss"]
    audit_rows = [row for row in records if row.get("result") != "loss"]
    if not train_rows:
        raise RuntimeError("no winning target-policy episodes were found")

    steps: list[list[list[Any]]] = [[] for _ in range(719)]
    provenance: list[dict[str, Any]] = []
    for source_index, row in enumerate(train_rows):
        replay_path = replay_path_for(row)
        replay = read_json(replay_path)
        teacher_seat = 1 - int(row["seat"])
        provenance.append(
            {
                "episode_id": str(row["episode_id"]),
                "replay_path": replay_path.relative_to(ROOT).as_posix(),
                "teacher_seat": teacher_seat,
            }
        )
        replay_steps = replay.get("steps", [])
        for step, state in enumerate(replay_steps[:719]):
            agent_state = state[teacher_seat]
            observation = agent_state.get("observation") or {}
            # Kaggle stores the action returned for observation t on replay
            # state t+1. Pairing equal indices delays the entire route by one
            # hour and is catastrophic for the opening hire/build sequence.
            action = normalized_action(replay_steps[step + 1][teacher_seat].get("action"))
            runtime_row = [
                policy.unit_count(observation),
                policy.feature_vector(observation),
                action,
            ]
            if args.include_source_id:
                runtime_row.append(source_index)
            steps[step].append(runtime_row)

    runtime_model = {
        "format": (
            "v126-opening-route-source-v1"
            if args.include_source_id
            else "v120-case-policy-v1"
        ),
        "feature_length": policy.FEATURE_LENGTH,
        "target_opening_hash": args.target_hash,
        "steps": steps,
    }
    encoded = json.dumps(runtime_model, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    compressed = gzip.compress(encoded, compresslevel=9, mtime=0)
    args.model.parent.mkdir(parents=True, exist_ok=True)
    args.model.write_bytes(compressed)

    audit_blocks: dict[str, dict[str, int]] = {}
    for row in audit_rows:
        replay = read_json(replay_path_for(row))
        teacher_seat = 1 - int(row["seat"])
        replay_steps = replay.get("steps", [])
        for step, state in enumerate(replay_steps[:719]):
            observation = state[teacher_seat].get("observation") or {}
            expected = normalized_action(replay_steps[step + 1][teacher_seat].get("action"))
            query = policy.feature_vector(observation)
            count = policy.unit_count(observation)
            candidates = steps[step]
            compatible = [candidate for candidate in candidates if int(candidate[0]) == count]
            pool = compatible or candidates
            chosen = min(pool, key=lambda candidate: policy.feature_distance(query, candidate[1]))
            block = f"{step // 144}"
            bucket = audit_blocks.setdefault(block, {"exact": 0, "field": 0, "total": 0})
            bucket["total"] += 1
            bucket["exact"] += canonical(chosen[2]) == canonical(expected)
            bucket["field"] += canonical(
                [chosen[2].get("farmer"), chosen[2].get("hands")]
            ) == canonical([expected.get("farmer"), expected.get("hands")])

    validation = {
        "target_opening_hash": args.target_hash,
        "target_cohort_games": len(records),
        "training_teacher_wins": len(train_rows),
        "held_out_nonwins": len(audit_rows),
        "training_examples": sum(len(rows) for rows in steps),
        "feature_length": policy.FEATURE_LENGTH,
        "uncompressed_bytes": len(encoded),
        "compressed_bytes": len(compressed),
        "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
        "held_out_action_agreement_by_block": {
            block: {
                **values,
                "exact_rate": values["exact"] / values["total"] if values["total"] else 0.0,
                "field_rate": values["field"] / values["total"] if values["total"] else 0.0,
            }
            for block, values in sorted(audit_blocks.items())
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    metadata = {
        "format": runtime_model["format"],
        "description": "Successful public-replay decisions from the dominant live opening cohort.",
        "runtime_excludes": [
            "episode ids",
            "submission ids",
            "ratings",
            "rewards and outcomes",
            "future observations",
        ],
        "selection_rule": "same step; same unit count when available; nearest current-state feature vector",
        "opaque_source_ids": bool(args.include_source_id),
        "provenance": provenance,
        "validation_report": args.report.resolve().relative_to(ROOT).as_posix(),
        "model_sha256": validation["compressed_sha256"],
    }
    args.metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
