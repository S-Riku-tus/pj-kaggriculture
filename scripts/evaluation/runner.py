"""Archive-only paired Gold-opponent runner."""

from __future__ import annotations

import gzip
import importlib.util
import inspect
import json
import os
import tarfile
import uuid
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from kaggle_environments import make

from .divergence import audit_pair
from .replay import lineage_hash, resolved_seed, result_label, result_score
from .safety import analyze_safety, classify_candidate_incidents


def extract_archive(archive: Path, target: Path) -> None:
    if target.exists():
        raise FileExistsError(f"archive target already exists: {target}")
    target.mkdir(parents=True)
    with tarfile.open(archive, "r:gz") as handle:
        root = target.resolve()
        for member in handle.getmembers():
            destination = (target / member.name).resolve()
            if not destination.is_relative_to(root):
                raise ValueError(f"unsafe archive entry: {member.name}")
        handle.extractall(target)
    if not (target / "main.py").is_file():
        raise FileNotFoundError(f"archive did not contain main.py: {archive}")


def _import_module(path: Path, role: str):
    name = f"_kaggriculture_eval_{role}_{os.getpid()}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import agent module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if hasattr(module, "reset_runtime_state"):
        module.reset_runtime_state()
    return module


def _call(function: Callable[..., Any], obs: Any, configuration: Any) -> Any:
    try:
        parameters = inspect.signature(function).parameters.values()
        accepts_configuration = any(
            parameter.kind in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD}
            for parameter in parameters
        ) or len(list(parameters)) >= 2
    except (TypeError, ValueError):
        accepts_configuration = True
    return function(obs, configuration) if accepts_configuration else function(obs)


def _trace_agent(module: Any, trace: dict[str, Any]):
    def wrapped(obs: Any, configuration: Any = None):
        try:
            emitted = _call(module.agent, obs, configuration)
            diagnostics = (
                module.policy_diagnostics(obs) if hasattr(module, "policy_diagnostics") else {}
            )
            diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
            if diagnostics.get("research_decision") is not None:
                trace["research_decision"] = diagnostics["research_decision"]
            step = int(diagnostics.get("canonical_step", getattr(obs, "step", 0)) or 0)
            goal = diagnostics.get("generalized_goal")
            if goal is not None and not trace.get("generalized_goal_requested"):
                trace["generalized_goal_requested"] = True
                trace["generalized_goal"] = goal
                trace["generalized_goal_step"] = step
            model = diagnostics.get("last_v113_model")
            if model is not None:
                trace["last_v113_model"] = model
            counts = diagnostics.get("strategy_decision_counts") or {}
            if isinstance(counts, dict):
                trace["strategy_counts"] = {str(key): int(value) for key, value in counts.items()}
            fallback = bool(diagnostics.get("fallback_latched")) or bool(
                diagnostics.get("strategy_fallback_reason")
            )
            trace["fallback_steps"] += int(fallback)
            trace["ood_steps"] += int(
                diagnostics.get("strategy_fallback_reason") == "strategy-model-ood"
            )
            if diagnostics.get("strategy_fallback_reason"):
                trace["fallback_reasons"].append(
                    {"step": step, "reason": diagnostics["strategy_fallback_reason"]}
                )
            trace["last_diagnostics"] = {
                key: diagnostics.get(key)
                for key in (
                    "version",
                    "strategic_policy",
                    "generalized_animal_gate_enabled",
                    "generalized_animal_tilt",
                    "premium_first_enabled",
                    "fallback_latched",
                    "strategy_fallback_reason",
                )
                if key in diagnostics
            }
            return emitted
        except Exception as exc:
            trace["agent_exceptions"].append(
                {"type": type(exc).__name__, "message": str(exc)}
            )
            raise

    return wrapped


def _run_game(
    agent_main: Path,
    opponent_main: Path,
    seed: int,
    seat: int,
    episode_steps: int,
    role: str,
) -> dict[str, Any]:
    module = _import_module(agent_main, role)
    opponent = _import_module(opponent_main, f"opponent_{role}")
    trace: dict[str, Any] = {
        "generalized_goal_requested": False,
        "generalized_goal": None,
        "generalized_goal_step": None,
        "last_v113_model": None,
        "strategy_counts": {},
        "fallback_steps": 0,
        "ood_steps": 0,
        "fallback_reasons": [],
        "agent_exceptions": [],
        "last_diagnostics": {},
    }
    focal = _trace_agent(module, trace)

    def opposing(obs: Any, configuration: Any = None):
        return _call(opponent.agent, obs, configuration)

    env = make(
        "kaggriculture",
        configuration={"episodeSteps": episode_steps, "seed": seed},
        debug=True,
    )
    env.run([focal, opposing] if seat == 0 else [opposing, focal])
    replay = env.toJSON()
    final = env.steps[-1]
    rewards = [float(state.reward or 0.0) for state in final]
    ours = rewards[seat]
    theirs = rewards[1 - seat]
    score = result_score(ours, theirs)
    return {
        "requested_seed": seed,
        "resolved_seed": resolved_seed(replay, seed),
        "seat": seat,
        "ours": ours,
        "theirs": theirs,
        "margin": ours - theirs,
        "score": score,
        "result": result_label(score),
        "final_statuses": [str(state.status) for state in final],
        "trace": trace,
        "replay": replay,
    }


def _write_replay(path: Path, replay: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(replay, handle, ensure_ascii=False, separators=(",", ":"))
    return str(path)


def _public_arm(game: dict[str, Any]) -> dict[str, Any]:
    return {
        key: game[key]
        for key in (
            "requested_seed",
            "resolved_seed",
            "seat",
            "ours",
            "theirs",
            "margin",
            "score",
            "result",
            "final_statuses",
        )
    }


def run_pair_task(task: dict[str, Any]) -> dict[str, Any]:
    seed = int(task["seed"])
    seat = int(task["seat"])
    control = _run_game(
        Path(task["control_main"]),
        Path(task["opponent_main"]),
        seed,
        seat,
        int(task["episode_steps"]),
        "control",
    )
    treatment = _run_game(
        Path(task["treatment_main"]),
        Path(task["opponent_main"]),
        seed,
        seat,
        int(task["episode_steps"]),
        "treatment",
    )
    gate_requested = bool(treatment["trace"]["generalized_goal_requested"])
    intervention_kind = task.get("intervention_kind", "cow_to_sheep")
    if intervention_kind == "route_choice":
        gate_requested = bool(treatment["trace"].get("research_decision", {}).get("committed"))
    divergence = audit_pair(
        control["replay"],
        treatment["replay"],
        seat,
        gate_requested=gate_requested,
        intended_action_step=int(task["intended_action_step"]),
        intervention_kind=intervention_kind,
    )
    control_safety = analyze_safety(
        control["replay"], seat, control["trace"], transaction_step=int(task["intended_action_step"])
    )
    treatment_safety = analyze_safety(
        treatment["replay"],
        seat,
        treatment["trace"],
        transaction_step=int(task["intended_action_step"]),
    )
    incidents = classify_candidate_incidents(control_safety, treatment_safety)
    if task.get("strict_all_step_safety"):
        for key in ("silent_field_noop", "silent_market_noop", "partial_market_commit", "missing_hand_actions"):
            left = int(control_safety["engine_action_audit"].get(key, 0))
            right = int(treatment_safety["engine_action_audit"].get(key, 0))
            if right > left:
                incidents["hard_safety_failures"].append(f"new_all_step_{key}")
        incidents["hard_safety_failure"] = bool(incidents["hard_safety_failures"])
    regressions = incidents["hard_safety_failures"]
    delivery_failures = incidents["treatment_delivery_failures"]
    save_replays = bool(
        divergence["first_focal_action"] or regressions or delivery_failures
    )
    replay_artifacts: dict[str, str] = {}
    if save_replays:
        base = (
            Path(task["replay_dir"])
            / str(task["phase"])
            / str(task["lineage_id"])
            / f"seed_{seed}_seat_{seat}"
        )
        replay_artifacts = {
            "control": _write_replay(base / "control.json.gz", control["replay"]),
            "treatment": _write_replay(base / "treatment.json.gz", treatment["replay"]),
        }
    if not regressions:
        control_safety["engine_action_examples"] = control_safety["engine_action_examples"][:10]
        treatment_safety["engine_action_examples"] = treatment_safety["engine_action_examples"][:10]
    control_public = _public_arm(control)
    treatment_public = _public_arm(treatment)
    pre_intervention_checkpoint = int(task["intended_action_step"])
    pair = {
        "phase": task["phase"],
        "lineage_id": task["lineage_id"],
        "opponent_name": task["opponent_name"],
        "opponent_tier": task["opponent_tier"],
        "meta_weight": float(task["meta_weight"]),
        "seed": seed,
        "seat": seat,
        "control": control_public,
        "treatment": treatment_public,
        "delta_self_coin": treatment_public["ours"] - control_public["ours"],
        "delta_opponent_coin": treatment_public["theirs"] - control_public["theirs"],
        "delta_margin": treatment_public["margin"] - control_public["margin"],
        "delta_win_score": treatment_public["score"] - control_public["score"],
        "loss_to_win": control_public["result"] == "loss" and treatment_public["result"] == "win",
        "win_to_loss": control_public["result"] == "win" and treatment_public["result"] == "loss",
        "gate_requested": gate_requested,
        "gate_model": treatment["trace"].get("last_v113_model"),
        "incremental_treatment": bool(divergence["incremental_treatment_emitted"]),
        "behavioral_isolation_valid": bool(divergence["behavioral_isolation_valid"]),
        "divergence_audit": divergence,
        "safety": {"control": control_safety, "treatment": treatment_safety},
        "candidate_new_major_regressions": regressions,
        "candidate_incident_classification": incidents,
        "agent_trace": {
            "control": control["trace"],
            "treatment": treatment["trace"],
        },
        "executed_lineages": {
            "control_h200": lineage_hash(control["replay"], seat, 200),
            "treatment_h200": lineage_hash(treatment["replay"], seat, 200),
            "opponent_control_h200": lineage_hash(control["replay"], 1 - seat, 200),
            "opponent_treatment_h200": lineage_hash(treatment["replay"], 1 - seat, 200),
            "pre_intervention_checkpoint": pre_intervention_checkpoint,
            "control_pre_intervention": lineage_hash(
                control["replay"], seat, pre_intervention_checkpoint
            ),
            "treatment_pre_intervention": lineage_hash(
                treatment["replay"], seat, pre_intervention_checkpoint
            ),
            "opponent_control_pre_intervention": lineage_hash(
                control["replay"], 1 - seat, pre_intervention_checkpoint
            ),
            "opponent_treatment_pre_intervention": lineage_hash(
                treatment["replay"], 1 - seat, pre_intervention_checkpoint
            ),
        },
        "replay_artifacts": replay_artifacts,
    }
    return pair


def run_tasks(
    tasks: list[dict[str, Any]],
    workers: int,
    progress: Callable[[int, int, dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    completed = 0
    result: list[dict[str, Any]] = []
    if workers <= 1:
        for task in tasks:
            row = run_pair_task(task)
            result.append(row)
            completed += 1
            if progress:
                progress(completed, len(tasks), row)
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(run_pair_task, task): task for task in tasks}
            for future in as_completed(futures):
                row = future.result()
                result.append(row)
                completed += 1
                if progress:
                    progress(completed, len(tasks), row)
    return sorted(result, key=lambda row: (row["phase"], row["lineage_id"], row["seed"], row["seat"]))
