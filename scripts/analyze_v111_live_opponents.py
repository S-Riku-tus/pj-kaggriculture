"""Analyze V110's observable opponent lineages and continuation failures.

This is a descriptive audit.  It never exposes team identity, rating, or
submission metadata to runtime code, and it does not promote a continuation
because it beat V110.  The output is used to decide whether a repeated,
same-opening continuation is sufficiently supported to become a candidate
teacher at all.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v110 import main as v110  # noqa: E402
from scripts.train_v111_strategy import (  # noqa: E402
    _action,
    _canonical_action,
    _lineage_hashes,
    _observation,
    _portfolio,
    _replay_path,
)

SUBMISSION = ROOT / "data/submissions/v110_submission_55903573"
OUTPUT = ROOT / "data/analysis/v111_live_opponent_lineages.json"
CHECKPOINT_DAYS = (1, 3, 7, 10, 12, 15, 20, 24, 29)


def _manifest() -> list[dict[str, str]]:
    with (SUBMISSION / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        return [
            row
            for row in csv.DictReader(handle)
            if row.get("replay_status") in {"downloaded", "skipped_existing"}
            and int(float(row.get("step_count") or 0)) >= 719
        ]


def _clone_trace(replay: dict[str, Any], seat: int) -> dict[str, Any]:
    confidence = 0
    maximum = 0
    first_confident: int | None = None
    distances: dict[str, int] = {}
    for step in (4, 24, *range(48, 720, 24)):
        obs = _observation(replay, step, seat)
        if obs is None:
            continue
        farms = obs.get("farms") or []
        if len(farms) < 2:
            continue
        distance = v110._signature_distance(
            v110._farm_signature(farms[seat]), v110._farm_signature(farms[1 - seat])
        )
        distances[str(step)] = int(distance)
        if distance <= 1:
            confidence = min(8, confidence + 1)
        elif distance <= 4:
            confidence = max(0, confidence - 1)
        else:
            confidence = max(0, confidence - 3)
        maximum = max(maximum, confidence)
        if confidence >= v110.CLONE_MIN_CONFIDENCE and first_confident is None:
            first_confident = step
    return {
        "maximum": maximum,
        "first_confident_step": first_confident,
        "distances": distances,
    }


def _similarity(replay: dict[str, Any], seat: int, end_step: int) -> dict[str, Any]:
    matches = 0
    first_difference: int | None = None
    for step in range(min(end_step, len(replay.get("steps") or []) - 1)):
        own = _canonical_action(_action(replay, step, seat))
        opponent = _canonical_action(_action(replay, step, 1 - seat))
        if own == opponent:
            matches += 1
        elif first_difference is None:
            first_difference = step
    return {
        "share": matches / max(1, end_step),
        "first_difference": first_difference,
    }


def _snapshots(replay: dict[str, Any], seat: int) -> dict[str, Any]:
    result = {}
    for day in CHECKPOINT_DAYS:
        obs = _observation(replay, day * 24, seat)
        if obs is None:
            continue
        farms = obs.get("farms") or []
        if len(farms) < 2:
            continue
        result[str(day)] = {
            "own": _portfolio(farms[seat]),
            "opponent": _portfolio(farms[1 - seat]),
            "own_money": float(farms[seat].get("money") or 0),
            "opponent_money": float(farms[1 - seat].get("money") or 0),
            "shops": list((obs.get("town") or {}).get("unlocked_shops") or []),
        }
    return result


def _group_summary(records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record[key])].append(record)
    rows = []
    for lineage, selected in grouped.items():
        rows.append(
            {
                "lineage": lineage,
                "episodes": len(selected),
                "v110_results": dict(Counter(record["result"] for record in selected)),
                "mean_v110_margin": mean(float(record["margin"]) for record in selected),
                "minimum_v110_margin": min(float(record["margin"]) for record in selected),
                "mean_action_similarity_h200": mean(
                    float(record["similarity_h200"]["share"]) for record in selected
                ),
                "episode_ids": sorted(record["episode_id"] for record in selected),
            }
        )
    return sorted(rows, key=lambda row: (-row["episodes"], row["mean_v110_margin"], row["lineage"]))


def main() -> None:
    records = []
    for manifest in _manifest():
        episode_id = str(manifest["episode_id"])
        seat = int(manifest["submission_seat"])
        replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
        own_lineages = _lineage_hashes(replay, seat)
        opponent_lineages = _lineage_hashes(replay, 1 - seat)
        clone = _clone_trace(replay, seat)
        records.append(
            {
                "episode_id": episode_id,
                "seat": seat,
                "result": str(manifest.get("result") or "unknown"),
                "own_reward": float(manifest.get("own_reward") or 0),
                "opponent_reward": float(manifest.get("opponent_reward") or 0),
                "margin": float(manifest.get("own_reward") or 0)
                - float(manifest.get("opponent_reward") or 0),
                "clone": clone,
                "near_clone": clone["maximum"] >= v110.CLONE_MIN_CONFIDENCE,
                "own_h100": own_lineages[100],
                "own_h200": own_lineages[200],
                "own_h400": own_lineages[400],
                "opponent_h100": opponent_lineages[100],
                "opponent_h200": opponent_lineages[200],
                "opponent_h400": opponent_lineages[400],
                "similarity_h100": _similarity(replay, seat, 100),
                "similarity_h200": _similarity(replay, seat, 200),
                "similarity_h400": _similarity(replay, seat, 400),
                "snapshots": _snapshots(replay, seat),
            }
        )
    near = [record for record in records if record["near_clone"]]
    non_clone = [record for record in records if not record["near_clone"]]

    def cohort(selected: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "episodes": len(selected),
            "results": dict(Counter(record["result"] for record in selected)),
            "mean_margin": mean(float(record["margin"]) for record in selected) if selected else 0.0,
            "p10_margin": (
                float(np.quantile([record["margin"] for record in selected], 0.10)) if selected else 0.0
            ),
        }

    # numpy is imported lazily here so the submitted agent never depends on it.
    import numpy as np

    result = {
        "format": "kaggriculture-v111-live-opponent-lineages-v1",
        "source": str(SUBMISSION.relative_to(ROOT)),
        "all": cohort(records),
        "near_clone": cohort(near),
        "non_clone": cohort(non_clone),
        "near_clone_first_confident_steps": dict(
            Counter(str(record["clone"]["first_confident_step"]) for record in near)
        ),
        "near_clone_opponent_h200_groups": _group_summary(near, "opponent_h200"),
        "near_clone_opponent_h400_groups": _group_summary(near, "opponent_h400"),
        "records": records,
        "interpretation": {
            "known": "cohorts use only replayed public farm similarity and recorded outcomes",
            "inference": "repeated opponent action hashes are behavioral lineages, not proof of shared source code",
            "limit": "outcome association cannot identify the causal value of copying any continuation",
        },
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {key: value for key, value in result.items() if key not in {"records"}},
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"result: {OUTPUT}")


if __name__ == "__main__":
    main()
