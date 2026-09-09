"""Preregistered v111-equivalent Control vs v113 generalized-gate evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evaluation.registry import verify_inputs, write_record  # noqa: E402
from scripts.evaluation.report import build_evaluation, markdown_report  # noqa: E402
from scripts.evaluation.runner import extract_archive, run_tasks  # noqa: E402
from scripts.evaluation.schema import load_preregistration  # noqa: E402


def _resolve(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def _task(
    *,
    phase: str,
    opponent: dict[str, Any],
    seed: int,
    seat: int,
    runtime: Path,
    replay_dir: Path,
    spec: dict[str, Any],
) -> dict[str, Any]:
    return {
        "phase": phase,
        "lineage_id": opponent["lineage_id"],
        "opponent_name": opponent["name"],
        "opponent_tier": opponent["tier"],
        "opponent_main": str(_resolve(opponent["path"])),
        "meta_weight": float(opponent["meta_weight"]),
        "seed": int(seed),
        "seat": int(seat),
        "episode_steps": int(spec["seat_configuration"]["episode_steps"]),
        "intended_action_step": int(spec["intervention"]["first_allowed_action_step"]),
        "control_main": str(runtime / "control" / "main.py"),
        "treatment_main": str(runtime / "treatment" / "main.py"),
        "replay_dir": str(replay_dir),
    }


def _tasks_for_phase(
    phase: str,
    seeds: list[int],
    opponents: list[dict[str, Any]],
    runtime: Path,
    replay_dir: Path,
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        _task(
            phase=phase,
            opponent=opponent,
            seed=seed,
            seat=seat,
            runtime=runtime,
            replay_dir=replay_dir,
            spec=spec,
        )
        for opponent in opponents
        for seed in seeds
        for seat in spec["seat_configuration"]["seats"]
    ]


def _progress(done: int, total: int, row: dict[str, Any]) -> None:
    print(
        json.dumps(
            {
                "progress": f"{done}/{total}",
                "phase": row["phase"],
                "lineage": row["lineage_id"],
                "seed": row["seed"],
                "seat": row["seat"],
                "trigger": row["gate_requested"],
                "incremental": row["incremental_treatment"],
                "delta_win_score": row["delta_win_score"],
                "delta_margin": row["delta_margin"],
                "major_regressions": row["candidate_new_major_regressions"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


def _fast_reject(rows: list[dict[str, Any]], spec: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons = []
    if any(row["candidate_new_major_regressions"] for row in rows):
        reasons.append("candidate-only major safety regression")
    if any(not row["behavioral_isolation_valid"] for row in rows):
        reasons.append("behavioral isolation failure")
    improvements = sum(row["loss_to_win"] for row in rows)
    harms = sum(row["win_to_loss"] for row in rows)
    tolerance = int(spec["fast_screen"]["harm_discordance_tolerance"])
    if harms > improvements + tolerance:
        reasons.append("clear discordant-pair harm")
    return bool(reasons), reasons


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=Path("experiments/v113_cow_sheep_gate_e3e4/preregistration.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    preregistration_path = (
        args.preregistration
        if args.preregistration.is_absolute()
        else ROOT / args.preregistration
    ).resolve()
    spec, preregistration_hash = load_preregistration(preregistration_path)
    provenance = verify_inputs(ROOT, spec)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"output directory already exists: {output}")
    output.mkdir(parents=True)
    runtime = output / "runtime"
    extract_archive(_resolve(spec["arms"]["control"]["archive"]), runtime / "control")
    extract_archive(_resolve(spec["arms"]["treatment"]["archive"]), runtime / "treatment")
    replay_dir = output / "replays"
    opponents = list(spec["opponent_pool"])

    diagnostic_spec = spec["diagnostic_reproduction"]
    diagnostic_opponents = [
        opponent
        for opponent in opponents
        if opponent["lineage_id"] == diagnostic_spec["lineage_id"]
    ]
    diagnostic_tasks = [
        _task(
            phase="first_divergence_reproduction",
            opponent=diagnostic_opponents[0],
            seed=int(diagnostic_spec["seed"]),
            seat=int(diagnostic_spec["seat"]),
            runtime=runtime,
            replay_dir=replay_dir,
            spec=spec,
        )
    ]
    diagnostic_rows = run_tasks(diagnostic_tasks, 1, _progress)

    fast_tasks = _tasks_for_phase(
        "fast_screen",
        list(spec["seed_manifest"]["fast_screen"]),
        opponents,
        runtime,
        replay_dir,
        spec,
    )
    fast_rows = run_tasks(fast_tasks, max(1, args.workers), _progress)
    rejected, fast_reject_reasons = _fast_reject(fast_rows, spec)
    formal_rows: list[dict[str, Any]] = []
    if not rejected:
        formal_tasks = _tasks_for_phase(
            "formal_promotion",
            list(spec["seed_manifest"]["formal_promotion"]),
            opponents,
            runtime,
            replay_dir,
            spec,
        )
        formal_rows = run_tasks(formal_tasks, max(1, args.workers), _progress)
    else:
        raise RuntimeError(f"fast screen rejected candidate before strength evaluation: {fast_reject_reasons}")

    evaluation = build_evaluation(
        fast_rows,
        formal_rows,
        diagnostic_rows,
        spec,
        provenance,
    )
    bronze_path = _resolve(spec["bronze_evidence"]["analysis_path"])
    bronze = json.loads(bronze_path.read_text(encoding="utf-8")) if bronze_path.is_file() else None
    created_at = datetime.now().astimezone().isoformat()
    payload = {
        "format": "kaggriculture-champion-challenger-result-v1",
        "created_at": created_at,
        "hypothesis_id": spec["hypothesis_id"],
        "preregistration": str(preregistration_path),
        "preregistration_sha256": preregistration_hash,
        "provenance": provenance,
        "dataset_roles": spec["dataset_roles"],
        "evidence_policy": spec["evidence_policy"],
        "evaluation": evaluation,
        "bronze_replay_evidence": bronze,
        "pairs": {
            "diagnostic_reproduction": diagnostic_rows,
            "fast_screen": fast_rows,
            "formal_promotion": formal_rows,
        },
    }
    result_path = output / "experiment_result.json"
    write_record(result_path, payload)
    (output / "report.md").write_text(markdown_report(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "decision": evaluation["decision"],
                "highest_supported_evidence": evaluation["highest_supported_evidence"],
                "result": str(result_path),
                "report": str(output / "report.md"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
