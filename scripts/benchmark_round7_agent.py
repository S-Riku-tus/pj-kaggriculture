"""Measure a packaged Round7 agent in isolated agent-only subprocesses."""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPLAY = (
    ROOT
    / "experiments/learning_round6_20260922/development_evaluation/replays/round6_sequence_bc_v1/v122"
    / "seed_2026102201_seat_1.json.gz"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def observation(replay: dict[str, Any], step: int, seat: int) -> dict[str, Any]:
    public = copy.deepcopy(replay["steps"][step][0]["observation"])
    private = replay["steps"][step][seat]["observation"]
    public["player"] = seat
    public["private"] = copy.deepcopy(private["private"])
    public["remainingOverageTime"] = private.get("remainingOverageTime", 60)
    public["step"] = step
    return public


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    position = quantile * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def worker(archive: Path, replay_path: Path, seat: int) -> dict[str, Any]:
    temp_parent = ROOT.parent / ".round7_tmp"
    temp_parent.mkdir(parents=True, exist_ok=True)
    work_root = Path(tempfile.mkdtemp(prefix=f"round7_agent_seat{seat}_", dir=temp_parent))
    try:
        with tarfile.open(archive, "r:gz") as stream:
            stream.extractall(work_root, filter="data")
        sys.path.insert(0, str(work_root))
        import_started = time.perf_counter()
        spec = importlib.util.spec_from_file_location(f"round7_benchmark_seat{seat}", work_root / "main.py")
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot load archive main.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cold_import_seconds = time.perf_counter() - import_started
        with gzip.open(replay_path, "rt", encoding="utf-8") as stream:
            replay = json.load(stream)
        durations: list[float] = []
        exceptions: list[dict[str, Any]] = []
        for step in range(len(replay["steps"]) - 1):
            started = time.perf_counter()
            try:
                action = module.agent(observation(replay, step, seat), {})
                if not isinstance(action, dict):
                    raise TypeError(f"agent returned {type(action).__name__}")
            except Exception as exc:  # preserve every runtime failure
                exceptions.append({"step": step, "error": f"{type(exc).__name__}: {exc}"})
            durations.append(time.perf_counter() - started)
        memory = psutil.Process().memory_info()
        peak_rss = int(getattr(memory, "peak_wset", memory.rss))
        return {
            "seat": seat,
            "observations": len(durations),
            "cold_import_seconds": cold_import_seconds,
            "inference_seconds": {
                "p50": percentile(durations, 0.50),
                "p95": percentile(durations, 0.95),
                "p99": percentile(durations, 0.99),
                "max": max(durations),
            },
            "peak_rss_bytes": peak_rss,
            "final_rss_bytes": int(memory.rss),
            "runtime_exceptions": exceptions,
        }
    finally:
        shutil.rmtree(work_root)


def parent(archive: Path, replay_path: Path, output: Path) -> None:
    rows = []
    for seat in (0, 1):
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            "--archive",
            str(archive),
            "--replay",
            str(replay_path),
            "--seat",
            str(seat),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=900)
        if completed.returncode:
            raise RuntimeError(
                f"agent subprocess seat {seat} failed rc={completed.returncode}: {completed.stderr[-2000:]}"
            )
        rows.append(json.loads(completed.stdout))
    payload = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "archive": str(archive.relative_to(ROOT)),
        "archive_sha256": sha256(archive),
        "source_replay": str(replay_path.relative_to(ROOT)),
        "source_replay_sha256": sha256(replay_path),
        "process_contract": "one fresh agent-only subprocess per seat; no engine or match process in worker",
        "seats": rows,
        "aggregate": {
            "cold_start_max_seconds": max(row["cold_import_seconds"] for row in rows),
            "inference_p50_max_seconds": max(row["inference_seconds"]["p50"] for row in rows),
            "inference_p95_max_seconds": max(row["inference_seconds"]["p95"] for row in rows),
            "inference_p99_max_seconds": max(row["inference_seconds"]["p99"] for row in rows),
            "inference_max_seconds": max(row["inference_seconds"]["max"] for row in rows),
            "peak_rss_max_bytes": max(row["peak_rss_bytes"] for row in rows),
            "runtime_exception_count": sum(len(row["runtime_exceptions"]) for row in rows),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--replay", type=Path, default=DEFAULT_REPLAY)
    parser.add_argument("--seat", type=int, choices=(0, 1))
    parser.add_argument("--worker", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "experiments/learning_round7_20260922/agent_subprocess_benchmark.json",
    )
    args = parser.parse_args()
    archive = args.archive.resolve()
    replay_path = args.replay.resolve()
    if args.worker:
        if args.seat is None:
            parser.error("--worker requires --seat")
        print(json.dumps(worker(archive, replay_path, args.seat), ensure_ascii=False))
    else:
        parent(archive, replay_path, args.output.resolve())


if __name__ == "__main__":
    main()
