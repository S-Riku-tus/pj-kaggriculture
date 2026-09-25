"""Audit raw decode, frozen-policy correction, and Round7 runtime stages."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import shutil
import sys
import tarfile
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evaluate_round6_imitation import (  # noqa: E402
    _action_token,
    _market_token,
    _prime_teacher_history,
    _quantity,
    _raw_prediction,
    _selected_teacher_rows,
    _units,
    restore_observation,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_wrapper(path: Path):
    for name in ("policy", "runtime", "common", "model_compat", "round7_stage_wrapper"):
        sys.modules.pop(name, None)
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location("round7_stage_wrapper", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def snapshot(policy: Any, runtime: Any | None) -> dict[str, Any]:
    # Raw and frozen-policy stages mutate only policy state.  Runtime plans and
    # trace are advanced exactly once by the final packaged call and must not be
    # deep-copied each turn (the trace grows throughout an episode).
    return {
        f"policy:{name}": copy.deepcopy(getattr(policy, name))
        for name in ("_history", "_previous_market", "_previous_actor", "_probes", "_stats")
    }


def restore(policy: Any, runtime: Any | None, state: dict[str, Any]) -> None:
    for key, value in state.items():
        owner, name = key.split(":", 1)
        setattr(policy if owner == "policy" else runtime, name, copy.deepcopy(value))


def quantity_bin(action: list[Any]) -> str:
    quantity = _quantity(action)
    if quantity >= 15:
        return ">=15"
    if quantity >= 10:
        return "10-14"
    if quantity >= 2:
        return "2-9"
    return "1"


def update_metric(counter: Counter[str], predicted: Any, teacher: Any) -> None:
    counter["total"] += 1
    counter["exact"] += int(predicted == teacher)


def rates(groups: dict[str, Counter[str]]) -> dict[str, Any]:
    return {
        key: {
            "total": int(value["total"]),
            "exact": int(value["exact"]),
            "accuracy": value["exact"] / max(1, value["total"]),
        }
        for key, value in sorted(groups.items())
    }


def model_evidence(policy: Any, observation: dict[str, Any], extracted: Path) -> dict[str, Any]:
    policy.reset_runtime_state()
    seat = int(observation["player"])
    history = policy._history.setdefault(seat, policy.MarketHistory())
    history.update(observation, None)
    features = policy._actor_features(observation, 0, "PASS", history, [])
    probabilities = policy.ACTOR_MODEL.probabilities(features)
    result: dict[str, Any] = {
        "actor_feature_sha256": hashlib.sha256(features.astype(np.float32).tobytes()).hexdigest(),
        "actor_probability_sha256": hashlib.sha256(probabilities.astype(np.float32).tobytes()).hexdigest(),
        "actor_selected_class": policy.ACTOR_MODEL.classes[int(probabilities.argmax())],
        "actor_selected_probability": float(probabilities.max()),
        "models": {},
    }
    for name, model in (
        ("actor_token", policy.ACTOR_MODEL),
        ("market_token", policy.MARKET_MODEL),
        ("actor_quantity", policy.ACTOR_QUANTITY_MODEL),
        ("market_quantity", policy.MARKET_QUANTITY_MODEL),
    ):
        path = Path(model.path)
        layers = getattr(model, "layers", None)
        if layers is None:
            shapes = [list(model.w1.shape), list(model.w2.shape)]
        else:
            shapes = [list(weight.shape) for weight, _bias in layers]
        result["models"][name] = {
            "path_inside_fresh_extraction": str(path.relative_to(extracted)),
            "sha256": sha256(path),
            "loader_class": type(model).__name__,
            "weight_shapes": shapes,
        }
    return result


def audit(archive: Path, output: Path) -> None:
    temp_parent = ROOT.parent / ".round7_tmp"
    temp_parent.mkdir(parents=True, exist_ok=True)
    extracted = Path(tempfile.mkdtemp(prefix="round7_stage_audit_", dir=temp_parent))
    try:
        with tarfile.open(archive, "r:gz") as stream:
            stream.extractall(extracted, filter="data")
        wrapper = load_wrapper(extracted / "main.py")
        policy = sys.modules["policy"]
        runtime = sys.modules.get("runtime")
        selected = _selected_teacher_rows()
        grouped: dict[str, Counter[str]] = defaultdict(Counter)
        transitions: dict[str, Counter[str]] = defaultdict(Counter)
        episode_rows = []
        evidence = None
        for episode_number, row in enumerate(selected, 1):
            replay_path = ROOT / row["path"]
            if sha256(replay_path) != row["sha256"]:
                raise RuntimeError(f"teacher hash mismatch: {replay_path}")
            replay = json.loads(replay_path.read_text(encoding="utf-8"))
            seat = int(row["seat"])
            if runtime is not None and hasattr(runtime, "reset_runtime_state"):
                runtime.reset_runtime_state()
            else:
                policy.reset_runtime_state()
            previous_teacher = None
            local_joint = {stage: Counter() for stage in ("raw", "policy_corrected", "round7_final")}
            for step in range(len(replay["steps"]) - 1):
                observation = restore_observation(replay["steps"][step], seat, step)
                if evidence is None:
                    evidence = model_evidence(policy, observation, extracted)
                    if runtime is not None and hasattr(runtime, "reset_runtime_state"):
                        runtime.reset_runtime_state()
                    else:
                        policy.reset_runtime_state()
                teacher = replay["steps"][step + 1][seat].get("action") or {
                    "farmer": ["PASS"],
                    "hands": [],
                    "market": [],
                }
                _prime_teacher_history(policy, seat, previous_teacher)
                initial = snapshot(policy, runtime)
                raw = _raw_prediction(policy, observation, seat)["action"]
                restore(policy, runtime, initial)
                corrected = policy.agent(observation, None)
                restore(policy, runtime, initial)
                final = wrapper.agent(observation, None)
                stages = {"raw": raw, "policy_corrected": corrected, "round7_final": final}
                for stage, predicted in stages.items():
                    update_metric(grouped[f"{stage}:joint"], predicted, teacher)
                    update_metric(local_joint[stage], predicted, teacher)
                    predicted_units = _units(predicted)
                    teacher_units = _units(teacher)
                    for index in range(max(len(predicted_units), len(teacher_units))):
                        pred = predicted_units[index] if index < len(predicted_units) else ["PASS"]
                        truth = teacher_units[index] if index < len(teacher_units) else ["PASS"]
                        pred_token = _action_token(policy, pred)
                        truth_token = _action_token(policy, truth)
                        update_metric(grouped[f"{stage}:actor_token"], pred_token, truth_token)
                        update_metric(grouped[f"{stage}:actor_action"], pred, truth)
                        update_metric(grouped[f"{stage}:actor_position:{index}"], pred, truth)
                        update_metric(grouped[f"{stage}:actor_operation:{truth_token}"], pred_token, truth_token)
                        if len(truth) >= 3:
                            update_metric(
                                grouped[f"{stage}:actor_quantity:{quantity_bin(truth)}"],
                                _quantity(pred) if pred_token == truth_token else None,
                                _quantity(truth),
                            )
                    predicted_orders = [list(value) for value in predicted.get("market") or []]
                    teacher_orders = [list(value) for value in teacher.get("market") or []]
                    update_metric(grouped[f"{stage}:market_sequence"], predicted_orders, teacher_orders)
                    for index in range(max(len(predicted_orders), len(teacher_orders)) + 1):
                        pred = predicted_orders[index] if index < len(predicted_orders) else []
                        truth = teacher_orders[index] if index < len(teacher_orders) else []
                        pred_token = _market_token(policy, pred)
                        truth_token = _market_token(policy, truth)
                        update_metric(grouped[f"{stage}:market_token"], pred_token, truth_token)
                        update_metric(grouped[f"{stage}:market_order"], pred, truth)
                        update_metric(grouped[f"{stage}:market_position:{index}"], pred, truth)
                        update_metric(grouped[f"{stage}:market_operation:{truth_token}"], pred_token, truth_token)
                        if len(truth) >= 3:
                            update_metric(
                                grouped[f"{stage}:market_quantity:{quantity_bin(truth)}"],
                                _quantity(pred) if pred_token == truth_token else None,
                                _quantity(truth),
                            )
                for before_name, after_name, reason in (
                    ("raw", "policy_corrected", "legality_inventory_economic_or_sequence_mask"),
                    ("policy_corrected", "round7_final", "round7_ledger_or_task_plan"),
                ):
                    before, after = stages[before_name], stages[after_name]
                    before_units, after_units = _units(before), _units(after)
                    for index in range(max(len(before_units), len(after_units))):
                        left = before_units[index] if index < len(before_units) else ["PASS"]
                        right = after_units[index] if index < len(after_units) else ["PASS"]
                        if left != right:
                            transitions[f"{before_name}->{after_name}:actor"][reason] += 1
                            transitions[f"{before_name}->{after_name}:actor"][f"position:{index}"] += 1
                            transitions[f"{before_name}->{after_name}:actor"][
                                f"operation:{_action_token(policy, left)}->{_action_token(policy, right)}"
                            ] += 1
                            transitions[f"{before_name}->{after_name}:actor"][
                                f"quantity:{quantity_bin(left)}->{quantity_bin(right)}"
                            ] += 1
                    left_orders = before.get("market") or []
                    right_orders = after.get("market") or []
                    for index in range(max(len(left_orders), len(right_orders))):
                        left = left_orders[index] if index < len(left_orders) else []
                        right = right_orders[index] if index < len(right_orders) else []
                        if left != right:
                            transitions[f"{before_name}->{after_name}:market"][reason] += 1
                            transitions[f"{before_name}->{after_name}:market"][f"position:{index}"] += 1
                            transitions[f"{before_name}->{after_name}:market"][
                                f"operation:{_market_token(policy, left)}->{_market_token(policy, right)}"
                            ] += 1
                            transitions[f"{before_name}->{after_name}:market"][
                                f"quantity:{quantity_bin(left)}->{quantity_bin(right)}"
                            ] += 1
                previous_teacher = teacher
            episode_rows.append(
                {
                    "episode_id": int(row["episode_id"]),
                    "seat": seat,
                    "source": str(replay_path.relative_to(ROOT)),
                    "source_sha256": row["sha256"],
                    "decisions": len(replay["steps"]) - 1,
                    **{
                        f"{stage}_joint_accuracy": value["exact"] / max(1, value["total"])
                        for stage, value in local_joint.items()
                    },
                }
            )
            print(f"episode {episode_number}/{len(selected)} {row['episode_id']}", flush=True)
        payload = {
            "created_at_utc": datetime.now(UTC).isoformat(),
            "archive": str(archive.relative_to(ROOT)),
            "archive_sha256": sha256(archive),
            "evaluation_status": "diagnostic_development_old_test_not_checkpoint_selection",
            "teacher_forced_previous_action_history": True,
            "reactive_opponent_or_closed_loop": False,
            "stage_definitions": {
                "raw": "unmasked learned argmax with learned quantity decode",
                "policy_corrected": "frozen learned policy legality/resource/economic correction",
                "round7_final": "packaged Round7 ledger and optional task-plan output",
            },
            "metrics": rates(grouped),
            "transition_counts": {
                key: {name: int(count) for name, count in value.most_common()} for key, value in transitions.items()
            },
            "episodes": episode_rows,
            "learned_weight_runtime_evidence": evidence,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "archive_sha256": payload["archive_sha256"],
                    "raw_joint": payload["metrics"]["raw:joint"],
                    "policy_corrected_joint": payload["metrics"]["policy_corrected:joint"],
                    "round7_final_joint": payload["metrics"]["round7_final:joint"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        shutil.rmtree(extracted)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit(args.archive.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
