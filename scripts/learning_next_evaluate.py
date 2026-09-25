"""Package and closed-loop evaluate the B, A, and independent-BC agents."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "learning_next_20260921"
AGENT = ROOT / "agents" / "learning_next_20260921"
ARCHIVES = ROOT / "artifacts" / "submissions"
EXTRACT_ROOT = Path("C:/tmp/kaggriculture-learning-next-20260921")
C0_ARCHIVE = ARCHIVES / "v126_control_candidate.tar.gz"
OPPONENTS = {
    "qeinstein_moev2": ROOT / "experiments" / "research_20260910" / "runtime" / "qeinstein_moev2" / "main.py",
    "mooman_e052a": ROOT / "experiments" / "research_20260910" / "runtime" / "mooman_e052a" / "main.py",
    "smart_farm": ROOT / "experiments" / "research_20260918_v120" / "acquisition" / "smart_farm" / "decoded_main_1.py",
    "souvik_v4": ROOT / "experiments" / "research_20260910" / "runtime" / "souvik_v4" / "main.py",
    "ggmljs_v16": ROOT / "experiments" / "research_20260910" / "runtime" / "ggmljs_v16" / "main.py",
    "robriculture_lean_feed": ROOT
    / "experiments"
    / "research_20260911_continuations"
    / "runtime"
    / "robriculture_lean_feed"
    / "main.py",
}
DEVELOPMENT_OPPONENTS = ("qeinstein_moev2", "mooman_e052a", "smart_farm", "souvik_v4")
ARM_SPECS = {
    "b_simple": {"main": "b_agent.py", "mode": "simple", "models": ("b_simple_model.json",)},
    "b_learned": {
        "main": "b_agent.py",
        "mode": "learned",
        "models": ("b_model.npz", "b_model.json", "b_simple_model.json"),
    },
    "a_baseline": {"main": "a_agent.py", "mode": "baseline", "models": ()},
    "a_learned": {"main": "a_agent.py", "mode": "learned", "models": ("a_model.npz", "a_model.json")},
    "independent_bc": {
        "main": "bc_agent.py",
        "models": (
            "bc_actor_model.npz",
            "bc_actor_model.json",
            "bc_market_model.npz",
            "bc_market_model.json",
            "bc_quantities.json",
        ),
    },
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_command(payload: dict[str, Any]) -> None:
    path = EXPERIMENT / "commands.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def _copy_c0_dependencies(target: Path) -> None:
    manifest_path = ROOT / "agents" / "v125_exec" / "submission_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    shutil.copy2(ROOT / "agents" / "v125_exec" / "main.py", target / "c0_main.py")
    for entry in manifest["files"]:
        if entry["target"] == "main.py":
            continue
        source = (manifest_path.parent / entry["source"]).resolve()
        shutil.copy2(source, target / entry["target"])


def package() -> None:
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "created_at_utc": utc_now(),
        "c0": {"path": str(C0_ARCHIVE.relative_to(ROOT)), "sha256": sha256(C0_ARCHIVE)},
        "arms": {},
    }
    for arm, spec in ARM_SPECS.items():
        staging = EXPERIMENT / "package_staging" / f"{arm}-{uuid.uuid4().hex}"
        staging.mkdir(parents=True, exist_ok=False)
        shutil.copy2(AGENT / str(spec["main"]), staging / "main.py")
        shutil.copy2(AGENT / "common.py", staging / "common.py")
        for model in spec["models"]:
            source = AGENT / str(model)
            if not source.is_file():
                raise FileNotFoundError(f"required model missing for {arm}: {source}")
            shutil.copy2(source, staging / str(model))
        if arm.startswith(("a_", "b_")):
            _copy_c0_dependencies(staging)
        if "mode" in spec:
            write_json(staging / "arm_config.json", {"mode": spec["mode"]})
        archive = ARCHIVES / f"learning_next_20260921_{arm}.tar.gz"
        with tarfile.open(archive, "w:gz") as stream:
            for path in sorted(staging.iterdir(), key=lambda value: value.name):
                stream.add(path, arcname=path.name)
        members = []
        with tarfile.open(archive, "r:gz") as stream:
            for member in stream.getmembers():
                extracted = stream.extractfile(member)
                content = extracted.read() if extracted is not None else b""
                members.append(
                    {"name": member.name, "bytes": member.size, "sha256": hashlib.sha256(content).hexdigest()}
                )
        result["arms"][arm] = {
            "path": str(archive.relative_to(ROOT)),
            "sha256": sha256(archive),
            "members": members,
            "staging_source": str(staging),
        }
        print(f"packaged {arm} {result['arms'][arm]['sha256']}", flush=True)
    write_json(EXPERIMENT / "archive_manifest.json", result)


def _safe_extract(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=False)
    root = target.resolve()
    with tarfile.open(archive, "r:gz") as stream:
        for member in stream.getmembers():
            destination = (target / member.name).resolve()
            if not destination.is_relative_to(root):
                raise ValueError(f"unsafe archive member {member.name}")
        stream.extractall(target)
    if not (target / "main.py").is_file():
        raise FileNotFoundError(f"main.py missing in {archive}")


def validate_packages() -> None:
    manifest = json.loads((EXPERIMENT / "archive_manifest.json").read_text(encoding="utf-8"))
    run_root = EXTRACT_ROOT / datetime.now().strftime("validation-%Y%m%d-%H%M%S")
    run_root.mkdir(parents=True, exist_ok=False)
    results = []
    for arm, row in {"c0": manifest["c0"], **manifest["arms"]}.items():
        archive = ROOT / row["path"]
        target = run_root / arm
        _safe_extract(archive, target)
        code = (
            "import importlib.util,pathlib,sys,time; "
            "p=pathlib.Path(sys.argv[1]); t=time.perf_counter(); "
            "s=importlib.util.spec_from_file_location('standalone_check',p/'main.py'); "
            "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
            "print(time.perf_counter()-t, callable(m.agent))"
        )
        completed = subprocess.run(
            [sys.executable, "-c", code, str(target)],
            cwd="C:/tmp",
            text=True,
            capture_output=True,
            check=False,
        )
        results.append(
            {
                "arm": arm,
                "archive": str(archive.relative_to(ROOT)),
                "archive_sha256": sha256(archive),
                "extracted_path": str(target),
                "separate_process_exit_code": completed.returncode,
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr[-2000:],
            }
        )
        if completed.returncode:
            raise RuntimeError(results[-1])
    write_json(EXPERIMENT / "package_validation.json", {"validated_at_utc": utc_now(), "results": results})


def _load_module(path: Path, label: str) -> Any:
    name = f"_learning_eval_{label}_{os.getpid()}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if hasattr(module, "reset_runtime_state"):
        module.reset_runtime_state()
    return module


def _call(function: Any, observation: Any, configuration: Any) -> Any:
    try:
        parameters = inspect.signature(function).parameters.values()
        accepts_configuration = (
            any(parameter.kind in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD} for parameter in parameters)
            or len(list(parameters)) >= 2
        )
    except (TypeError, ValueError):
        accepts_configuration = True
    return function(observation, configuration) if accepts_configuration else function(observation)


def _run_game(task: dict[str, Any]) -> dict[str, Any]:
    import psutil
    from kaggle_environments import make

    process = psutil.Process(os.getpid())
    rss_before = process.memory_info().rss
    import_started = time.perf_counter()
    focal_module = _load_module(Path(task["agent_main"]), f"{task['arm']}_focal")
    import_seconds = time.perf_counter() - import_started
    opponent_module = _load_module(Path(task["opponent_main"]), f"{task['opponent']}_opponent")
    timings: list[float] = []
    diagnostics: dict[str, Any] = {}

    def focal(observation: Any, configuration: Any = None) -> Any:
        nonlocal diagnostics
        started = time.perf_counter()
        action = _call(focal_module.agent, observation, configuration)
        timings.append(time.perf_counter() - started)
        getter = getattr(focal_module, "policy_diagnostics", None)
        if callable(getter):
            positional = [
                parameter
                for parameter in inspect.signature(getter).parameters.values()
                if parameter.kind
                in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            ]
            has_varargs = any(
                parameter.kind == inspect.Parameter.VAR_POSITIONAL
                for parameter in inspect.signature(getter).parameters.values()
            )
            value = getter(observation) if positional or has_varargs else getter()
            diagnostics = dict(value) if isinstance(value, dict) else {}
        return action

    def opponent(observation: Any, configuration: Any = None) -> Any:
        return _call(opponent_module.agent, observation, configuration)

    env = make(
        "kaggriculture",
        configuration={"episodeSteps": 720, "seed": int(task["seed"])},
        debug=True,
    )
    agents = [focal, opponent] if int(task["seat"]) == 0 else [opponent, focal]
    started = time.perf_counter()
    env.run(agents)
    elapsed = time.perf_counter() - started
    replay = env.toJSON()
    rss_after = process.memory_info().rss
    final = replay["steps"][-1]
    rewards = [float(state.get("reward") or 0.0) for state in final]
    statuses = [str(state.get("status")) for state in final]
    seat = int(task["seat"])
    replay_path = Path(task["replay_path"])
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(replay_path, "wt", encoding="utf-8", compresslevel=6) as stream:
        json.dump(replay, stream, ensure_ascii=False, separators=(",", ":"))
    array = np.asarray(timings, dtype=np.float64)
    shop_history = [state[0]["observation"]["town"].get("unlocked_shops", []) for state in replay["steps"]]
    return {
        **task,
        "our_cash": rewards[seat],
        "opponent_cash": rewards[1 - seat],
        "margin": rewards[seat] - rewards[1 - seat],
        "score": 1.0 if rewards[seat] > rewards[1 - seat] else 0.5 if rewards[seat] == rewards[1 - seat] else 0.0,
        "statuses": statuses,
        "stored_states": len(replay["steps"]),
        "elapsed_seconds": elapsed,
        "cold_import_seconds": import_seconds,
        "inference": {
            "calls": len(timings),
            "mean_seconds": float(array.mean()),
            "p50_seconds": float(np.percentile(array, 50)),
            "p95_seconds": float(np.percentile(array, 95)),
            "p99_seconds": float(np.percentile(array, 99)),
            "max_seconds": float(array.max()),
            "rss_before_bytes": int(rss_before),
            "rss_after_bytes": int(rss_after),
            "rss_delta_bytes": int(rss_after - rss_before),
        },
        "diagnostics": diagnostics,
        "shop_history_sha256": hashlib.sha256(json.dumps(shop_history, separators=(",", ":")).encode()).hexdigest(),
    }


def _action_differences(
    control_path: Path, candidate_path: Path, seat: int
) -> tuple[int, int | None, dict[str, Any]]:
    with gzip.open(control_path, "rt", encoding="utf-8") as stream:
        control = json.load(stream)
    with gzip.open(candidate_path, "rt", encoding="utf-8") as stream:
        candidate = json.load(stream)
    differences = 0
    first = None
    by_day_band: dict[str, int] = {}
    candidate_ops: dict[str, int] = {}
    candidate_market_items: dict[str, int] = {}
    for index in range(1, min(len(control["steps"]), len(candidate["steps"]))):
        left = control["steps"][index][seat].get("action")
        right = candidate["steps"][index][seat].get("action")
        if left != right:
            differences += 1
            if first is None:
                first = index - 1
            day = (index - 1) // 24
            band = f"d{(day // 6) * 6:02d}-{min(29, (day // 6) * 6 + 5):02d}"
            by_day_band[band] = by_day_band.get(band, 0) + 1
            if isinstance(right, dict):
                for action in [right.get("farmer"), *(right.get("hands") or [])]:
                    if isinstance(action, list) and action:
                        op = str(action[0])
                        candidate_ops[op] = candidate_ops.get(op, 0) + 1
                for order in right.get("market") or []:
                    if isinstance(order, list) and len(order) >= 2:
                        item = str(order[1])
                        candidate_market_items[item] = candidate_market_items.get(item, 0) + 1
    return differences, first, {
        "by_day_band": by_day_band,
        "candidate_ops_on_different_turns": candidate_ops,
        "candidate_market_items_on_different_turns": candidate_market_items,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _clustered_interval(rows: list[dict[str, Any]], seed: int = 20260921) -> list[float]:
    clusters: dict[tuple[str, int], list[float]] = {}
    for row in rows:
        key = (str(row["opponent_family"]), int(row["requested_seed"]))
        clusters.setdefault(key, []).append(float(row["paired_score_delta_vs_c0"]))
    values = np.asarray([mean(group) for group in clusters.values()], dtype=np.float64)
    if not len(values):
        return [0.0, 0.0]
    rng = np.random.default_rng(seed)
    samples = np.asarray([rng.choice(values, size=len(values), replace=True).mean() for _ in range(2000)])
    return [float(np.percentile(samples, 2.5)), float(np.percentile(samples, 97.5))]


def evaluate(
    stage: str,
    output_id: str | None = None,
    requested_arms: str | None = None,
    requested_opponents: str | None = None,
) -> None:
    if not (EXPERIMENT / "archive_manifest.json").is_file():
        package()
    validate_packages()
    validation = json.loads((EXPERIMENT / "package_validation.json").read_text(encoding="utf-8"))
    extracted = {row["arm"]: Path(row["extracted_path"]) / "main.py" for row in validation["results"]}
    if stage == "smoke":
        arms = ("c0", "b_simple", "b_learned", "a_baseline", "a_learned", "independent_bc")
        opponents = ("qeinstein_moev2",)
        seeds = (2026092301,)
    elif stage == "calibration":
        arms = ("c0",)
        opponents = tuple(OPPONENTS)
        seeds = (2026092306, 2026092307)
    else:
        arms = ("c0", "b_learned", "a_learned", "independent_bc")
        opponents = DEVELOPMENT_OPPONENTS
        seeds = (2026092311, 2026092312, 2026092313, 2026092314, 2026092315)
    if requested_arms:
        selected = tuple(value.strip() for value in requested_arms.split(",") if value.strip())
        unknown = set(selected) - {"c0", *ARM_SPECS}
        if unknown:
            raise ValueError(f"unknown --arms: {sorted(unknown)}")
        arms = tuple(dict.fromkeys(("c0", *selected)))
    if requested_opponents:
        selected_opponents = tuple(value.strip() for value in requested_opponents.split(",") if value.strip())
        unknown_opponents = set(selected_opponents) - set(OPPONENTS)
        if unknown_opponents:
            raise ValueError(f"unknown --opponents: {sorted(unknown_opponents)}")
        opponents = selected_opponents
    output_name = output_id or f"{stage}_evaluation"
    if Path(output_name).name != output_name:
        raise ValueError("--output-id must be a single directory name")
    output = EXPERIMENT / output_name
    tasks = []
    for arm in arms:
        for opponent in opponents:
            for seed in seeds:
                for seat in (0, 1):
                    tasks.append(
                        {
                            "arm": arm,
                            "opponent": opponent,
                            "seed": seed,
                            "seat": seat,
                            "agent_main": str(extracted[arm]),
                            "opponent_main": str(OPPONENTS[opponent]),
                            "replay_path": str(
                                output / "replays" / arm / opponent / f"seed_{seed}_seat_{seat}.json.gz"
                            ),
                        }
                    )
    results = []
    with ProcessPoolExecutor(max_workers=min(4, len(tasks))) as executor:
        futures = {executor.submit(_run_game, task): task for task in tasks}
        for index, future in enumerate(as_completed(futures), 1):
            result = future.result()
            results.append(result)
            print(
                f"{index}/{len(tasks)} {result['arm']} seat={result['seat']} "
                f"score={result['score']} margin={result['margin']}",
                flush=True,
            )
    lookup = {(row["arm"], row["opponent"], row["seed"], row["seat"]): row for row in results}
    flat = []
    model_usage: dict[str, Any] = {}
    benchmarks: dict[str, Any] = {}
    for row in sorted(results, key=lambda value: (value["arm"], value["opponent"], value["seed"], value["seat"])):
        control = lookup[("c0", row["opponent"], row["seed"], row["seat"])]
        differences, first, difference_detail = (0, None, {})
        if row["arm"] != "c0":
            differences, first, difference_detail = _action_differences(
                Path(control["replay_path"]), Path(row["replay_path"]), int(row["seat"])
            )
        flat.append(
            {
                "arm": row["arm"],
                "opponent_family": row["opponent"],
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
                "action_difference_detail": json.dumps(difference_detail, ensure_ascii=False, separators=(",", ":")),
                "stored_states": row["stored_states"],
                "statuses": "/".join(row["statuses"]),
                "shop_history_sha256": row["shop_history_sha256"],
                "replay_path": str(Path(row["replay_path"]).relative_to(ROOT)),
            }
        )
        model_usage.setdefault(row["arm"], []).append(row["diagnostics"])
        benchmarks.setdefault(row["arm"], []).append(
            {"cold_import_seconds": row["cold_import_seconds"], **row["inference"]}
        )
    fields = list(flat[0])
    _write_csv(output / "paired_results.csv", flat, fields)
    paired_summary = {}
    for arm in arms:
        selected = [row for row in flat if row["arm"] == arm]
        paired_summary[arm] = {
            "games": len(selected),
            "mean_paired_win_score_delta": mean(row["paired_score_delta_vs_c0"] for row in selected),
            "mean_paired_margin_delta": mean(row["paired_margin_delta_vs_c0"] for row in selected),
            "loss_to_win": sum(
                lookup[("c0", row["opponent_family"], row["requested_seed"], row["seat"])]["score"] == 0
                and row["score"] == 1
                for row in selected
            ),
            "win_to_loss": sum(
                lookup[("c0", row["opponent_family"], row["requested_seed"], row["seat"])]["score"] == 1
                and row["score"] == 0
                for row in selected
            ),
            "cluster_bootstrap_95pct_mean_score_delta": _clustered_interval(selected),
            "cluster_unit": "opponent_family x requested_seed; both seats retained within each cluster",
        }
    write_json(output / "paired_summary.json", paired_summary)
    payoff = []
    for arm in arms:
        for opponent in opponents:
            selected = [row for row in flat if row["arm"] == arm and row["opponent_family"] == opponent]
            payoff.append(
                {
                    "arm": arm,
                    "opponent_family": opponent,
                    "games": len(selected),
                    "wins": sum(row["score"] == 1 for row in selected),
                    "draws": sum(row["score"] == 0.5 for row in selected),
                    "losses": sum(row["score"] == 0 for row in selected),
                    "mean_score": mean(row["score"] for row in selected),
                    "mean_margin": mean(row["margin"] for row in selected),
                    "mean_paired_score_delta_vs_c0": mean(row["paired_score_delta_vs_c0"] for row in selected),
                }
            )
    _write_csv(output / "payoff_by_family.csv", payoff, list(payoff[0]))
    usage_summary = {}
    benchmark_summary = {}
    for arm in arms:
        rows = model_usage[arm]
        numeric_keys = {key for row in rows for key, value in row.items() if isinstance(value, int | float)}
        usage_summary[arm] = {key: sum(float(row.get(key, 0)) for row in rows) for key in sorted(numeric_keys)}
        measures = benchmarks[arm]
        benchmark_summary[arm] = {
            "games": len(measures),
            "cold_start_max_seconds": max(row["cold_import_seconds"] for row in measures),
            "inference_p50_seconds": float(np.median([row["p50_seconds"] for row in measures])),
            "inference_p95_seconds": max(row["p95_seconds"] for row in measures),
            "inference_p99_seconds": max(row["p99_seconds"] for row in measures),
            "inference_max_seconds": max(row["max_seconds"] for row in measures),
            "rss_after_max_bytes": max(row["rss_after_bytes"] for row in measures),
            "rss_delta_max_bytes": max(row["rss_delta_bytes"] for row in measures),
            "memory_note": "worker-process RSS includes the engine and opponent; delta brackets one full game",
        }
    write_json(output / "model_usage.json", usage_summary)
    write_json(output / "inference_benchmark.json", benchmark_summary)
    write_json(
        output / "evaluation_manifest.json",
        {
            "stage": stage,
            "output_id": output_name,
            "created_at_utc": utc_now(),
            "engine": "kaggle-environments==1.32.7",
            "engine_sha256": "bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e",
            "arms": list(arms),
            "opponents": {
                name: {
                    "path": str(OPPONENTS[name].relative_to(ROOT)),
                    "sha256": sha256(OPPONENTS[name]),
                    "evidence_tier": "Silver public executable proxy",
                }
                for name in opponents
            },
            "seeds": list(seeds),
            "seats": [0, 1],
            "games": len(results),
            "formal_strength_claim": False,
            "reason": (
                "smoke implementation evidence"
                if stage == "smoke"
                else "C0-only challenge sensitivity calibration"
                if stage == "calibration"
                else "development evidence; not fresh holdout"
            ),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("package")
    sub.add_parser("validate")
    evaluate_parser = sub.add_parser("evaluate")
    evaluate_parser.add_argument("--stage", choices=("smoke", "calibration", "development"), default="smoke")
    evaluate_parser.add_argument("--output-id")
    evaluate_parser.add_argument("--arms", help="comma-separated arm subset; C0 is always included")
    evaluate_parser.add_argument("--opponents", help="comma-separated opponent subset")
    args = parser.parse_args()
    if args.command == "package":
        package()
    elif args.command == "validate":
        validate_packages()
    else:
        evaluate(args.stage, args.output_id, args.arms, args.opponents)


if __name__ == "__main__":
    started = time.time()
    command = {
        "command": subprocess.list2cmdline(sys.argv),
        "started_at_utc": utc_now(),
        "device": "cpu",
        "pid": os.getpid(),
    }
    try:
        main()
    except Exception as exc:
        command.update(
            {
                "ended_at_utc": utc_now(),
                "duration_seconds": time.time() - started,
                "exit_code": 1,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        append_command(command)
        raise
    command.update({"ended_at_utc": utc_now(), "duration_seconds": time.time() - started, "exit_code": 0})
    append_command(command)
