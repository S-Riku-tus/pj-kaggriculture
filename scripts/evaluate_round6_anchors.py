"""Frozen-archive evaluation against the V122/V123/V124 internal anchors.

This runner implements the 2026-09-22 Round6 addendum.  It intentionally
separates development and sealed final-confirmation seeds, loads every agent
from its final tar.gz, and treats both seats for one anchor/seed as one block.
It never submits to Kaggle.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import subprocess
import sys
import tarfile
import tempfile
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "learning_round6_20260922"
PREREGISTRATION = EXPERIMENT / "preregistration.json"
ENGINE = (
    ROOT
    / ".venv"
    / "Lib"
    / "site-packages"
    / "kaggle_environments"
    / "envs"
    / "kaggriculture"
    / "kaggriculture.py"
)

ANCHOR_MANIFESTS = {
    "v122": ROOT / "agents" / "v122" / "submission_manifest.json",
    "v123": ROOT / "agents" / "v123" / "submission_manifest.json",
    "v124": ROOT / "agents" / "v124" / "submission_manifest.json",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_preregistration() -> dict[str, Any]:
    return json.loads(PREREGISTRATION.read_text(encoding="utf-8"))


def archive_members(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with tarfile.open(path, "r:gz") as stream:
        for member in sorted(stream.getmembers(), key=lambda item: item.name):
            extracted = stream.extractfile(member)
            content = extracted.read() if extracted is not None else b""
            rows.append(
                {
                    "name": member.name,
                    "bytes": member.size,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "is_file": member.isfile(),
                }
            )
    return rows


def _working_manifest_comparison(anchor: str, members: list[dict[str, Any]]) -> dict[str, Any]:
    manifest_path = ANCHOR_MANIFESTS[anchor]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    archive_hash = {row["name"]: row["sha256"] for row in members if row["is_file"]}
    rows = []
    for entry in manifest["files"]:
        source = (manifest_path.parent / entry["source"]).resolve()
        target = str(entry["target"])
        source_hash = sha256(source)
        rows.append(
            {
                "source": str(source.relative_to(ROOT)),
                "target": target,
                "source_sha256": source_hash,
                "archive_sha256": archive_hash.get(target),
                "matches": archive_hash.get(target) == source_hash,
            }
        )
    return {
        "manifest": str(manifest_path.relative_to(ROOT)),
        "files": rows,
        "all_files_match": all(row["matches"] for row in rows),
    }


def identity() -> None:
    prereg = read_preregistration()
    anchors: dict[str, Any] = {}
    arms: dict[str, Any] = {}
    for name, spec in prereg["anchors"].items():
        archive = ROOT / spec["archive"]
        members = archive_members(archive)
        anchors[name] = {
            **spec,
            "bytes": archive.stat().st_size,
            "archive_sha256": sha256(archive),
            "entrypoint": "main.py",
            "members": members,
            "working_tree_comparison": _working_manifest_comparison(name, members),
            "frozen_artifact_status": "MATCHES_LOCAL_SUBMISSION_MANIFEST"
            if _working_manifest_comparison(name, members)["all_files_match"]
            else "MISMATCH_REQUIRES_NEW_NAME",
        }
    for name, spec in prereg["arms"].items():
        archive = ROOT / spec["archive"]
        arms[name] = {
            **spec,
            "bytes": archive.stat().st_size,
            "archive_sha256": sha256(archive),
            "entrypoint": "main.py",
            "members": archive_members(archive),
        }
    try:
        from kaggle_environments import make

        env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": 0}, debug=True)
        configuration = dict(env.configuration)
    except Exception as exc:  # pragma: no cover - diagnostic fallback
        configuration = {"capture_error": f"{type(exc).__name__}: {exc}"}
    payload = {
        "created_at_utc": utc_now(),
        "engine": {
            "path": str(ENGINE.relative_to(ROOT)),
            "sha256": sha256(ENGINE),
            "configuration": configuration,
        },
        "anchors": anchors,
        "arms": arms,
        "online_identity_limit": (
            "submission IDs and historical ratings come from saved local analyses; the exact bytes uploaded "
            "to Kaggle were not downloaded again in this run"
        ),
    }
    write_json(EXPERIMENT / "anchor_identity.json", payload)
    print(json.dumps({"anchors": {k: v["archive_sha256"] for k, v in anchors.items()}}, indent=2))


def safe_extract(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=False)
    root = target.resolve()
    with tarfile.open(archive, "r:gz") as stream:
        for member in stream.getmembers():
            destination = (target / member.name).resolve()
            if not destination.is_relative_to(root):
                raise ValueError(f"unsafe archive member: {member.name}")
        stream.extractall(target)
    if not (target / "main.py").is_file():
        raise FileNotFoundError(f"archive has no root main.py: {archive}")


def prepare_archives(names: list[str]) -> tuple[Path, dict[str, Path]]:
    prereg = read_preregistration()
    temp_root = ROOT / ".tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    run_root = Path(tempfile.mkdtemp(prefix="kaggriculture-round6-", dir=str(temp_root)))
    paths: dict[str, Path] = {}
    combined = {**prereg["anchors"], **prereg["arms"]}
    for name in names:
        target = run_root / name
        safe_extract(ROOT / combined[name]["archive"], target)
        paths[name] = target / "main.py"
    return run_root, paths


def _run_game(task: dict[str, Any]) -> dict[str, Any]:
    """Delegate to the established evaluator while keeping one process/game."""
    # Kaggle's archive loader makes the extracted root importable.  The
    # Round5 archive deliberately exercises this fallback for its sibling
    # modules, so reproduce that contract before the established game runner
    # imports root main.py.
    sys.path.insert(0, str(Path(task["opponent_main"]).parent))
    sys.path.insert(0, str(Path(task["agent_main"]).parent))
    sys.path.insert(0, str(ROOT / "scripts"))
    from learning_next_evaluate import _run_game as established_run_game

    return established_run_game(task)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _bootstrap(values: list[float], draws: int, seed: int) -> dict[str, Any]:
    array = np.asarray(values, dtype=np.float64)
    if not len(array):
        return {"two_sided_95": [None, None], "degenerate": True}
    rng = np.random.default_rng(seed)
    sample_means = np.empty(draws, dtype=np.float64)
    for index in range(draws):
        sample_means[index] = rng.choice(array, size=len(array), replace=True).mean()
    return {
        "two_sided_95": [float(np.percentile(sample_means, 2.5)), float(np.percentile(sample_means, 97.5))],
        "one_sided_95_lower": float(np.percentile(sample_means, 5.0)),
        "degenerate": bool(np.ptp(sample_means) == 0),
    }


def _hoeffding_lower(point: float, blocks: int, alpha: float = 0.05) -> float:
    if blocks <= 0:
        return 0.0
    return max(0.0, point - math.sqrt(math.log(1.0 / alpha) / (2.0 * blocks)))


def _hoeffding_interval(point: float, blocks: int, alpha: float = 0.05) -> list[float]:
    if blocks <= 0:
        return [0.0, 1.0]
    radius = math.sqrt(math.log(2.0 / alpha) / (2.0 * blocks))
    return [max(0.0, point - radius), min(1.0, point + radius)]


def _summary(rows: list[dict[str, Any]], prereg: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"arms": {}}
    draws = int(prereg["statistics"]["bootstrap_draws"])
    bootstrap_seed = int(prereg["statistics"]["bootstrap_seed"])
    for arm in sorted({str(row["arm"]) for row in rows}):
        arm_rows = [row for row in rows if row["arm"] == arm]
        anchor_rows: dict[str, Any] = {}
        points: list[float] = []
        for anchor in sorted({str(row["anchor"]) for row in arm_rows}):
            selected = [row for row in arm_rows if row["anchor"] == anchor]
            by_seed: dict[int, list[float]] = defaultdict(list)
            for row in selected:
                by_seed[int(row["seed"])].append(float(row["score"]))
            seed_scores = [mean(by_seed[seed]) for seed in sorted(by_seed)]
            point = mean(seed_scores)
            points.append(point)
            bootstrap = _bootstrap(seed_scores, draws, bootstrap_seed + sum(map(ord, arm + anchor)))
            lower = _hoeffding_lower(point, len(seed_scores))
            margins = [float(row["margin"]) for row in selected]
            cash = [float(row["our_cash"]) for row in selected]
            opponent_cash = [float(row["opponent_cash"]) for row in selected]
            anchor_rows[anchor] = {
                "games": len(selected),
                "seed_blocks": len(seed_scores),
                "wins": sum(float(row["score"]) == 1.0 for row in selected),
                "draws": sum(float(row["score"]) == 0.5 for row in selected),
                "losses": sum(float(row["score"]) == 0.0 for row in selected),
                "pure_win_rate_all_games": mean(float(row["score"]) == 1.0 for row in selected),
                "point_rate": point,
                "seat_point_rate": {
                    str(seat): mean(float(row["score"]) for row in selected if int(row["seat"]) == seat)
                    for seat in (0, 1)
                },
                "seed_block_scores": {str(seed): mean(by_seed[seed]) for seed in sorted(by_seed)},
                "bootstrap": bootstrap,
                "conservative_two_sided_95": _hoeffding_interval(point, len(seed_scores)),
                "prespecified_one_sided_95_lower": lower,
                "decision_interval_method": "Hoeffding lower bound over bounded seed-block scores",
                "target_point_rate_0_60_met": point >= 0.60,
                "clear_advantage_met": point >= 0.60 and lower > 0.50,
                "mean_our_cash": mean(cash),
                "mean_opponent_cash": mean(opponent_cash),
                "mean_margin": mean(margins),
                "median_margin": median(margins),
                "margin_q10": float(np.percentile(margins, 10)),
                "runtime_errors": sum(str(row["statuses"]) != "DONE/DONE" for row in selected),
            }
        result["arms"][arm] = {
            "by_anchor": anchor_rows,
            "p_internal_equal_anchor_weight": mean(points),
            "all_three_point_targets_met": all(value["target_point_rate_0_60_met"] for value in anchor_rows.values()),
            "clear_advantage_all_three": all(value["clear_advantage_met"] for value in anchor_rows.values()),
        }
    return result


def _actual_shop_history(replay_path: Path) -> list[dict[str, Any]]:
    with gzip.open(replay_path, "rt", encoding="utf-8") as stream:
        replay = json.load(stream)
    rows = []
    prior: list[str] | None = None
    for record, states in enumerate(replay["steps"]):
        shops = list(states[0]["observation"]["town"].get("unlocked_shops", []))
        if shops != prior:
            rows.append({"record": record, "decision_step": max(0, record - 1), "shops": shops})
            prior = shops
    return rows


def _result_from_existing_replay(task: dict[str, Any]) -> dict[str, Any] | None:
    """Recover a completed game after an interrupted aggregation run."""
    replay_path = Path(task["replay_path"])
    if not replay_path.is_file():
        return None
    try:
        with gzip.open(replay_path, "rt", encoding="utf-8") as stream:
            replay = json.load(stream)
        if len(replay["steps"]) != 720:
            return None
        final = replay["steps"][-1]
        statuses = [str(state.get("status")) for state in final]
        if statuses != ["DONE", "DONE"]:
            return None
        rewards = [float(state.get("reward") or 0.0) for state in final]
        seat = int(task["seat"])
        shop_history = [
            state[0]["observation"]["town"].get("unlocked_shops", []) for state in replay["steps"]
        ]
    except (OSError, EOFError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return {
        **task,
        "our_cash": rewards[seat],
        "opponent_cash": rewards[1 - seat],
        "margin": rewards[seat] - rewards[1 - seat],
        "score": 1.0
        if rewards[seat] > rewards[1 - seat]
        else 0.5
        if rewards[seat] == rewards[1 - seat]
        else 0.0,
        "statuses": statuses,
        "stored_states": len(replay["steps"]),
        "elapsed_seconds": None,
        "cold_import_seconds": None,
        "inference": {"p99_seconds": None, "max_seconds": None},
        "diagnostics": {},
        "shop_history_sha256": hashlib.sha256(
            json.dumps(shop_history, separators=(",", ":")).encode()
        ).hexdigest(),
        "resumed_from_existing_replay": True,
    }


def evaluate(stage: str, arms_arg: str | None, workers: int) -> None:
    prereg = read_preregistration()
    if stage == "final":
        raise RuntimeError(
            "sealed final-confirmation seeds cannot be opened by this command; "
            "freeze one candidate and add explicit authorization"
        )
    available_arms = list(prereg["arms"])
    arms = available_arms if not arms_arg else [value.strip() for value in arms_arg.split(",") if value.strip()]
    unknown = set(arms) - set(available_arms)
    if unknown:
        raise ValueError(f"unknown arms: {sorted(unknown)}")
    anchors = list(prereg["anchors"])
    seeds = [int(value) for value in prereg["development"]["seeds"]]
    if not (EXPERIMENT / "anchor_identity.json").is_file():
        identity()
    run_root, extracted = prepare_archives([*anchors, *arms])
    output = EXPERIMENT / "development_evaluation"
    tasks = []
    for arm in arms:
        for anchor in anchors:
            for seed in seeds:
                for seat in (0, 1):
                    tasks.append(
                        {
                            "arm": arm,
                            "opponent": anchor,
                            "seed": seed,
                            "seat": seat,
                            "agent_main": str(extracted[arm]),
                            "opponent_main": str(extracted[anchor]),
                            "replay_path": str(output / "replays" / arm / anchor / f"seed_{seed}_seat_{seat}.json.gz"),
                        }
                    )
    results: list[dict[str, Any]] = []
    pending_tasks: list[dict[str, Any]] = []
    for task in tasks:
        recovered = _result_from_existing_replay(task)
        if recovered is None:
            pending_tasks.append(task)
        else:
            results.append(recovered)
    if results:
        print(f"reused {len(results)} completed replay(s); running {len(pending_tasks)} game(s)", flush=True)
    # One task per process prevents module caches and mutable policy state from
    # leaking into the next game.  This is material for the similarly-named
    # V122/V123 archive dependencies.
    with ProcessPoolExecutor(max_workers=max(1, workers), max_tasks_per_child=1) as executor:
        futures = {executor.submit(_run_game, task): task for task in pending_tasks}
        for index, future in enumerate(as_completed(futures), 1):
            row = future.result()
            row["resumed_from_existing_replay"] = False
            results.append(row)
            print(
                f"{index}/{len(pending_tasks)} {row['arm']} vs {row['opponent']} "
                f"seed={row['seed']} seat={row['seat']} score={row['score']} margin={row['margin']}",
                flush=True,
            )
    flat: list[dict[str, Any]] = []
    shop_histories: dict[str, Any] = {}
    for row in sorted(results, key=lambda value: (value["arm"], value["opponent"], value["seed"], value["seat"])):
        replay_path = Path(row["replay_path"])
        relative = str(replay_path.relative_to(ROOT))
        actual_shops = _actual_shop_history(replay_path)
        shop_histories[f"{row['arm']}|{row['opponent']}|{row['seed']}|{row['seat']}"] = actual_shops
        flat.append(
            {
                "arm": row["arm"],
                "anchor": row["opponent"],
                "seed": row["seed"],
                "seat": row["seat"],
                "score": row["score"],
                "win": int(row["score"] == 1.0),
                "draw": int(row["score"] == 0.5),
                "loss": int(row["score"] == 0.0),
                "our_cash": row["our_cash"],
                "opponent_cash": row["opponent_cash"],
                "margin": row["margin"],
                "statuses": "/".join(row["statuses"]),
                "stored_states": row["stored_states"],
                "elapsed_seconds": row["elapsed_seconds"],
                "cold_import_seconds": row["cold_import_seconds"],
                "inference_p99_seconds": row["inference"]["p99_seconds"],
                "inference_max_seconds": row["inference"]["max_seconds"],
                "shop_history_sha256": row["shop_history_sha256"],
                "shop_change_records": len(actual_shops),
                "replay": relative,
                "replay_sha256": sha256(replay_path),
                "resumed_from_existing_replay": bool(row.get("resumed_from_existing_replay", False)),
            }
        )
    _write_csv(output / "games.csv", flat)
    write_json(output / "shop_histories.json", shop_histories)
    summary = _summary(flat, prereg)
    summary.update(
        {
            "created_at_utc": utc_now(),
            "stage": "development",
            "games": len(flat),
            "arms": summary["arms"],
            "anchors": anchors,
            "seeds": seeds,
            "seats": [0, 1],
            "fresh_process_per_game": True,
            "archive_loader_path": True,
            "extraction_root": str(run_root),
            "engine_sha256": sha256(ENGINE),
            "shop_divergence_policy": "retained; no game excluded",
        }
    )
    write_json(output / "summary.json", summary)
    write_json(
        output / "evaluation_manifest.json",
        {
            "created_at_utc": utc_now(),
            "preregistration_sha256": sha256(PREREGISTRATION),
            "identity_sha256": sha256(EXPERIMENT / "anchor_identity.json"),
            "arms": arms,
            "anchors": anchors,
            "seeds": seeds,
            "seats": [0, 1],
            "expected_games": len(tasks),
            "completed_games": len(flat),
            "reused_completed_replays": sum(row["resumed_from_existing_replay"] for row in flat),
            "all_done": all(row["statuses"] == "DONE/DONE" and int(row["stored_states"]) == 720 for row in flat),
            "online_operations": 0,
        },
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def validate_imports() -> None:
    prereg = read_preregistration()
    names = [*prereg["anchors"], *prereg["arms"]]
    run_root, extracted = prepare_archives(names)
    rows = []
    code = (
        "import importlib.util,pathlib,sys,time;"
        "p=pathlib.Path(sys.argv[1]);sys.path.insert(0,str(p.parent));t=time.perf_counter();"
        "s=importlib.util.spec_from_file_location('round6_loader',p);"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        "print(time.perf_counter()-t,callable(m.agent))"
    )
    for name, path in extracted.items():
        print(f"validating archive import: {name}", flush=True)
        try:
            completed = subprocess.run(
                [sys.executable, "-c", code, str(path)],
                cwd=str(ROOT / ".tmp"),
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            rows.append(
                {
                    "name": name,
                    "main": str(path),
                    "exit_code": completed.returncode,
                    "stdout": completed.stdout.strip(),
                    "stderr": completed.stderr[-2000:],
                }
            )
        except subprocess.TimeoutExpired as exc:
            rows.append(
                {
                    "name": name,
                    "main": str(path),
                    "exit_code": "TIMEOUT",
                    "stdout": (exc.stdout or "")[-2000:],
                    "stderr": (exc.stderr or "")[-2000:],
                }
            )
    payload = {
        "created_at_utc": utc_now(),
        "extraction_root": str(run_root),
        "fresh_process_imports": rows,
        "all_passed": all(row["exit_code"] == 0 for row in rows),
        "seat_and_clock_validation": "covered by both-seat 720-step development games",
        "cross_game_state_policy": "every development game uses a newly spawned process",
    }
    write_json(EXPERIMENT / "loader_validation.json", payload)
    if not payload["all_passed"]:
        raise RuntimeError(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("identity")
    sub.add_parser("validate")
    evaluation = sub.add_parser("evaluate")
    evaluation.add_argument("--stage", choices=("development", "final"), default="development")
    evaluation.add_argument("--arms", help="comma-separated arm names; defaults to all preregistered arms")
    evaluation.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    args = parser.parse_args()
    if args.command == "identity":
        identity()
    elif args.command == "validate":
        validate_imports()
    else:
        evaluate(args.stage, args.arms, args.workers)


if __name__ == "__main__":
    started = time.time()
    main()
    print(f"elapsed_seconds={time.time() - started:.3f}", flush=True)
