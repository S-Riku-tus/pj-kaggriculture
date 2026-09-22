# ruff: noqa: E501
"""Validate one archive with the pinned public Kaggle loader in isolation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tarfile
import tempfile
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_extract(archive: Path, target: Path) -> None:
    root = target.resolve()
    with tarfile.open(archive, "r:gz") as stream:
        for member in stream.getmembers():
            if not (target / member.name).resolve().is_relative_to(root):
                raise ValueError(f"unsafe archive member: {member.name}")
        stream.extractall(target)


class BlockNumpy:
    def find_spec(self, fullname: str, _path: Any = None, _target: Any = None) -> None:
        if fullname == "numpy" or fullname.startswith("numpy."):
            raise ModuleNotFoundError("NumPy deliberately unavailable in Round3 loader validation")
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--full-game", action="store_true")
    parser.add_argument("--extracted-dir", type=Path)
    args = parser.parse_args()
    archive = args.archive.resolve()

    # Import the pinned runner before NumPy is blocked.  The submitted archive
    # itself is then compiled/executed with the official empty globals path.
    import kaggle_environments
    from kaggle_environments import make
    from kaggle_environments.agent import get_last_callable
    print("probe_stage=kaggle_imported", file=sys.stderr, flush=True)

    context = (
        nullcontext(str(args.extracted_dir.resolve().parent))
        if args.extracted_dir is not None
        else tempfile.TemporaryDirectory(prefix="kaggriculture_r3_loader_", dir="C:/tmp")
    )
    with context as raw_tmp:
        temporary = Path(raw_tmp)
        extracted = args.extracted_dir.resolve() if args.extracted_dir is not None else temporary / "archive"
        arbitrary_cwd = temporary / "arbitrary_cwd"
        if args.extracted_dir is None:
            extracted.mkdir()
            safe_extract(archive, extracted)
        arbitrary_cwd.mkdir(exist_ok=True)
        print("probe_stage=archive_extracted", file=sys.stderr, flush=True)
        main_path = extracted / "main.py"
        if not main_path.is_file():
            raise FileNotFoundError(main_path)
        source = main_path.read_text(encoding="utf-8")

        old_cwd = Path.cwd()
        old_path = list(sys.path)
        repository_root = archive.parents[2]
        sys.path[:] = [
            entry
            for entry in sys.path
            if not entry or Path(entry).resolve() != repository_root
        ]
        os.chdir(arbitrary_cwd)
        episode_steps = 720 if args.full_game else 4
        preflight_env = make("kaggriculture", configuration={"episodeSteps": episode_steps, "seed": 2026092599}, debug=True)
        preflight_env.reset(2)
        blocker = BlockNumpy()
        sys.meta_path.insert(0, blocker)
        # A preloaded NumPy must not make an archive dependency appear valid.
        preloaded_numpy = {key: value for key, value in list(sys.modules.items()) if key == "numpy" or key.startswith("numpy.")}
        for key in preloaded_numpy:
            sys.modules.pop(key, None)
        started = time.perf_counter()
        try:
            selected = get_last_callable(source, path=str(main_path))
            cold_import = time.perf_counter() - started
            print(f"probe_stage=loader_selected seconds={cold_import:.6f}", file=sys.stderr, flush=True)
            selected_name = getattr(selected, "__name__", None)
            if selected_name != "agent":
                raise AssertionError(f"last callable is {selected_name!r}, expected 'agent'")
            preflight_action = selected(preflight_env.state[0].observation)
            reset = selected.__globals__.get("reset_runtime_state")
            if callable(reset):
                reset()
            # NumPy is absent for archive execution and one real observation.
            # Restore the runner's own already-loaded dependency afterward.
            sys.meta_path.remove(blocker)
            sys.modules.update(preloaded_numpy)
            calls = 0
            timings: list[float] = []

            def measured(observation: Any, configuration: Any = None) -> Any:
                nonlocal calls
                tick = time.perf_counter()
                try:
                    return selected(observation, configuration)
                except TypeError:
                    return selected(observation)
                finally:
                    calls += 1
                    timings.append(time.perf_counter() - tick)

            env = make("kaggriculture", configuration={"episodeSteps": episode_steps, "seed": 2026092599}, debug=True)
            print("probe_stage=environment_created", file=sys.stderr, flush=True)
            env.run([measured, "pass"])
            print("probe_stage=game_finished", file=sys.stderr, flush=True)
            replay = env.toJSON()
            final = replay["steps"][-1]
            actions = [row[0].get("action") for row in replay["steps"][1:]]
            result = {
                "archive": str(archive),
                "archive_sha256": sha256(archive),
                "archive_members": sorted(path.name for path in extracted.iterdir() if path.is_file()),
                "kaggle_environments_version": kaggle_environments.__version__,
                "loader": "kaggle_environments.agent.get_last_callable",
                "empty_globals": True,
                "arbitrary_cwd": str(arbitrary_cwd),
                "repository_removed_from_sys_path": True,
                "numpy_blocked_during_archive_exec_and_game": False,
                "numpy_blocked_during_archive_exec_and_preflight_inference": True,
                "numpy_blocked_during_game": False,
                "preflight_action_type": type(preflight_action).__name__,
                "last_callable": selected_name,
                "cold_import_seconds": cold_import,
                "warm_calls": calls,
                "warm_mean_seconds": sum(timings) / len(timings),
                "warm_max_seconds": max(timings),
                "stored_states": len(replay["steps"]),
                "terminal_statuses": [str(row.get("status")) for row in final],
                "terminal_rewards": [row.get("reward") for row in final],
                "action_sha256": hashlib.sha256(json.dumps(actions, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                "passed": selected_name == "agent" and all(str(row.get("status")) == "DONE" for row in final),
            }
        finally:
            if blocker in sys.meta_path:
                sys.meta_path.remove(blocker)
            sys.modules.update(preloaded_numpy)
            sys.path[:] = old_path
            os.chdir(old_cwd)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
