from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import importlib.util
import json
import shutil
import sys
import tarfile
import tempfile
import traceback
import types
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "experiments/learning_round7_20260922/runtime_validation.json"
FIXED_PACKAGE = ROOT / ".venv/Lib/site-packages/kaggle_environments"
DAY1_REPLAY = (
    ROOT
    / "experiments/learning_round6_20260922/development_evaluation/replays/round6_sequence_bc_v1/v122"
    / "seed_2026102201_seat_1.json.gz"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
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


def load_fresh(main_path: Path, module_name: str):
    for name in ("policy", "runtime", "common", "model_compat", module_name):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(module_name, main_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {main_path}")
    sys.path.insert(0, str(main_path.parent))
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def load_fixed_agent_module():
    """Load the fixed real loader without importing every environment plugin."""
    package = types.ModuleType("kaggle_environments")
    package.__path__ = [str(FIXED_PACKAGE)]
    sys.modules["kaggle_environments"] = package
    for name in ("errors", "utils", "agent"):
        qualified = f"kaggle_environments.{name}"
        spec = importlib.util.spec_from_file_location(qualified, FIXED_PACKAGE / f"{name}.py")
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load fixed {name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[qualified] = module
        spec.loader.exec_module(module)
    return sys.modules["kaggle_environments.agent"]


def mark_progress(path: Path, archive: Path, stage: str, started: float) -> None:
    path.write_text(
        json.dumps(
            {
                "archive": archive.name,
                "stage": stage,
                "elapsed_seconds": perf_counter() - started,
                "updated_at_utc": datetime.now(UTC).isoformat(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def validate(archive: Path, work_root: Path, run_day1: bool, progress_path: Path) -> dict[str, Any]:
    started = perf_counter()
    mark_progress(progress_path, archive, "extract_start", started)
    print(f"validating {archive.name}: extract", flush=True)
    extracted = work_root / archive.stem.replace(".tar", "")
    extracted.mkdir()
    with tarfile.open(archive, "r:gz") as stream:
        stream.extractall(extracted, filter="data")

    member_hashes = {
        str(path.relative_to(extracted)).replace("\\", "/"): sha256(path)
        for path in sorted(extracted.rglob("*"))
        if path.is_file()
    }
    mark_progress(progress_path, archive, "official_loader_start", started)
    loader_error = None
    loader_started = perf_counter()
    try:
        for name in ("policy", "runtime", "common", "model_compat"):
            sys.modules.pop(name, None)
        loader_module = load_fixed_agent_module()
        with gzip.open(DAY1_REPLAY, "rt", encoding="utf-8") as stream:
            replay = json.load(stream)
        initial_observation = observation(replay, 0, 0)
        loaded_agent, _parallel = loader_module.build_agent(
            str(extracted / "main.py"), {}, "kaggriculture"
        )
        loader_action = loaded_agent(initial_observation, {})
        loader_passed = isinstance(loader_action, dict)
    except Exception as exc:  # evidence must include loader failures verbatim
        loader_passed = False
        loader_action = None
        loader_error = f"{type(exc).__name__}: {exc}"
    loader_seconds = perf_counter() - loader_started
    mark_progress(progress_path, archive, "fresh_import_start", started)
    print(f"validating {archive.name}: official loader {loader_seconds:.3f}s", flush=True)

    fresh_error = None
    day1_actions: list[dict[str, Any]] = []
    fresh_started = perf_counter()
    try:
        module = load_fresh(extracted / "main.py", f"round7_{len(member_hashes)}_{archive.stat().st_size}")
        if run_day1:
            with gzip.open(DAY1_REPLAY, "rt", encoding="utf-8") as stream:
                replay = json.load(stream)
            day1_actions = [module.agent(observation(replay, step, 1), {}) for step in range(28)]
        fresh_passed = True
    except Exception:  # evidence must retain the exception instead of hiding the candidate
        fresh_passed = False
        fresh_error = traceback.format_exc()
    fresh_seconds = perf_counter() - fresh_started
    mark_progress(progress_path, archive, "complete", started)
    print(f"validating {archive.name}: fresh/day1 {fresh_seconds:.3f}s", flush=True)

    record27 = day1_actions[26] if len(day1_actions) >= 27 else None
    record28 = day1_actions[27] if len(day1_actions) >= 28 else None
    return {
        "archive": str(archive.relative_to(ROOT)),
        "archive_sha256": sha256(archive),
        "isolated_extraction": str(extracted),
        "member_hashes": member_hashes,
        "official_path_loader": {
            "passed": loader_passed,
            "initial_action": loader_action,
            "error": loader_error,
            "configuration": {},
            "loader": "fixed kaggle_environments.agent.build_agent(path, {}, 'kaggriculture')",
            "exec_globals_contract": "empty dict inside fixed loader",
            "fixed_agent_py_sha256": sha256(FIXED_PACKAGE / "agent.py"),
            "elapsed_seconds": loader_seconds,
        },
        "fresh_import": {"passed": fresh_passed, "error": fresh_error, "elapsed_seconds": fresh_seconds},
        "day1_causal_trace": {
            "seat": 1,
            "records_replayed": len(day1_actions),
            "record27_action": record27,
            "record28_action": record28,
            "farmer_picked_up_two_wheat": bool(record27 and record27.get("farmer") == ["PICKUP", "WHEAT", 2]),
            "farmer_fed_next_record": bool(record28 and record28.get("farmer") == ["FEED"]),
        },
        "total_elapsed_seconds": perf_counter() - started,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archives", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-day1", action="store_true")
    args = parser.parse_args()

    temp_parent = ROOT.parent / ".round7_tmp"
    temp_parent.mkdir(parents=True, exist_ok=True)
    work_root = Path(tempfile.mkdtemp(prefix="kaggriculture_round7_validate_", dir=temp_parent))
    progress_path = args.output.with_suffix(args.output.suffix + ".progress.json")
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        rows = [
            validate(
                (ROOT / archive).resolve() if not archive.is_absolute() else archive,
                work_root,
                run_day1=not args.skip_day1,
                progress_path=progress_path,
            )
            for archive in args.archives
        ]
        result = {
            "created_at_utc": datetime.now(UTC).isoformat(),
            "engine_version": "1.32.7",
            "work_root_was_outside_repo": not work_root.is_relative_to(ROOT),
            "day1_replay": str(DAY1_REPLAY.relative_to(ROOT)),
            "candidates": rows,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        shutil.rmtree(work_root)


if __name__ == "__main__":
    main()
