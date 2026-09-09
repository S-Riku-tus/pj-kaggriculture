"""Probe executable opponents and collapse duplicate executed action families."""

from __future__ import annotations

import argparse
import json
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.gold_opponent_pool import (
    ACTION_CHECKPOINTS,
    ROOT,
    cluster_sources,
    dependency_closure_sha256,
    run_executable_game,
    sha256_file,
    validate_complete_games,
)


def _resolve(path: str) -> Path:
    candidate = Path(path)
    return (candidate if candidate.is_absolute() else ROOT / candidate).resolve()


def load_candidates(path: Path, probe_game_count: int) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    candidates = []
    ids: set[str] = set()
    for raw in payload["candidates"]:
        candidate = dict(raw)
        candidate_id = str(candidate["candidate_id"])
        if candidate_id in ids:
            raise ValueError(f"duplicate candidate_id: {candidate_id}")
        ids.add(candidate_id)
        candidate["expected_probe_games"] = probe_game_count
        if candidate.get("kind") != "builtin":
            entrypoint = _resolve(str(candidate["entrypoint"]))
            if not entrypoint.is_file():
                candidate["manifest_error"] = f"missing entrypoint: {entrypoint}"
            else:
                candidate["entrypoint"] = str(entrypoint)
                candidate["entrypoint_sha256"] = sha256_file(entrypoint)
                candidate["dependency_closure_sha256"] = dependency_closure_sha256(entrypoint)
        candidates.append(candidate)
    return candidates


def _run_tasks(
    tasks: list[dict[str, Any]], workers: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=context,
        max_tasks_per_child=1,
    ) as executor:
        futures = {executor.submit(run_executable_game, task): task for task in tasks}
        for completed, future in enumerate(as_completed(futures), start=1):
            task = futures[future]
            try:
                rows.append(future.result())
            except Exception as exc:  # pragma: no cover - exercised by external agents
                errors.append(
                    {
                        "candidate_id": task["candidate"]["candidate_id"],
                        "seed": task["seed"],
                        "champion_seat": task["champion_seat"],
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )
            if completed % 10 == 0 or completed == len(tasks):
                print(
                    f"probe progress: {completed}/{len(tasks)} "
                    f"games, errors={len(errors)}",
                    flush=True,
                )
    rows.sort(
        key=lambda row: (
            str(row["candidate_id"]),
            int(row["requested_seed"]),
            int(row["champion_seat"]),
        )
    )
    errors.sort(
        key=lambda row: (
            str(row["candidate_id"]),
            int(row["seed"]),
            int(row["champion_seat"]),
        )
    )
    return rows, errors


def _markdown(payload: dict[str, Any]) -> str:
    cluster = payload["clustering"]
    source_by_id = {row["candidate_id"]: row for row in cluster["sources"]}
    lines = [
        "# Independent Gold Opponent action-family clustering",
        "",
        f"Generated: `{payload['created_at']}`",
        "",
        "This is a Discovery/Development probe, not promotion or Fresh Holdout evidence. "
        "A source name is never counted as an independent policy by itself.",
        "",
        "## Probe contract",
        "",
        f"- Seeds: `{payload['configuration']['seeds']}`",
        "- Seats: champion seat 0 and 1 for every seed",
        f"- Cumulative action checkpoints: `{payload['configuration']['action_checkpoints']}`",
        "- Isolation: one game per fresh spawned Python process",
        f"- Exact complete families: **{cluster['exact_behavior_family_count']}**",
        "",
        "## Exact action families",
        "",
        "| Family | Representative | Source members | V111 probe strict WR | V111 mean margin |",
        "|---|---|---|---:|---:|",
    ]
    for family in cluster["exact_families"]:
        representative = family["representative_candidate_id"]
        source = source_by_id[representative]
        lines.append(
            "| {family} | {representative} | {members} | {win_rate:.1%} | {margin:.1f} |".format(
                family=family["behavior_family_id"],
                representative=representative,
                members=", ".join(family["source_members"]),
                win_rate=float(source.get("strict_win_rate_of_v111", 0.0)),
                margin=float(source.get("mean_margin_of_v111", 0.0)),
            )
        )
    lines.extend(
        [
            "",
            "## Incomplete or failed probes",
            "",
        ]
    )
    incomplete = [row for row in cluster["sources"] if row["probe_status"] != "COMPLETE"]
    if not incomplete:
        lines.append("None.")
    else:
        for row in incomplete:
            lines.append(
                f"- `{row['candidate_id']}`: {row['completed_games']}/{row['expected_games']} completed"
            )
    lines.extend(
        [
            "",
            "## Interpretation guardrails",
            "",
            "- Exact-family collapse uses the full seed×seat×checkpoint vector.",
            "- Checkpoint clusters are also retained so common openings and later continuation splits remain visible.",
            "- Shared source ancestry remains metadata; forced branches from one public router "
            "do not become multiple Meta votes.",
            "- A positive result in this panel does not establish Candidate strength.",
            "- Every probed family is excluded from future Fresh Holdout status.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--candidate-manifest",
        type=Path,
        default=Path("experiments/independent_gold_pool/candidate_sources.json"),
    )
    parser.add_argument("--seed", action="append", type=int, default=[])
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/evaluation/independent_gold_pool/common_probe.json"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("docs/independent_gold_action_family_clustering.md"),
    )
    args = parser.parse_args()
    seeds = args.seed or [29114001, 29114002]
    candidate_manifest = _resolve(str(args.candidate_manifest))
    candidates = load_candidates(candidate_manifest, len(seeds) * 2)
    champion_path = (ROOT / "agents/v111/main.py").resolve()
    champion = {
        "candidate_id": "champion_v111",
        "kind": "python",
        "entrypoint": str(champion_path),
        "entrypoint_sha256": sha256_file(champion_path),
        "dependency_closure_sha256": dependency_closure_sha256(champion_path),
    }
    tasks = [
        {
            "champion": champion,
            "candidate": candidate,
            "seed": seed,
            "champion_seat": seat,
            "episode_steps": 720,
            "action_checkpoints": ACTION_CHECKPOINTS,
        }
        for candidate in candidates
        if not candidate.get("manifest_error")
        for seed in seeds
        for seat in (0, 1)
    ]
    rows, errors = _run_tasks(tasks, max(1, args.workers))
    clustering = cluster_sources(candidates, rows)
    payload = {
        "format": "kaggriculture-independent-gold-common-probe-v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "evidence_level": "E3 infrastructure discovery; no Candidate treatment",
        "dataset_role": "Discovery/Development; permanently excluded from Fresh Holdout",
        "champion": champion,
        "candidate_manifest": str(candidate_manifest),
        "configuration": {
            "seeds": seeds,
            "seats": [0, 1],
            "episode_steps": 720,
            "action_checkpoints": list(ACTION_CHECKPOINTS),
            "fresh_process_per_game": True,
        },
        "candidates": candidates,
        "clustering": clustering,
        "safety": {
            "failed_tasks": errors,
            "non_done_games": validate_complete_games(rows),
        },
        "games": rows,
    }
    output = _resolve(str(args.output))
    report = _resolve(str(args.report))
    output.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report.write_text(_markdown(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "sources": clustering["source_count"],
                "complete_sources": clustering["complete_source_count"],
                "exact_action_families": clustering["exact_behavior_family_count"],
                "failed_tasks": len(errors),
                "output": str(output),
                "report": str(report),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
