"""Build the reproducible V112 teacher and provenance audit.

This script does not score a candidate by wins against an older local agent.
It summarizes current Rank 1-3 teacher trajectories, compares their phase
portfolios with the two V111 submissions, measures action-lineage diversity,
and records the exact public artifact boundary used by V112.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DETAILS = ROOT / "data/analysis/v112_episode_metrics.csv"
CORPUS_SUMMARY = ROOT / "data/analysis/v112_corpus_comparison.json"
V112_MAIN = ROOT / "agents/v112/main.py"
EXPECTED_SHA256 = "f48c21166eac68d1b05a401f04f94a2eb6154e65415af64893672365ff33c7b8"

CORPORA = {
    "current_rank1": ROOT
    / "data/submissions/leaderboard_20260831_rank1_tetsuya_submission_55905066",
    "current_rank2": ROOT
    / "data/submissions/leaderboard_20260831_rank2_yusuke_hayashi_submission_55865730",
    "current_rank3": ROOT
    / "data/submissions/leaderboard_20260831_rank3_mtn_submission_55867591",
    "v111_first": ROOT / "data/submissions/v111_submission_55909167",
    "v111_second": ROOT / "data/submissions/v111_submission_55912910",
}

RATINGS_AT_SNAPSHOT = {
    "current_rank1": {"submission_id": 55905066, "team": "tetsuya", "rating": 2918.2},
    "current_rank2": {
        "submission_id": 55865730,
        "team": "Yusuke Hayashi",
        "rating": 2842.6,
    },
    "current_rank3": {"submission_id": 55867591, "team": "MtN", "rating": 2832.2},
    "v111_first": {"submission_id": 55909167, "team": "local", "rating": 1688.6},
    "v111_second": {"submission_id": 55912910, "team": "local", "rating": 1730.7},
}

ITEMS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "GOOSE", "COW", "SHEEP")
CHECKPOINTS = (24, 100, 200, 400)


def _manifest(directory: Path) -> list[dict[str, str]]:
    with (directory / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        return [
            row
            for row in csv.DictReader(handle)
            if row.get("replay_status") in {"downloaded", "skipped_existing"}
            and int(float(row.get("step_count") or 0)) >= 719
        ]


def _replay_path(row: dict[str, str]) -> Path:
    direct = ROOT / str(row["replay_path"])
    return direct if direct.is_file() else ROOT / "data" / str(row["replay_path"])


def _action(replay: dict[str, Any], step: int, seat: int) -> dict[str, Any]:
    stored = step + 1
    if stored >= len(replay.get("steps") or []):
        return {}
    value = (replay["steps"][stored][seat] or {}).get("action") or {}
    return value if isinstance(value, dict) else {}


def _canonical(action: dict[str, Any], component: str) -> str:
    actors = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
    if component == "field":
        payload: Any = actors
    elif component == "market":
        payload = action.get("market") or []
    else:
        payload = {"field": actors, "market": action.get("market") or []}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _lineages(replay: dict[str, Any], seat: int, component: str) -> dict[int, str]:
    digest = hashlib.sha1()
    result: dict[int, str] = {}
    for step in range(CHECKPOINTS[-1]):
        digest.update(_canonical(_action(replay, step, seat), component).encode())
        digest.update(b"\n")
        if step + 1 in CHECKPOINTS:
            result[step + 1] = digest.hexdigest()[:16]
    return result


def _obs(replay: dict[str, Any], step: int, seat: int) -> dict[str, Any]:
    value = replay["steps"][step][seat].get("observation") or {}
    return value if isinstance(value, dict) else {}


def _replay_audit(directory: Path) -> dict[str, Any]:
    counts = {
        component: {checkpoint: Counter() for checkpoint in CHECKPOINTS}
        for component in ("field", "market", "full")
    }
    behind_day12 = recovered_from_behind = ahead_day12 = lost_from_ahead = 0
    statuses: Counter[str] = Counter()
    episodes = 0
    for row in _manifest(directory):
        replay = json.loads(_replay_path(row).read_text(encoding="utf-8"))
        seat = int(row["submission_seat"])
        episodes += 1
        for component in counts:
            for checkpoint, lineage in _lineages(replay, seat, component).items():
                counts[component][checkpoint][lineage] += 1

        day12 = _obs(replay, 12 * 24, seat)
        farms = day12.get("farms") or []
        if len(farms) >= 2:
            own = float(farms[seat].get("money") or 0)
            opponent = float(farms[1 - seat].get("money") or 0)
            margin = float(row.get("own_reward") or 0) - float(row.get("opponent_reward") or 0)
            if own < opponent:
                behind_day12 += 1
                recovered_from_behind += margin > 0
            elif own > opponent:
                ahead_day12 += 1
                lost_from_ahead += margin < 0

        final = replay.get("steps", [])[-1]
        for state in final:
            statuses[str(state.get("status", "unknown"))] += 1

    lineage_summary = {
        component: {
            str(checkpoint): {
                "distinct": len(counter),
                "largest_count": counter.most_common(1)[0][1] if counter else 0,
                "largest_share": (
                    counter.most_common(1)[0][1] / episodes if counter and episodes else 0.0
                ),
            }
            for checkpoint, counter in checkpoints.items()
        }
        for component, checkpoints in counts.items()
    }
    return {
        "episodes": episodes,
        "lineages": lineage_summary,
        "day12_recovery": {
            "behind_games": behind_day12,
            "recovered_to_final_win": recovered_from_behind,
            "recovery_rate": recovered_from_behind / behind_day12 if behind_day12 else None,
            "ahead_games": ahead_day12,
            "lost_by_finish": lost_from_ahead,
            "lead_loss_rate": lost_from_ahead / ahead_day12 if ahead_day12 else None,
        },
        "terminal_statuses": dict(statuses),
    }


def _mean(values: list[float]) -> float | None:
    return mean(values) if values else None


def _phase_and_demand() -> tuple[dict[str, Any], dict[str, Any]]:
    with DETAILS.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    label_alias = {"v111a": "v111_first", "v111b": "v111_second"}
    selected = {
        label: [row for row in rows if label_alias.get(row["label"], row["label"]) == label]
        for label in CORPORA
    }
    phases: dict[str, Any] = {}
    demand: dict[str, Any] = {}
    for label, corpus in selected.items():
        phases[label] = {}
        for day in (4, 7, 10, 12, 15, 20, 24, 29):
            vectors: list[dict[str, float]] = []
            for row in corpus:
                snapshots = json.loads(row["day_snapshots"])
                snapshot = snapshots.get(str(day), {})
                crops = snapshot.get("crops", {})
                animals = snapshot.get("animals", {})
                vectors.append(
                    {item: float(crops.get(item, animals.get(item, 0)) or 0) for item in ITEMS}
                )
            phases[label][str(day)] = {
                item: _mean([vector[item] for vector in vectors]) for item in ITEMS
            }

        yarn = [row for row in corpus if "YARN_STORE" in json.loads(row["final_shops"])]
        no_yarn = [row for row in corpus if "YARN_STORE" not in json.loads(row["final_shops"])]
        demand[label] = {}
        for group, group_rows in (("yarn", yarn), ("no_yarn", no_yarn)):
            demand[label][group] = {
                "episodes": len(group_rows),
                "mean_max_cow": _mean([float(row["max_cow"]) for row in group_rows]),
                "mean_max_sheep": _mean([float(row["max_sheep"]) for row in group_rows]),
                "mean_reward": _mean([float(row["own_reward"]) for row in group_rows]),
                "mean_margin": _mean([float(row["margin"]) for row in group_rows]),
            }
    return phases, demand


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v112_strategy_analysis.json"),
    )
    args = parser.parse_args()
    phase_portfolios, animal_demand = _phase_and_demand()
    corpus_summary = json.loads(CORPUS_SUMMARY.read_text(encoding="utf-8"))
    replay_audits = {label: _replay_audit(directory) for label, directory in CORPORA.items()}
    actual_sha = hashlib.sha256(V112_MAIN.read_bytes()).hexdigest()
    payload = {
        "format": "kaggriculture-v112-strategy-analysis-v1",
        "snapshot": {
            "date": "2026-08-31",
            "ratings": RATINGS_AT_SNAPSHOT,
            "warning": "recorded episode outcomes are historical samples, not contemporaneous rating estimates",
        },
        "artifact": {
            "path": str(V112_MAIN.relative_to(ROOT)),
            "sha256": actual_sha,
            "expected_upstream_sha256": EXPECTED_SHA256,
            "exact_upstream_match": actual_sha == EXPECTED_SHA256,
            "upstream_public_score": 3090.1,
            "new_submission_rating_verified": False,
        },
        "aggregate_corpus": corpus_summary["corpora"],
        "phase_portfolios": phase_portfolios,
        "animal_allocation_by_yarn_visibility": animal_demand,
        "replay_audits": replay_audits,
        "evidence_boundary": {
            "known": [
                "the V112 bytes match the public notebook output hash",
                "current Rank 1-3 and both V111 corpora contain complete 720-state replays",
                "current Rank 1 uses many more distinct field and market continuations than V111",
            ],
            "inferred": [
                "current Rank 1 is state-responsive rather than one fixed tape",
                "a coherent high-yield route plus bounded market ordering is safer than imitating sparse field actions",
            ],
            "unverified": [
                "a fresh V112 submission will reproduce the upstream public score",
                "the current matchmaking pool will value the same route identically",
            ],
        },
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"analysis: {output}")
    print(f"artifact_exact_match: {payload['artifact']['exact_upstream_match']}")
    for label, audit in replay_audits.items():
        h400 = audit["lineages"]["field"]["400"]
        recovery = audit["day12_recovery"]
        print(
            label,
            f"episodes={audit['episodes']}",
            f"field_h400={h400['distinct']}",
            f"recovery={recovery['recovered_to_final_win']}/{recovery['behind_games']}",
        )


if __name__ == "__main__":
    main()
