"""Validate a Round5 archive through the pinned public Kaggle loader."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tarfile
import tempfile
import time
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
        stream.extractall(target, filter="data")


class BlockNumpy:
    def find_spec(self, fullname: str, _path: Any = None, _target: Any = None) -> None:
        if fullname == "numpy" or fullname.startswith("numpy."):
            raise ModuleNotFoundError("NumPy deliberately unavailable in Round4 rule validation")
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--seat", type=int, choices=(0, 1), required=True)
    parser.add_argument("--steps", type=int, default=720)
    parser.add_argument("--expected-arm", choices=("none", "rule", "learned"), required=True)
    parser.add_argument("--block-numpy", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    archive = args.archive.resolve()

    print("stage=before_kaggle_import", file=sys.stderr, flush=True)
    import kaggle_environments
    import numpy
    import psutil
    from kaggle_environments import make
    from kaggle_environments.agent import get_last_callable
    print("stage=after_kaggle_import", file=sys.stderr, flush=True)

    # Keep the validation sandbox beside its evidence file.  The shared C:\tmp
    # can contain a very large number of unrelated entries on this workstation,
    # which makes Windows temporary-directory allocation spuriously slow.
    validation_tmp_root = args.output.resolve().parent / "_loader_tmp"
    validation_tmp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="run_", dir=validation_tmp_root) as raw:
        print("stage=temporary_created", file=sys.stderr, flush=True)
        temporary = Path(raw)
        extracted = temporary / "archive"
        arbitrary_cwd = temporary / "arbitrary_cwd"
        extracted.mkdir()
        arbitrary_cwd.mkdir()
        safe_extract(archive, extracted)
        main_path = extracted / "main.py"
        source = main_path.read_text(encoding="utf-8")
        old_cwd, old_path = Path.cwd(), list(sys.path)
        repository_root = archive.parents[2]
        sys.path[:] = [entry for entry in sys.path if not entry or Path(entry).resolve() != repository_root]
        sys.path.insert(0, str(extracted))
        os.chdir(arbitrary_cwd)
        blocker = BlockNumpy()
        preloaded_numpy = {
            key: value for key, value in list(sys.modules.items()) if key == "numpy" or key.startswith("numpy.")
        }
        try:
            # Direct empty-globals execution proves the source does not rely on
            # an injected __file__.  Official loader selection is checked next.
            empty_environment: dict[str, Any] = {}
            exec(compile(source, "<string>", "exec"), empty_environment)
            print("stage=empty_exec_complete", file=sys.stderr, flush=True)
            no_file_global = "__file__" not in empty_environment
            direct_agent = empty_environment.get("agent")
            if not callable(direct_agent):
                raise AssertionError("empty-globals execution did not expose agent")

            selected = get_last_callable(source, path=str(main_path))
            print("stage=official_loader_complete", file=sys.stderr, flush=True)
            if getattr(selected, "__name__", None) != "agent":
                raise AssertionError(f"last callable is {getattr(selected, '__name__', None)!r}")
            reset = selected.__globals__.get("reset_runtime_state")
            if callable(reset):
                reset()

            if args.block_numpy:
                sys.meta_path.insert(0, blocker)
                for key in preloaded_numpy:
                    sys.modules.pop(key, None)
            process = psutil.Process(os.getpid())
            before_rss = process.memory_info().rss
            timings: list[float] = []

            def measured(observation: Any, configuration: Any = None) -> Any:
                started = time.perf_counter()
                try:
                    return selected(observation, configuration)
                except TypeError:
                    return selected(observation)
                finally:
                    timings.append(time.perf_counter() - started)

            configuration = {"episodeSteps": args.steps, "seed": 2026092700 + args.seat}
            env = make("kaggriculture", configuration=configuration, debug=True)
            print("stage=environment_created", file=sys.stderr, flush=True)
            env.run([measured, "starter"] if args.seat == 0 else ["starter", measured])
            print("stage=episode_complete", file=sys.stderr, flush=True)
            replay = env.toJSON()
            final = replay["steps"][-1]
            # main.py intentionally exposes a bound RuntimePolicy.agent.  Its
            # __globals__ belong to policy_runtime.py, so query the globals
            # populated by the direct empty-environment execution instead.
            diagnostics = empty_environment.get("policy_diagnostics")
            diagnostic_value = diagnostics() if callable(diagnostics) else {}
            expected_runtime = f"round5_{args.expected_arm}"
            runtime_ok = diagnostic_value.get("arm") == expected_runtime
            model_ok = (
                args.expected_arm != "learned"
                or (
                    int(diagnostic_value.get("strategy_inference_calls", 0)) > 0
                    and int(diagnostic_value.get("selector_runtime_calls", 0)) > 0
                    and int(diagnostic_value.get("silent_fallbacks", 0)) == 0
                )
            )
            result = {
                "archive": str(archive),
                "archive_sha256": sha256(archive),
                "archive_members": sorted(path.name for path in extracted.iterdir() if path.is_file()),
                "kaggle_environments_version": kaggle_environments.__version__,
                "numpy_version": numpy.__version__,
                "loader": "kaggle_environments.agent.get_last_callable",
                "loader_exec_globals_started_empty": True,
                "main_source_received_file_global": not no_file_global,
                "arbitrary_cwd": True,
                "repository_removed_from_sys_path": True,
                "last_callable": getattr(selected, "__name__", None),
                "seat": args.seat,
                "numpy_blocked": args.block_numpy,
                "stored_states": len(replay["steps"]),
                "terminal_statuses": [str(row.get("status")) for row in final],
                "terminal_rewards": [row.get("reward") for row in final],
                "calls": len(timings),
                "warm_mean_seconds": sum(timings) / max(1, len(timings)),
                "warm_max_seconds": max(timings),
                "rss_delta_bytes": process.memory_info().rss - before_rss,
                "external_communication_required": False,
                "diagnostics": diagnostic_value,
                "expected_arm": args.expected_arm,
                "runtime_identity_ok": runtime_ok,
                "model_runtime_ok": model_ok,
                "passed": (
                    len(replay["steps"]) == args.steps
                    and [str(row.get("status")) for row in final] == ["DONE", "DONE"]
                    and getattr(selected, "__name__", None) == "agent"
                    and no_file_global
                    and runtime_ok
                    and model_ok
                ),
            }
        finally:
            if blocker in sys.meta_path:
                sys.meta_path.remove(blocker)
            sys.modules.update(preloaded_numpy)
            sys.path[:] = old_path
            os.chdir(old_cwd)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
