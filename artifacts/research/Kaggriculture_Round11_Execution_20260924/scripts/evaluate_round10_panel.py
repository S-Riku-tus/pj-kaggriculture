"""Run reproducible paired Kaggriculture panels on official or validated L1.

The JSON config names arms/opponents, loading mode, seeds and output.  L1
games save an observation/action trace; official games save env.toJSON().
Both formats are gzip-compressed and every row carries content hashes.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.util
import json
import os
import sys
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CPP_ROOT = ROOT / "experiments/round10_public_learning_20260924/engines/kaggriculture-cppsim"
MINGW_BIN = Path(r"C:\msys64\ucrt64\bin")
EMPTY_ACTION = {"farmer": ["PASS"], "hands": [], "market": []}
_DLL_HANDLE: Any = None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=lambda item: dict(item)))


def load_entry(path: Path, mode: str, label: str) -> tuple[Callable[..., Any], Any]:
    if mode == "module_agent":
        name = f"_round10_{label}_{os.getpid()}_{time.time_ns()}"
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ImportError(path)
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(path.parent))
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
        reset = getattr(module, "reset_runtime_state", None)
        if callable(reset):
            reset()
        return module.agent, module
    if mode == "last_callable":
        source = path.read_text(encoding="utf-8")
        code = compile(source, str(path), "exec")
        namespace: dict[str, Any] = {"__file__": str(path), "__name__": f"_round10_{label}"}
        sys.path.append(str(path.parent))
        try:
            exec(code, namespace)
        finally:
            sys.path.pop()
        callables = [value for value in namespace.values() if callable(value)]
        if not callables:
            raise ValueError(f"no callable in {path}")
        return callables[-1], namespace
    raise ValueError(f"unsupported loading mode: {mode}")


def invoke(agent: Callable[..., Any], observation: dict[str, Any], configuration: dict[str, Any]) -> dict[str, Any]:
    argc = getattr(getattr(agent, "__code__", None), "co_argcount", 1)
    action = agent(observation, configuration) if argc >= 2 else agent(observation)
    if not isinstance(action, dict):
        return dict(EMPTY_ACTION)
    return {
        "farmer": list(action.get("farmer") or ["PASS"]),
        "hands": [list(item) for item in (action.get("hands") or [])],
        "market": [list(item) for item in (action.get("market") or [])],
    }


def diagnostics(container: Any, seat: int) -> dict[str, Any]:
    names = ("round10_diagnostics", "latest_diagnostics")
    for name in names:
        getter = container.get(name) if isinstance(container, dict) else getattr(container, name, None)
        if not callable(getter):
            continue
        for args in ((seat,), ()):
            try:
                value = getter(*args)
            except (TypeError, KeyError):
                continue
            if isinstance(value, dict):
                return jsonable(value)
    # Public single-file agents commonly attach a mutable telemetry dictionary
    # to the loader-selected final callable instead of exporting a getter.
    if isinstance(container, dict):
        for value in reversed(list(container.values())):
            report = getattr(value, "telemetry", None) if callable(value) else None
            if isinstance(report, dict):
                return jsonable(report)
    return {}


def init_kagsim() -> Any:
    global _DLL_HANDLE
    if CPP_ROOT.as_posix() not in [Path(item).as_posix() for item in sys.path if item]:
        sys.path.insert(0, str(CPP_ROOT))
    if os.name == "nt" and MINGW_BIN.is_dir() and hasattr(os, "add_dll_directory"):
        _DLL_HANDLE = _DLL_HANDLE or os.add_dll_directory(str(MINGW_BIN))
    import kagsim

    if kagsim.ENGINE_VERSION != "1.32.7":
        raise RuntimeError(f"unexpected kagsim engine: {kagsim.ENGINE_VERSION}")
    return kagsim


def shop_events_from_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    previous: list[str] | None = None
    for step, observation in enumerate(observations):
        shops = list((observation.get("town") or {}).get("unlocked_shops") or [])
        if shops != previous:
            events.append({"step": step, "shops": shops})
            previous = shops
    return events


def write_gzip_json(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as stream:
        json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
    return sha256_file(path)


def run_l1(
    task: dict[str, Any], arm_fn: Callable[..., Any], opponent_fn: Callable[..., Any]
) -> tuple[Any, list[dict[str, Any]], dict[str, Any]]:
    kagsim = init_kagsim()
    game = kagsim.Game(int(task["seed"]))
    configuration = {"episodeSteps": 720, "seed": int(task["seed"])}
    decisions: list[dict[str, Any]] = []
    arm_observations: list[dict[str, Any]] = []
    while not game.done:
        observations = [jsonable(game.observe(0)), jsonable(game.observe(1))]
        functions = [arm_fn, opponent_fn] if int(task["seat"]) == 0 else [opponent_fn, arm_fn]
        actions = [invoke(functions[player], observations[player], configuration) for player in (0, 1)]
        arm_observations.append(observations[int(task["seat"])])
        decisions.append(
            {
                "step": int(game.step_count),
                "observations": observations,
                "actions": actions,
            }
        )
        game.step(actions[0], actions[1])
    rewards = [float(game.reward(0)), float(game.reward(1))]
    telemetry = {"players": [jsonable(game.telemetry(0)), jsonable(game.telemetry(1))]}
    replay = {
        "format": "round10-kagsim-l1-trace-v1",
        "engine_version": kagsim.ENGINE_VERSION,
        "seed": int(task["seed"]),
        "decisions": decisions,
        "rewards": rewards,
        "telemetry": telemetry,
    }
    return replay, arm_observations, telemetry


def run_official(
    task: dict[str, Any], arm_fn: Callable[..., Any], opponent_fn: Callable[..., Any]
) -> tuple[Any, list[dict[str, Any]], dict[str, Any]]:
    from kaggle_environments import make

    configuration = {"episodeSteps": 720, "seed": int(task["seed"])}
    env = make("kaggriculture", configuration=configuration, debug=True)
    entries = [arm_fn, opponent_fn] if int(task["seat"]) == 0 else [opponent_fn, arm_fn]
    env.run(entries)
    replay = env.toJSON()
    arm_observations = [
        jsonable(step[int(task["seat"])].get("observation") or {})
        for step in replay.get("steps", [])
    ]
    return replay, arm_observations, {"players": []}


def replay_rewards(replay: dict[str, Any]) -> list[float]:
    if replay.get("format") == "round10-kagsim-l1-trace-v1":
        return [float(value) for value in replay["rewards"]]
    final = replay["steps"][-1]
    return [float(state.get("reward") or 0) for state in final]


def run_task(task: dict[str, Any]) -> dict[str, Any]:
    arm_path = Path(task["arm_path"])
    opponent_path = Path(task["opponent_path"])
    arm_fn, arm_container = load_entry(arm_path, task["arm_mode"], f"arm_{task['arm']}")
    opponent_fn, _ = load_entry(opponent_path, task["opponent_mode"], f"opp_{task['opponent']}")
    started = time.perf_counter()
    if task["engine"] == "kagsim":
        replay, observations, telemetry = run_l1(task, arm_fn, opponent_fn)
    else:
        replay, observations, telemetry = run_official(task, arm_fn, opponent_fn)
    elapsed = time.perf_counter() - started
    rewards = replay_rewards(replay)
    seat = int(task["seat"])
    own, other = rewards[seat], rewards[1 - seat]
    result = "W" if own > other else "L" if own < other else "T"
    shop_events = shop_events_from_observations(observations)
    shop_hash = sha256_bytes(json.dumps(shop_events, sort_keys=True).encode("utf-8"))
    diag = diagnostics(arm_container, seat)
    replay_path = Path(task["replay_path"])
    replay_sha = write_gzip_json(replay_path, replay)
    return {
        "arm": task["arm"],
        "baseline_id": task.get("baseline_id", ""),
        "opponent_id": task["opponent"],
        "opponent_family": task["opponent_family"],
        "seed": int(task["seed"]),
        "seat": seat,
        "self_final_cash": own,
        "opp_final_cash": other,
        "margin": own - other,
        "result": result,
        "engine": task["engine"],
        "elapsed_seconds": round(elapsed, 6),
        "model_loaded": int(bool(diag.get("model_loaded"))),
        "model_calls": int(diag.get("model_calls", 0) or 0),
        "model_selected_tasks": int(diag.get("model_selected_tasks", 0) or 0),
        "model_changed_final_actions": int(diag.get("model_changed_final_actions", 0) or 0),
        "rule_overrides": int(diag.get("rule_overrides", 0) or 0),
        "planned_retirements": int(diag.get("planned_retirements", 0) or 0),
        "unplanned_losses": int(diag.get("unplanned_losses", 0) or 0),
        "contract_failures": int(diag.get("contract_failures", 0) or 0),
        "shop_sequence_hash": shop_hash,
        "shop_events_json": json.dumps(shop_events, ensure_ascii=False, separators=(",", ":")),
        "replay": replay_path.relative_to(ROOT).as_posix(),
        "replay_sha256": replay_sha,
        "agent_sha256": task["agent_sha256"],
        "opponent_sha256": task["opponent_sha256"],
        "engine_sha256": task["engine_sha256"],
        "telemetry_json": json.dumps(telemetry, ensure_ascii=False, separators=(",", ":")),
        "diagnostics_json": json.dumps(diag, ensure_ascii=False, separators=(",", ":")),
        "error": "",
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    config = json.loads(config_path.read_text(encoding="utf-8"))
    output = ROOT / config["output"]
    engine = config.get("engine", "kagsim")
    if engine not in {"kagsim", "official"}:
        raise ValueError(engine)
    if engine == "kagsim":
        init_kagsim()
        engine_path = next(CPP_ROOT.glob("kagsim*.pyd"))
    else:
        import kaggle_environments.envs.kaggriculture.kaggriculture as official

        engine_path = Path(official.__file__)
    engine_hash = sha256_file(engine_path)

    tasks: list[dict[str, Any]] = []
    for arm, arm_spec in config["arms"].items():
        arm_path = (ROOT / arm_spec["path"]).resolve()
        for opponent, opponent_spec in config["opponents"].items():
            opponent_path = (ROOT / opponent_spec["path"]).resolve()
            for seed in config["seeds"]:
                for seat in config.get("seats", [0, 1]):
                    replay_path = output / "replays" / arm / opponent / f"seed_{seed}_seat_{seat}.json.gz"
                    tasks.append(
                        {
                            "arm": arm,
                            "arm_path": str(arm_path),
                            "arm_mode": arm_spec["mode"],
                            "baseline_id": arm_spec.get("baseline_id", ""),
                            "opponent": opponent,
                            "opponent_path": str(opponent_path),
                            "opponent_mode": opponent_spec["mode"],
                            "opponent_family": opponent_spec.get("family", opponent),
                            "seed": int(seed),
                            "seat": int(seat),
                            "engine": engine,
                            "replay_path": str(replay_path),
                            "agent_sha256": sha256_file(arm_path),
                            "opponent_sha256": sha256_file(opponent_path),
                            "engine_sha256": engine_hash,
                        }
                    )

    preregistration = {
        "format": "round10-panel-v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "config": config,
        "engine_path": engine_path.relative_to(ROOT).as_posix(),
        "engine_sha256": engine_hash,
        "tasks": len(tasks),
        "development_evidence_not_holdout": bool(config.get("development_evidence_not_holdout", True)),
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "preregistration.json").write_text(
        json.dumps(preregistration, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(run_task, task): task for task in tasks}
        for future in as_completed(futures):
            task = futures[future]
            try:
                row = future.result()
            except Exception as exc:
                row = {
                    "arm": task["arm"],
                    "opponent_id": task["opponent"],
                    "opponent_family": task["opponent_family"],
                    "seed": task["seed"],
                    "seat": task["seat"],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            results.append(row)
            print(
                f"{row['arm']} vs {row['opponent_id']} seed={row['seed']} seat={row['seat']} "
                f"result={row.get('result', 'ERR')} margin={row.get('margin', '')} {row.get('error', '')}",
                flush=True,
            )
    results.sort(key=lambda row: (row["arm"], row["opponent_id"], row["seed"], row["seat"]))
    if any(row.get("error") for row in results):
        (output / "errors.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        raise RuntimeError("one or more panel games failed; see errors.json")
    write_csv(output / "games.csv", results)
    summary: list[dict[str, Any]] = []
    for arm in config["arms"]:
        for opponent in config["opponents"]:
            selected = [row for row in results if row["arm"] == arm and row["opponent_id"] == opponent]
            summary.append(
                {
                    "arm": arm,
                    "opponent_id": opponent,
                    "games": len(selected),
                    "wins": sum(row["result"] == "W" for row in selected),
                    "losses": sum(row["result"] == "L" for row in selected),
                    "ties": sum(row["result"] == "T" for row in selected),
                    "score_rate": mean(
                        1.0 if row["result"] == "W" else 0.5 if row["result"] == "T" else 0.0
                        for row in selected
                    ),
                    "mean_self_cash": mean(float(row["self_final_cash"]) for row in selected),
                    "mean_opp_cash": mean(float(row["opp_final_cash"]) for row in selected),
                    "mean_margin": mean(float(row["margin"]) for row in selected),
                }
            )
    write_csv(output / "summary.csv", summary)
    print(json.dumps({"games": len(results), "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
