#!/usr/bin/env python3
"""Build V121's sparse continuation model from current-meta winning routes."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FORENSICS = ROOT / "experiments/research_20260918_v121/live_forensics.json"
DEFAULT_AGENT = ROOT / "agents/v121/main.py"
DEFAULT_V120_MODEL = ROOT / "agents/v120/model.json.gz"
DEFAULT_MODEL = ROOT / "agents/v121/model.json.gz"
DEFAULT_METADATA = ROOT / "agents/v121/model_metadata.json"
DEFAULT_REPORT = ROOT / "experiments/research_20260918_v121/model_build.json"
TARGET_HASH = "8d1581ebb81f920f"
OPENING_END = 288
ANIMAL_CHECKPOINT = 360
EXPANSION_CHECKPOINT = 480


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--forensics", type=Path, default=DEFAULT_FORENSICS)
    parser.add_argument("--agent", type=Path, default=DEFAULT_AGENT)
    parser.add_argument("--v120-model", type=Path, default=DEFAULT_V120_MODEL)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--minimum-opponent-rating", type=float, default=1500.0)
    parser.add_argument("--target-hash", default=TARGET_HASH)
    parser.add_argument("--beam-size", type=int, default=8)
    return parser.parse_args()


def load_policy(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("v121_build_policy", path.resolve())
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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
        / "data/replays"
        / f"v120_submission_{int(row['submission_id'])}"
        / f"episode_{int(row['episode_id'])}.json"
    )


def portfolio(policy: Any, observation: Mapping[str, Any], seat: int) -> Counter[str]:
    farms = list(observation.get("farms") or [])
    farm = farms[seat] if 0 <= seat < len(farms) else {}
    counts: Counter[str] = Counter()
    for tile in policy.base._board(farm):
        if not isinstance(tile, Mapping):
            continue
        crop = tile.get("crop")
        animal = tile.get("animal")
        if crop:
            counts[str(crop)] += 1
        if animal:
            counts[str(animal)] += 1
    return counts


def animal_route(policy: Any, observation: Mapping[str, Any], seat: int) -> int:
    counts = portfolio(policy, observation, seat)
    if counts["GOOSE"] == 0 and counts["SHEEP"] >= 8:
        return policy.WOOL
    if counts["COW"] >= 9 and counts["SHEEP"] <= 6:
        return policy.MILK
    return policy.BALANCED


def expansion_route(policy: Any, observation: Mapping[str, Any], seat: int) -> int:
    farms = list(observation.get("farms") or [])
    farm = farms[seat] if 0 <= seat < len(farms) else {}
    counts = portfolio(policy, observation, seat)
    land = len(set(farm.get("unlocked_quadrants") or []))
    return int(land >= 4 and counts["TOMATO"] >= 8)


def main() -> int:
    args = parse_args()
    if args.beam_size < 1:
        raise ValueError("--beam-size must be positive")
    policy = load_policy(args.agent)
    forensics = read_json(args.forensics.resolve())
    selected = [
        row
        for row in forensics.get("records", [])
        if not row.get("is_self_play")
        and row.get("result") in {"win", "loss"}
        and float(row.get("opponent_initial_rating", 0.0)) >= args.minimum_opponent_rating
        and row.get("opponent_field_h48") == args.target_hash
    ]
    if not selected:
        raise RuntimeError("no state-compatible current-meta winners were selected")

    with gzip.open(args.v120_model.resolve(), "rt", encoding="utf-8") as stream:
        v120_model = json.load(stream)
    v120_steps = v120_model.get("steps") or []
    steps: list[list[list[Any]]] = [[] for _ in range(719)]
    for step in range(OPENING_END):
        for unit_count, features, action in v120_steps[step]:
            steps[step].append([unit_count, -1, -1, -1, features, action])

    provenance: list[dict[str, Any]] = []
    route_counts: Counter[str] = Counter()
    for source_id, row in enumerate(sorted(selected, key=lambda value: int(value["episode_id"]))):
        replay_path = replay_path_for(row)
        replay = read_json(replay_path)
        own_seat = int(row["seat"])
        teacher_seat = own_seat if row["result"] == "win" else 1 - own_seat
        replay_steps = replay.get("steps") or []
        if len(replay_steps) < 720:
            continue
        animal_observation = replay_steps[ANIMAL_CHECKPOINT][teacher_seat].get("observation") or {}
        expansion_observation = replay_steps[EXPANSION_CHECKPOINT][teacher_seat].get("observation") or {}
        animal = animal_route(policy, animal_observation, teacher_seat)
        expansion = expansion_route(policy, expansion_observation, teacher_seat)
        route_counts[f"{animal}:{expansion}"] += 1
        provenance.append(
            {
                "source": source_id,
                "submission_id": str(row["submission_id"]),
                "episode_id": str(row["episode_id"]),
                "teacher_seat": teacher_seat,
                "teacher_origin": "v120" if row["result"] == "win" else "winning_opponent",
                "opponent_initial_rating": row["opponent_initial_rating"],
                "animal_route": animal,
                "expansion": bool(expansion),
                "replay_path": replay_path.relative_to(ROOT).as_posix(),
            }
        )
        for step in range(OPENING_END, 719):
            observation = replay_steps[step][teacher_seat].get("observation") or {}
            action = normalized_action(replay_steps[step + 1][teacher_seat].get("action"))
            steps[step].append(
                [
                    policy.base.unit_count(observation),
                    source_id,
                    animal,
                    expansion,
                    policy.base.feature_vector(observation),
                    action,
                ]
            )

    runtime_model = {
        "format": policy.MODEL_FORMAT,
        "feature_length": policy.FEATURE_LENGTH,
        "beam_size": args.beam_size,
        "gate_steps": list(policy.DEFAULT_GATES),
        "steps": steps,
    }
    encoded = json.dumps(runtime_model, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    compressed = gzip.compress(encoded, compresslevel=9, mtime=0)
    args.model.parent.mkdir(parents=True, exist_ok=True)
    args.model.write_bytes(compressed)

    report = {
        "format": policy.MODEL_FORMAT,
        "minimum_opponent_rating": args.minimum_opponent_rating,
        "target_opening_hash": args.target_hash,
        "opening_policy": "v120 unchanged through step 287",
        "selected_winning_continuations": len(provenance),
        "teacher_origins": dict(Counter(row["teacher_origin"] for row in provenance)),
        "route_counts": dict(sorted(route_counts.items())),
        "beam_size": args.beam_size,
        "gate_steps": list(policy.DEFAULT_GATES),
        "training_examples": sum(map(len, steps)),
        "uncompressed_bytes": len(encoded),
        "compressed_bytes": len(compressed),
        "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    metadata = {
        "format": policy.MODEL_FORMAT,
        "description": "Sparse event-gated continuation library from current-meta winning public trajectories.",
        "runtime_excludes": [
            "episode ids",
            "submission ids",
            "team names",
            "ratings",
            "rewards and outcomes",
            "future observations",
        ],
        "selection_rule": (
            "V120 through day 12; state-compatible animal route; demand-backed expansion; "
            "nearest case inside a gate-latched source beam"
        ),
        "provenance": provenance,
        "build_report": args.report.resolve().relative_to(ROOT).as_posix(),
        "model_sha256": report["compressed_sha256"],
    }
    args.metadata.parent.mkdir(parents=True, exist_ok=True)
    args.metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
