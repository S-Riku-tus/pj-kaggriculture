"""Run the preregistered clean-PSR experiment without external mutation."""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import importlib.metadata
import importlib.util
import inspect
import json
import os
import sys
import time
import uuid
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EXP = ROOT / "experiments/research_20260914_clean_psr"
ENGINE = ROOT / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py"
ENGINE_JSON = ENGINE.with_suffix(".json")
PREREG = EXP / "preregistration.json"
OLD_FREEZE = ROOT / "experiments/research_20260914_lowcash/candidate_freeze.json"

CANDIDATES = {
    "V111": {
        "main": ROOT / "agents/v111/main.py",
        "source_sha256": "699c73f75ec786e9bddcfabb6476fc64c07939f22abe3ed00691a5bef6f72660",
        "package_sha256": "85ba0176b1774ca1bc45f77601210d847e4bb8c01b550181c3c87bd3f6a1c85e",
    },
    "D1_e052a_no_opponent_tape": {
        "main": EXP / "candidates/D1_e052a_no_opponent_tape/main.py",
        "source": EXP / "candidates/D1_e052a_no_opponent_tape/policy.py",
        "source_sha256": "e465bdcce3cc6560abafcdc916f06843b111e79c2c625dcdd74db47ec7f7279b",
        "package_sha256": "5f4203c9974a3cf4ca1b26a1ea7fda0cd8a5fb4728a42605babab9df9dd49f4d",
    },
    "P1_psr_clean": {
        "main": EXP / "candidates/P1_psr_clean/main.py",
        "source_sha256": "91772fda544e2d5768afff819e2de75ecb7a12db8acb40a48ee9edcf76aca434",
        "package_sha256": "9e48f29463fd386f93157854aa8777b28d9e584ee4c648bf8a7c21caed508334",
    },
}

OLD_SOURCES = {
    "mooman_e052a": ROOT / "experiments/research_20260910/runtime/mooman_e052a/main.py",
    "souvik_v4": ROOT / "experiments/research_20260910/runtime/souvik_v4/main.py",
    "ggmljs_v16": ROOT / "experiments/research_20260910/runtime/ggmljs_v16/main.py",
    "qeinstein_moev2": ROOT / "experiments/research_20260910/runtime/qeinstein_moev2/main.py",
}

SCREEN_SOURCES = {
    "deepeshumrao_head": {
        "main": ROOT
        / "artifacts/opponent_pool/candidates/deepeshumrao_kaggriculture_agent"
        / "deliverables/kaggriculture_submission.py",
        "ancestry": "github_deepeshumrao",
        "priority": 2,
        "isolate": (),
    },
    "lonespear_head": {
        "main": ROOT / "artifacts/opponent_pool/candidates/lonespear_kaggriculture/main.py",
        "ancestry": "github_lonespear",
        "priority": 3,
        "isolate": (),
    },
    "robriculture_lean_feed": {
        "main": ROOT / "experiments/research_20260911_continuations/runtime/robriculture_lean_feed/main.py",
        "ancestry": "robriculture_hand_job",
        "priority": 1,
        "isolate": ("kaggisim", "strategies"),
    },
}


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"partial JSONL record {path}:{number}") from exc
    return result


def append(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def composite_hash(items: dict[str, str]) -> str:
    encoded = json.dumps(items, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def core_hashes() -> dict[str, str]:
    return {path.relative_to(ROOT).as_posix(): sha(path) for path in sorted((ROOT / "scripts/evaluation").glob("*.py"))}


def candidate_dir(candidate_id: str) -> Path:
    return EXP / "candidates" / candidate_id


def required_hashes(candidate_id: str, source_ids: list[str]) -> dict[str, str]:
    paths = [ENGINE, ENGINE_JSON, PREREG, Path(__file__), CANDIDATES[candidate_id]["main"]]
    source = CANDIDATES[candidate_id].get("source")
    if source:
        paths.append(source)
    paths.extend((ROOT / name) for name in core_hashes())
    paths.extend(OLD_SOURCES[name] for name in source_ids)
    return {str(path): sha(path) for path in paths}


def update_manifest(phase: str, state: str) -> None:
    path = EXP / "manifest.json"
    value = read(path)
    value.update(
        {
            "phase": phase,
            "status": state,
            "updated_at": now(),
            "evaluation_pid": os.getpid() if state == "RUNNING" else None,
        }
    )
    save(path, value)


def load_module(path: Path, role: str, isolate: tuple[str, ...] = ()) -> Any:
    for key in list(sys.modules):
        if any(key == prefix or key.startswith(prefix + ".") for prefix in isolate):
            del sys.modules[key]
    name = f"_clean_psr_{role}_{os.getpid()}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "agent", None)):
        raise TypeError(f"missing explicit agent callable: {path}")
    if hasattr(module, "reset_runtime_state"):
        module.reset_runtime_state()
    return module


def call_agent(function: Any, obs: Any, configuration: Any) -> Any:
    try:
        count = len(inspect.signature(function).parameters)
    except (TypeError, ValueError):
        count = 2
    return function(obs, configuration) if count >= 2 else function(obs)


def initial_observations() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    old = jsonl(ROOT / "data/evaluation/research_20260914_lowcash/discovery/pairs.jsonl")[0]
    path = Path(old["replay_artifacts"]["control"])
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        replay = json.load(handle)
    observations = [copy.deepcopy(replay["steps"][0][seat]["observation"]) for seat in (0, 1)]
    for seat, obs in enumerate(observations):
        obs.setdefault("step", 0)
        obs["player"] = seat
    return observations, replay["configuration"]


def validate() -> None:
    prereg = read(PREREG)
    assert prereg["frozen_before_first_new_game"]
    assert sha(ENGINE) == prereg["environment"]["engine_sha256"]
    assert sha(ENGINE_JSON) == prereg["environment"]["configuration_sha256"]
    current_core = core_hashes()
    for name, digest in prereg["environment"]["evaluation_core_sha256"].items():
        assert current_core[f"scripts/evaluation/{name}"] == digest, name
    observations, configuration = initial_observations()
    checks = []
    for candidate_id, data in CANDIDATES.items():
        source_path = data.get("source", data["main"])
        assert sha(source_path) == data["source_sha256"]
        modules = [load_module(data["main"], f"{candidate_id}_{index}", ("kaggriculture",)) for index in range(2)]
        outputs = []
        for seat in (0, 1):
            left = call_agent(modules[0].agent, copy.deepcopy(observations[seat]), configuration)
            reset = call_agent(modules[0].agent, copy.deepcopy(observations[seat]), configuration)
            independent = call_agent(modules[1].agent, copy.deepcopy(observations[seat]), configuration)
            assert left == reset == independent
            assert set(left) == {"farmer", "hands", "market"}
            outputs.append(left)
        checks.append(
            {
                "candidate": candidate_id,
                "source_sha256": data["source_sha256"],
                "explicit_callable": "agent",
                "callable_is_last_public_entrypoint": callable(getattr(modules[0], "agent", None)),
                "both_seats": True,
                "step0_reset_repeatable": True,
                "independent_imports_equal": True,
                "module_objects_distinct": modules[0] is not modules[1],
                "step0_actions": outputs,
            }
        )
    source_checks = []
    for source_id, data in SCREEN_SOURCES.items():
        module = load_module(data["main"], source_id, tuple(data["isolate"]))
        source_checks.append(
            {
                "source": source_id,
                "entrypoint_sha256": sha(data["main"]),
                "native_import": True,
                "callable": callable(module.agent),
            }
        )
    result = {
        "created_at": now(),
        "passed": True,
        "engine_version": importlib.metadata.version("kaggle-environments"),
        "engine_sha256": sha(ENGINE),
        "configuration_sha256": sha(ENGINE_JSON),
        "evaluation_core_sha256": current_core,
        "evaluation_core_composite_sha256": composite_hash(current_core),
        "candidates": checks,
        "independent_sources": source_checks,
    }
    save(EXP / "validation_pre_games.json", result)
    print(
        json.dumps({"passed": True, "candidates": len(checks), "sources": len(source_checks)}),
        flush=True,
    )


def semantic_replay(path: Path) -> list[Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        replay = json.load(handle)
    result = []
    for step in replay["steps"]:
        clean_step = []
        for state in step:
            obs = state.get("observation")
            if isinstance(obs, str):
                obs = json.loads(obs)
            obs = dict(obs or {})
            obs.pop("remainingOverageTime", None)
            clean_step.append(
                {
                    "observation": obs,
                    "action": state.get("action"),
                    "reward": state.get("reward"),
                    "status": state.get("status"),
                }
            )
        result.append(clean_step)
    return result


def pair_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row["candidate_id"],
        row["candidate_source_sha256"],
        row["evaluation_core_sha256"],
        row["lineage_id"],
        int(row["seed"]),
        int(row["seat"]),
    )


def run_candidate_phase(candidate_id: str, phase: str, sources: list[str], seeds: list[int], workers: int) -> None:
    from scripts.evaluation.runner import run_tasks

    data = CANDIDATES[candidate_id]
    folder = candidate_dir(candidate_id)
    pairs_path = folder / "pairs" / f"{phase}.jsonl"
    runs_path = folder / "runs" / f"{phase}.jsonl"
    summary_path = folder / "summary" / f"{phase}.json"
    core = composite_hash(core_hashes())
    plan = {
        "created_at": now(),
        "candidate_id": candidate_id,
        "candidate_source_sha256": data["source_sha256"],
        "candidate_package_sha256": data["package_sha256"],
        "evaluation_core_sha256": core,
        "phase": phase,
        "sources": sources,
        "seeds": seeds,
        "seats": [0, 1],
        "episode_steps": 720,
        "control": "V111",
        "control_source_sha256": CANDIDATES["V111"]["source_sha256"],
        "driver_sha256": sha(Path(__file__)),
        "preregistration_sha256": sha(PREREG),
    }
    plan_path = folder / "plans" / f"{phase}.json"
    if plan_path.exists():
        existing_plan = read(plan_path)
        plan["created_at"] = existing_plan["created_at"]
        assert existing_plan == plan, f"resume plan mismatch: {plan_path}"
    else:
        save(plan_path, plan)
    provenance = {
        "plan_sha256": sha(plan_path),
        "preregistration_sha256": sha(PREREG),
        "engine_sha256": sha(ENGINE),
        "configuration_sha256": sha(ENGINE_JSON),
        "driver_sha256": sha(Path(__file__)),
    }
    prior = jsonl(pairs_path)
    seen: set[tuple[Any, ...]] = set()
    for row in prior:
        key = pair_key(row)
        assert key not in seen, f"duplicate pair key: {key}"
        seen.add(key)
        assert row["provenance"] == provenance
        assert all(row["safety"][arm]["completed_720"] for arm in ("control", "treatment"))
    required = required_hashes(candidate_id, sources)
    required[str(plan_path)] = sha(plan_path)
    tasks = []
    for source_id in sources:
        for seed in seeds:
            for seat in (0, 1):
                wanted = (candidate_id, data["source_sha256"], core, source_id, seed, seat)
                if wanted in seen:
                    continue
                control_main = CANDIDATES["V111"]["main"]
                treatment_main = data["main"]
                if phase == "aa":
                    control_main = treatment_main
                tasks.append(
                    {
                        "control_main": str(control_main),
                        "treatment_main": str(treatment_main),
                        "opponent_main": str(OLD_SOURCES[source_id]),
                        "seed": seed,
                        "seat": seat,
                        "episode_steps": 720,
                        "phase": phase,
                        "lineage_id": source_id,
                        "opponent_name": source_id,
                        "opponent_tier": "frozen old public source",
                        "meta_weight": 1 / len(sources),
                        "intended_action_step": 0,
                        "inherited_transaction_step": 248,
                        "intervention_kind": "complete_policy",
                        "strict_all_step_safety": True,
                        "save_all_replays": True,
                        "replay_dir": str(folder / "replays" / phase),
                        "isolate_packages": ["kaggriculture"],
                        "provenance": provenance,
                        "required_file_hashes": required,
                    }
                )
    update_manifest(f"{candidate_id}:{phase}", "RUNNING")
    started = time.perf_counter()

    def progress(done: int, total: int, row: dict[str, Any]) -> None:
        row.update(
            {
                "candidate_id": candidate_id,
                "candidate_source_sha256": data["source_sha256"],
                "candidate_package_sha256": data["package_sha256"],
                "evaluation_core_sha256": core,
            }
        )
        key = pair_key(row)
        if key in seen:
            raise RuntimeError(f"duplicate completed pair key: {key}")
        seen.add(key)
        append(pairs_path, row)
        save(
            folder / "progress" / f"{phase}.json",
            {
                "updated_at": now(),
                "completed_new": done,
                "total_new": total,
                "reused": len(prior),
                "last_pair_key": list(key),
                "elapsed_seconds": time.perf_counter() - started,
            },
        )
        print(
            json.dumps(
                {
                    "candidate": candidate_id,
                    "phase": phase,
                    "done": done,
                    "total": total,
                    "source": row["lineage_id"],
                    "seed": row["seed"],
                    "seat": row["seat"],
                    "C": row["control"]["result"],
                    "T": row["treatment"]["result"],
                    "safety": row["candidate_new_major_regressions"],
                }
            ),
            flush=True,
        )

    completed = run_tasks(tasks, workers, progress)
    elapsed = time.perf_counter() - started
    append(
        runs_path,
        {
            "finished_at": now(),
            "pid": os.getpid(),
            "workers": workers,
            "new_pairs": len(completed),
            "reused_pairs": len(prior),
            "wall_seconds": elapsed,
        },
    )
    all_rows = jsonl(pairs_path)
    expected = len(sources) * len(seeds) * 2
    if len(all_rows) != expected or len({pair_key(row) for row in all_rows}) != expected:
        raise RuntimeError(f"incomplete/duplicate phase: {len(all_rows)} != {expected}")
    transitions = Counter(row["control"]["result"] + "->" + row["treatment"]["result"] for row in all_rows)
    summary = {
        "created_at": now(),
        "candidate": candidate_id,
        "phase": phase,
        "contexts": len(all_rows),
        "completed_720": sum(
            all(row["safety"][arm]["completed_720"] for arm in ("control", "treatment")) for row in all_rows
        ),
        "runtime_or_delivery_failures": sum(
            bool(row["candidate_incident_classification"]["treatment_delivery_failure"]) for row in all_rows
        ),
        "raw_safety_contexts": sum(bool(row["candidate_new_major_regressions"]) for row in all_rows),
        "raw_safety_reasons": dict(
            Counter(reason for row in all_rows for reason in row["candidate_new_major_regressions"])
        ),
        "transitions": dict(transitions),
        "control_wdl": dict(Counter(row["control"]["result"] for row in all_rows)),
        "treatment_wdl": dict(Counter(row["treatment"]["result"] for row in all_rows)),
        "paired_win_score_delta": sum(row["delta_win_score"] for row in all_rows) / len(all_rows),
    }
    if phase == "aa":
        comparisons = []
        for row in all_rows:
            left = Path(row["replay_artifacts"]["control"])
            right = Path(row["replay_artifacts"]["treatment"])
            comparisons.append(
                {
                    "source": row["lineage_id"],
                    "seed": row["seed"],
                    "seat": row["seat"],
                    "public_arm_equal": row["control"] == row["treatment"],
                    "all_semantic_states_actions_equal": semantic_replay(left) == semantic_replay(right),
                    "control_replay_sha256": sha(left),
                    "repeat_replay_sha256": sha(right),
                }
            )
        summary["aa"] = comparisons
        summary["passed"] = all(
            item["public_arm_equal"] and item["all_semantic_states_actions_equal"] for item in comparisons
        )
        if not summary["passed"]:
            raise RuntimeError(f"A/A failed for {candidate_id}")
    save(summary_path, summary)
    update_manifest(f"{candidate_id}:{phase}", "COMPLETE")
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def run_screen_game(task: dict[str, Any]) -> dict[str, Any]:
    from scripts.evaluation.runner import _run_game, _write_replay
    from scripts.evaluation.safety import analyze_safety

    for filename, digest in task["required_file_hashes"].items():
        if sha(filename) != digest:
            raise ValueError(f"screen input changed: {filename}")
    game = _run_game(
        Path(task["control_main"]),
        Path(task["opponent_main"]),
        int(task["seed"]),
        int(task["seat"]),
        720,
        "independent_screen",
        tuple(task.get("isolate_packages", ())),
    )
    replay_path = Path(task["replay_path"])
    _write_replay(replay_path, game["replay"])
    safety = analyze_safety(game["replay"], int(task["seat"]), game["trace"], transaction_step=248, intervention_step=0)
    return {
        "source": task["source"],
        "source_sha256": task["source_sha256"],
        "ancestry": task["ancestry"],
        "priority": task["priority"],
        "seed": task["seed"],
        "seat": task["seat"],
        "control": {
            key: game[key] for key in ("ours", "theirs", "margin", "score", "result", "final_statuses", "resolved_seed")
        },
        "completed_720": safety["completed_720"],
        "agent_exceptions": game["trace"]["agent_exceptions"],
        "replay": str(replay_path),
        "replay_sha256": sha(replay_path),
        "provenance": task["provenance"],
        "execution_seconds": task.get("execution_seconds"),
    }


def screen(workers: int) -> None:
    folder = EXP / "independent_screen"
    pairs_path = folder / "pairs.jsonl"
    core = composite_hash(core_hashes())
    plan = {
        "created_at": now(),
        "sources": list(SCREEN_SOURCES),
        "seeds": [10091011, 10091012, 10091013, 10091014],
        "seats": [0, 1],
        "control_sha256": CANDIDATES["V111"]["source_sha256"],
        "evaluation_core_sha256": core,
        "pre_results_audit_sha256": sha(EXP / "independent_source_audit_pre_results.json"),
        "driver_sha256": sha(Path(__file__)),
    }
    plan_path = folder / "plan.json"
    if plan_path.exists():
        existing = read(plan_path)
        plan["created_at"] = existing["created_at"]
        assert existing == plan
    else:
        save(plan_path, plan)
    provenance = {
        "plan_sha256": sha(plan_path),
        "pre_results_audit_sha256": plan["pre_results_audit_sha256"],
        "engine_sha256": sha(ENGINE),
        "configuration_sha256": sha(ENGINE_JSON),
    }
    prior = jsonl(pairs_path)
    seen = set()
    for row in prior:
        key = (row["source"], row["source_sha256"], row["seed"], row["seat"])
        assert key not in seen and row["provenance"] == provenance
        seen.add(key)
    tasks = []
    for source_id, data in SCREEN_SOURCES.items():
        source_digest = sha(data["main"])
        required = {
            str(ENGINE): sha(ENGINE),
            str(ENGINE_JSON): sha(ENGINE_JSON),
            str(PREREG): sha(PREREG),
            str(plan_path): sha(plan_path),
            str(data["main"]): source_digest,
            str(CANDIDATES["V111"]["main"]): sha(CANDIDATES["V111"]["main"]),
        }
        if source_id == "robriculture_lean_feed":
            runtime = data["main"].parent
            required.update(
                {
                    str(path): sha(path)
                    for path in runtime.rglob("*")
                    if path.is_file() and "__pycache__" not in path.parts
                }
            )
        for seed in plan["seeds"]:
            for seat in plan["seats"]:
                key = (source_id, source_digest, seed, seat)
                if key in seen:
                    continue
                tasks.append(
                    {
                        "source": source_id,
                        "source_sha256": source_digest,
                        "ancestry": data["ancestry"],
                        "priority": data["priority"],
                        "control_main": str(CANDIDATES["V111"]["main"]),
                        "opponent_main": str(data["main"]),
                        "seed": seed,
                        "seat": seat,
                        "isolate_packages": ["kaggriculture", *data["isolate"]],
                        "replay_path": str(folder / "replays" / source_id / f"seed_{seed}_seat_{seat}.json.gz"),
                        "required_file_hashes": required,
                        "provenance": provenance,
                    }
                )
    update_manifest("independent_source_screen", "RUNNING")
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(run_screen_game, task) for task in tasks]
        for done, future in enumerate(as_completed(futures), 1):
            row = future.result()
            key = (row["source"], row["source_sha256"], row["seed"], row["seat"])
            if key in seen:
                raise RuntimeError(f"duplicate screen key {key}")
            seen.add(key)
            append(pairs_path, row)
            print(
                json.dumps(
                    {
                        "screen": done,
                        "total": len(tasks),
                        "source": row["source"],
                        "seed": row["seed"],
                        "seat": row["seat"],
                        "result": row["control"]["result"],
                    }
                ),
                flush=True,
            )
    append(
        folder / "runs.jsonl",
        {
            "finished_at": now(),
            "new_contexts": len(tasks),
            "reused": len(prior),
            "workers": workers,
            "wall_seconds": time.perf_counter() - started,
        },
    )
    all_rows = jsonl(pairs_path)
    if (
        len(all_rows) != 24
        or len({(row["source"], row["source_sha256"], row["seed"], row["seat"]) for row in all_rows}) != 24
    ):
        raise RuntimeError("independent screen incomplete or duplicated")
    results = []
    for source_id, data in SCREEN_SOURCES.items():
        selected = [row for row in all_rows if row["source"] == source_id]
        score = sum(row["control"]["score"] for row in selected) / len(selected)
        results.append(
            {
                "source": source_id,
                "ancestry": data["ancestry"],
                "priority": data["priority"],
                "contexts": len(selected),
                "wdl": dict(Counter(row["control"]["result"] for row in selected)),
                "v111_win_score": score,
                "mean_margin": sum(row["control"]["margin"] for row in selected) / len(selected),
                "completed_720": all(row["completed_720"] for row in selected),
                "native_runtime_ok": not any(row["agent_exceptions"] for row in selected),
                "qualifies_25_75": 0.25 <= score <= 0.75
                and all(row["completed_720"] for row in selected)
                and not any(row["agent_exceptions"] for row in selected),
            }
        )
    qualifying = sorted(
        (row for row in results if row["qualifies_25_75"]), key=lambda row: (row["priority"], row["source"])
    )
    selected_sources = qualifying[:2]
    output = {
        "created_at": now(),
        "primary_results_available_at_selection": False,
        "selection_rule_sha256": sha(EXP / "independent_source_audit_pre_results.json"),
        "screen_results": results,
        "selected": [row["source"] for row in selected_sources],
        "selected_ancestries": [row["ancestry"] for row in selected_sources],
        "diversity_status": "ADEQUATE" if selected_sources else "INSUFFICIENT",
        "final_status_cap": None if selected_sources else "PROMISING_UNPROVEN",
        "robriculture_anchor_is_not_strong_third_ancestry": "robriculture_lean_feed"
        in [row["source"] for row in selected_sources],
    }
    save(folder / "selection.json", output)
    update_manifest("independent_source_screen", "COMPLETE")
    print(json.dumps(output, ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "aa", "screen", "smoke", "spent"))
    parser.add_argument("--candidate", choices=tuple(CANDIDATES))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.command == "validate":
        validate()
        return
    if args.command == "screen":
        screen(args.workers)
        return
    if args.command == "aa":
        if not args.candidate:
            raise SystemExit("--candidate is required")
        run_candidate_phase(args.candidate, "aa", ["qeinstein_moev2"], [10091011], args.workers)
        return
    if args.candidate not in {"D1_e052a_no_opponent_tape", "P1_psr_clean"}:
        raise SystemExit("smoke/spent requires D1 or P1")
    if args.command == "smoke":
        run_candidate_phase(args.candidate, "smoke", ["qeinstein_moev2", "souvik_v4"], [10091011], args.workers)
    else:
        run_candidate_phase(
            args.candidate, "spent", list(OLD_SOURCES), [10091011, 10091012, 10091013, 10091014], args.workers
        )


if __name__ == "__main__":
    main()
