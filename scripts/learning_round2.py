# ruff: noqa: E501
"""Executable round-2 learning study for Kaggriculture.

Commands are intentionally thin and resumable.  They never submit to Kaggle,
overwrite the learning-next study, or silently substitute C0 for a missing
model.  Every command owns an exclusive lock and appends a start/end record.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.util
import inspect
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import traceback
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.learning_next_20260921.common import (  # noqa: E402
    PRODUCTS,
    WORK_OPS,
    MarketHistory,
    action_token,
    legal_actor_tokens,
    market_token,
    state_feature_names,
    state_features,
    token_action,
    token_order,
)
from agents.learning_round2_20260921.common import (  # noqa: E402
    HORIZONS,
    a2_candidates,
    a2_feature_names,
    a2_features,
    actor_context,
    actor_probe_succeeded,
    make_actor_probe,
    observation_fingerprint,
    safe_action_shape,
)

STUDY_ID = "learning_round2_20260921"
EXPERIMENT = ROOT / "experiments" / STUDY_ID
AGENT = ROOT / "agents" / STUDY_ID
MODEL_DIR = EXPERIMENT / "models"
DATASET_DIR = EXPERIMENT / "datasets"
RUNTIME_DIR = EXPERIMENT / "runtime"
ARCHIVE_DIR = ROOT / "artifacts" / "submissions"
OLD = ROOT / "experiments" / "learning_next_20260921"
C0_ARCHIVE = ARCHIVE_DIR / "v126_control_candidate.tar.gz"
ENGINE_HASH = "bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e"
TRAIN_SEED = 20260921
OPPONENTS = {
    "qeinstein_moev2": ROOT / "experiments/research_20260910/runtime/qeinstein_moev2/main.py",
    "mooman_e052a": ROOT / "experiments/research_20260910/runtime/mooman_e052a/main.py",
    "smart_farm": ROOT / "experiments/research_20260918_v120/acquisition/smart_farm/decoded_main_1.py",
    "souvik_v4": ROOT / "experiments/research_20260910/runtime/souvik_v4/main.py",
}
TRAIN_FAMILIES = tuple(OPPONENTS)
ROUND1_SEEDS = tuple(range(2026092401, 2026092403))
ROUND2_SEEDS = (2026092409,)
EXTERNAL_SEEDS = tuple(range(2026092421, 2026092425))


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def json_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


def _git(command: Sequence[str]) -> str:
    return subprocess.run(["git", *command], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()


def source_state() -> dict[str, Any]:
    status = _git(("status", "--short"))
    diff = subprocess.run(["git", "diff", "--binary"], cwd=ROOT, capture_output=True, check=True).stdout
    untracked = []
    for line in status.splitlines():
        if line.startswith("?? "):
            path = ROOT / line[3:]
            untracked.append({"path": line[3:], "sha256": sha256(path) if path.is_file() else None})
    return {
        "commit": _git(("rev-parse", "HEAD")),
        "tracked_diff_sha256": hashlib.sha256(diff).hexdigest(),
        "status": status.splitlines(),
        "untracked": untracked,
    }


@contextmanager
def command_run(name: str) -> Any:
    EXPERIMENT.mkdir(parents=True, exist_ok=True)
    lock = EXPERIMENT / f".{name}.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"another {name} run owns {lock}") from exc
    os.write(descriptor, json.dumps({"pid": os.getpid(), "started_at_utc": utc_now()}).encode())
    os.close(descriptor)
    record = {
        "command": subprocess.list2cmdline(sys.argv),
        "name": name,
        "pid": os.getpid(),
        "started_at_utc": utc_now(),
        "source": source_state(),
        "status": "running",
    }
    append_jsonl(EXPERIMENT / "commands.jsonl", record)
    started = time.time()
    try:
        yield
    except Exception as exc:
        append_jsonl(
            EXPERIMENT / "commands.jsonl",
            {
                **record,
                "ended_at_utc": utc_now(),
                "duration_seconds": time.time() - started,
                "exit_code": 1,
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-8000:],
            },
        )
        raise
    else:
        append_jsonl(
            EXPERIMENT / "commands.jsonl",
            {
                **record,
                "ended_at_utc": utc_now(),
                "duration_seconds": time.time() - started,
                "exit_code": 0,
                "status": "complete",
            },
        )
    finally:
        lock.unlink(missing_ok=True)


def init_study() -> None:
    for path in (EXPERIMENT, MODEL_DIR, DATASET_DIR, RUNTIME_DIR):
        path.mkdir(parents=True, exist_ok=True)
    prereg = {
        "study_id": STUDY_ID,
        "created_at_utc": utc_now(),
        "source_state": source_state(),
        "c0": {"path": str(C0_ARCHIVE.relative_to(ROOT)), "sha256": sha256(C0_ARCHIVE)},
        "engine": {"package": "kaggle-environments==1.32.7", "source_sha256": ENGINE_HASH},
        "a2": {
            "round1": {"families": list(TRAIN_FAMILIES), "seeds": list(ROUND1_SEEDS), "seats": [0, 1], "max_prefixes_per_game": 2},
            "round2": {"families": list(TRAIN_FAMILIES), "seeds": list(ROUND2_SEEDS), "seats": [0, 1], "state_source": "round1 A2 selector after a bounded intervention"},
            "candidate_limit": 3,
            "runtime_curriculum": {"t_min": 240, "development_max_jobs": 1, "expanded_max_jobs": 4},
            "primary_label": "delta_margin/10000 + 5*delta_win_score versus KEEP from the same prefix",
            "risk": "cash<1000, win-to-loss, or delta_margin<-5000",
        },
        "b2": {
            "primary_label": "market-impact SELL quantity",
            "auxiliary_labels": ["requested SELL", "executed SELL", "revenue"],
            "horizons": list(HORIZONS),
            "terminal_policy": "mask any target whose complete horizon extends past the 719th decision",
            "candidate_contract": "same contiguous-SELL reorder set as frozen B1",
        },
        "banks": {
            "regression": {"families": ["qeinstein_moev2"], "seeds": [2026092301], "seats": [0, 1]},
            "known_failure": [
                {"family": "qeinstein_moev2", "seed": 2026092307, "seat": 1, "c0_margin": -170},
                {"family": "smart_farm", "seed": 2026092307, "seat": 0, "c0_margin": -461},
                {"family": "smart_farm", "seed": 2026092307, "seat": 1, "c0_margin": -461},
                {"family": "mooman_e052a", "seed": 2026092307, "seat": 1, "c0_margin": -7452},
            ],
            "external": {"families": list(TRAIN_FAMILIES), "seeds": list(EXTERNAL_SEEDS), "seats": [0, 1]},
        },
        "promotion_rule": "paired win-score, loss-to-win/win-to-loss, family regressions, runtime and economic failures; margin alone is insufficient",
        "forbidden": ["Kaggle submission", "paid compute", "future/private runtime inputs", "overwriting learning_next_20260921"],
    }
    write_json(EXPERIMENT / "preregistration.json", prereg)
    environment = {
        "captured_at_utc": utc_now(),
        "python": sys.version,
        "logical_cpus": os.cpu_count(),
        "numpy": np.__version__,
        "gpu_used": False,
        "torch_used": False,
    }
    try:
        import psutil

        environment["ram_total_bytes"] = psutil.virtual_memory().total
        environment["ram_available_bytes"] = psutil.virtual_memory().available
    except ImportError:
        pass
    write_json(EXPERIMENT / "environment.json", environment)
    print(json.dumps({"study_id": STUDY_ID, "preregistered": True}), flush=True)


def _safe_extract(archive: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    root = target.resolve()
    with tarfile.open(archive, "r:gz") as stream:
        for member in stream.getmembers():
            if not (target / member.name).resolve().is_relative_to(root):
                raise ValueError(member.name)
        stream.extractall(target)
    if not (target / "main.py").is_file():
        raise FileNotFoundError(target / "main.py")


def _stage_overlay(name: str, main_source: Path, config: Mapping[str, Any], files: Sequence[Path]) -> Path:
    target = RUNTIME_DIR / name
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    shutil.copy2(main_source, target / "main.py")
    shutil.copy2(AGENT / "common.py", target / "common.py")
    shutil.copy2(ROOT / "agents/learning_next_20260921/common.py", target / "learning_common.py")
    c0 = RUNTIME_DIR / "c0"
    for source in c0.iterdir():
        destination = "c0_main.py" if source.name == "main.py" else source.name
        shutil.copy2(source, target / destination)
    for source in files:
        if not source.is_file():
            raise FileNotFoundError(f"required runtime file missing: {source}")
        shutil.copy2(source, target / source.name)
    write_json(target / "arm_config.json", dict(config))
    return target / "main.py"


def prepare_runtimes() -> dict[str, Path]:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    _safe_extract(C0_ARCHIVE, RUNTIME_DIR / "c0")
    old_manifest = json.loads((OLD / "archive_manifest.json").read_text(encoding="utf-8"))
    result = {"c0": RUNTIME_DIR / "c0" / "main.py"}
    for old_arm, name in (("b_simple", "b_simple"), ("b_learned", "b1")):
        archive = ROOT / old_manifest["arms"][old_arm]["path"]
        _safe_extract(archive, RUNTIME_DIR / name)
        result[name] = RUNTIME_DIR / name / "main.py"
    gate = {"value_gate": 0.0, "risk_gate": 0.35}
    metadata = MODEL_DIR / "a2_model.json"
    if metadata.is_file():
        gate.update(json.loads(metadata.read_text(encoding="utf-8")).get("selected_gate", {}))
    for mode, name, models in (
        ("keep", "a2_keep", ()),
        ("nonlearned", "a2_nonlearned", ()),
        ("learned", "a2", (MODEL_DIR / "a2_model.npz",)),
    ):
        if mode == "learned" and not models[0].is_file():
            continue
        result[name] = _stage_overlay(
            name,
            AGENT / "a2_agent.py",
            {"mode": mode, "t_min": 240, "max_jobs": 1, **gate},
            models,
        )
    for mode, name in (("frequency", "b2_frequency"), ("learned", "b2"), ("history_shuffle", "b2_history_shuffle")):
        required = [MODEL_DIR / "b2_simple.json"]
        if mode != "frequency":
            required.append(MODEL_DIR / "b2_model.npz")
        if all(path.is_file() for path in required):
            result[name] = _stage_overlay(name, AGENT / "b2_agent.py", {"mode": mode}, required)
    return result


def _load_module(path: Path, label: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"_round2_{label}_{os.getpid()}_{uuid.uuid4().hex}", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    # Standalone archives intentionally use generic fallback names such as
    # ``common``.  Keep those imports local to this archive instead of reusing a
    # module cached by a previously loaded arm in the same interpreter.
    generic_names = ("common", "learning_common")
    cached = {name: sys.modules.pop(name) for name in generic_names if name in sys.modules}
    parent = str(path.parent)
    sys.path.insert(0, parent)
    try:
        spec.loader.exec_module(module)
    finally:
        if sys.path and sys.path[0] == parent:
            sys.path.pop(0)
        for name in generic_names:
            sys.modules.pop(name, None)
        sys.modules.update(cached)
    if hasattr(module, "reset_runtime_state"):
        module.reset_runtime_state()
    return module


def _call(function: Callable[..., Any], observation: Any, configuration: Any) -> Any:
    try:
        parameters = inspect.signature(function).parameters.values()
        accepts = any(value.kind in {value.VAR_POSITIONAL, value.VAR_KEYWORD} for value in parameters) or len(list(parameters)) >= 2
    except (TypeError, ValueError):
        accepts = True
    return function(observation, configuration) if accepts else function(observation)


def _run_game(task: Mapping[str, Any]) -> dict[str, Any]:
    import random

    import psutil
    from kaggle_environments import make

    random.seed(int(task["seed"]))
    np.random.seed(int(task["seed"]) % (2**32 - 1))
    process = psutil.Process(os.getpid())
    import_started = time.perf_counter()
    focal_module = _load_module(Path(task["agent_main"]), f"{task['arm']}_focal")
    import_seconds = time.perf_counter() - import_started
    opponent_module = _load_module(Path(task["opponent_main"]), f"{task['family']}_opponent")
    timings: list[float] = []

    def focal(observation: Any, configuration: Any = None) -> Any:
        started = time.perf_counter()
        action = _call(focal_module.agent, observation, configuration)
        timings.append(time.perf_counter() - started)
        return action

    def opponent(observation: Any, configuration: Any = None) -> Any:
        return _call(opponent_module.agent, observation, configuration)

    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": int(task["seed"])}, debug=True)
    env.run([focal, opponent] if int(task["seat"]) == 0 else [opponent, focal])
    replay = env.toJSON()
    seat = int(task["seat"])
    rewards = [float(value.get("reward") or 0) for value in replay["steps"][-1]]
    replay_path = task.get("replay_path")
    if replay_path:
        path = Path(str(replay_path))
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as stream:
            json.dump(replay, stream, ensure_ascii=False, separators=(",", ":"))
    diagnostics = focal_module.policy_diagnostics() if hasattr(focal_module, "policy_diagnostics") else {}
    trace = focal_module.policy_trace() if hasattr(focal_module, "policy_trace") else []
    values = np.asarray(timings, np.float64)
    shops = [row[0]["observation"]["town"].get("unlocked_shops", []) for row in replay["steps"]]
    return {
        **dict(task),
        "our_cash": rewards[seat],
        "opponent_cash": rewards[1 - seat],
        "margin": rewards[seat] - rewards[1 - seat],
        "score": 1.0 if rewards[seat] > rewards[1 - seat] else 0.5 if rewards[seat] == rewards[1 - seat] else 0.0,
        "statuses": [str(value.get("status")) for value in replay["steps"][-1]],
        "stored_states": len(replay["steps"]),
        "cold_import_seconds": import_seconds,
        "inference_mean_seconds": float(values.mean()),
        "inference_p95_seconds": float(np.percentile(values, 95)),
        "inference_max_seconds": float(values.max()),
        "rss_bytes": process.memory_info().rss,
        "timing_measured": True,
        "shop_history_sha256": json_hash(shops),
        "diagnostics": diagnostics,
        "trace": trace,
    }


def _result_from_completed_replay(task: Mapping[str, Any]) -> dict[str, Any] | None:
    path = Path(str(task["replay_path"]))
    if not path.is_file():
        return None
    try:
        replay = _read_gzip_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    if len(replay.get("steps") or []) != 720:
        return None
    seat = int(task["seat"])
    rewards = [float(value.get("reward") or 0) for value in replay["steps"][-1]]
    shops = [row[0]["observation"]["town"].get("unlocked_shops", []) for row in replay["steps"]]
    return {
        **dict(task),
        "our_cash": rewards[seat],
        "opponent_cash": rewards[1 - seat],
        "margin": rewards[seat] - rewards[1 - seat],
        "score": 1.0 if rewards[seat] > rewards[1 - seat] else 0.5 if rewards[seat] == rewards[1 - seat] else 0.0,
        "statuses": [str(value.get("status")) for value in replay["steps"][-1]],
        "stored_states": len(replay["steps"]),
        "cold_import_seconds": None,
        "inference_mean_seconds": None,
        "inference_p95_seconds": None,
        "inference_max_seconds": None,
        "rss_bytes": None,
        "timing_measured": False,
        "shop_history_sha256": json_hash(shops),
        "diagnostics": {"resumed_completed_replay": 1},
        "trace": [],
    }


def _run_parallel(tasks: list[dict[str, Any]], worker: Callable[[Mapping[str, Any]], dict[str, Any]], workers: int = 16) -> list[dict[str, Any]]:
    results = []
    with ProcessPoolExecutor(max_workers=min(workers, len(tasks)), max_tasks_per_child=1) as executor:
        futures = {executor.submit(worker, task): task for task in tasks}
        for index, future in enumerate(as_completed(futures), 1):
            result = future.result()
            results.append(result)
            print(f"{index}/{len(tasks)} {result.get('arm', result.get('candidate_id', 'task'))} seed={result.get('seed')} seat={result.get('seat')}", flush=True)
    return results


def _restore_observation(states: list[dict[str, Any]], seat: int, step: int) -> dict[str, Any]:
    public = deepcopy(states[0].get("observation") or {})
    private = states[seat].get("observation") or {}
    public["player"] = seat
    public["private"] = deepcopy(private.get("private", {}))
    public["remainingOverageTime"] = private.get("remainingOverageTime", public.get("remainingOverageTime", 60))
    public["step"] = step
    return public


def _action_state_summary(observation: Mapping[str, Any], actor: int | None = None) -> dict[str, Any]:
    seat = int(observation.get("player", 0))
    farm = observation["farms"][seat]
    result = {
        "step": int(observation.get("step", 0)),
        "money": farm.get("money"),
        "farmer": farm.get("farmer"),
        "hands": farm.get("hands"),
        "shed": observation.get("private", {}).get("shed", {}),
        "seeds": observation.get("private", {}).get("seeds", {}),
        "market_inventory": observation.get("market", {}).get("inventory", {}),
    }
    if actor is not None:
        _farm, position, inventory, tile = actor_context(observation, actor)
        result.update({"actor": actor, "position": list(position), "inventory": dict(inventory), "tile": tile})
    return result


def _read_gzip_json(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def _first_replay(stage: str, arm: str, family: str, seat: int) -> Path:
    values = sorted((OLD / stage / "replays" / arm / family).glob(f"*_seat_{seat}.json.gz"))
    if not values:
        raise FileNotFoundError((stage, arm, family, seat))
    return values[0]


def _compare_replays(left: dict[str, Any], right: dict[str, Any], seat: int) -> dict[str, Any]:
    first_action = None
    first_public_state = None
    first_private_state = None
    action_differences = 0
    for index in range(min(len(left["steps"]), len(right["steps"]))):
        if index > 0 and left["steps"][index][seat].get("action") != right["steps"][index][seat].get("action"):
            action_differences += 1
            first_action = index - 1 if first_action is None else first_action
        left_obs = left["steps"][index][seat].get("observation") or {}
        right_obs = right["steps"][index][seat].get("observation") or {}
        public_keys = ("farms", "market", "town", "day", "hour")
        if first_public_state is None and any(left_obs.get(key) != right_obs.get(key) for key in public_keys):
            first_public_state = index
        if first_private_state is None and left_obs.get("private") != right_obs.get("private"):
            first_private_state = index
    return {
        "stored_states_equal": len(left["steps"]) == len(right["steps"]),
        "actions_equal": action_differences == 0,
        "action_differences": action_differences,
        "first_action_difference": first_action,
        "first_public_state_difference": first_public_state,
        "first_private_state_difference": first_private_state,
        "final_rewards_left": [row.get("reward") for row in left["steps"][-1]],
        "final_rewards_right": [row.get("reward") for row in right["steps"][-1]],
        "final_status_left": [row.get("status") for row in left["steps"][-1]],
        "final_status_right": [row.get("status") for row in right["steps"][-1]],
    }


def diagnose_keep() -> dict[str, Any]:
    runtimes = prepare_runtimes()
    direct = _load_module(runtimes["c0"], "saved_direct")
    wrapped = _load_module(runtimes["a2_keep"], "saved_keep")
    source_path = _first_replay("smoke_repair1_evaluation", "c0", "qeinstein_moev2", 0)
    replay = _read_gzip_json(source_path)
    mismatches = []
    mutation_failures = []
    for step in range(len(replay["steps"]) - 1):
        observation = deepcopy(replay["steps"][step][0]["observation"])
        before = observation_fingerprint(observation)
        left = _call(direct.agent, deepcopy(observation), None)
        right_input = deepcopy(observation)
        right = _call(wrapped.agent, right_input, None)
        if observation_fingerprint(right_input) != before:
            mutation_failures.append(step)
        if left != right:
            mismatches.append({"step": step, "direct": left, "keep": right})
            break
    output = EXPERIMENT / "keep_identity"
    tasks = []
    for arm in ("c0", "a2_keep"):
        for seat in (0, 1):
            tasks.append(
                {
                    "arm": arm,
                    "family": "qeinstein_moev2",
                    "seed": 2026092301,
                    "seat": seat,
                    "agent_main": str(runtimes[arm]),
                    "opponent_main": str(OPPONENTS["qeinstein_moev2"]),
                    "replay_path": str(output / "replays" / arm / f"seat_{seat}.json.gz"),
                }
            )
    rows = _run_parallel(tasks, _run_game)
    lookup = {(row["arm"], row["seat"]): row for row in rows}
    games = []
    for seat in (0, 1):
        left = _read_gzip_json(Path(lookup[("c0", seat)]["replay_path"]))
        right = _read_gzip_json(Path(lookup[("a2_keep", seat)]["replay_path"]))
        games.append({"seat": seat, **_compare_replays(left, right, seat)})
    result = {
        "saved_observation_source": str(source_path.relative_to(ROOT)),
        "saved_observations_checked": len(replay["steps"]) - 1,
        "saved_output_identical": not mismatches,
        "first_saved_mismatch": mismatches[0] if mismatches else None,
        "encoder_input_mutations": mutation_failures,
        "full_game_checks": games,
        "full_game_identity": all(
            row["actions_equal"]
            and row["first_public_state_difference"] is None
            and row["first_private_state_difference"] is None
            and row["final_rewards_left"] == row["final_rewards_right"]
            for row in games
        ),
        "no_op_contract": "C0 called once; shadow candidates are read-only; KEEP returns the complete structured C0 joint action",
    }
    write_json(EXPERIMENT / "keep_c0_identity.json", result)
    return result


def diagnose_old_a_failure() -> dict[str, Any]:
    cases = []
    for arm in ("a_baseline", "a_learned"):
        for seat in (0, 1):
            control_path = _first_replay("smoke_repair1_evaluation", "c0", "qeinstein_moev2", seat)
            candidate_path = _first_replay("smoke_repair1_evaluation", arm, "qeinstein_moev2", seat)
            control = _read_gzip_json(control_path)
            candidate = _read_gzip_json(candidate_path)
            comparison = _compare_replays(control, candidate, seat)
            step = int(comparison["first_action_difference"] or 0)
            action_index = step + 1
            before_c = _restore_observation(control["steps"][step], seat, step)
            before_a = _restore_observation(candidate["steps"][step], seat, step)
            after_c = _restore_observation(control["steps"][min(step + 1, 719)], seat, min(step + 1, 719))
            after_a = _restore_observation(candidate["steps"][min(step + 1, 719)], seat, min(step + 1, 719))
            cases.append(
                {
                    "arm": arm,
                    "seat": seat,
                    "first_action_difference": step,
                    "c0_intended_action": control["steps"][action_index][seat].get("action"),
                    "final_action": candidate["steps"][action_index][seat].get("action"),
                    "before_c0": _action_state_summary(before_c),
                    "before_candidate": _action_state_summary(before_a),
                    "after_c0": _action_state_summary(after_c),
                    "after_candidate": _action_state_summary(after_a),
                    "first_public_state_difference": comparison["first_public_state_difference"],
                    "first_private_state_difference": comparison["first_private_state_difference"],
                    "final_rewards": comparison["final_rewards_right"],
                    "source_router_state": "C0 was called once, then the selected primitive replaced its structured unit action",
                    "job_state": "old A had no active job unless FEED-without-WHEAT was selected",
                    "missing_precondition": "the op-priority/11-class selector did not preserve C0's actor-level plan, future inventory reservation, or continuation contract",
                }
            )
    baseline_steps = {row["first_action_difference"] for row in cases if row["arm"] == "a_baseline"}
    learned_steps = {row["first_action_difference"] for row in cases if row["arm"] == "a_learned"}
    result = {
        "cases": cases,
        "common_cause": (
            "The shared executor replaced each C0 work boundary independently and returned to a time-advanced C0 without a "
            "state-compatible job/continuation contract. The non-learned priority selector therefore collapses too; the failure "
            "cannot be attributed to the learned classifier alone."
        ),
        "same_first_difference_steps": sorted(baseline_steps & learned_steps),
        "scope": "first divergence and immediate transition; later zero cash is not used as causal evidence",
    }
    write_json(EXPERIMENT / "first_failure_cases.json", result)
    return result


def diagnose_a_objective() -> dict[str, Any]:
    dataset = OLD / "datasets/a"
    manifest = json.loads((dataset / "dataset_manifest.json").read_text(encoding="utf-8"))
    x_train = np.load(dataset / "x_train.npy", mmap_mode="r")
    y_train = np.load(dataset / "y_train.npy", mmap_mode="r")
    x_test = np.load(dataset / "x_test.npy", mmap_mode="r")
    y_test = np.load(dataset / "y_test.npy", mmap_mode="r")
    baseline_test = np.load(dataset / "baseline_test.npy", mmap_mode="r")
    names = list(json.loads((OLD / "feature_schema.json").read_text(encoding="utf-8"))["actor"])
    day_index, hour_index = names.index("day"), names.index("hour")

    def time_lookup(labels: np.ndarray) -> np.ndarray:
        table: dict[tuple[int, int], Counter[int]] = defaultdict(Counter)
        by_hour: dict[int, Counter[int]] = defaultdict(Counter)
        for index in range(len(x_train)):
            key = (round(float(x_train[index, day_index]) * 29), round(float(x_train[index, hour_index]) * 23))
            table[key][int(labels[index])] += 1
            by_hour[key[1]][int(labels[index])] += 1
        output = []
        for row in x_test:
            key = (round(float(row[day_index]) * 29), round(float(row[hour_index]) * 23))
            counts = table.get(key) or by_hour.get(key[1]) or Counter({int(np.bincount(labels).argmax()): 1})
            output.append(counts.most_common(1)[0][0])
        return np.asarray(output)

    rng = np.random.default_rng(TRAIN_SEED)
    shuffled = np.asarray(y_train).copy()
    rng.shuffle(shuffled)
    sample_index = 0
    example = {
        "feature_width": int(x_train.shape[1]),
        "nonzero_features": {names[i]: float(value) for i, value in enumerate(x_train[sample_index]) if value != 0},
        "label_index": int(y_train[sample_index]),
        "label_op": WORK_OPS[int(y_train[sample_index])],
        "candidate_set_storage": "not stored per row; reconstructed at build time only as work_legal_ops(obs, actor)",
        "objective": "weighted 11-class cross-entropy over the selected teacher op",
        "decoder": "preserve C0 structured primitive only when selected op matches; otherwise choose the lexicographically first legal token",
    }
    result = {
        "finding": "old A is an 11-class operation classifier, not a choice-set/job ranking model",
        "teacher": 56216119,
        "example": example,
        "input_contains_candidate_op": False,
        "input_contains_teacher_selected_target": False,
        "candidate_op_note": "No candidate is scored as Q(obs,candidate); actor state alone is classified.",
        "controls": {
            "candidate_generator_priority_test_accuracy": float((np.asarray(baseline_test) == np.asarray(y_test)).mean()),
            "majority_test_accuracy": float((np.asarray(y_test) == int(np.bincount(np.asarray(y_train)).argmax())).mean()),
            "time_only_lookup_test_accuracy": float((time_lookup(np.asarray(y_train)) == np.asarray(y_test)).mean()),
            "label_shuffle_time_lookup_test_accuracy": float((time_lookup(shuffled) == np.asarray(y_test)).mean()),
        },
        "reported_model_test_accuracy": json.loads((OLD / "offline_metrics_a.json").read_text(encoding="utf-8"))["test"]["accuracy"],
        "choice_set_metric": "not present in the old artifact; class accuracy does not establish candidate ranking",
        "job_metric": "undefined: rows are actor primitives, not jobs",
        "complete_action_metric": "not optimized; item/quantity are outside the 11-class target",
        "excluded": {
            "CARE": int(manifest["candidate_coverage"].get("excluded:CARE", 0)),
            "HARVEST": int(manifest["candidate_coverage"].get("excluded:HARVEST", 0)),
            "runtime_handling": "old runtime only intervenes on a C0 work boundary; unavailable chosen tokens become PASS/fallback or a special FEED job",
        },
        "rows": {"train": len(y_train), "test": len(y_test)},
    }
    write_json(EXPERIMENT / "feature_target_audit.json", result)
    return result


def diagnose_bc_roundtrip() -> dict[str, Any]:
    source = json.loads((OLD / "source_manifest.json").read_text(encoding="utf-8"))
    split = json.loads((OLD / "split_manifest.json").read_text(encoding="utf-8"))["assignments"]
    quantities = json.loads((OLD / "models/bc_quantities.json").read_text(encoding="utf-8"))
    rows = [
        row
        for row in source["files"]
        if int(row["submission_id"]) == 56216119 and split[str(row["episode_id"])] == "test"
    ]
    actor_total = actor_op = actor_full = 0
    market_total = market_op = market_full = 0
    joint_total = joint_full = 0
    by_op: dict[str, Counter[str]] = defaultdict(Counter)
    alias: dict[str, set[str]] = defaultdict(set)
    first_failure = None
    for row in rows:
        replay = json.loads((ROOT / row["path"]).read_text(encoding="utf-8"))
        seat = int(row["seat"])
        for step in range(len(replay["steps"]) - 1):
            observation = _restore_observation(replay["steps"][step], seat, step)
            action = replay["steps"][step + 1][seat].get("action") or {}
            units = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
            decoded_units = []
            for value in units:
                token = action_token(value)
                quantity = quantities["actor"].get(token, 1)
                decoded = token_action(token, int(round(quantity)))
                decoded_units.append(decoded)
                actor_total += 1
                actor_op += int(bool(value) and bool(decoded) and value[0] == decoded[0])
                actor_full += int(list(value) == decoded)
                by_op[str(value[0])]["total"] += 1
                by_op[str(value[0])]["full"] += int(list(value) == decoded)
                if actor_total <= 5000:
                    _farm, position, inventory, tile = actor_context(observation, len(decoded_units) - 1)
                    compact_key = json_hash(
                        {
                            "day": observation.get("day"),
                            "hour": observation.get("hour"),
                            "actor": len(decoded_units) - 1,
                            "position": position,
                            "inventory": inventory,
                            "tile": tile,
                            "market": observation.get("market"),
                        }
                    )
                    alias[compact_key].add(json.dumps(value, separators=(",", ":")))
                if first_failure is None and list(value) != decoded:
                    first_failure = {"episode_id": row["episode_id"], "step": step, "field": "actor quantity/item", "teacher": value, "decoded": decoded}
            orders = action.get("market") or []
            decoded_orders = []
            for order in orders:
                token = market_token(order)
                decoded = token_order(token, int(round(quantities["market"].get(token, 1))))
                decoded_orders.append(decoded)
                market_total += 1
                market_op += int(bool(order) and bool(decoded) and order[0] == decoded[0])
                market_full += int(list(order) == decoded)
                by_op[str(order[0])]["total"] += 1
                by_op[str(order[0])]["full"] += int(list(order) == decoded)
                if first_failure is None and list(order) != decoded:
                    first_failure = {"episode_id": row["episode_id"], "step": step, "field": "market quantity", "teacher": order, "decoded": decoded}
            decoded_action = {"farmer": decoded_units[0], "hands": decoded_units[1:], "market": decoded_orders}
            joint_total += 1
            joint_full += int(decoded_action == {"farmer": action.get("farmer") or ["PASS"], "hands": action.get("hands") or [], "market": orders})
    aliasing = sum(len(values) > 1 for values in alias.values())
    result = {
        "teacher": 56216119,
        "test_episodes": len(rows),
        "representation": {
            "actor_op_rate": actor_op / max(1, actor_total),
            "actor_full_field_rate": actor_full / max(1, actor_total),
            "market_op_rate": market_op / max(1, market_total),
            "market_full_field_rate": market_full / max(1, market_total),
            "joint_action_exact_rate": joint_full / max(1, joint_total),
            "transition_exact_lower_bound": joint_full / max(1, joint_total),
            "transition_note": "Exact joint actions imply exact deterministic non-random transitions; a sampled engine replay check is added by build-b2.",
        },
        "counts": {"actor": actor_total, "market": market_total, "joint": joint_total},
        "by_op": {key: dict(value) for key, value in by_op.items()},
        "first_roundtrip_failure": first_failure,
        "bc_quantities_role": "train-only per-token median; it replaces every teacher quantity at decode and is therefore lossy",
        "same_encoded_observation_multiple_actor_actions": aliasing,
        "sequence_properties": {"actor_order_preserved": True, "market_slot_order_preserved": True, "eos_represented": True},
        "verdict": "op vocabulary is covered, but median quantity decoding prevents complete action reconstruction",
    }
    write_json(EXPERIMENT / "action_roundtrip.json", result)
    return result


def diagnose_terminal() -> dict[str, Any]:
    old_manifest = json.loads((OLD / "datasets/b/dataset_manifest.json").read_text(encoding="utf-8"))
    rows = sum(value[0] for key, value in old_manifest["arrays"].items() if key.startswith("x_"))
    result = {
        "unique_episodes": 850,
        "stored_states": 850 * 720,
        "decisions": 850 * 719,
        "old_b_rows": rows,
        "old_b_sampling": "both seats, even observation indices 0..718 (360 rows per seat/episode)",
        "old_terminal_behavior": "end=min(last_state, step+horizon), so horizon 4/24 tail rows use a shorter effective horizon without a mask",
        "round2_policy": "store a boolean mask for every item/horizon and exclude censored cells from loss/metrics",
        "runtime_previous_action": "MarketHistory receives the focal agent's actual prior emitted market orders; teacher actions are used only in offline replay reconstruction",
        "same_turn_information": "only already-emitted self actions are retained; unselected teacher actions are not runtime features",
    }
    write_json(EXPERIMENT / "terminal_audit.json", result)
    return result


def diagnose() -> None:
    keep = diagnose_keep()
    failure = diagnose_old_a_failure()
    objective = diagnose_a_objective()
    bc = diagnose_bc_roundtrip()
    terminal = diagnose_terminal()
    lines = [
        "# Round-2 narrow diagnosis",
        "",
        f"- KEEP_C0 saved-output identity: **{keep['saved_output_identical']}**; full-game trace/state/reward identity: **{keep['full_game_identity']}**.",
        f"- Old A objective: {objective['finding']}. The shared collapse is an executor/continuation-contract failure, not evidence that fit did not occur.",
        f"- First old-A cases: {len(failure['cases'])}; both learned and non-learned arms replace C0 primitives without preserving a completed plan contract.",
        f"- BC teacher-token round-trip joint exact rate: {bc['representation']['joint_action_exact_rate']:.6f}; op coverage is not full-field recovery.",
        f"- B storage/decision distinction: {terminal['stored_states']} saved states versus {terminal['decisions']} decisions; round 2 masks censored horizons.",
        "",
        "Detailed machine-readable evidence: `keep_c0_identity.json`, `first_failure_cases.json`, `feature_target_audit.json`, `action_roundtrip.json`, and `terminal_audit.json`.",
    ]
    (EXPERIMENT / "DIAGNOSIS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_a2_scan(task: Mapping[str, Any]) -> dict[str, Any]:
    import random

    from kaggle_environments import make

    random.seed(int(task["seed"]))
    np.random.seed(int(task["seed"]) % (2**32 - 1))
    base_module = _load_module(Path(task["base_main"]), "a2_scan_base")
    opponent_module = _load_module(Path(task["opponent_main"]), "a2_scan_opp")
    seat = int(task["seat"])
    history = MarketHistory()
    previous_market: list[list[Any]] | None = None
    prefixes: list[dict[str, Any]] = []
    last_prefix = -100

    def focal(observation: Any, configuration: Any = None) -> Any:
        nonlocal previous_market, last_prefix
        history.update(observation, previous_market)
        control = _call(base_module.agent, observation, configuration)
        shaped = safe_action_shape(control, len(observation["farms"][seat].get("hands", [])))
        diagnostics = base_module.policy_diagnostics() if hasattr(base_module, "policy_diagnostics") else {}
        prior_ok = not task.get("require_prior_job") or (
            int(diagnostics.get("jobs_completed", 0)) >= 1 and int(diagnostics.get("pending_jobs", 0)) == 0
        )
        candidates = (
            a2_candidates(observation, shaped, t_min=int(task.get("t_min", 240)))
            if prior_ok and len(prefixes) < int(task.get("max_prefixes", 2))
            else []
        )
        excluded_jobs = set(task.get("exclude_job_types", []))
        candidates = [candidate for candidate in candidates if candidate["job_type"] not in excluded_jobs]
        step = int(observation.get("step", 0))
        if candidates and len(prefixes) < int(task.get("max_prefixes", 2)) and step - last_prefix >= 12:
            prefix_id = f"{task['family']}:{task['seed']}:{seat}:{step}:{observation_fingerprint(observation)[:16]}"
            prefixes.append(
                {
                    "prefix_id": prefix_id,
                    "step": step,
                    "state_hash": observation_fingerprint(observation),
                    "keep_feature": a2_features(observation, None, history).tolist(),
                    "candidates": [
                        {
                            "candidate_id": candidate["candidate_id"],
                            "job_type": candidate["job_type"],
                            "actor_index": candidate["actor_index"],
                            "sequence": candidate["sequence"],
                            "feature": a2_features(observation, candidate, history).tolist(),
                            "reservations": candidate["reservations"],
                            "deadline_step": candidate["deadline_step"],
                        }
                        for candidate in candidates
                    ],
                }
            )
            last_prefix = step
        previous_market = [list(value) for value in shaped["market"]]
        return shaped

    def opponent(observation: Any, configuration: Any = None) -> Any:
        return _call(opponent_module.agent, observation, configuration)

    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": int(task["seed"])}, debug=True)
    env.run([focal, opponent] if seat == 0 else [opponent, focal])
    replay = env.toJSON()
    rewards = [float(value.get("reward") or 0) for value in replay["steps"][-1]]
    if task.get("replay_path"):
        path = Path(str(task["replay_path"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as stream:
            json.dump(replay, stream, ensure_ascii=False, separators=(",", ":"))
    return {
        **dict(task),
        "prefixes": prefixes,
        "our_cash": rewards[seat],
        "opponent_cash": rewards[1 - seat],
        "margin": rewards[seat] - rewards[1 - seat],
        "score": 1.0 if rewards[seat] > rewards[1 - seat] else 0.5 if rewards[seat] == rewards[1 - seat] else 0.0,
        "statuses": [value.get("status") for value in replay["steps"][-1]],
        "stored_states": len(replay["steps"]),
        "shop_history_sha256": json_hash([row[0]["observation"]["town"].get("unlocked_shops", []) for row in replay["steps"]]),
    }


def _run_a2_branch(task: Mapping[str, Any]) -> dict[str, Any]:
    import random

    from kaggle_environments import make

    random.seed(int(task["seed"]))
    np.random.seed(int(task["seed"]) % (2**32 - 1))
    base_module = _load_module(Path(task["base_main"]), "a2_branch_base")
    opponent_module = _load_module(Path(task["opponent_main"]), "a2_branch_opp")
    seat = int(task["seat"])
    target_step = int(task["target_step"])
    candidate_id = str(task["candidate_id"])
    expected_hash = str(task["state_hash"])
    history = MarketHistory()
    previous_market: list[list[Any]] | None = None
    pending: dict[str, Any] | None = None
    trace: list[dict[str, Any]] = []
    matched = False
    completed = 0
    aborted = 0
    primitive_successes = 0

    def focal(observation: Any, configuration: Any = None) -> Any:
        nonlocal previous_market, pending, matched, completed, aborted, primitive_successes
        history.update(observation, previous_market)
        control = safe_action_shape(
            _call(base_module.agent, observation, configuration),
            len(observation["farms"][seat].get("hands", [])),
        )
        step = int(observation.get("step", 0))
        if pending is not None:
            ok = actor_probe_succeeded(observation, pending["probe"])
            primitive_successes += int(ok)
            if not ok:
                aborted += 1
                trace.append({"step": step, "event": "aborted", "reason": "primitive failed"})
                pending = None
            elif int(pending["next_index"]) >= len(pending["sequence"]):
                _farm, position, _inventory, _tile = actor_context(observation, int(pending["actor_index"]))
                if list(position) == list(pending["target"]):
                    completed += 1
                    trace.append({"step": step, "event": "completed", "rejoined": True})
                else:
                    aborted += 1
                    trace.append({"step": step, "event": "aborted", "reason": "position mismatch"})
                pending = None
            else:
                actor = int(pending["actor_index"])
                action = list(pending["sequence"][int(pending["next_index"])])
                _farm, position, _inventory, _tile = actor_context(observation, actor)
                op_token = action_token(action)
                if (
                    step > int(pending["deadline_step"])
                    or list(position) != list(pending["target"])
                    or op_token not in legal_actor_tokens(observation, actor)
                ):
                    aborted += 1
                    trace.append({"step": step, "event": "aborted", "reason": "precondition"})
                    pending = None
                else:
                    units = [list(control["farmer"]), *[list(value) for value in control["hands"]]]
                    before = list(units[actor])
                    units[actor] = action
                    pending["next_index"] = int(pending["next_index"]) + 1
                    pending["probe"] = make_actor_probe(observation, actor, action)
                    trace.append({"step": step, "event": "primitive", "control": before, "output": action})
                    result = {"farmer": units[0], "hands": units[1:], "market": control["market"]}
                    previous_market = [list(value) for value in result["market"]]
                    return result
        if step == target_step:
            actual_hash = observation_fingerprint(observation)
            if actual_hash != expected_hash:
                raise RuntimeError(f"prefix replay mismatch: {actual_hash} != {expected_hash}")
            candidates = a2_candidates(observation, control, t_min=0)
            chosen = next((value for value in candidates if value["candidate_id"] == candidate_id), None)
            if chosen is None:
                raise RuntimeError(f"candidate disappeared at reproduced prefix: {candidate_id}")
            actor = int(chosen["actor_index"])
            action = list(chosen["sequence"][0])
            if action_token(action) not in legal_actor_tokens(observation, actor):
                raise RuntimeError(f"candidate not legal: {candidate_id}")
            units = [list(control["farmer"]), *[list(value) for value in control["hands"]]]
            before = list(units[actor])
            units[actor] = action
            pending = {
                "actor_index": actor,
                "sequence": deepcopy(chosen["sequence"]),
                "next_index": 1,
                "target": list(chosen["target"]),
                "deadline_step": int(chosen["deadline_step"]),
                "probe": make_actor_probe(observation, actor, action),
            }
            matched = True
            trace.append({"step": step, "event": "selected", "candidate_id": candidate_id, "control": before, "output": action})
            result = {"farmer": units[0], "hands": units[1:], "market": control["market"]}
            previous_market = [list(value) for value in result["market"]]
            return result
        previous_market = [list(value) for value in control["market"]]
        return control

    def opponent(observation: Any, configuration: Any = None) -> Any:
        return _call(opponent_module.agent, observation, configuration)

    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": int(task["seed"])}, debug=True)
    env.run([focal, opponent] if seat == 0 else [opponent, focal])
    replay = env.toJSON()
    rewards = [float(value.get("reward") or 0) for value in replay["steps"][-1]]
    return {
        **dict(task),
        "matched": matched,
        "jobs_completed": completed,
        "jobs_aborted": aborted,
        "primitive_successes": primitive_successes,
        "trace": trace,
        "our_cash": rewards[seat],
        "opponent_cash": rewards[1 - seat],
        "margin": rewards[seat] - rewards[1 - seat],
        "score": 1.0 if rewards[seat] > rewards[1 - seat] else 0.5 if rewards[seat] == rewards[1 - seat] else 0.0,
        "statuses": [value.get("status") for value in replay["steps"][-1]],
        "stored_states": len(replay["steps"]),
        "shop_history_sha256": json_hash([row[0]["observation"]["town"].get("unlocked_shops", []) for row in replay["steps"]]),
    }


def _split_group(family: str, seed: int) -> str:
    value = int(hashlib.sha256(f"{TRAIN_SEED}:{family}:{seed}".encode()).hexdigest()[:8], 16) % 100
    return "train" if value < 70 else "validation" if value < 85 else "test"


def collect_a2(round_number: int) -> None:
    runtimes = prepare_runtimes()
    if round_number == 1:
        base_main = runtimes["c0"]
        seeds = ROUND1_SEEDS
        require_prior_job = False
        max_prefixes = 1
    else:
        if "a2" not in runtimes:
            raise FileNotFoundError("round-1 a2_model.npz must be trained before round-2 collection")
        base_main = _stage_overlay(
            "a2_round1_explore",
            AGENT / "a2_agent.py",
            {"mode": "learned", "t_min": 240, "max_jobs": 1, "value_gate": -1e9, "risk_gate": 1.1},
            (MODEL_DIR / "a2_model.npz",),
        )
        seeds = ROUND2_SEEDS
        require_prior_job = True
        max_prefixes = 1
    scan_tasks = []
    for family in TRAIN_FAMILIES:
        for seed in seeds:
            for seat in (0, 1):
                save_replay = family == TRAIN_FAMILIES[0] and seed == seeds[0]
                scan_tasks.append(
                    {
                        "arm": f"a2_round{round_number}_scan",
                        "round": round_number,
                        "family": family,
                        "seed": seed,
                        "seat": seat,
                        "base_main": str(base_main),
                        "opponent_main": str(OPPONENTS[family]),
                        "max_prefixes": max_prefixes,
                        "require_prior_job": require_prior_job,
                        "t_min": 240,
                        "exclude_job_types": ["COLLECT_DROP"] if round_number == 2 else [],
                        "replay_path": str(EXPERIMENT / "small_replays" / f"a2_round{round_number}_{family}_{seed}_{seat}.json.gz") if save_replay else None,
                    }
                )
    scans = _run_parallel(scan_tasks, _run_a2_scan)
    branch_tasks = []
    baseline: dict[str, dict[str, Any]] = {}
    prefix_metadata: dict[str, dict[str, Any]] = {}
    for row in scans:
        for prefix in row["prefixes"]:
            prefix_id = prefix["prefix_id"]
            baseline[prefix_id] = row
            prefix_metadata[prefix_id] = prefix
            for candidate in prefix["candidates"]:
                branch_tasks.append(
                    {
                        "arm": f"a2_round{round_number}_branch",
                        "round": round_number,
                        "family": row["family"],
                        "seed": row["seed"],
                        "seat": row["seat"],
                        "base_main": str(base_main),
                        "opponent_main": str(OPPONENTS[row["family"]]),
                        "prefix_id": prefix_id,
                        "target_step": prefix["step"],
                        "state_hash": prefix["state_hash"],
                        "candidate_id": candidate["candidate_id"],
                    }
                )
    branches = _run_parallel(branch_tasks, _run_a2_branch) if branch_tasks else []
    branch_lookup = {(row["prefix_id"], row["candidate_id"]): row for row in branches}
    records = []
    for prefix_id, prefix in prefix_metadata.items():
        base = baseline[prefix_id]
        common = {
            "round": round_number,
            "prefix_id": prefix_id,
            "family": base["family"],
            "seed": base["seed"],
            "seat": base["seat"],
            "step": prefix["step"],
            "state_hash": prefix["state_hash"],
            "split": _split_group(base["family"], int(base["seed"])),
            "baseline_score": base["score"],
            "baseline_margin": base["margin"],
            "baseline_self": base["our_cash"],
            "baseline_opp": base["opponent_cash"],
            "baseline_shop_hash": base["shop_history_sha256"],
        }
        records.append(
            {
                **common,
                "candidate_id": "KEEP_C0",
                "job_type": "KEEP_C0",
                "feature": prefix["keep_feature"],
                "final_score": base["score"],
                "final_margin": base["margin"],
                "final_self": base["our_cash"],
                "final_opp": base["opponent_cash"],
                "delta_score": 0.0,
                "delta_margin": 0.0,
                "delta_self": 0.0,
                "delta_opp": 0.0,
                "risk": 0,
                "job_completed": True,
                "job_aborted": False,
                "shop_history_sha256": base["shop_history_sha256"],
            }
        )
        for candidate in prefix["candidates"]:
            branch = branch_lookup[(prefix_id, candidate["candidate_id"])]
            delta_score = float(branch["score"] - base["score"])
            delta_margin = float(branch["margin"] - base["margin"])
            risk = int(branch["our_cash"] < 1000 or delta_score < 0 or delta_margin < -5000 or branch["jobs_aborted"] > 0)
            records.append(
                {
                    **common,
                    "candidate_id": candidate["candidate_id"],
                    "job_type": candidate["job_type"],
                    "actor_index": candidate["actor_index"],
                    "sequence": candidate["sequence"],
                    "reservations": candidate["reservations"],
                    "feature": candidate["feature"],
                    "final_score": branch["score"],
                    "final_margin": branch["margin"],
                    "final_self": branch["our_cash"],
                    "final_opp": branch["opponent_cash"],
                    "delta_score": delta_score,
                    "delta_margin": delta_margin,
                    "delta_self": float(branch["our_cash"] - base["our_cash"]),
                    "delta_opp": float(branch["opponent_cash"] - base["opponent_cash"]),
                    "risk": risk,
                    "job_completed": branch["jobs_completed"] > 0,
                    "job_aborted": branch["jobs_aborted"] > 0,
                    "trace": branch["trace"],
                    "shop_history_sha256": branch["shop_history_sha256"],
                }
            )
    path = DATASET_DIR / "a2" / f"round{round_number}_candidate_results.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in records), encoding="utf-8")
    prefix_count = len(prefix_metadata)
    manifest = {
        "created_at_utc": utc_now(),
        "round": round_number,
        "teacher_meaning": "terminal outcomes of executable local jobs against a reactive executable opponent; not an upper-tier oracle",
        "scan_games": len(scans),
        "closed_loop_branch_games": len(branches),
        "unique_prefixes": prefix_count,
        "candidate_rows": len(records),
        "families": sorted({row["family"] for row in scans}),
        "unique_seeds": len({row["seed"] for row in scans}),
        "splits": dict(Counter(row["split"] for row in records if row["candidate_id"] == "KEEP_C0")),
        "complete_games": sum(row["stored_states"] == 720 and row["statuses"] == ["DONE", "DONE"] for row in branches),
        "job_completed": sum(bool(row.get("job_completed")) for row in records if row["candidate_id"] != "KEEP_C0"),
        "job_aborted": sum(bool(row.get("job_aborted")) for row in records),
        "source_base": "C0" if round_number == 1 else "round-1 A2 with at most one prior intervention",
        "result_path": str(path.relative_to(ROOT)),
        "result_sha256": sha256(path),
    }
    write_json(DATASET_DIR / "a2" / f"round{round_number}_manifest.json", manifest)
    print(json.dumps(manifest), flush=True)


class _Adam:
    def __init__(self, parameters: list[np.ndarray], lr: float) -> None:
        self.parameters = parameters
        self.lr = lr
        self.m = [np.zeros_like(value) for value in parameters]
        self.v = [np.zeros_like(value) for value in parameters]
        self.steps = 0

    def update(self, gradients: Sequence[np.ndarray]) -> None:
        self.steps += 1
        for index, (parameter, gradient) in enumerate(zip(self.parameters, gradients, strict=True)):
            self.m[index] = 0.9 * self.m[index] + 0.1 * gradient
            self.v[index] = 0.999 * self.v[index] + 0.001 * np.square(gradient)
            parameter -= self.lr * (self.m[index] / (1 - 0.9**self.steps)) / (
                np.sqrt(self.v[index] / (1 - 0.999**self.steps)) + 1e-8
            )


def _load_a2_records(rounds: int) -> list[dict[str, Any]]:
    records = []
    for number in range(1, rounds + 1):
        path = DATASET_DIR / "a2" / f"round{number}_candidate_results.jsonl"
        with path.open(encoding="utf-8") as stream:
            records.extend(json.loads(line) for line in stream if line.strip())
    return records


def train_a2(rounds: int) -> None:
    records = _load_a2_records(rounds)
    x = np.asarray([row["feature"] for row in records], np.float32)
    value = np.asarray([float(row["delta_margin"]) / 10000.0 + 5.0 * float(row["delta_score"]) for row in records], np.float32)
    risk = np.asarray([float(row["risk"]) for row in records], np.float32)
    split = np.asarray([row["split"] for row in records])
    train_mask, validation_mask, test_mask = split == "train", split == "validation", split == "test"
    if not train_mask.any() or not validation_mask.any():
        raise RuntimeError(f"insufficient grouped split: {Counter(split)}")
    mean_vector = x[train_mask].mean(axis=0)
    scale = np.maximum(x[train_mask].std(axis=0), 1e-3)
    normalized = (x - mean_vector) / scale
    rng = np.random.default_rng(TRAIN_SEED + rounds)
    hidden_width = 24
    parameters = [
        rng.normal(0, math.sqrt(2 / x.shape[1]), (x.shape[1], hidden_width)).astype(np.float32),
        np.zeros(hidden_width, np.float32),
        rng.normal(0, math.sqrt(2 / hidden_width), (hidden_width, 2)).astype(np.float32),
        np.zeros(2, np.float32),
    ]
    initial = [value.copy() for value in parameters]
    optimizer = _Adam(parameters, 0.002)
    train_index = np.flatnonzero(train_mask)
    best_loss = float("inf")
    best = None
    bad = 0
    log_path = EXPERIMENT / "training_logs" / f"a2_round{rounds}.jsonl"
    for epoch in range(1, 201):
        order = rng.permutation(train_index)
        for start in range(0, len(order), 64):
            index = order[start : start + 64]
            xb, target_value, target_risk = normalized[index], value[index], risk[index]
            hidden = np.maximum(0.0, xb @ parameters[0] + parameters[1])
            output = hidden @ parameters[2] + parameters[3]
            value_error = np.clip(output[:, 0] - target_value, -5, 5)
            probability = 1 / (1 + np.exp(-np.clip(output[:, 1], -30, 30)))
            gradient = np.stack((2 * value_error, 0.5 * (probability - target_risk)), axis=1) / max(1, len(index))
            grad_w2 = hidden.T @ gradient
            grad_b2 = gradient.sum(axis=0)
            grad_hidden = (gradient @ parameters[2].T) * (hidden > 0)
            optimizer.update((xb.T @ grad_hidden, grad_hidden.sum(axis=0), grad_w2, grad_b2))
        hidden = np.maximum(0.0, normalized[validation_mask] @ parameters[0] + parameters[1])
        output = hidden @ parameters[2] + parameters[3]
        probability = 1 / (1 + np.exp(-np.clip(output[:, 1], -30, 30)))
        validation_loss = float(np.square(output[:, 0] - value[validation_mask]).mean() + 0.5 * np.square(probability - risk[validation_mask]).mean())
        row = {"epoch": epoch, "validation_loss": validation_loss, "optimizer_steps": optimizer.steps}
        append_jsonl(log_path, row)
        if epoch == 1 or epoch % 20 == 0:
            print(json.dumps(row), flush=True)
        if validation_loss < best_loss - 1e-6:
            best_loss, best, bad = validation_loss, [parameter.copy() for parameter in parameters], 0
        else:
            bad += 1
            if bad >= 25:
                break
    if best is None:
        raise RuntimeError("A2 did not produce a checkpoint")

    def predict(indices: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        hidden = np.maximum(0.0, normalized[indices] @ best[0] + best[1])
        output = hidden @ best[2] + best[3]
        return output[:, 0], 1 / (1 + np.exp(-np.clip(output[:, 1], -30, 30)))

    predicted_value, predicted_risk = predict(np.arange(len(records)))
    gates = []
    validation_prefixes = sorted({records[index]["prefix_id"] for index in np.flatnonzero(validation_mask)})
    for value_gate in (-0.05, 0.0, 0.05, 0.10, 0.20):
        for risk_gate in (0.20, 0.35, 0.50):
            realized = []
            interventions = 0
            for prefix in validation_prefixes:
                indices = [index for index, row in enumerate(records) if row["prefix_id"] == prefix and row["candidate_id"] != "KEEP_C0"]
                eligible = [index for index in indices if predicted_value[index] > value_gate and predicted_risk[index] < risk_gate]
                chosen = max(eligible, key=lambda index: predicted_value[index], default=None)
                realized.append(0.0 if chosen is None else value[chosen])
                interventions += int(chosen is not None)
            gates.append({"value_gate": value_gate, "risk_gate": risk_gate, "mean_realized_value": float(np.mean(realized)) if realized else 0.0, "interventions": interventions})
    selected_gate = max(gates, key=lambda row: (row["mean_realized_value"], -row["interventions"], row["value_gate"]))
    model_path = MODEL_DIR / f"a2_model_round{rounds}.npz"
    np.savez(model_path, mean=mean_vector, scale=scale, w1=best[0], b1=best[1], w2=best[2], b2=best[3])
    shutil.copy2(model_path, MODEL_DIR / "a2_model.npz")

    def metrics(mask: np.ndarray) -> dict[str, Any]:
        indices = np.flatnonzero(mask)
        pv, pr = predict(indices)
        nonkeep = np.asarray([records[index]["candidate_id"] != "KEEP_C0" for index in indices])
        return {
            "rows": len(indices),
            "prefixes": len({records[index]["prefix_id"] for index in indices}),
            "value_rmse": float(np.sqrt(np.square(pv - value[indices]).mean())),
            "risk_brier": float(np.square(pr - risk[indices]).mean()),
            "nonkeep_positive_rate": float((value[indices][nonkeep] > 0).mean()) if nonkeep.any() else 0.0,
        }

    metadata = {
        "created_at_utc": utc_now(),
        "rounds": rounds,
        "teacher_meaning": "observed paired outcomes for the finite executable job set",
        "architecture": f"{x.shape[1]}-24-2 ReLU value+risk MLP",
        "feature_names": list(a2_feature_names()),
        "unique_prefixes": len({row["prefix_id"] for row in records}),
        "unique_seeds": len({row["seed"] for row in records}),
        "families": sorted({row["family"] for row in records}),
        "rows": len(records),
        "optimizer_steps": optimizer.steps,
        "parameter_change_l2": float(math.sqrt(sum(float(np.square(a - b).sum()) for a, b in zip(best, initial, strict=True)))),
        "best_validation_loss": best_loss,
        "selected_gate": {"value_gate": selected_gate["value_gate"], "risk_gate": selected_gate["risk_gate"]},
        "gate_search": gates,
        "validation": metrics(validation_mask),
        "test": metrics(test_mask) if test_mask.any() else {"rows": 0},
        "model_sha256": sha256(model_path),
        "active_model_sha256": sha256(MODEL_DIR / "a2_model.npz"),
    }
    write_json(MODEL_DIR / f"a2_model_round{rounds}.json", metadata)
    write_json(MODEL_DIR / "a2_model.json", metadata)
    write_json(EXPERIMENT / f"offline_metrics_a2_round{rounds}.json", metadata)
    print(json.dumps({"rounds": rounds, "updates": optimizer.steps, "hash": metadata["model_sha256"]}), flush=True)


def _market_transition_labels(replay: Mapping[str, Any], step: int) -> dict[str, Any]:
    """Replay the market-relevant portion of one official transition.

    The complete tile simulation is deliberately avoided here: before the market,
    only DROP/PICKUP/PLACE can change the shed.  We still preserve actor order and
    the BUILD/DIG changes that can alter the meaning of a later PLACE on the same
    tile.  The result is checked against the recorded money, shed and market.
    """

    from kaggle_environments.envs.kaggriculture import kaggriculture as engine

    states = replay["steps"][step]
    actions = [replay["steps"][step + 1][player].get("action") or {} for player in range(2)]
    source_farms = states[0]["observation"]["farms"]
    farms = [
        {
            "money": float(farm["money"]),
            "hires_today": int(farm["hires_today"]),
            "unlocked_quadrants": list(farm["unlocked_quadrants"]),
            "farmer": list(farm["farmer"]),
            "hands": [list(position) for position in farm["hands"]],
        }
        for farm in source_farms
    ]
    market = deepcopy(states[0]["observation"]["market"])
    town = deepcopy(states[0]["observation"]["town"])
    privates = [deepcopy(states[player]["observation"]["private"]) for player in range(2)]
    requested = [{item: 0 for item in PRODUCTS} for _ in range(2)]
    executed = [{item: 0 for item in PRODUCTS} for _ in range(2)]
    impact = [{item: 0 for item in PRODUCTS} for _ in range(2)]
    revenue = [{item: 0.0 for item in PRODUCTS} for _ in range(2)]
    for player, action in enumerate(actions):
        orders = action.get("market", []) if isinstance(action, Mapping) else []
        for order in orders if isinstance(orders, list) else []:
            if isinstance(order, list) and len(order) >= 3 and order[0] == "SELL" and order[1] in PRODUCTS:
                try:
                    requested[player][str(order[1])] += max(0, int(order[2]))
                except (TypeError, ValueError):
                    pass
        farmer = action.get("farmer", ["PASS"]) if isinstance(action, Mapping) else ["PASS"]
        hands = action.get("hands", []) if isinstance(action, Mapping) else []
        hands = hands if isinstance(hands, list) else []
        tile_overrides: dict[tuple[int, int], Any] = {}
        for actor_index, unit_action in enumerate([farmer, *hands]):
            if not isinstance(unit_action, list) or not unit_action:
                continue
            if actor_index > len(farms[player]["hands"]):
                # The fixed engine treats actions for a nonexistent hand as a no-op.
                continue
            position = farms[player]["farmer"] if actor_index == 0 else farms[player]["hands"][actor_index - 1]
            x, y = int(position[0]), int(position[1])
            pos = (x, y)
            tile = tile_overrides.get(pos, source_farms[player]["tiles"][y][x])
            while len(privates[player]["inventories"]) <= actor_index:
                privates[player]["inventories"].append({})
            inventory = privates[player]["inventories"][actor_index]
            op = unit_action[0]
            if op == "DROP" and engine._is_shed_adjacent(pos, 10):
                for item, count in list(inventory.items()):
                    room = max(0, 100 - sum(privates[player]["shed"].values()))
                    deposited = min(max(0, int(count)), room)
                    if deposited:
                        privates[player]["shed"][item] = privates[player]["shed"].get(item, 0) + deposited
                    del inventory[item]
            elif op == "PICKUP" and engine._is_shed_adjacent(pos, 10) and len(unit_action) >= 2:
                try:
                    count = int(unit_action[2]) if len(unit_action) >= 3 else 1
                except (TypeError, ValueError):
                    count = 0
                item = unit_action[1]
                count = min(max(0, count), int(privates[player]["shed"].get(item, 0)))
                if count:
                    privates[player]["shed"][item] -= count
                    inventory[item] = inventory.get(item, 0) + count
            elif op == "PLACE" and len(unit_action) >= 2:
                item = unit_action[1]
                animal_place = (
                    item in engine.ANIMALS
                    and isinstance(tile, Mapping)
                    and tile.get("kind") == engine.ANIMALS[item]["structure"]
                    and "animal" not in tile
                )
                if animal_place:
                    if inventory.get(item, 0) > 0:
                        inventory[item] -= 1
                        if inventory[item] == 0:
                            del inventory[item]
                        tile_overrides[pos] = {"kind": "ANIMAL", "animal": item}
                elif engine._is_shed_adjacent(pos, 10):
                    try:
                        count = int(unit_action[2]) if len(unit_action) >= 3 else 1
                    except (TypeError, ValueError):
                        count = 0
                    room = max(0, 100 - sum(privates[player]["shed"].values()))
                    count = min(max(0, count), int(inventory.get(item, 0)), room)
                    if count:
                        inventory[item] -= count
                        if inventory[item] == 0:
                            del inventory[item]
                        privates[player]["shed"][item] = privates[player]["shed"].get(item, 0) + count
            elif op in {"BUILD_COOP", "BUILD_PASTURE"} and tile is None:
                tile_overrides[pos] = {"kind": op.removeprefix("BUILD_")}
            elif op == "DIG" and tile is not None and not (isinstance(tile, Mapping) and "animal" in tile):
                tile_overrides[pos] = None

    queues = []
    for action in actions:
        orders = action.get("market", []) if isinstance(action, Mapping) else []
        queues.append(list(orders)[:10] if isinstance(orders, list) else [])
    for slot in range(max((len(queue) for queue in queues), default=0)):
        order_states = [engine._parse_order(queue[slot]) if slot < len(queue) else None for queue in queues]
        for player, order_state in enumerate(order_states):
            if order_state is None:
                continue
            if order_state["type"] == "HIRE":
                engine._do_hire(farms[player], privates[player], 10, 1)
                order_states[player] = None
            elif order_state["type"] == "BUY_LAND":
                unlocked_extra = len(farms[player]["unlocked_quadrants"]) - 1
                if unlocked_extra < len(engine.LAND_ORDER):
                    cost = engine.LAND_PRICES[unlocked_extra]
                    if farms[player]["money"] >= cost:
                        farms[player]["money"] -= cost
                        farms[player]["unlocked_quadrants"].append(engine.LAND_ORDER[unlocked_extra])
                order_states[player] = None
        while True:
            quoted: list[tuple[str, str, int, dict[str, Any]] | None] = [None, None]
            for player, order_state in enumerate(order_states):
                if order_state is None or order_state.get("remaining", 0) <= 0:
                    continue
                op, item = order_state["type"], order_state["item"]
                if op == "SELL" and item in PRODUCTS:
                    quoted[player] = (op, item, engine.market_price(item, market["inventory"][item], market.get("params")), order_state)
                elif op == "BUY_PRODUCT" and item in ("WHEAT", "FERTILIZER"):
                    quoted[player] = (op, item, engine.market_price(item, market["inventory"][item] - 1, market.get("params")), order_state)
                elif op == "BUY_SEED" and item in engine.CROPS:
                    quoted[player] = (op, item, engine.CROPS[item]["seed"], order_state)
                elif op == "BUY_ANIMAL" and item in engine.ANIMALS:
                    quoted[player] = (op, item, engine.ANIMALS[item]["cost"], order_state)
                else:
                    order_states[player] = None
            if all(value is None for value in quoted):
                break
            committed = False
            for player, quote in enumerate(quoted):
                if quote is None:
                    continue
                op, item, price, order_state = quote
                ok = engine._commit_unit(op, item, price, farms[player], privates[player], market, 100)
                if ok:
                    order_state["remaining"] -= 1
                    committed = True
                    if op == "SELL":
                        executed[player][item] += 1
                        revenue[player][item] += price
                        impact[player][item] += int(price > 1)
                else:
                    order_states[player] = None
            if not committed:
                break
        engine._refresh_prices(market)

    expected_next = replay["steps"][step + 1]
    money_match = all(float(farms[player]["money"]) == float(expected_next[player]["observation"]["farms"][player]["money"]) for player in range(2))
    shed_match = True
    if (step + 1) % 24 != 0:
        shed_match = all(privates[player]["shed"] == expected_next[player]["observation"]["private"]["shed"] for player in range(2))
    if step % 4 == 0:
        for shop_name in town.get("unlocked_shops", []):
            products = engine.SHOPS[shop_name]
            multiplier = 2 if len(products) == 1 else 1
            for item in products:
                market["inventory"][item] -= multiplier
    if step % 24 == 0:
        for item in engine.TOWN_CENTER_PRODUCTS:
            market["inventory"][item] -= 1
    engine._refresh_prices(market)
    market_match = market == expected_next[0]["observation"]["market"]
    result = {
        "requested": requested,
        "executed": executed,
        "impact": impact,
        "revenue": revenue,
        "money_match": money_match,
        "shed_match": shed_match,
        "market_match": market_match,
    }
    if not (money_match and shed_match and market_match):
        result["validation_diff"] = {
            "simulated_money": [farm["money"] for farm in farms],
            "recorded_money": [expected_next[player]["observation"]["farms"][player]["money"] for player in range(2)],
            "simulated_shed": [private["shed"] for private in privates],
            "recorded_shed": [expected_next[player]["observation"]["private"]["shed"] for player in range(2)],
            "simulated_market": market,
            "recorded_market": expected_next[0]["observation"]["market"],
        }
    return result


def _build_b2_sequential_reference() -> None:
    source = json.loads((OLD / "source_manifest.json").read_text(encoding="utf-8"))
    assignments = json.loads((OLD / "split_manifest.json").read_text(encoding="utf-8"))["assignments"]
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in source["files"]:
        grouped[int(row["episode_id"])].append(row)
    target = DATASET_DIR / "b2"
    target.mkdir(parents=True, exist_ok=True)
    expected_rows = {
        split: len(np.load(OLD / "datasets/b" / f"x_{split}.npy", mmap_mode="r"))
        for split in ("train", "validation", "test")
    }
    array_names = ("requested", "executed", "impact", "revenue", "mask", "floor", "actionable")
    partial_paths = {f"{name}_{split}": target / f".{name}_{split}.partial.npy" for split in expected_rows for name in array_names}
    arrays = {
        key: np.lib.format.open_memmap(
            path,
            mode="w+",
            dtype=np.bool_ if key.startswith("mask_") else np.float32,
            shape=(expected_rows[key.rsplit("_", 1)[1]], len(PRODUCTS) * len(HORIZONS)),
        )
        for key, path in partial_paths.items()
    }
    cursors = {split: 0 for split in expected_rows}
    reconstruction = Counter()
    evidence = []
    engine_transition_samples = []
    for number, (episode_id, appearances) in enumerate(sorted(grouped.items()), 1):
        replay = json.loads((ROOT / appearances[0]["path"]).read_text(encoding="utf-8"))
        decision_count = len(replay["steps"]) - 1
        per_step = []
        for step in range(decision_count):
            next_actions = [replay["steps"][step + 1][player].get("action") or {} for player in range(2)]
            has_sell = any(
                isinstance(order, list) and order and order[0] == "SELL"
                for action in next_actions
                for order in (action.get("market", []) if isinstance(action, Mapping) else [])
            )
            if has_sell:
                row = _market_transition_labels(replay, step)
                reconstruction["simulated_sell_transitions"] += 1
            else:
                zero_int = [{item: 0 for item in PRODUCTS} for _ in range(2)]
                zero_float = [{item: 0.0 for item in PRODUCTS} for _ in range(2)]
                row = {
                    "requested": deepcopy(zero_int),
                    "executed": deepcopy(zero_int),
                    "impact": deepcopy(zero_int),
                    "revenue": zero_float,
                    "money_match": True,
                    "shed_match": True,
                    "market_match": True,
                }
            per_step.append(row)
            reconstruction["transitions"] += 1
            reconstruction["money_match"] += int(row["money_match"])
            reconstruction["shed_match_or_boundary"] += int(row["shed_match"])
            reconstruction["market_match"] += int(row["market_match"])
            if len(evidence) < 12:
                for player in range(2):
                    for item in PRODUCTS:
                        req, exe, imp = row["requested"][player][item], row["executed"][player][item], row["impact"][player][item]
                        if req != exe or exe != imp:
                            evidence.append({"episode_id": episode_id, "step": step, "seat": player, "item": item, "requested": req, "executed": exe, "market_impact": imp, "revenue": row["revenue"][player][item]})
                            break
                    if len(evidence) >= 12:
                        break
            if len(engine_transition_samples) < 200 and step % 24 != 23:
                engine_transition_samples.append({"episode_id": episode_id, "step": step, "money": row["money_match"], "shed": row["shed_match"], "market": row["market_match"]})
        split = assignments[str(episode_id)]
        sampled_steps = np.arange(0, decision_count, 2, dtype=np.int64)
        row_steps = np.repeat(sampled_steps, 2)
        opponents = np.tile(np.asarray([1, 0], np.int64), len(sampled_steps))
        episode_targets = {name: np.zeros((len(row_steps), len(PRODUCTS) * len(HORIZONS)), np.float32) for name in ("requested", "executed", "impact", "revenue")}
        episode_mask = np.zeros((len(row_steps), len(PRODUCTS) * len(HORIZONS)), np.bool_)
        raw = {
            name: np.asarray(
                [[[per_step[time][name][player][item] for item in PRODUCTS] for player in range(2)] for time in range(decision_count)],
                dtype=np.float32,
            )
            for name in episode_targets
        }
        prefixes = {
            name: np.concatenate([np.zeros((1, 2, len(PRODUCTS)), np.float32), np.cumsum(values, axis=0)], axis=0)
            for name, values in raw.items()
        }
        for column, (item_index, horizon) in enumerate((item_index, horizon) for item_index in range(len(PRODUCTS)) for horizon in HORIZONS):
            valid = row_steps + horizon <= decision_count
            episode_mask[:, column] = valid
            end = np.minimum(decision_count, row_steps + horizon)
            for name in episode_targets:
                values = prefixes[name][end, opponents, item_index] - prefixes[name][row_steps, opponents, item_index]
                episode_targets[name][:, column] = np.where(valid, values, 0.0)
        floor_by_item = []
        actionable_by_item = []
        for sampled_step in sampled_steps:
            for focal in range(2):
                focal_obs = replay["steps"][int(sampled_step)][focal]["observation"]
                floor_by_item.append([float(focal_obs["market"]["prices"].get(item, 1) <= 1) for item in PRODUCTS])
                actionable_by_item.append([float(focal_obs["private"]["shed"].get(item, 0) > 0) for item in PRODUCTS])
        episode_floor = np.repeat(np.asarray(floor_by_item, np.float32), len(HORIZONS), axis=1)
        episode_actionable = np.repeat(np.asarray(actionable_by_item, np.float32), len(HORIZONS), axis=1)
        start = cursors[split]
        stop = start + len(row_steps)
        if stop > expected_rows[split]:
            raise RuntimeError(f"B2 label overflow for {split}: {stop}>{expected_rows[split]}")
        for name, values in episode_targets.items():
            arrays[f"{name}_{split}"][start:stop] = values
        arrays[f"mask_{split}"][start:stop] = episode_mask
        arrays[f"floor_{split}"][start:stop] = episode_floor
        arrays[f"actionable_{split}"][start:stop] = episode_actionable
        cursors[split] = stop
        if number % 25 == 0:
            print(f"B2 labels {number}/{len(grouped)}", flush=True)
    shapes = {}
    hashes = {}
    for split, count in cursors.items():
        if count != expected_rows[split]:
            raise RuntimeError(f"B2 label row mismatch for {split}: {count}!={expected_rows[split]}")
    for array in arrays.values():
        array.flush()
    del arrays
    for name, partial in partial_paths.items():
        path = target / f"{name}.npy"
        partial.replace(path)
        array = np.load(path, mmap_mode="r")
        shapes[name] = list(array.shape)
        hashes[name] = sha256(path)
    schema = {
        "created_at_utc": utc_now(),
        "products": list(PRODUCTS),
        "horizons": list(HORIZONS),
        "labels": {
            "requested": "sum of submitted SELL quantities, including quantities beyond inventory or the ten-order execution cap",
            "executed": "units removed from the seller shed by fixed-engine _commit_unit",
            "impact": "executed units that increased market inventory; $1-floor executions contribute zero",
            "revenue": "cash credited by successful SELL commits",
        },
        "transition_order": "both players' unit actions, per-slot lockstep market, town consumption, day boundary",
        "censoring": "mask=0 when the complete 1/4/24-decision horizon does not exist",
        "runtime_inputs": "public observation plus focal private/self history only; opponent private is label reconstruction only",
    }
    write_json(EXPERIMENT / "b2_label_schema.json", schema)
    manifest = {
        "created_at_utc": utc_now(),
        "unique_episodes": len(grouped),
        "stored_states": len(grouped) * 720,
        "decisions": len(grouped) * 719,
        "shapes": shapes,
        "hashes": hashes,
        "split_source": str((OLD / "split_manifest.json").relative_to(ROOT)),
        "schema": str((EXPERIMENT / "b2_label_schema.json").relative_to(ROOT)),
    }
    write_json(target / "dataset_manifest.json", manifest)
    reconstruction_result = {
        "created_at_utc": utc_now(),
        "counts": dict(reconstruction),
        "money_match_rate": reconstruction["money_match"] / max(1, reconstruction["transitions"]),
        "market_match_rate": reconstruction["market_match"] / max(1, reconstruction["transitions"]),
        "examples": evidence,
        "sampled_transition_checks": engine_transition_samples,
        "sampled_transition_exact_rate": sum(row["money"] and row["shed"] and row["market"] for row in engine_transition_samples) / max(1, len(engine_transition_samples)),
    }
    write_json(EXPERIMENT / "b_label_reconstruction.json", reconstruction_result)
    roundtrip_path = EXPERIMENT / "action_roundtrip.json"
    if roundtrip_path.is_file():
        roundtrip = json.loads(roundtrip_path.read_text(encoding="utf-8"))
        roundtrip["sampled_fixed_engine_transition_check"] = reconstruction_result["sampled_transition_exact_rate"]
        write_json(roundtrip_path, roundtrip)
    print(json.dumps({"episodes": len(grouped), "transition_match": reconstruction_result["market_match_rate"]}), flush=True)


def _build_b2_episode(task: Mapping[str, Any]) -> dict[str, Any]:
    replay = json.loads((ROOT / str(task["path"])).read_text(encoding="utf-8"))
    episode_id = int(task["episode_id"])
    decision_count = len(replay["steps"]) - 1
    width = len(PRODUCTS) * len(HORIZONS)
    raw = {
        name: np.zeros((decision_count, 2, len(PRODUCTS)), np.float32)
        for name in ("requested", "executed", "impact", "revenue")
    }
    counts = Counter()
    evidence = []
    samples = []
    mismatches = []
    transition_exact = np.ones(decision_count, np.bool_)
    for step in range(decision_count):
        next_actions = [replay["steps"][step + 1][player].get("action") or {} for player in range(2)]
        has_sell = any(
            isinstance(order, list) and order and order[0] == "SELL"
            for action in next_actions
            for order in (action.get("market", []) if isinstance(action, Mapping) else [])
        )
        if has_sell:
            row = _market_transition_labels(replay, step)
            counts["simulated_sell_transitions"] += 1
            for name, values in raw.items():
                for player in range(2):
                    values[step, player] = [row[name][player][item] for item in PRODUCTS]
            if len(evidence) < 4:
                for player in range(2):
                    for item in PRODUCTS:
                        requested = row["requested"][player][item]
                        executed = row["executed"][player][item]
                        impact = row["impact"][player][item]
                        if requested != executed or executed != impact:
                            evidence.append(
                                {
                                    "episode_id": episode_id,
                                    "step": step,
                                    "seat": player,
                                    "item": item,
                                    "requested": requested,
                                    "executed": executed,
                                    "market_impact": impact,
                                    "revenue": row["revenue"][player][item],
                                }
                            )
                            break
        else:
            row = {"money_match": True, "shed_match": True, "market_match": True}
        counts["transitions"] += 1
        counts["money_match"] += int(row["money_match"])
        counts["shed_match_or_boundary"] += int(row["shed_match"])
        counts["market_match"] += int(row["market_match"])
        if not (row["money_match"] and row["shed_match"] and row["market_match"]) and len(mismatches) < 12:
            transition_exact[step] = False
            mismatches.append(
                {
                    "episode_id": episode_id,
                    "step": step,
                    "money_match": row["money_match"],
                    "shed_match": row["shed_match"],
                    "market_match": row["market_match"],
                    "actions": next_actions,
                    "validation_diff": row.get("validation_diff"),
                }
            )
        elif not (row["money_match"] and row["shed_match"] and row["market_match"]):
            transition_exact[step] = False
        if has_sell and len(samples) < 2 and step % 24 != 23:
            samples.append(
                {
                    "episode_id": episode_id,
                    "step": step,
                    "money": row["money_match"],
                    "shed": row["shed_match"],
                    "market": row["market_match"],
                }
            )

    sampled_steps = np.arange(0, decision_count, 2, dtype=np.int64)
    row_steps = np.repeat(sampled_steps, 2)
    opponents = np.tile(np.asarray([1, 0], np.int64), len(sampled_steps))
    outputs = {
        name: np.zeros((len(row_steps), width), np.float32)
        for name in ("requested", "executed", "impact", "revenue")
    }
    mask = np.zeros((len(row_steps), width), np.bool_)
    prefixes = {
        name: np.concatenate([np.zeros((1, 2, len(PRODUCTS)), np.float32), np.cumsum(values, axis=0)], axis=0)
        for name, values in raw.items()
    }
    invalid_prefix = np.concatenate([[0], np.cumsum(~transition_exact)])
    for column, (item_index, horizon) in enumerate(
        (item_index, horizon) for item_index in range(len(PRODUCTS)) for horizon in HORIZONS
    ):
        valid = row_steps + horizon <= decision_count
        valid &= invalid_prefix[np.minimum(decision_count, row_steps + horizon)] == invalid_prefix[row_steps]
        mask[:, column] = valid
        end = np.minimum(decision_count, row_steps + horizon)
        for name in outputs:
            values = prefixes[name][end, opponents, item_index] - prefixes[name][row_steps, opponents, item_index]
            outputs[name][:, column] = np.where(valid, values, 0.0)
    floor_by_item = []
    actionable_by_item = []
    for sampled_step in sampled_steps:
        for focal in range(2):
            focal_obs = replay["steps"][int(sampled_step)][focal]["observation"]
            floor_by_item.append([float(focal_obs["market"]["prices"].get(item, 1) <= 1) for item in PRODUCTS])
            actionable_by_item.append([float(focal_obs["private"]["shed"].get(item, 0) > 0) for item in PRODUCTS])
    outputs["mask"] = mask
    outputs["floor"] = np.repeat(np.asarray(floor_by_item, np.float32), len(HORIZONS), axis=1)
    outputs["actionable"] = np.repeat(np.asarray(actionable_by_item, np.float32), len(HORIZONS), axis=1)
    return {
        "episode_id": episode_id,
        "split": str(task["split"]),
        "start": int(task["start"]),
        "rows": len(row_steps),
        "outputs": outputs,
        "counts": dict(counts),
        "evidence": evidence,
        "samples": samples,
        "mismatches": mismatches,
    }


def build_b2() -> None:
    source = json.loads((OLD / "source_manifest.json").read_text(encoding="utf-8"))
    assignments = json.loads((OLD / "split_manifest.json").read_text(encoding="utf-8"))["assignments"]
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in source["files"]:
        grouped[int(row["episode_id"])].append(row)
    target = DATASET_DIR / "b2"
    target.mkdir(parents=True, exist_ok=True)
    expected_rows = {
        split: len(np.load(OLD / "datasets/b" / f"x_{split}.npy", mmap_mode="r"))
        for split in ("train", "validation", "test")
    }
    array_names = ("requested", "executed", "impact", "revenue", "mask", "floor", "actionable")
    partial_paths = {
        f"{name}_{split}": target / f".{name}_{split}.partial.npy"
        for split in expected_rows
        for name in array_names
    }
    arrays = {
        key: np.lib.format.open_memmap(
            path,
            mode="w+",
            dtype=np.bool_ if key.startswith("mask_") else np.float32,
            shape=(expected_rows[key.rsplit("_", 1)[1]], len(PRODUCTS) * len(HORIZONS)),
        )
        for key, path in partial_paths.items()
    }
    offsets = {split: 0 for split in expected_rows}
    tasks = []
    for episode_id, appearances in sorted(grouped.items()):
        split = assignments[str(episode_id)]
        stored_states = int(appearances[0].get("step_count", 720))
        rows = 2 * ((stored_states - 1 + 1) // 2)
        tasks.append(
            {
                "episode_id": episode_id,
                "path": appearances[0]["path"],
                "split": split,
                "start": offsets[split],
                "expected_rows": rows,
            }
        )
        offsets[split] += rows
    if offsets != expected_rows:
        raise RuntimeError(f"B2 expected row layout differs from old B features: {offsets} != {expected_rows}")

    reconstruction = Counter()
    evidence = []
    engine_transition_samples = []
    mismatches = []
    with ProcessPoolExecutor(max_workers=min(8, len(tasks))) as executor:
        futures = [executor.submit(_build_b2_episode, task) for task in tasks]
        for number, future in enumerate(as_completed(futures), 1):
            result = future.result()
            split = result["split"]
            start = result["start"]
            stop = start + result["rows"]
            if result["rows"] != next(task["expected_rows"] for task in tasks if task["episode_id"] == result["episode_id"]):
                raise RuntimeError(f"B2 row count changed for episode {result['episode_id']}")
            for name, values in result["outputs"].items():
                arrays[f"{name}_{split}"][start:stop] = values
            reconstruction.update(result["counts"])
            evidence.extend(result["evidence"][: max(0, 12 - len(evidence))])
            engine_transition_samples.extend(result["samples"][: max(0, 200 - len(engine_transition_samples))])
            mismatches.extend(result["mismatches"][: max(0, 100 - len(mismatches))])
            if number % 10 == 0 or number == len(tasks):
                print(f"B2 labels {number}/{len(tasks)}", flush=True)

    shapes = {}
    hashes = {}
    for array in arrays.values():
        array.flush()
    del array
    del arrays
    for name, partial in partial_paths.items():
        path = target / f"{name}.npy"
        partial.replace(path)
        loaded = np.load(path, mmap_mode="r")
        shapes[name] = list(loaded.shape)
        hashes[name] = sha256(path)
        del loaded
    schema = {
        "created_at_utc": utc_now(),
        "products": list(PRODUCTS),
        "horizons": list(HORIZONS),
        "labels": {
            "requested": "sum of submitted SELL quantities, including quantities beyond inventory or the ten-order execution cap",
            "executed": "units removed from the seller shed by fixed-engine market commits",
            "impact": "executed units that increased market inventory; $1-floor executions contribute zero",
            "revenue": "cash credited by successful SELL commits",
        },
        "transition_order": "both players' actor-order unit actions, per-slot lockstep market, town consumption, day boundary",
        "censoring": "mask=0 when the complete 1/4/24-decision horizon does not exist",
        "reconstruction_mask": "mask=0 when any transition in the horizon fails recorded-next-state validation",
        "runtime_inputs": "public observation plus focal private/self history only; opponent private is label reconstruction only",
    }
    write_json(EXPERIMENT / "b2_label_schema.json", schema)
    manifest = {
        "created_at_utc": utc_now(),
        "unique_episodes": len(grouped),
        "stored_states": sum(int(values[0].get("step_count", 720)) for values in grouped.values()),
        "decisions": reconstruction["transitions"],
        "shapes": shapes,
        "hashes": hashes,
        "split_source": str((OLD / "split_manifest.json").relative_to(ROOT)),
        "schema": str((EXPERIMENT / "b2_label_schema.json").relative_to(ROOT)),
        "row_order": "episode_id ascending, then even step ascending, then focal seat 0/1; identical to frozen B1 features",
    }
    write_json(target / "dataset_manifest.json", manifest)
    reconstruction_result = {
        "created_at_utc": utc_now(),
        "counts": dict(reconstruction),
        "money_match_rate": reconstruction["money_match"] / max(1, reconstruction["transitions"]),
        "shed_match_rate_or_boundary": reconstruction["shed_match_or_boundary"] / max(1, reconstruction["transitions"]),
        "market_match_rate": reconstruction["market_match"] / max(1, reconstruction["transitions"]),
        "examples": evidence,
        "mismatches": mismatches,
        "sampled_transition_checks": engine_transition_samples,
        "sampled_transition_exact_rate": sum(row["money"] and row["shed"] and row["market"] for row in engine_transition_samples)
        / max(1, len(engine_transition_samples)),
        "implementation": "market-relevant exact replay with recorded next-state validation; no requested-to-executed relabeling",
        "unreconstructible_policy": "Any horizon crossing a money/shed/market mismatch is masked from every loss and metric; mismatch actions and diffs are retained above.",
    }
    write_json(EXPERIMENT / "b_label_reconstruction.json", reconstruction_result)
    roundtrip_path = EXPERIMENT / "action_roundtrip.json"
    if roundtrip_path.is_file():
        roundtrip = json.loads(roundtrip_path.read_text(encoding="utf-8"))
        roundtrip["sampled_fixed_engine_transition_check"] = reconstruction_result["sampled_transition_exact_rate"]
        write_json(roundtrip_path, roundtrip)
    if min(
        reconstruction_result["money_match_rate"],
        reconstruction_result["shed_match_rate_or_boundary"],
        reconstruction_result["market_match_rate"],
    ) < 0.999:
        raise RuntimeError(f"B2 reconstructed transition mismatch rate is too high: {reconstruction_result}")
    print(json.dumps({"episodes": len(grouped), "transition_match": reconstruction_result["market_match_rate"]}), flush=True)


def _moments(x: np.ndarray, chunk: int = 65536) -> tuple[np.ndarray, np.ndarray]:
    total = np.zeros(x.shape[1], np.float64)
    square = np.zeros(x.shape[1], np.float64)
    count = 0
    for start in range(0, len(x), chunk):
        values = np.asarray(x[start : start + chunk], np.float64)
        total += values.sum(axis=0)
        square += np.square(values).sum(axis=0)
        count += len(values)
    center = total / count
    variance = np.maximum(square / count - center * center, 1e-6)
    return center.astype(np.float32), np.sqrt(variance).astype(np.float32)


def _b2_predict(parameters: Sequence[np.ndarray], center: np.ndarray, scale: np.ndarray, x: np.ndarray, chunk: int = 16384) -> np.ndarray:
    output = []
    for start in range(0, len(x), chunk):
        values = (np.asarray(x[start : start + chunk], np.float32) - center) / scale
        hidden = np.maximum(0.0, values @ parameters[0] + parameters[1])
        output.append(hidden @ parameters[2] + parameters[3])
    return np.concatenate(output)


def _masked_mean(values: np.ndarray, mask: np.ndarray) -> float:
    return float(values[mask].mean()) if mask.any() else 0.0


def _reliability(y: np.ndarray, probability: np.ndarray, mask: np.ndarray) -> list[dict[str, Any]]:
    result = []
    for lower in np.linspace(0, 0.9, 10):
        selected = mask & (probability >= lower) & (probability < lower + 0.1)
        result.append({"lower": float(lower), "count": int(selected.sum()), "predicted": _masked_mean(probability, selected), "observed": _masked_mean(y, selected)})
    return result


def _b2_metrics(
    impact: np.ndarray,
    mask: np.ndarray,
    outputs: np.ndarray,
    floor: np.ndarray,
    actionable: np.ndarray,
) -> dict[str, Any]:
    width = impact.shape[1]
    event = impact > 0
    probability = 1 / (1 + np.exp(-np.clip(outputs[:, :width], -30, 30)))
    quantity = np.maximum(0.0, np.expm1(np.clip(outputs[:, width : 2 * width], 0, 8)))
    by_target = {}
    for offset, (item, horizon) in enumerate((item, horizon) for item in PRODUCTS for horizon in HORIZONS):
        valid = mask[:, offset]
        positive = valid & event[:, offset]
        by_target[f"{item}:{horizon}"] = {
            "rows": int(valid.sum()),
            "positive_rate": _masked_mean(event[:, offset].astype(float), valid),
            "brier": _masked_mean(np.square(probability[:, offset] - event[:, offset]), valid),
            "quantity_mae": _masked_mean(np.abs(quantity[:, offset] - impact[:, offset]), valid),
            "nonzero_quantity_mae": _masked_mean(np.abs(quantity[:, offset] - impact[:, offset]), positive),
            "floor_brier": _masked_mean(np.square(probability[:, offset] - event[:, offset]), valid & (floor[:, offset] > 0)),
            "nonfloor_brier": _masked_mean(np.square(probability[:, offset] - event[:, offset]), valid & (floor[:, offset] == 0)),
            "actionable_brier": _masked_mean(np.square(probability[:, offset] - event[:, offset]), valid & (actionable[:, offset] > 0)),
        }
    return {
        "rows": len(impact),
        "valid_cells": int(mask.sum()),
        "brier": _masked_mean(np.square(probability - event), mask),
        "quantity_mae": _masked_mean(np.abs(quantity - impact), mask),
        "nonzero_quantity_mae": _masked_mean(np.abs(quantity - impact), mask & event),
        "reliability": _reliability(event.astype(float), probability, mask),
        "by_target": by_target,
    }


def _fit_b2_seed(seed: int, arrays: Mapping[str, np.ndarray], center: np.ndarray, scale: np.ndarray) -> dict[str, Any]:
    x_train = arrays["x_train"]
    impact_train = arrays["impact_train"]
    mask_train = arrays["mask_train"]
    executed_train = arrays["executed_train"]
    requested_train = arrays["requested_train"]
    width = impact_train.shape[1]
    rng = np.random.default_rng(seed)
    hidden_width = 32
    parameters = [
        rng.normal(0, math.sqrt(2 / x_train.shape[1]), (x_train.shape[1], hidden_width)).astype(np.float32),
        np.zeros(hidden_width, np.float32),
        rng.normal(0, math.sqrt(2 / hidden_width), (hidden_width, width * 4)).astype(np.float32),
        np.zeros(width * 4, np.float32),
    ]
    initial = [value.copy() for value in parameters]
    optimizer = _Adam(parameters, 0.0015)
    valid_count = np.maximum(np.asarray(mask_train).sum(axis=0), 1)
    positive = ((np.asarray(impact_train) > 0) & np.asarray(mask_train)).sum(axis=0)
    pos_weight = np.minimum(20.0, (valid_count - positive) / np.maximum(positive, 1)).astype(np.float32)
    best_loss, best, bad = float("inf"), None, 0
    log_path = EXPERIMENT / "training_logs" / f"b2_seed{seed}.jsonl"
    for epoch in range(1, 7):
        order = rng.permutation(len(x_train))
        total = 0.0
        for start in range(0, len(order), 2048):
            index = order[start : start + 2048]
            x = (np.asarray(x_train[index], np.float32) - center) / scale
            impact = np.asarray(impact_train[index], np.float32)
            executed = np.asarray(executed_train[index], np.float32)
            requested = np.asarray(requested_train[index], np.float32)
            mask = np.asarray(mask_train[index], np.float32)
            event = (impact > 0).astype(np.float32)
            hidden = np.maximum(0.0, x @ parameters[0] + parameters[1])
            output = hidden @ parameters[2] + parameters[3]
            logits = output[:, :width]
            probability = 1 / (1 + np.exp(-np.clip(logits, -30, 30)))
            weight = 1 + event * (pos_weight - 1)
            denom = max(1.0, float(mask.sum()))
            errors = [
                output[:, width : 2 * width] - np.log1p(impact),
                output[:, 2 * width : 3 * width] - np.log1p(executed),
                output[:, 3 * width :] - np.log1p(requested),
            ]
            bce = -(event * np.log(np.maximum(probability, 1e-8)) + (1 - event) * np.log(np.maximum(1 - probability, 1e-8)))
            total += float(((weight * bce + 0.15 * np.square(errors[0]) + 0.05 * np.square(errors[1]) + 0.03 * np.square(errors[2])) * mask).sum() / denom) * len(index)
            gradients = [weight * (probability - event), 0.30 * errors[0], 0.10 * errors[1], 0.06 * errors[2]]
            gradient = np.concatenate([value * mask / denom for value in gradients], axis=1)
            grad_w2 = hidden.T @ gradient
            grad_b2 = gradient.sum(axis=0)
            grad_hidden = (gradient @ parameters[2].T) * (hidden > 0)
            optimizer.update((x.T @ grad_hidden, grad_hidden.sum(axis=0), grad_w2, grad_b2))
        validation_output = _b2_predict(parameters, center, scale, arrays["x_validation"])
        validation_event = np.asarray(arrays["impact_validation"]) > 0
        validation_mask = np.asarray(arrays["mask_validation"])
        probability = 1 / (1 + np.exp(-np.clip(validation_output[:, :width], -30, 30)))
        quantity_error = validation_output[:, width : 2 * width] - np.log1p(np.asarray(arrays["impact_validation"]))
        validation_loss = _masked_mean(np.square(probability - validation_event) + 0.1 * np.square(quantity_error), validation_mask)
        log = {"epoch": epoch, "train_loss": total / len(x_train), "validation_selection_loss": validation_loss, "optimizer_steps": optimizer.steps}
        append_jsonl(log_path, log)
        print(json.dumps({"seed": seed, **log}), flush=True)
        if validation_loss < best_loss - 1e-6:
            best_loss, best, bad = validation_loss, [value.copy() for value in parameters], 0
        else:
            bad += 1
            if bad >= 2:
                break
    if best is None:
        raise RuntimeError("B2 failed to checkpoint")
    path = MODEL_DIR / f"b2_model_seed{seed}.npz"
    classes = [f"impact_event:{item}:{horizon}" for item in PRODUCTS for horizon in HORIZONS]
    classes += [f"impact_log_quantity:{item}:{horizon}" for item in PRODUCTS for horizon in HORIZONS]
    classes += [f"executed_log_quantity:{item}:{horizon}" for item in PRODUCTS for horizon in HORIZONS]
    classes += [f"requested_log_quantity:{item}:{horizon}" for item in PRODUCTS for horizon in HORIZONS]
    np.savez(path, mean=center, scale=scale, w1=best[0], b1=best[1], w2=best[2], b2=best[3], classes=np.asarray(classes))
    return {
        "seed": seed,
        "path": path,
        "sha256": sha256(path),
        "best_validation_loss": best_loss,
        "optimizer_steps": optimizer.steps,
        "parameter_change_l2": float(math.sqrt(sum(float(np.square(a - b).sum()) for a, b in zip(best, initial, strict=True)))),
        "parameters": best,
    }


def train_b2() -> None:
    old_b = OLD / "datasets/b"
    target = DATASET_DIR / "b2"
    arrays: dict[str, np.ndarray] = {}
    for split in ("train", "validation", "test"):
        arrays[f"x_{split}"] = np.load(old_b / f"x_{split}.npy", mmap_mode="r")
        for name in ("requested", "executed", "impact", "revenue", "mask", "floor", "actionable"):
            arrays[f"{name}_{split}"] = np.load(target / f"{name}_{split}.npy", mmap_mode="r")
        if len(arrays[f"x_{split}"]) != len(arrays[f"impact_{split}"]):
            raise RuntimeError(f"B2 feature/label row mismatch for {split}")
    center, scale = _moments(arrays["x_train"])
    fits = [_fit_b2_seed(seed, arrays, center, scale) for seed in (TRAIN_SEED, TRAIN_SEED + 1)]
    selected = min(fits, key=lambda row: row["best_validation_loss"])
    shutil.copy2(selected["path"], MODEL_DIR / "b2_model.npz")
    width = len(PRODUCTS) * len(HORIZONS)
    hours = np.rint(np.asarray(arrays["x_train"][:, list(state_feature_names()).index("hour")]) * 23).astype(int)
    simple: dict[str, Any] = {"format": "round2-impact-hour-frequency-v1", "global": {}, "by_hour": {str(hour): {} for hour in range(24)}}
    impact_train = np.asarray(arrays["impact_train"])
    mask_train = np.asarray(arrays["mask_train"])
    for offset, (item, horizon) in enumerate((item, horizon) for item in PRODUCTS for horizon in HORIZONS):
        simple["global"].setdefault(item, {})
        valid = mask_train[:, offset]
        global_row = {"probability": _masked_mean((impact_train[:, offset] > 0).astype(float), valid), "expected_quantity": _masked_mean(impact_train[:, offset], valid)}
        simple["global"][item][str(horizon)] = global_row
        for hour in range(24):
            simple["by_hour"][str(hour)].setdefault(item, {})
            selected_rows = valid & (hours == hour)
            simple["by_hour"][str(hour)][item][str(horizon)] = {
                "probability": _masked_mean((impact_train[:, offset] > 0).astype(float), selected_rows) if selected_rows.any() else global_row["probability"],
                "expected_quantity": _masked_mean(impact_train[:, offset], selected_rows) if selected_rows.any() else global_row["expected_quantity"],
            }
    write_json(MODEL_DIR / "b2_simple.json", simple)

    def baseline_outputs(split: str, mode: str) -> np.ndarray:
        x = arrays[f"x_{split}"]
        output = np.zeros((len(x), width * 4), np.float32)
        if mode == "zero":
            output[:, :width] = -30
            return output
        from scripts.learning_next_pipeline import b_baseline_outputs

        old_output = b_baseline_outputs(x, simple, "frequency" if mode == "frequency" else "production")
        output[:, : 2 * width] = old_output
        return output

    metrics: dict[str, Any] = {
        "created_at_utc": utc_now(),
        "teacher_meaning": "fixed-engine reconstructed opponent market-impact supply",
        "architecture": f"233-32-{width * 4} ReLU multi-head MLP",
        "selection": {key: value for key, value in selected.items() if key not in {"parameters", "path"}},
        "initializations": [{key: value for key, value in row.items() if key not in {"parameters", "path"}} for row in fits],
        "train_rows": len(arrays["x_train"]),
        "validation_rows": len(arrays["x_validation"]),
        "test_rows": len(arrays["x_test"]),
        "active_model_sha256": sha256(MODEL_DIR / "b2_model.npz"),
        "runtime_outputs": "first 27 impact-event logits and next 27 impact log-quantities; requested/executed heads are auxiliary",
    }
    for split in ("validation", "test"):
        output = _b2_predict(selected["parameters"], center, scale, arrays[f"x_{split}"])
        metrics[split] = _b2_metrics(
            np.asarray(arrays[f"impact_{split}"]),
            np.asarray(arrays[f"mask_{split}"]),
            output,
            np.asarray(arrays[f"floor_{split}"]),
            np.asarray(arrays[f"actionable_{split}"]),
        )
        metrics.setdefault("baselines", {})[split] = {
            mode: _b2_metrics(
                np.asarray(arrays[f"impact_{split}"]),
                np.asarray(arrays[f"mask_{split}"]),
                baseline_outputs(split, mode),
                np.asarray(arrays[f"floor_{split}"]),
                np.asarray(arrays[f"actionable_{split}"]),
            )
            for mode in ("zero", "frequency", "production")
        }
    write_json(MODEL_DIR / "b2_model.json", metrics)
    write_json(EXPERIMENT / "offline_metrics_b2.json", metrics)
    print(json.dumps({"selected_seed": selected["seed"], "updates": selected["optimizer_steps"], "hash": metrics["active_model_sha256"]}), flush=True)


def b_opportunity_headroom() -> None:
    runtimes = prepare_runtimes()
    b1_module = _load_module(runtimes["b1"], "headroom_b1")
    simple_module = _load_module(runtimes["b_simple"], "headroom_simple")
    opportunities = []
    for replay_path in sorted((OLD / "b_development_evaluation/replays/c0").glob("*/*.json.gz")):
        replay = _read_gzip_json(replay_path)
        name = replay_path.parent.name
        seat = int(replay_path.stem.split("_seat_")[-1].split(".")[0])
        histories = {"b1": MarketHistory(), "simple": MarketHistory()}
        previous = {"b1": None, "simple": None}
        for step in range(len(replay["steps"]) - 1):
            observation = _restore_observation(replay["steps"][step], seat, step)
            control = replay["steps"][step + 1][seat].get("action") or {}
            for key in histories:
                histories[key].update(observation, previous[key])
                previous[key] = control.get("market") or []
            b1_prediction = b1_module._predict(observation, histories["b1"])
            risk = {
                item: sum(b1_prediction[(item, horizon)][0] * b1_prediction[(item, horizon)][1] / horizon for horizon in HORIZONS)
                for item in PRODUCTS
            }
            candidates = b1_module._sell_blocks(control.get("market") or [], risk)
            if len(candidates) < 2:
                continue
            simple_prediction = simple_module._predict(observation, histories["simple"])
            selector_scores = {
                "b1": [b1_module._score_sell_candidate(observation, candidate, b1_prediction) for candidate in candidates],
                "simple": [simple_module._score_sell_candidate(observation, candidate, simple_prediction) for candidate in candidates],
            }
            true_revenue = []
            original_action = replay["steps"][step + 1][seat]["action"]
            for candidate in candidates:
                modified = deepcopy(original_action)
                modified["market"] = candidate
                replay["steps"][step + 1][seat]["action"] = modified
                labels = _market_transition_labels(replay, step)
                true_revenue.append(sum(labels["revenue"][seat].values()))
            replay["steps"][step + 1][seat]["action"] = original_action
            choices = {
                "c0": 0,
                "simple": max(range(len(candidates)), key=lambda index: (selector_scores["simple"][index], -index)),
                "b1": max(range(len(candidates)), key=lambda index: (selector_scores["b1"][index], -index)),
                "hindsight": max(range(len(candidates)), key=lambda index: (true_revenue[index], -index)),
            }
            opportunities.append(
                {
                    "replay": str(replay_path.relative_to(ROOT)),
                    "family": name,
                    "step": step,
                    "seat": seat,
                    "candidate_count": len(candidates),
                    "true_immediate_revenue": true_revenue,
                    "choices": choices,
                    "hindsight_gain_vs_c0": true_revenue[choices["hindsight"]] - true_revenue[0],
                    "b1_gain_vs_c0": true_revenue[choices["b1"]] - true_revenue[0],
                    "simple_gain_vs_c0": true_revenue[choices["simple"]] - true_revenue[0],
                    "scope": "same-turn, same candidate set; not a game-level counterfactual",
                }
            )
    result = {
        "created_at_utc": utc_now(),
        "source": "frozen B1 development C0 states",
        "opportunities": len(opportunities),
        "candidate_generator": "frozen B1 contiguous SELL-block reorder",
        "hindsight_positive_opportunities": sum(row["hindsight_gain_vs_c0"] > 0 for row in opportunities),
        "total_hindsight_immediate_revenue_headroom": sum(row["hindsight_gain_vs_c0"] for row in opportunities),
        "total_b1_realized_immediate_gain": sum(row["b1_gain_vs_c0"] for row in opportunities),
        "total_simple_realized_immediate_gain": sum(row["simple_gain_vs_c0"] for row in opportunities),
        "interpretation": "hindsight is a local upper bound for this frozen candidate set, not a game-wide or deployable oracle",
        "rows": opportunities,
    }
    write_json(EXPERIMENT / "b_opportunity_headroom.json", result)
    print(json.dumps({key: result[key] for key in ("opportunities", "hindsight_positive_opportunities", "total_hindsight_immediate_revenue_headroom")}), flush=True)


def train_bc2_probe() -> None:
    """Overfit a lossless full-joint-action representation on one short sequence."""

    source = json.loads((OLD / "source_manifest.json").read_text(encoding="utf-8"))
    row = next(value for value in source["files"] if int(value["submission_id"]) == 56216119)
    replay = json.loads((ROOT / row["path"]).read_text(encoding="utf-8"))
    seat = int(row["seat"])
    history = MarketHistory()
    features = []
    labels = []
    start, stop = 240, 312
    for step in range(stop):
        observation = _restore_observation(replay["steps"][step], seat, step)
        prior = replay["steps"][step][seat].get("action") if step > 0 else None
        history.update(observation, prior.get("market", []) if isinstance(prior, Mapping) else [])
        if step >= start:
            features.append(state_features(observation, history))
            action = replay["steps"][step + 1][seat].get("action") or {}
            labels.append(json.dumps(action, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    classes = sorted(set(labels))
    y = np.asarray([classes.index(value) for value in labels], np.int64)
    x = np.asarray(features, np.float32)
    center, scale = x.mean(axis=0), np.maximum(x.std(axis=0), 1e-3)
    x = (x - center) / scale
    rng = np.random.default_rng(TRAIN_SEED)
    parameters = [
        rng.normal(0, math.sqrt(2 / x.shape[1]), (x.shape[1], 96)).astype(np.float32),
        np.zeros(96, np.float32),
        rng.normal(0, math.sqrt(2 / 96), (96, len(classes))).astype(np.float32),
        np.zeros(len(classes), np.float32),
    ]
    initial = [value.copy() for value in parameters]
    optimizer = _Adam(parameters, 0.01)
    log_path = EXPERIMENT / "training_logs/bc2_short_overfit.jsonl"
    accuracy = 0.0
    for epoch in range(1, 2001):
        hidden = np.maximum(0.0, x @ parameters[0] + parameters[1])
        logits = hidden @ parameters[2] + parameters[3]
        shifted = logits - logits.max(axis=1, keepdims=True)
        probability = np.exp(np.clip(shifted, -30, 30))
        probability /= probability.sum(axis=1, keepdims=True)
        accuracy = float((np.argmax(probability, axis=1) == y).mean())
        gradient = probability.copy()
        gradient[np.arange(len(y)), y] -= 1
        gradient /= len(y)
        grad_w2 = hidden.T @ gradient
        grad_hidden = (gradient @ parameters[2].T) * (hidden > 0)
        optimizer.update((x.T @ grad_hidden, grad_hidden.sum(axis=0), grad_w2, gradient.sum(axis=0)))
        if epoch == 1 or epoch % 100 == 0 or accuracy == 1.0:
            append_jsonl(log_path, {"epoch": epoch, "accuracy": accuracy, "optimizer_steps": optimizer.steps})
        if accuracy == 1.0:
            break
    path = MODEL_DIR / "bc2_short_overfit.npz"
    np.savez(path, mean=center, scale=scale, w1=parameters[0], b1=parameters[1], w2=parameters[2], b2=parameters[3], classes=np.asarray(classes))
    result = {
        "teacher": 56216119,
        "episode_id": row["episode_id"],
        "seat": seat,
        "interval": [start, stop],
        "rows": len(y),
        "unique_full_joint_actions": len(classes),
        "representation": "canonical JSON of farmer, ordered hands, ordered market, all item/quantity fields and stopping by list length",
        "optimizer_steps": optimizer.steps,
        "teacher_forced_exact_action_accuracy": accuracy,
        "parameter_change_l2": float(math.sqrt(sum(float(np.square(a - b).sum()) for a, b in zip(parameters, initial, strict=True)))),
        "model_sha256": sha256(path),
        "runtime_integrated": False,
        "closed_loop_rollouts": 0,
        "limitation": "a one-sequence capacity/representation probe; it is not an unknown-state policy or an upper-tier oracle",
    }
    write_json(EXPERIMENT / "offline_metrics_bc2.json", result)
    print(json.dumps(result), flush=True)


def package_round2() -> None:
    runtimes = prepare_runtimes()
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {"created_at_utc": utc_now(), "study_id": STUDY_ID, "archives": {}}
    for arm, main in runtimes.items():
        if arm in {"c0", "b1", "b_simple"}:
            continue
        directory = main.parent
        archive = ARCHIVE_DIR / f"{STUDY_ID}_{arm}.tar.gz"
        with tarfile.open(archive, "w:gz") as stream:
            for path in sorted(directory.iterdir(), key=lambda value: value.name):
                if path.is_file():
                    stream.add(path, arcname=path.name)
        manifest["archives"][arm] = {
            "path": str(archive.relative_to(ROOT)),
            "sha256": sha256(archive),
            "members": [
                {"name": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)}
                for path in sorted(directory.iterdir(), key=lambda value: value.name)
                if path.is_file()
            ],
        }
    write_json(EXPERIMENT / "archive_manifest.json", manifest)

    validation_root = ROOT / ".tmp" / f"{STUDY_ID}_archive_validation"
    validation_root.mkdir(parents=True, exist_ok=True)
    results = []
    for arm, row in manifest["archives"].items():
        target = validation_root / arm
        _safe_extract(ROOT / row["path"], target)
        code = (
            "import importlib.util,pathlib,sys,time; from kaggle_environments import make; "
            "p=pathlib.Path(sys.argv[1]); t=time.perf_counter(); s=importlib.util.spec_from_file_location('archive_main',p/'main.py'); "
            "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); imp=time.perf_counter()-t; "
            "e=make('kaggriculture',configuration={'episodeSteps':720,'seed':2026092399},debug=True); "
            "e.run([m.agent,'pass']); print(imp,len(e.steps),[x.status for x in e.steps[-1]])"
        )
        completed = subprocess.run([sys.executable, "-c", code, str(target)], cwd=target, text=True, capture_output=True, check=False, timeout=180)
        results.append({"arm": arm, "archive_sha256": row["sha256"], "exit_code": completed.returncode, "stdout": completed.stdout.strip(), "stderr": completed.stderr[-2000:]})
        if completed.returncode:
            raise RuntimeError(results[-1])
    write_json(EXPERIMENT / "package_validation.json", {"created_at_utc": utc_now(), "results": results})
    print(json.dumps({"archives": len(manifest["archives"]), "validated": len(results)}), flush=True)


def _action_differences(control_path: Path, candidate_path: Path, seat: int) -> tuple[int, int | None]:
    control = _read_gzip_json(control_path)
    candidate = _read_gzip_json(candidate_path)
    differences = 0
    first = None
    for index in range(1, min(len(control["steps"]), len(candidate["steps"]))):
        if control["steps"][index][seat].get("action") != candidate["steps"][index][seat].get("action"):
            differences += 1
            first = index - 1 if first is None else first
    return differences, first


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _bank_tasks(bank: str, runtimes: Mapping[str, Path], output: Path) -> list[dict[str, Any]]:
    if bank == "regression":
        arms = [name for name in ("c0", "a2_keep", "a2_nonlearned", "a2", "b_simple", "b1", "b2_frequency", "b2", "b2_history_shuffle") if name in runtimes]
        cases = [("qeinstein_moev2", 2026092301, seat) for seat in (0, 1)]
    elif bank == "known_failure":
        arms = [name for name in ("c0", "b1", "b2_frequency", "b2") if name in runtimes]
        cases = [
            ("qeinstein_moev2", 2026092307, 1),
            ("smart_farm", 2026092307, 0),
            ("smart_farm", 2026092307, 1),
            ("mooman_e052a", 2026092307, 1),
        ]
    elif bank == "external":
        arms = [name for name in ("c0", "a2_keep", "a2_nonlearned", "a2", "b_simple", "b1", "b2_frequency", "b2") if name in runtimes]
        cases = [(family, seed, seat) for family in TRAIN_FAMILIES for seed in EXTERNAL_SEEDS for seat in (0, 1)]
    else:
        raise ValueError(bank)
    return [
        {
            "arm": arm,
            "bank": bank,
            "family": family,
            "seed": seed,
            "seat": seat,
            "agent_main": str(runtimes[arm]),
            "opponent_main": str(OPPONENTS[family]),
            "replay_path": str(output / "replays" / arm / family / f"seed_{seed}_seat_{seat}.json.gz"),
        }
        for arm in arms
        for family, seed, seat in cases
    ]


def evaluate_bank(bank: str, package: bool = True) -> None:
    runtimes = prepare_runtimes()
    if package:
        validation_path = EXPERIMENT / "package_validation.json"
        archive_path = EXPERIMENT / "archive_manifest.json"
        package_valid = False
        if validation_path.is_file() and archive_path.is_file():
            validation = json.loads(validation_path.read_text(encoding="utf-8"))
            archives = json.loads(archive_path.read_text(encoding="utf-8")).get("archives", {})
            package_valid = bool(validation.get("results")) and all(
                int(row.get("exit_code", 1)) == 0 for row in validation["results"]
            ) and all((ROOT / row["path"]).is_file() for row in archives.values())
        if not package_valid:
            package_round2()
    output = EXPERIMENT / f"{bank}_bank"
    tasks = _bank_tasks(bank, runtimes, output)
    results = []
    pending = []
    for task in tasks:
        completed = _result_from_completed_replay(task)
        if completed is None:
            pending.append(task)
        else:
            results.append(completed)
    if results:
        print(f"resumed {len(results)}/{len(tasks)} completed replays", flush=True)
    results.extend(_run_parallel(pending, _run_game, workers=16) if pending else [])
    lookup = {(row["arm"], row["family"], row["seed"], row["seat"]): row for row in results}
    flat = []
    trace_rows = []
    for row in sorted(results, key=lambda value: (value["arm"], value["family"], value["seed"], value["seat"])):
        control = lookup[("c0", row["family"], row["seed"], row["seat"])]
        differences, first = (0, None)
        if row["arm"] != "c0":
            differences, first = _action_differences(Path(control["replay_path"]), Path(row["replay_path"]), int(row["seat"]))
        flat.append(
            {
                "bank": bank,
                "arm": row["arm"],
                "opponent_family": row["family"],
                "requested_seed": row["seed"],
                "seat": row["seat"],
                "score": row["score"],
                "our_cash": row["our_cash"],
                "opponent_cash": row["opponent_cash"],
                "margin": row["margin"],
                "paired_score_delta_vs_c0": row["score"] - control["score"],
                "paired_margin_delta_vs_c0": row["margin"] - control["margin"],
                "action_differences_vs_c0": differences,
                "first_action_difference": first,
                "stored_states": row["stored_states"],
                "statuses": "/".join(row["statuses"]),
                "shop_history_sha256": row["shop_history_sha256"],
                "replay_path": str(Path(row["replay_path"]).relative_to(ROOT)),
            }
        )
        for trace in row.get("trace", []):
            trace_rows.append({"bank": bank, "arm": row["arm"], "family": row["family"], "seed": row["seed"], "seat": row["seat"], **trace})
    _write_csv(output / "paired_results.csv", flat)
    summaries = {}
    for arm in sorted({row["arm"] for row in flat}):
        selected = [row for row in flat if row["arm"] == arm]
        summaries[arm] = {
            "games": len(selected),
            "wins": sum(row["score"] == 1 for row in selected),
            "draws": sum(row["score"] == 0.5 for row in selected),
            "losses": sum(row["score"] == 0 for row in selected),
            "mean_score": mean(row["score"] for row in selected),
            "mean_margin": mean(row["margin"] for row in selected),
            "mean_paired_score_delta": mean(row["paired_score_delta_vs_c0"] for row in selected),
            "mean_paired_margin_delta": mean(row["paired_margin_delta_vs_c0"] for row in selected),
            "loss_to_win": sum(
                lookup[("c0", row["opponent_family"], row["requested_seed"], row["seat"])]["score"] == 0 and row["score"] == 1
                for row in selected
            ),
            "win_to_loss": sum(
                lookup[("c0", row["opponent_family"], row["requested_seed"], row["seat"])]["score"] == 1 and row["score"] == 0
                for row in selected
            ),
            "action_differences": sum(row["action_differences_vs_c0"] for row in selected),
        }
    write_json(output / "paired_summary.json", summaries)
    payoff = []
    for arm in sorted({row["arm"] for row in flat}):
        for family in sorted({row["opponent_family"] for row in flat}):
            selected = [row for row in flat if row["arm"] == arm and row["opponent_family"] == family]
            if selected:
                payoff.append(
                    {
                        "arm": arm,
                        "opponent_family": family,
                        "games": len(selected),
                        "wins": sum(row["score"] == 1 for row in selected),
                        "draws": sum(row["score"] == 0.5 for row in selected),
                        "losses": sum(row["score"] == 0 for row in selected),
                        "mean_margin": mean(row["margin"] for row in selected),
                        "mean_paired_score_delta_vs_c0": mean(row["paired_score_delta_vs_c0"] for row in selected),
                    }
                )
    _write_csv(output / "payoff_by_family.csv", payoff)
    usage = {}
    benchmark = {}
    for arm in sorted({row["arm"] for row in results}):
        selected = [row for row in results if row["arm"] == arm]
        measured = [row for row in selected if row.get("timing_measured", True)]
        keys = {key for row in selected for key, value in row["diagnostics"].items() if isinstance(value, int | float)}
        usage[arm] = {key: sum(float(row["diagnostics"].get(key, 0)) for row in selected) for key in sorted(keys)}
        benchmark[arm] = {
            "games": len(selected),
            "timing_measured_games": len(measured),
            "resumed_replay_games": len(selected) - len(measured),
            "cold_import_max_seconds": max((row["cold_import_seconds"] for row in measured), default=None),
            "inference_mean_seconds": mean(row["inference_mean_seconds"] for row in measured) if measured else None,
            "inference_p95_max_seconds": max((row["inference_p95_seconds"] for row in measured), default=None),
            "inference_max_seconds": max((row["inference_max_seconds"] for row in measured), default=None),
            "rss_max_bytes": max((row["rss_bytes"] for row in measured), default=None),
        }
    write_json(output / "model_usage.json", usage)
    write_json(output / "inference_benchmark.json", benchmark)
    if trace_rows:
        trace_path = output / "candidate_action_trace.jsonl"
        trace_path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in trace_rows), encoding="utf-8")
    archive_manifest = json.loads((EXPERIMENT / "archive_manifest.json").read_text(encoding="utf-8"))
    old_archive = json.loads((OLD / "archive_manifest.json").read_text(encoding="utf-8"))
    write_json(
        output / "evaluation_manifest.json",
        {
            "created_at_utc": utc_now(),
            "bank": bank,
            "engine_sha256": ENGINE_HASH,
            "games": len(results),
            "arms": sorted({row["arm"] for row in results}),
            "opponents": {name: {"path": str(path.relative_to(ROOT)), "sha256": sha256(path), "executable": True, "public_identity_claim": "proxy only"} for name, path in OPPONENTS.items() if any(row["family"] == name for row in results)},
            "new_archives": archive_manifest["archives"],
            "c0_archive": {"path": str(C0_ARCHIVE.relative_to(ROOT)), "sha256": sha256(C0_ARCHIVE)},
            "b1_archive": old_archive["arms"]["b_learned"],
            "b_simple_archive": old_archive["arms"]["b_simple"],
            "grouping": "family x requested_seed; two seats are one world cluster when both are present",
            "formal_strength_claim": bank == "external",
            "known_failure_is_holdout": False,
        },
    )
    print(json.dumps(summaries), flush=True)


def evaluate_all() -> None:
    package_round2()
    for bank in ("regression", "known_failure", "external"):
        evaluate_bank(bank, package=False)


def finalize() -> None:
    bank_rows = []
    for bank in ("regression", "known_failure", "external"):
        path = EXPERIMENT / f"{bank}_bank/paired_results.csv"
        if path.is_file():
            with path.open(encoding="utf-8-sig", newline="") as stream:
                bank_rows.extend(dict(row) for row in csv.DictReader(stream))
    _write_csv(EXPERIMENT / "paired_results.csv", bank_rows)
    summaries = {
        bank: json.loads((EXPERIMENT / f"{bank}_bank/paired_summary.json").read_text(encoding="utf-8"))
        for bank in ("regression", "known_failure", "external")
        if (EXPERIMENT / f"{bank}_bank/paired_summary.json").is_file()
    }
    a2_rounds = [
        json.loads((DATASET_DIR / "a2" / f"round{number}_manifest.json").read_text(encoding="utf-8"))
        for number in (1, 2)
        if (DATASET_DIR / "a2" / f"round{number}_manifest.json").is_file()
    ]
    a2_model = json.loads((MODEL_DIR / "a2_model.json").read_text(encoding="utf-8")) if (MODEL_DIR / "a2_model.json").is_file() else {}
    b2_model = json.loads((MODEL_DIR / "b2_model.json").read_text(encoding="utf-8")) if (MODEL_DIR / "b2_model.json").is_file() else {}
    bc2 = json.loads((EXPERIMENT / "offline_metrics_bc2.json").read_text(encoding="utf-8")) if (EXPERIMENT / "offline_metrics_bc2.json").is_file() else {}
    b_reconstruction = json.loads((EXPERIMENT / "b_label_reconstruction.json").read_text(encoding="utf-8")) if (EXPERIMENT / "b_label_reconstruction.json").is_file() else {}
    external = summaries.get("external", {})
    regression = summaries.get("regression", {})
    a2_total_updates = sum(
        json.loads((MODEL_DIR / f"a2_model_round{number}.json").read_text(encoding="utf-8")).get("optimizer_steps", 0)
        for number in (1, 2)
        if (MODEL_DIR / f"a2_model_round{number}.json").is_file()
    )
    a2_jobs_completed = sum(int(row.get("job_completed", 0)) for row in a2_rounds)
    a2_jobs_aborted = sum(int(row.get("job_aborted", 0)) for row in a2_rounds)
    b2_total_updates = sum(int(row.get("optimizer_steps", 0)) for row in b2_model.get("initializations", []))
    b2_representation_valid = bool(b_reconstruction) and min(
        float(b_reconstruction.get("money_match_rate", 0)),
        float(b_reconstruction.get("shed_match_rate_or_boundary", 0)),
        float(b_reconstruction.get("market_match_rate", 0)),
    ) >= 0.999
    source_manifest = json.loads((OLD / "source_manifest.json").read_text(encoding="utf-8"))
    replay_paths = {int(row["episode_id"]): ROOT / row["path"] for row in source_manifest["files"]}
    replay_seeds = []
    missing_replay_seeds = []
    seed_pattern = re.compile(rb'"info":\{.*?"seed":(\d+)\}')
    for episode_id, path in replay_paths.items():
        with path.open("rb") as stream:
            match = seed_pattern.search(stream.read(8192))
        if match:
            replay_seeds.append(int(match.group(1)))
        else:
            missing_replay_seeds.append(episode_id)
    replay_seed_audit = {
        "unique_episodes": len(replay_paths),
        "parsed_replay_seeds": len(replay_seeds),
        "unique_replay_seeds": len(set(replay_seeds)),
        "duplicate_seed_episodes": len(replay_seeds) - len(set(replay_seeds)),
        "missing_episode_ids": missing_replay_seeds,
        "method": "read the replay-level info.seed from the first 8192 bytes; configuration.seed is intentionally null",
    }
    write_json(EXPERIMENT / "replay_seed_audit.json", replay_seed_audit)

    def verdict(arm: str, trained: bool, representation: bool, integrated: bool) -> dict[str, Any]:
        summary = external.get(arm, {})
        changed = int(summary.get("action_differences", 0))
        economic = bool(summary) and int(summary.get("losses", 0)) <= int(external.get("c0", {}).get("losses", 0)) and int(summary.get("win_to_loss", 0)) == 0
        evaluated = bool(summary)
        promotable = evaluated and economic and float(summary.get("mean_paired_score_delta", 0)) > 0
        return {
            "TRAINED": trained,
            "REPRESENTATION_VALIDATED": representation,
            "INTEGRATED": integrated,
            "ECONOMICALLY_FUNCTIONAL": economic,
            "EVALUATED": evaluated,
            "PROMOTABLE": promotable,
            "NO_EFFECT": bool(integrated and evaluated and changed == 0),
            "action_differences": changed,
        }

    status = {
        "A2": verdict("a2", bool(a2_model), True, "a2" in external),
        "B2": verdict("b2", bool(b2_model), b2_representation_valid, "b2" in external),
        "BC2": {
            "TRAINED": bool(bc2),
            "REPRESENTATION_VALIDATED": bool(bc2 and bc2.get("teacher_forced_exact_action_accuracy") == 1.0),
            "INTEGRATED": False,
            "ECONOMICALLY_FUNCTIONAL": False,
            "EVALUATED": False,
            "PROMOTABLE": False,
            "NO_EFFECT": False,
        },
    }
    status["A2"]["DISPOSITION"] = "REJECTED"
    status["B2"]["DISPOSITION"] = "REJECTED"
    status["BC2"]["DISPOSITION"] = "PARTIAL"
    write_json(EXPERIMENT / "status_verdicts.json", status)
    write_json(
        EXPERIMENT / "feature_schema.json",
        {
            "a2": list(a2_feature_names()),
            "b2": list(state_feature_names()),
            "forbidden_runtime_inputs": ["opponent private", "future", "seed", "episode/submission identity", "teacher action"],
        },
    )
    write_json(
        EXPERIMENT / "split_manifest.json",
        {
            "a2": {"unit": "family x seed (all prefixes/candidates remain together)", "round_manifests": [str((DATASET_DIR / "a2" / f"round{row['round']}_manifest.json").relative_to(ROOT)) for row in a2_rounds]},
            "b2": {"unit": "old episode-level frozen split", "source": str((OLD / "split_manifest.json").relative_to(ROOT))},
            "external": {"unit": "family x seed; both seats retained in one cluster", "seeds": list(EXTERNAL_SEEDS)},
        },
    )
    write_json(EXPERIMENT / "offline_metrics.json", {"a2": a2_model, "b2": b2_model, "bc2": bc2})
    usage = {
        bank: json.loads((EXPERIMENT / f"{bank}_bank/model_usage.json").read_text(encoding="utf-8"))
        for bank in ("regression", "known_failure", "external")
        if (EXPERIMENT / f"{bank}_bank/model_usage.json").is_file()
    }
    write_json(EXPERIMENT / "model_usage.json", usage)
    benchmarks = {
        bank: json.loads((EXPERIMENT / f"{bank}_bank/inference_benchmark.json").read_text(encoding="utf-8"))
        for bank in ("regression", "known_failure", "external")
        if (EXPERIMENT / f"{bank}_bank/inference_benchmark.json").is_file()
    }
    write_json(
        EXPERIMENT / "runtime_measurements.json",
        {
            "measurements": benchmarks,
            "scope": "local Windows process import and Python action wall time; not equated to Kaggle runner time",
            "official_configuration": {"actTimeout": 1, "episodeSteps": 720, "remainingOverageTime": "runner-managed cumulative allowance"},
        },
    )
    trace_output = EXPERIMENT / "candidate_action_trace.jsonl"
    with trace_output.open("w", encoding="utf-8") as destination:
        for bank in ("regression", "known_failure", "external"):
            source_path = EXPERIMENT / f"{bank}_bank/candidate_action_trace.jsonl"
            if source_path.is_file():
                destination.write(source_path.read_text(encoding="utf-8"))
        for round_number in (1, 2):
            source_path = DATASET_DIR / "a2" / f"round{round_number}_candidate_results.jsonl"
            if source_path.is_file():
                with source_path.open(encoding="utf-8") as stream:
                    for line in stream:
                        row = json.loads(line)
                        if row.get("trace"):
                            destination.write(json.dumps({"stage": f"a2_round{round_number}_counterfactual", "prefix_id": row["prefix_id"], "candidate_id": row["candidate_id"], "trace": row["trace"]}, ensure_ascii=False, separators=(",", ":")) + "\n")
    write_json(
        EXPERIMENT / "repair_history.json",
        {
            "old_artifacts_overwritten": False,
            "repairs": [
                "KEEP_C0 now preserves the complete structured action after one C0 call and read-only shadow encoding.",
                "A2 interventions own a bounded two-primitive job, verify each transition, reserve resources, and rejoin without tape rewind.",
                "B2 reconstructs requested, executed and price-floor-adjusted market-impact quantities separately with terminal masks.",
                "BC2 uses a lossless full-joint-action representation for its short capacity probe; the old median-quantity decoder remains unmodified evidence.",
                "Forty-nine replay transitions that did not match the recorded next state are explicitly retained and every crossing B2 horizon is masked.",
                "Evaluation imports are isolated per archive and each game uses a fresh process after a generic common-module cache collision was detected.",
            ],
        },
    )

    a2_summary = external.get("a2", {})
    b2_summary = external.get("b2", {})
    report = [
        "# Kaggriculture learning round 2 実行報告（2026-09-21）",
        "",
        "## 冒頭サマリ",
        "",
        "| 系統 | 教師の意味 | unique episode/seed/family/prefix | 更新 | model hash | runtime使用/完全action変更 | 成功・破綻 | closed-loop / W-D-L | paired差 | 未実施 |",
        "|---|---|---|---:|---|---|---|---|---|---|",
        f"| A2 | 実行可能jobのKEEP比終局結果 | episode N/A / seed {a2_model.get('unique_seeds', 0)} / family {len(a2_model.get('families', []))} / prefix {a2_model.get('unique_prefixes', 0)} | {a2_total_updates}（最終refit {a2_model.get('optimizer_steps', 0)}） | `{a2_model.get('active_model_sha256', 'NOT_RUN')}` | model {external.get('a2', {}).get('games', 0)}戦 / {a2_summary.get('action_differences', 0)} turn | CF job完了 {a2_jobs_completed}, 中断 {a2_jobs_aborted}; external losses {a2_summary.get('losses', 'NA')} | CF branch {sum(int(row.get('closed_loop_branch_games', 0)) for row in a2_rounds)} + external {a2_summary.get('games', 0)} / {a2_summary.get('wins', 0)}-{a2_summary.get('draws', 0)}-{a2_summary.get('losses', 0)} | score {a2_summary.get('mean_paired_score_delta', 'NA')}, margin {a2_summary.get('mean_paired_margin_delta', 'NA')} | 24–72turnへの拡張・非公開上位本人評価 |",
        f"| B2 | 固定engine再演で検証したmarket-impact供給 | episode {replay_seed_audit['unique_episodes']} / seed {replay_seed_audit['unique_replay_seeds']} / family 3 / prefix N/A | {b2_total_updates}（採用 {b2_model.get('selection', {}).get('optimizer_steps', 0)}） | `{b2_model.get('active_model_sha256', 'NOT_RUN')}` | model {b2_summary.get('games', 0)}戦 / {b2_summary.get('action_differences', 0)} turn | requested/executed/impact分離; 復元不一致transition {b_reconstruction.get('counts', {}).get('transitions', 0) - b_reconstruction.get('counts', {}).get('shed_match_or_boundary', 0)}はmask; external losses {b2_summary.get('losses', 'NA')} | external {b2_summary.get('games', 0)} / {b2_summary.get('wins', 0)}-{b2_summary.get('draws', 0)}-{b2_summary.get('losses', 0)} | score {b2_summary.get('mean_paired_score_delta', 'NA')}, margin {b2_summary.get('mean_paired_margin_delta', 'NA')} | 候補集合外の売却時刻変更 |",
        f"| BC2 | 1 teacher短区間のlossless full-action容量試験 | episode 1 / seed 1 / family 1 / prefix 72 | {bc2.get('optimizer_steps', 0)} | `{bc2.get('model_sha256', 'NOT_RUN')}` | runtime未統合 / 0 | teacher-forced exact {bc2.get('teacher_forced_exact_action_accuracy', 'NA')} / 経済未評価 | 0 / NOT_RUN | NOT_RUN | on-policy teacher照会・4/12/24/72 closed-loop |",
        "",
        "## 判定",
        "",
        f"- A2: `{json.dumps(status['A2'], ensure_ascii=False)}`",
        f"- B2: `{json.dumps(status['B2'], ensure_ascii=False)}`",
        f"- BC2: `{json.dumps(status['BC2'], ensure_ascii=False)}`",
        "",
        "PROMOTABLEは外部bankのpaired win-scoreが正で、Win→Lossと経済破綻がない場合だけtrueにした。平均marginやoffline精度だけでは昇格していない。既知4敗はstressでありholdoutではない。公開実行相手はproxyで、現非公開上位への勝率とは主張しない。",
        "",
        "## 診断と学習",
        "",
        "KEEP_C0は保存観測と両seat full gameで構造化action・state・reward同一性を検査した。旧Aは学習版だけでなく非学習priority版もC0計画をprimitive単位で置換し、完結jobと再合流前提を持たなかったことが共通崩壊だった。旧97.7%は11-class op分類でありjob rankingではない。詳細はDIAGNOSIS.md。",
        "",
        "A2はC0到達状態のKEEPと最大3 jobを、同じ初期seedから反応する相手と再実行した。round 2はround-1 A2の限定介入後に到達した状態を追加してrefitした。これは上位本人へのDAggerではなく、有限候補の実行結果による局所方策改善である。",
        "",
        f"B2はunit action→lockstep market→Townの固定順序を再演し、要求・約定・価格床で市場在庫を増やした数量・収益を分けた。記録次状態に一致しないtransitionは理由と差分を保存し、それを横切るhorizonをmaskした（money {b_reconstruction.get('money_match_rate', 'NA')}, shed {b_reconstruction.get('shed_match_rate_or_boundary', 'NA')}, market {b_reconstruction.get('market_match_rate', 'NA')}）。存在しない未来も通常のゼロではなくmaskした。hindsight headroomは同一候補集合の同turn局所上限であり、ゲーム全体のoracleではない。",
        "",
        "BC2は旧decoderのmedian quantityが完全復元を妨げることを確認した。lossless表現は短区間を過学習できたがruntime統合もclosed-loop評価もしていないためPARTIALである。",
        "",
        "## 採否結論",
        "",
        "- **A2は棄却**。round 1の非KEEP 16件は全てmargin悪化（平均 -10452.3125）、round 2の16件は全て差0で、正の訓練例がなかった。にもかかわらず凍結gateはExternalで850 turnを変更し、C0の30-0-2に対して23-0-9、Win→Loss 7、paired score -0.21875となった。TRAINED/INTEGRATED/EVALUATEDではあるがECONOMICALLY_FUNCTIONALでもPROMOTABLEでもない。",
        f"- **B2はruntime採用を棄却**。offline testではimpact Brier {b2_model.get('test', {}).get('brier', 'NA')}（frequency {b2_model.get('baselines', {}).get('test', {}).get('frequency', {}).get('brier', 'NA')}）、数量MAE {b2_model.get('test', {}).get('quantity_mae', 'NA')}（frequency {b2_model.get('baselines', {}).get('test', {}).get('frequency', {}).get('quantity_mae', 'NA')}）まで改善したが、Externalは28-0-4、Win→Loss 2、paired score -0.0625、margin -309.8125で、非学習frequencyと実質同水準だった。予測改善が同じSELL並べ替えselectorの終局価値へ接続しなかった。",
        "- **BC2はPARTIAL**。lossless表現の短区間容量は確認したが、runtime未統合・closed-loop 0なので強化版とはしない。C0と旧A/B/BCの正式verdict・artifactは上書きしていない。",
        "",
        "## 評価bank",
        "",
        f"- Regression: `{json.dumps(regression, ensure_ascii=False)}`",
        f"- Known failure/stress: `{json.dumps(summaries.get('known_failure', {}), ensure_ascii=False)}`",
        f"- External comparison: `{json.dumps(external, ensure_ascii=False)}`",
        "",
        "全seatを独立世界とは扱わず、family×seedをcluster単位とする。seedは乱数入力であり日付とは解釈しない。Externalは4既存実行可能familyの未使用seedであり、新規familyの取得・現非公開上位本人評価は未実施で、強度証拠は不足する。Kaggle提出・課金は行っていない。",
    ]
    (EXPERIMENT / "REPORT_JA.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    resume = """# Round-2 resume commands

```powershell
.\\.venv\\Scripts\\python.exe scripts\\learning_round2.py --help
.\\.venv\\Scripts\\python.exe scripts\\learning_round2.py diagnose
.\\.venv\\Scripts\\python.exe scripts\\learning_round2.py collect-a2 --round 1
.\\.venv\\Scripts\\python.exe scripts\\learning_round2.py train-a2 --rounds 1
.\\.venv\\Scripts\\python.exe scripts\\learning_round2.py collect-a2 --round 2
.\\.venv\\Scripts\\python.exe scripts\\learning_round2.py train-a2 --rounds 2
.\\.venv\\Scripts\\python.exe scripts\\learning_round2.py build-b2
.\\.venv\\Scripts\\python.exe scripts\\learning_round2.py train-b2
.\\.venv\\Scripts\\python.exe scripts\\learning_round2.py b-headroom
.\\.venv\\Scripts\\python.exe scripts\\learning_round2.py train-bc2
.\\.venv\\Scripts\\python.exe scripts\\learning_round2.py evaluate --bank all
.\\.venv\\Scripts\\python.exe scripts\\learning_round2.py finalize
```

各commandはexclusive lock、開始/終了/exit codeを`commands.jsonl`へ記録する。既存の完了artifactがある場合も上書き対象はこのstudy内だけで、旧studyは変更しない。
"""
    (EXPERIMENT / "RESUME_COMMANDS.md").write_text(resume, encoding="utf-8")

    important = [
        EXPERIMENT / "REPORT_JA.md",
        EXPERIMENT / "DIAGNOSIS.md",
        EXPERIMENT / "paired_results.csv",
        EXPERIMENT / "RESUME_COMMANDS.md",
        EXPERIMENT / "initial_workspace_state.json",
        EXPERIMENT / "preregistration.json",
        EXPERIMENT / "preregistration_resource_amendment.json",
        EXPERIMENT / "commands.jsonl",
        EXPERIMENT / "feature_schema.json",
        EXPERIMENT / "feature_target_audit.json",
        EXPERIMENT / "split_manifest.json",
        EXPERIMENT / "offline_metrics.json",
        EXPERIMENT / "model_usage.json",
        EXPERIMENT / "repair_history.json",
        EXPERIMENT / "status_verdicts.json",
        EXPERIMENT / "replay_seed_audit.json",
        EXPERIMENT / "candidate_action_trace.jsonl",
        EXPERIMENT / "b2_label_schema.json",
        EXPERIMENT / "b_label_reconstruction.json",
        EXPERIMENT / "b_opportunity_headroom.json",
        EXPERIMENT / "action_roundtrip.json",
        EXPERIMENT / "first_failure_cases.json",
        EXPERIMENT / "runtime_measurements.json",
        EXPERIMENT / "archive_manifest.json",
        EXPERIMENT / "package_validation.json",
        MODEL_DIR / "a2_model.npz",
        MODEL_DIR / "a2_model.json",
        MODEL_DIR / "b2_model.npz",
        MODEL_DIR / "b2_model.json",
        MODEL_DIR / "bc2_short_overfit.npz",
        AGENT / "common.py",
        AGENT / "a2_agent.py",
        AGENT / "b2_agent.py",
        ROOT / "scripts/learning_round2.py",
    ]
    important.extend(sorted((DATASET_DIR / "a2").glob("*manifest.json")))
    important.extend(sorted((DATASET_DIR / "a2").glob("*candidate_results.jsonl")))
    important.extend(sorted((DATASET_DIR / "b2").glob("*manifest.json")))
    important.extend(sorted((EXPERIMENT / "training_logs").glob("*.jsonl")))
    for bank in ("regression", "known_failure", "external"):
        bank_dir = EXPERIMENT / f"{bank}_bank"
        important.extend(
            bank_dir / name
            for name in (
                "paired_results.csv",
                "paired_summary.json",
                "payoff_by_family.csv",
                "model_usage.json",
                "inference_benchmark.json",
                "evaluation_manifest.json",
            )
        )
    important.extend(sorted((EXPERIMENT / "small_replays").glob("*.json.gz"))[:4])
    archive_manifest = json.loads((EXPERIMENT / "archive_manifest.json").read_text(encoding="utf-8")) if (EXPERIMENT / "archive_manifest.json").is_file() else {"archives": {}}
    important.extend(ROOT / row["path"] for row in archive_manifest.get("archives", {}).values() if row.get("path"))
    files = []
    for path in important:
        if path.is_file() and path not in files:
            files.append(path)
    final_manifest = {
        "created_at_utc": utc_now(),
        "study_id": STUDY_ID,
        "source_state": source_state(),
        "c0": {"path": str(C0_ARCHIVE.relative_to(ROOT)), "sha256": sha256(C0_ARCHIVE)},
        "engine_sha256": ENGINE_HASH,
        "models": {
            name: {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)}
            for name, path in {
                "a2": MODEL_DIR / "a2_model.npz",
                "b2": MODEL_DIR / "b2_model.npz",
                "bc2_probe": MODEL_DIR / "bc2_short_overfit.npz",
            }.items()
            if path.is_file()
        },
        "archives": archive_manifest.get("archives", {}),
        "banks": summaries,
        "status": status,
        "files": [{"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size, "sha256": sha256(path)} for path in files],
        "kaggle_submissions": 0,
    }
    write_json(EXPERIMENT / "FINAL_MANIFEST.json", final_manifest)
    files.append(EXPERIMENT / "FINAL_MANIFEST.json")

    import zipfile

    handoff = EXPERIMENT / "handoff_evidence.zip"
    with zipfile.ZipFile(handoff, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as stream:
        for path in files:
            stream.write(path, arcname=str(path.relative_to(ROOT)).replace("\\", "/"))
    final_manifest["handoff_evidence"] = {"path": str(handoff.relative_to(ROOT)), "bytes": handoff.stat().st_size, "sha256": sha256(handoff)}
    write_json(EXPERIMENT / "FINAL_MANIFEST.json", final_manifest)
    print(json.dumps({"report": str((EXPERIMENT / 'REPORT_JA.md').relative_to(ROOT)), "handoff": final_manifest["handoff_evidence"], "status": status}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create the isolated study and preregistration")
    sub.add_parser("diagnose", help="run narrow KEEP/A-objective/BC/terminal diagnostics")
    collect = sub.add_parser("collect-a2", help="collect terminal counterfactual outcomes for A2")
    collect.add_argument("--round", type=int, choices=(1, 2), required=True)
    train_a = sub.add_parser("train-a2", help="fit A2 value+risk model")
    train_a.add_argument("--rounds", type=int, choices=(1, 2), required=True)
    sub.add_parser("build-b2", help="reconstruct requested/executed/impact B2 labels")
    sub.add_parser("train-b2", help="fit two B2 initializations and freeze validation winner")
    sub.add_parser("b-headroom", help="measure frozen B1 candidate-set hindsight headroom")
    sub.add_parser("train-bc2", help="run the short lossless full-action overfit probe")
    sub.add_parser("package", help="build and full-game validate standalone archives")
    evaluate = sub.add_parser("evaluate", help="run a preregistered closed-loop bank")
    evaluate.add_argument("--bank", choices=("regression", "known_failure", "external", "all"), required=True)
    sub.add_parser("finalize", help="assemble report, manifests and handoff evidence")
    sub.add_parser("all", help="run diagnosis, two A2 rounds, B2, BC2, evaluation and finalize")
    args = parser.parse_args()
    with command_run(args.command):
        if args.command == "init":
            init_study()
        elif args.command == "diagnose":
            diagnose()
        elif args.command == "collect-a2":
            collect_a2(args.round)
        elif args.command == "train-a2":
            train_a2(args.rounds)
        elif args.command == "build-b2":
            build_b2()
        elif args.command == "train-b2":
            train_b2()
        elif args.command == "b-headroom":
            b_opportunity_headroom()
        elif args.command == "train-bc2":
            train_bc2_probe()
        elif args.command == "package":
            package_round2()
        elif args.command == "evaluate":
            evaluate_all() if args.bank == "all" else evaluate_bank(args.bank)
        elif args.command == "finalize":
            finalize()
        else:
            init_study()
            diagnose()
            collect_a2(1)
            train_a2(1)
            collect_a2(2)
            train_a2(2)
            build_b2()
            train_b2()
            b_opportunity_headroom()
            train_bc2_probe()
            evaluate_all()
            finalize()


if __name__ == "__main__":
    main()
