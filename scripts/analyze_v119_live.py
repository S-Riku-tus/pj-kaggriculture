"""Focused diagnosis of the two V119 live submissions.

This script consumes the detailed output produced by
``analyze_20260917_v117_live.py`` and the public replay JSON files.  It adds
the V119 router's actual branch choices, rating-band performance, conditional
checkpoint gaps, and action-consensus diagnostics for repeated opponent
openings.  Replay-only identities and ratings are analysis inputs, never
runtime features.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FORENSICS = ROOT / "experiments/research_20260918_v120/live_forensics.json"
DEFAULT_OUTPUT = ROOT / "experiments/research_20260918_v120/live_diagnosis.json"
PSR_SOURCE = (
    ROOT
    / "experiments/research_20260914_clean_psr/candidates/P1_psr_clean/main.py"
)
BLOCKS = ((0, 144), (144, 288), (288, 432), (432, 576), (576, 719))
CHECKPOINTS = (24, 96, 168, 240, 288, 360, 480, 576, 648, 696, 719)
METRICS = ("money", "productive", "inventory_value")


def _load_psr() -> Any:
    spec = importlib.util.spec_from_file_location("_v119_psr_analysis", PSR_SOURCE)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {PSR_SOURCE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical(action: object) -> str:
    return json.dumps(action or {}, sort_keys=True, separators=(",", ":"))


def _hash_actions(actions: list[str]) -> str:
    return hashlib.sha256("\n".join(actions).encode()).hexdigest()[:16]


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = probability * (len(ordered) - 1)
    lower, upper = math.floor(index), math.ceil(index)
    if lower == upper:
        return ordered[lower]
    fraction = index - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"episodes": 0}
    margins = [float(row["margin"]) for row in rows]
    return {
        "episodes": len(rows),
        "wins": sum(row["result"] == "win" for row in rows),
        "losses": sum(row["result"] == "loss" for row in rows),
        "draws": sum(row["result"] == "draw" for row in rows),
        "win_score": mean(
            1.0 if row["result"] == "win" else 0.5 if row["result"] == "draw" else 0.0
            for row in rows
        ),
        "mean_reward": mean(float(row["reward"]) for row in rows),
        "mean_margin": mean(margins),
        "median_margin": _quantile(margins, 0.5),
        "p10_margin": _quantile(margins, 0.1),
        "mean_opponent_rating": mean(float(row["opponent_initial_rating"]) for row in rows),
    }


def _checkpoint_gaps(rows: list[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for result in ("win", "loss", "draw"):
        selected = [row for row in rows if row["result"] == result]
        if not selected:
            continue
        output[result] = {}
        for checkpoint in CHECKPOINTS:
            key = str(checkpoint)
            output[result][key] = {
                metric: mean(
                    float(row["own_checkpoints"][key][metric])
                    - float(row["opponent_checkpoints"][key][metric])
                    for row in selected
                )
                for metric in METRICS
            }
    return output


def _action_consensus(
    action_sequences: list[list[str]],
) -> dict[str, Any]:
    if not action_sequences:
        return {"episodes": 0}
    horizon = min(map(len, action_sequences))
    modal_support: list[float] = []
    for step in range(horizon):
        counts = Counter(sequence[step] for sequence in action_sequences)
        modal_support.append(counts.most_common(1)[0][1] / len(action_sequences))
    block_summaries = []
    for start, end in BLOCKS:
        support = modal_support[start:min(end, horizon)]
        sequence_hashes = Counter(_hash_actions(sequence[start:end]) for sequence in action_sequences)
        block_summaries.append(
            {
                "start": start,
                "end": end,
                "unique_sequences": len(sequence_hashes),
                "largest_sequence_cluster": sequence_hashes.most_common(1)[0][1],
                "mean_modal_step_support": mean(support),
                "minimum_modal_step_support": min(support),
            }
        )
    return {
        "episodes": len(action_sequences),
        "horizon": horizon,
        "full_sequence_clusters": [
            {"hash": key, "episodes": count}
            for key, count in Counter(_hash_actions(sequence[:horizon]) for sequence in action_sequences).most_common()
        ],
        "mean_modal_step_support": mean(modal_support),
        "steps_with_unanimous_action": sum(value == 1.0 for value in modal_support),
        "blocks": block_summaries,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--forensics", type=Path, default=DEFAULT_FORENSICS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    forensics_path = args.forensics if args.forensics.is_absolute() else ROOT / args.forensics
    output_path = args.output if args.output.is_absolute() else ROOT / args.output
    source = json.loads(forensics_path.read_text(encoding="utf-8"))
    records = [row for row in source["records"] if not row["is_self_play"]]
    psr = _load_psr()

    opponent_sequences: dict[str, list[list[str]]] = defaultdict(list)
    router_choices: dict[str, Counter[int]] = {
        "day_6": Counter(),
        "day_24": Counter(),
    }
    route_rows: dict[str, dict[int, list[dict[str, Any]]]] = {
        "day_6": defaultdict(list),
        "day_24": defaultdict(list),
    }

    for row in records:
        replay_path = (
            ROOT
            / "data/replays"
            / f"v119_submission_{row['submission_id']}"
            / f"episode_{row['episode_id']}.json"
        )
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
        steps = replay.get("steps") or []
        seat = int(row["seat"])
        opponent_seat = 1 - seat
        actions = [
            _canonical(step[opponent_seat].get("action"))
            for step in steps
            if opponent_seat < len(step)
        ]
        opponent_sequences[str(row["opponent_field_h48"])].append(actions)

        for label, step_index, block in (("day_6", 144, 1), ("day_24", 576, 4)):
            observation = steps[step_index][seat].get("observation") or {}
            route = int(psr._choose(block, psr._features(observation)))
            router_choices[label][route] += 1
            route_rows[label][route].append(row)

    rating_bands = {}
    for lower, upper in ((0, 1250), (1250, 1400), (1400, 1500), (1500, 1600), (1600, 1700), (1700, 10000)):
        rating_bands[f"{lower}_{upper}"] = _summary(
            [row for row in records if lower <= float(row["opponent_initial_rating"]) < upper]
        )

    repeated_openings = {}
    for opening, sequences in opponent_sequences.items():
        if len(sequences) < 2:
            continue
        selected = [row for row in records if row["opponent_field_h48"] == opening]
        repeated_openings[opening] = {
            "performance": _summary(selected),
            "action_consensus": _action_consensus(sequences),
            "opponent_submission_ids": dict(Counter(str(row["opponent_submission_id"]) for row in selected)),
        }

    output = {
        "format": "kaggriculture-v119-live-diagnosis-v1",
        "source": str(forensics_path.relative_to(ROOT)).replace("\\", "/"),
        "overall": _summary(records),
        "rating_bands": rating_bands,
        "router": {
            label: {
                "choices": {str(route): count for route, count in sorted(router_choices[label].items())},
                "outcomes": {
                    str(route): _summary(selected)
                    for route, selected in sorted(route_rows[label].items())
                },
            }
            for label in router_choices
        },
        "checkpoint_gaps_by_result": _checkpoint_gaps(records),
        "repeated_opponent_openings": repeated_openings,
        "diagnosis": {
            "primary_target_opening": "8d1581ebb81f920f",
            "analysis_only_features": [
                "submission IDs",
                "team names",
                "ratings",
                "replay hashes",
                "future outcomes",
            ],
            "causal_limit": "Associations require prospective paired-game validation before promotion.",
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"output: {output_path}")


if __name__ == "__main__":
    main()
