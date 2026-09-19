#!/usr/bin/env python3
"""Measure how far a gate-latched V122 source drifts from per-turn NN choices."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from collections import Counter
from pathlib import Path
from statistics import mean, median
from typing import Any


def _load(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("v122_coherence_policy", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _quantile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * (len(ordered) - 1)))]


def analyze(agent_path: Path, replay_paths: list[Path], submission_id: str) -> dict[str, Any]:
    policy = _load(agent_path.resolve())
    gaps: list[int] = []
    ratios: list[float] = []
    unavailable = 0
    comparisons = 0
    switches = 0
    games = 0
    manifest_cache: dict[Path, dict[str, int]] = {}

    for replay_path in replay_paths:
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
        agents = replay.get("info", {}).get("EpisodeId")
        del agents
        steps = replay.get("steps") or []
        if len(steps) < 720:
            continue
        submission_root = replay_path.parents[3]
        if submission_root not in manifest_cache:
            seat_by_episode: dict[str, int] = {}
            with (submission_root / "episodes.csv").open(newline="", encoding="utf-8-sig") as stream:
                for row in csv.DictReader(stream):
                    if row.get("agent_0_submission_id") == submission_id:
                        seat_by_episode[str(row["episode_id"])] = 0
                    elif row.get("agent_1_submission_id") == submission_id:
                        seat_by_episode[str(row["episode_id"])] = 1
            manifest_cache[submission_root] = seat_by_episode
        episode_id = replay_path.parent.parent.name
        candidate_seats = [manifest_cache[submission_root][episode_id]]

        for seat in candidate_seats:
            games += 1
            policy.reset_runtime_state()
            active_source = None
            for step in range(policy.sparse.OPENING_END, 719):
                observation = steps[step][seat].get("observation") or {}
                model = policy.sparse._load_model()
                rows = list((model.get("steps") or [])[step] or [])
                if not rows:
                    continue
                query = policy.sparse.base.feature_vector(observation)
                policy.sparse._refresh_sparse_state(observation, rows, query, model)
                pool = policy.sparse._route_pool(policy.sparse._compatible_units(rows, observation), step)
                beam = set(policy.sparse._STATE.get("beam") or ())
                beamed = [row for row in pool if not beam or int(row[policy.sparse.ROW_SOURCE]) in beam]
                if beamed:
                    pool = beamed
                nearest = min(
                    pool,
                    key=lambda row: policy.sparse.base.feature_distance(query, row[policy.sparse.ROW_FEATURES]),
                )
                nearest_source = int(nearest[policy.sparse.ROW_SOURCE])
                if policy.sparse._STATE.get("last_gate") == step or active_source is None:
                    active_source = nearest_source
                active_rows = [row for row in pool if int(row[policy.sparse.ROW_SOURCE]) == active_source]
                comparisons += 1
                if not active_rows:
                    unavailable += 1
                    if nearest_source != active_source:
                        switches += 1
                    active_source = nearest_source
                    continue
                active = active_rows[0]
                best_distance = policy.sparse.base.feature_distance(query, nearest[policy.sparse.ROW_FEATURES])
                active_distance = policy.sparse.base.feature_distance(query, active[policy.sparse.ROW_FEATURES])
                gap = max(0, active_distance - best_distance)
                gaps.append(gap)
                ratios.append(active_distance / max(1, best_distance))

    thresholds = (0, 100, 250, 500, 1000, 2000, 5000, 10000)
    return {
        "games_or_seats": games,
        "comparisons": comparisons,
        "active_source_unavailable": unavailable,
        "forced_switches": switches,
        "gap": {
            "mean": mean(gaps) if gaps else None,
            "median": median(gaps) if gaps else None,
            "p75": _quantile(gaps, 0.75),
            "p90": _quantile(gaps, 0.90),
            "p95": _quantile(gaps, 0.95),
            "p99": _quantile(gaps, 0.99),
            "within_threshold": {str(value): sum(gap <= value for gap in gaps) / len(gaps) for value in thresholds},
        },
        "ratio": {
            "mean": mean(ratios) if ratios else None,
            "median": median(ratios) if ratios else None,
            "p90": _quantile([int(value * 1000) for value in ratios], 0.90),
            "p95": _quantile([int(value * 1000) for value in ratios], 0.95),
        },
        "notes": dict(Counter({"focal_submission_seats_only": games})),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", type=Path, default=Path("agents/v122/main.py"))
    parser.add_argument("--submission-id", required=True)
    parser.add_argument("--max-replays", type=int, default=0)
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    replay_paths = [
        candidate
        for path in args.paths
        for candidate in ([path] if path.is_file() else sorted(path.rglob("episode_*.json")))
        if "replay" in candidate.parts
    ]
    if args.max_replays > 0:
        replay_paths = replay_paths[: args.max_replays]
    print(
        json.dumps(
            analyze(args.agent, replay_paths, args.submission_id),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
