"""Create paired terminal labels for one scheduled-fertilization task per fork.

Every treatment restarts the deterministic episode and both agents from step 0.
The target wrapper is action-identical to B1 before the recorded candidate,
then executes FERTILIZE -> WATER.  No Game snapshot/clone API is assumed.
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
from collections import defaultdict
from collections.abc import Callable, Mapping
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CPP_ROOT = ROOT / "experiments/round10_public_learning_20260924/engines/kaggriculture-cppsim"
MINGW_BIN = Path(r"C:\msys64\ucrt64\bin")
POLICY_ROOT = ROOT / "agents/round10_task_learning_20260924"
EMPTY_ACTION = {"farmer": ["PASS"], "hands": [], "market": []}
_DLL_HANDLE: Any = None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=lambda item: dict(item)))


def init_kagsim() -> Any:
    global _DLL_HANDLE
    sys.path.insert(0, str(CPP_ROOT))
    if os.name == "nt" and MINGW_BIN.is_dir() and hasattr(os, "add_dll_directory"):
        _DLL_HANDLE = _DLL_HANDLE or os.add_dll_directory(str(MINGW_BIN))
    import kagsim

    if kagsim.ENGINE_VERSION != "1.32.7":
        raise RuntimeError(f"unexpected engine {kagsim.ENGINE_VERSION}")
    return kagsim


def load_last_callable(path: Path, label: str) -> Callable[..., Any]:
    source = path.read_text(encoding="utf-8")
    namespace: dict[str, Any] = {"__file__": str(path), "__name__": f"_round10_{label}_{os.getpid()}"}
    sys.path.insert(0, str(path.parent))
    try:
        exec(compile(source, str(path), "exec"), namespace)
    finally:
        sys.path.pop(0)
    values = [value for value in namespace.values() if callable(value)]
    if not values:
        raise RuntimeError(f"no callable in {path}")
    return values[-1]


def load_module_agent(path: Path, label: str) -> Callable[..., Any]:
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
    return module.agent


def load_opponent(specification: Mapping[str, Any], label: str) -> Callable[..., Any]:
    path = ROOT / str(specification["path"])
    if specification.get("mode") == "last_callable":
        return load_last_callable(path, label)
    return load_module_agent(path, label)


def load_policy(mode: str, target: Mapping[str, Any] | None = None) -> Callable[..., Any]:
    sys.path.insert(0, str(POLICY_ROOT))
    try:
        from policy_runtime import build_agent

        return build_agent(mode, target=target, max_tasks=1)
    finally:
        sys.path.pop(0)


def invoke(agent: Callable[..., Any], observation: dict[str, Any], configuration: dict[str, Any]) -> dict[str, Any]:
    argc = getattr(getattr(agent, "__code__", None), "co_argcount", 1)
    raw = agent(observation, configuration) if argc >= 2 else agent(observation)
    if not isinstance(raw, Mapping):
        return dict(EMPTY_ACTION)
    return {
        "farmer": list(raw.get("farmer") or ["PASS"]),
        "hands": [list(value) for value in (raw.get("hands") or [])],
        "market": [list(value) for value in (raw.get("market") or [])],
    }


def write_replay(path: Path, replay: Mapping[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as stream:
        json.dump(replay, stream, ensure_ascii=False, separators=(",", ":"))
    return sha256_file(path)


def run_episode(
    seed: int,
    seat: int,
    policy: Callable[..., Any],
    opponent: Callable[..., Any],
    *,
    collect_candidates: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    kagsim = init_kagsim()
    if collect_candidates:
        sys.path.insert(0, str(POLICY_ROOT))
        try:
            from policy_runtime import candidate_from_action
        finally:
            sys.path.pop(0)
    game = kagsim.Game(seed)
    configuration = {"episodeSteps": 720, "seed": seed}
    decisions: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    while not game.done:
        observations = [jsonable(game.observe(0)), jsonable(game.observe(1))]
        functions = [policy, opponent] if seat == 0 else [opponent, policy]
        actions = [invoke(functions[player], observations[player], configuration) for player in (0, 1)]
        decision = {"step": int(game.step_count), "observations": observations, "actions": actions}
        decisions.append(decision)
        if collect_candidates:
            for candidate in candidate_from_action(observations[seat], actions[seat]):
                candidate["opportunity_index"] = len(candidates)
                candidates.append(candidate)
        game.step(actions[0], actions[1])
    diagnostics = getattr(policy, "round10_diagnostics", lambda: {})()
    replay = {
        "format": "round10-task-paired-l1-v1",
        "engine_version": kagsim.ENGINE_VERSION,
        "seed": seed,
        "seat": seat,
        "decisions": decisions,
        "rewards": [float(game.reward(0)), float(game.reward(1))],
        "telemetry": {"players": [jsonable(game.telemetry(0)), jsonable(game.telemetry(1))]},
        "diagnostics": diagnostics,
    }
    return replay, candidates


def select_candidates(candidates: list[dict[str, Any]], limit: int, key: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        grouped[str(candidate["crop"])].append(candidate)
    priorities = ("MELON", "WHEAT", "STRAWBERRY", "TOMATO", "CARROT")
    selected: list[dict[str, Any]] = []
    for crop in priorities:
        values = grouped.get(crop) or []
        if not values:
            continue
        values.sort(key=lambda item: canonical_hash([key, item["candidate_id"]]))
        selected.append(values[0])
        if len(selected) >= limit:
            return selected
    remaining = [value for values in grouped.values() for value in values if value not in selected]
    remaining.sort(key=lambda item: canonical_hash([key, item["candidate_id"]]))
    return (selected + remaining)[:limit]


def own_margin(replay: Mapping[str, Any], seat: int) -> tuple[float, float, float, int]:
    rewards = [float(value) for value in replay["rewards"]]
    own, other = rewards[seat], rewards[1 - seat]
    return own, other, own - other, int(own > other) - int(own < other)


def treatment_task(task: Mapping[str, Any]) -> dict[str, Any]:
    opponent = load_opponent(task["opponent_spec"], str(task["opponent_id"]))
    policy = load_policy("target", task["target"])
    replay, _ = run_episode(
        int(task["seed"]), int(task["seat"]), policy, opponent, collect_candidates=False
    )
    replay_path = ROOT / str(task["replay_path"])
    replay_sha = write_replay(replay_path, replay)
    baseline_path = ROOT / str(task["baseline_replay"])
    with gzip.open(baseline_path, "rt", encoding="utf-8") as stream:
        baseline = json.load(stream)
    target_step = int(task["target"]["created_step"])
    prefix_hash = canonical_hash(replay["decisions"][:target_step])
    baseline_prefix_hash = canonical_hash(baseline["decisions"][:target_step])
    own, other, margin, outcome = own_margin(replay, int(task["seat"]))
    base_own, base_other, base_margin, base_outcome = own_margin(baseline, int(task["seat"]))
    diagnostics = replay.get("diagnostics") or {}
    return {
        "candidate_id": task["target"]["candidate_id"],
        "group_id": f"{task['opponent_id']}:{task['seed']}",
        "opponent_id": task["opponent_id"],
        "opponent_family": task["opponent_spec"].get("family", task["opponent_id"]),
        "seed": int(task["seed"]),
        "seat": int(task["seat"]),
        "created_step": int(task["target"]["created_step"]),
        "actor_index": int(task["target"]["actor_index"]),
        "target_json": json.dumps(task["target"]["target"], separators=(",", ":")),
        "crop": task["target"]["crop"],
        "features_json": json.dumps(task["target"]["features"], separators=(",", ":")),
        "feature_vector_json": json.dumps(task["target"]["feature_vector"], separators=(",", ":")),
        "contract_json": json.dumps(
            {
                key: task["target"][key]
                for key in (
                    "target_identity",
                    "required_carried",
                    "reserved_resources",
                    "start_condition",
                    "planned_actions",
                    "completion",
                    "failure",
                    "recovery",
                )
            },
            separators=(",", ":"),
        ),
        "baseline_self_cash": base_own,
        "baseline_opp_cash": base_other,
        "baseline_margin": base_margin,
        "baseline_outcome": base_outcome,
        "treatment_self_cash": own,
        "treatment_opp_cash": other,
        "treatment_margin": margin,
        "treatment_outcome": outcome,
        "margin_delta": margin - base_margin,
        "win_delta": outcome - base_outcome,
        "prefix_match": int(prefix_hash == baseline_prefix_hash),
        "prefix_sha256": prefix_hash,
        "baseline_prefix_sha256": baseline_prefix_hash,
        "tasks_started": int(diagnostics.get("tasks_started", 0) or 0),
        "tasks_completed": int(diagnostics.get("tasks_completed", 0) or 0),
        "contract_failures": int(diagnostics.get("contract_failures", 0) or 0),
        "remaining_obligations_json": json.dumps(diagnostics.get("pending_obligations") or {}, separators=(",", ":")),
        "execution_established": int(
            diagnostics.get("tasks_started") == 1
            and diagnostics.get("tasks_completed") == 1
            and diagnostics.get("contract_failures") == 0
            and not diagnostics.get("pending_obligations")
        ),
        "diagnostics_json": json.dumps(diagnostics, ensure_ascii=False, separators=(",", ":")),
        "baseline_replay": task["baseline_replay"],
        "treatment_replay": task["replay_path"],
        "treatment_replay_sha256": replay_sha,
        "error": "",
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
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
    output.mkdir(parents=True, exist_ok=True)
    preregistration = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "config": config,
        "config_sha256": sha256_file(config_path),
        "engine": "kagsim L1 pinned/validated against official 1.32.7",
        "fork_method": "restart both agents from step 0; no snapshot/clone",
        "label": "paired terminal margin delta; future outcome excluded from runtime features",
    }
    (output / "preregistration.json").write_text(
        json.dumps(preregistration, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    baseline_rows: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    for opponent_id, opponent_spec in config["opponents"].items():
        for seed in config["seeds"]:
            for seat in config.get("seats", [0, 1]):
                policy = load_policy("baseline")
                opponent = load_opponent(opponent_spec, str(opponent_id))
                replay, candidates = run_episode(int(seed), int(seat), policy, opponent, collect_candidates=True)
                relative = Path(config["output"]) / "replays" / "baseline" / str(opponent_id) / (
                    f"seed_{seed}_seat_{seat}.json.gz"
                )
                replay_sha = write_replay(ROOT / relative, replay)
                selected = select_candidates(
                    candidates,
                    int(config.get("candidate_limit_per_game", 3)),
                    f"{opponent_id}:{seed}:{seat}",
                )
                own, other, margin, outcome = own_margin(replay, int(seat))
                baseline_rows.append(
                    {
                        "opponent_id": opponent_id,
                        "seed": seed,
                        "seat": seat,
                        "self_cash": own,
                        "opp_cash": other,
                        "margin": margin,
                        "outcome": outcome,
                        "opportunities": len(candidates),
                        "selected_forks": len(selected),
                        "replay": relative.as_posix(),
                        "replay_sha256": replay_sha,
                    }
                )
                for candidate in selected:
                    target = {**candidate, **{key: candidate[key] for key in candidate}}
                    treatment_relative = (
                        Path(config["output"])
                        / "replays"
                        / "treatment"
                        / str(opponent_id)
                        / f"seed_{seed}_seat_{seat}_{candidate['candidate_id'].replace(':', '_')}.json.gz"
                    )
                    tasks.append(
                        {
                            "opponent_id": opponent_id,
                            "opponent_spec": opponent_spec,
                            "seed": int(seed),
                            "seat": int(seat),
                            "target": target,
                            "baseline_replay": relative.as_posix(),
                            "replay_path": treatment_relative.as_posix(),
                        }
                    )
                print(
                    f"baseline {opponent_id} seed={seed} seat={seat}: "
                    f"margin={margin:.1f} opportunities={len(candidates)} forks={len(selected)}",
                    flush=True,
                )
    write_csv(output / "baseline_games.csv", baseline_rows)
    rows: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        future_map = {pool.submit(treatment_task, task): task for task in tasks}
        for future in as_completed(future_map):
            task = future_map[future]
            try:
                row = future.result()
            except Exception as exc:
                row = {
                    "candidate_id": task["target"]["candidate_id"],
                    "opponent_id": task["opponent_id"],
                    "seed": task["seed"],
                    "seat": task["seat"],
                    "error": repr(exc),
                }
            rows.append(row)
            print(
                f"fork {task['opponent_id']} seed={task['seed']} seat={task['seat']} "
                f"{task['target']['crop']}: {row.get('margin_delta')} established={row.get('execution_established')}",
                flush=True,
            )
    rows.sort(
        key=lambda row: (
            str(row.get("opponent_id")),
            int(row.get("seed", 0)),
            int(row.get("seat", 0)),
            str(row.get("candidate_id")),
        )
    )
    write_csv(output / "task_labels.csv", rows)
    summary = {
        "baseline_games": len(baseline_rows),
        "forks": len(rows),
        "errors": sum(bool(row.get("error")) for row in rows),
        "prefix_matches": sum(int(row.get("prefix_match", 0) or 0) for row in rows),
        "execution_established": sum(int(row.get("execution_established", 0) or 0) for row in rows),
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
