"""Evaluate Round9 T1/T2/T3 without conflating the three regimes."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from kaggle_environments import make

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "round9_teacher_reproduction_and_closed_loop_bc_20260923"
DATASET = EXPERIMENT / "trajectory_control_episode_109118332_v1" / "dataset"
REPLAY_PATH = ROOT / "data" / "replays" / "submission_56216119" / "episode_109118332.json"
OUTPUT = EXPERIMENT / "trajectory_t1_t2_t3_v2"
AGENTS = {
    "trajectory_memorizer_seed20260925": ROOT
    / "agents"
    / "round9_teacher_reproduction_and_closed_loop_bc_20260923"
    / "trajectory_memorizer_seed20260925",
    "a2_seed20260924": ROOT / "agents" / "round9_teacher_reproduction_and_closed_loop_bc_20260923" / "a2",
}
MOVE = {"NORTH", "SOUTH", "EAST", "WEST"}
QUANTITY_ACTOR_PREFIX = ("PICKUP:", "PLACE:")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_round9_contract_controls import (  # noqa: E402
    action_metrics,
    canonical_action,
    core_state,
    isolated_step,
    recorded_action,
    restore_observation,
)

sys.path.pop(0)


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_gzip_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))


def plain(value: Any) -> Any:
    return json.loads(json.dumps(value))


def load_agent(directory: Path, label: str):
    for name in ("common", "spatial", "spatial_policy", "policy", "runtime", "model_compat", label):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(label, directory / "main.py")
    if spec is None or spec.loader is None:
        raise ImportError(directory / "main.py")
    sys.path.insert(0, str(directory))
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module, sys.modules["runtime"], sys.modules["spatial_policy"], sys.modules["common"]
    finally:
        sys.path.pop(0)


def predict(model: Any, x: np.ndarray, chunk: int = 2048) -> np.ndarray:
    result = np.empty(len(x), dtype=np.int64)
    for start in range(0, len(x), chunk):
        result[start : start + chunk] = model.logits(np.asarray(x[start : start + chunk])).argmax(axis=1)
    return result


def t1(directory: Path, policy: Any, common: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "regime": "T1 teacher physical state + teacher causal actor/order prefix",
        "teacher_forcing": True,
        "self_generated_physical_state": False,
    }
    predictions: dict[str, np.ndarray] = {}
    truths: dict[str, np.ndarray] = {}
    quantities: dict[str, dict[int, int]] = {}
    for group, model, quantity_model, tokens in (
        ("actor", policy.ACTOR_MODEL, policy.ACTOR_QUANTITY_MODEL, common.ACTOR_TOKENS),
        ("market", policy.MARKET_MODEL, policy.MARKET_QUANTITY_MODEL, common.MARKET_TOKENS),
    ):
        x = np.load(DATASET / f"{group}_x.npy", mmap_mode="r", allow_pickle=False)
        y = np.load(DATASET / f"{group}_y.npy", allow_pickle=False).astype(np.int64)
        q = np.load(DATASET / f"{group}_q.npy", allow_pickle=False).astype(np.int64)
        pred = predict(model, x)
        predictions[group], truths[group] = pred, y
        applicable = np.asarray(
            [
                token.startswith(QUANTITY_ACTOR_PREFIX)
                if group == "actor"
                else token not in {"EOS", "HIRE", "BUY_LAND"}
                for token in tokens
            ],
            dtype=bool,
        )
        rows = np.flatnonzero(applicable[y])
        one_hot = np.zeros((len(rows), len(tokens)), dtype=np.float32)
        one_hot[np.arange(len(rows)), y[rows]] = 1.0
        qx = np.concatenate((np.asarray(x[rows], dtype=np.float32), one_hot), axis=1)
        qpred_class = predict(quantity_model, qx)
        qpred = np.asarray([int(quantity_model.classes[index]) for index in qpred_class], dtype=np.int64)
        quantities[group] = {int(row): int(value) for row, value in zip(rows, qpred, strict=True)}
        token_correct = pred == y
        quantity_correct = np.asarray(
            [quantities[group].get(index, int(q[index])) == int(q[index]) for index in range(len(y))]
        )
        complete = token_correct & quantity_correct
        result[group] = {
            "token": {
                "numerator": int(token_correct.sum()),
                "denominator": len(y),
                "ratio": float(token_correct.mean()),
            },
            "quantity_all_applicable_rows": {
                "numerator": int(sum(quantities[group][int(row)] == int(q[row]) for row in rows)),
                "denominator": len(rows),
                "ratio": float(np.mean([quantities[group][int(row)] == int(q[row]) for row in rows]))
                if len(rows)
                else None,
                "unknown_label_count": 0,
            },
            "complete_command_or_order": {
                "numerator": int(complete.sum()),
                "denominator": len(y),
                "ratio": float(complete.mean()),
            },
            "first_token_error_row": int(np.flatnonzero(~token_correct)[0]) if (~token_correct).any() else None,
        }
        result[f"_{group}_complete"] = complete
    actor_steps = np.load(DATASET / "actor_step.npy", allow_pickle=False)
    market_steps = np.load(DATASET / "market_step.npy", allow_pickle=False)
    actor_complete, market_complete = result.pop("_actor_complete"), result.pop("_market_complete")
    joint = []
    market_lists = []
    for step in range(719):
        actor_rows = np.flatnonzero(actor_steps == step)
        market_rows = np.flatnonzero(market_steps == step)
        actor_ok = bool(actor_complete[actor_rows].all())
        market_ok = bool(market_complete[market_rows].all())
        joint.append(actor_ok and market_ok)
        market_lists.append(market_ok)
    result["ordered_market_list"] = {
        "numerator": int(sum(market_lists)),
        "denominator": 719,
        "ratio": sum(market_lists) / 719,
    }
    result["joint_turn"] = {"numerator": int(sum(joint)), "denominator": 719, "ratio": sum(joint) / 719}
    result["checkpoint_hashes"] = {
        name: sha256(directory / f"{name}.npz")
        for name in ("actor_token", "actor_quantity", "market_token", "market_quantity")
    }
    return result


def counter_metrics(counts: Counter[str]) -> dict[str, Any]:
    def metric(n: str, d: str) -> dict[str, Any]:
        return {
            "numerator": counts[n],
            "denominator": counts[d],
            "ratio": counts[n] / counts[d] if counts[d] else None,
        }

    return {
        "actor_token": metric("actor_token_exact", "actor_total"),
        "actor_complete_command": metric("actor_command_exact", "actor_total"),
        "market_token": metric("market_token_exact", "market_total"),
        "ordered_market_list": metric("market_list_exact", "market_list_total"),
        "joint_turn": metric("joint_exact", "joint_total"),
        "quantity_all_rows": metric("quantity_exact", "quantity_total"),
        "issued_work_commands": counts["predicted_work"],
    }


def t2(replay: dict[str, Any], module: Any, runtime: Any, policy: Any, common: Any, label: str) -> dict[str, Any]:
    runtime.reset_runtime_state()
    policy.reset_runtime_state()
    counts: Counter[str] = Counter()
    actions = []
    first_token_difference = None
    first_effect_difference = None
    effect_equivalent = 0
    differing = 0
    for step in range(len(replay["steps"]) - 1):
        observation = restore_observation(replay["steps"][step], 0, step)
        actor_count = 1 + len(observation["farms"][0].get("hands", []))
        teacher = canonical_action(recorded_action(replay, step, 0), actor_count)
        predicted = canonical_action(module.agent(observation, replay["configuration"]), actor_count)
        actions.append({"step": step, "teacher": teacher, "predicted": predicted})
        counts.update(action_metrics(teacher, predicted, common))
        if teacher == predicted:
            effect_equivalent += 1
            continue
        differing += 1
        equivalent = isolated_step(replay, step, teacher) == isolated_step(replay, step, predicted)
        effect_equivalent += int(equivalent)
        if first_token_difference is None:
            first_token_difference = {"step": step, "teacher": teacher, "predicted": predicted}
        if not equivalent and first_effect_difference is None:
            first_effect_difference = {"step": step, "teacher": teacher, "predicted": predicted}
    diagnostics = plain(runtime.diagnostics())
    write_gzip_json(OUTPUT / f"{label}_t2_actions_and_trace.json.gz", {"actions": actions, "diagnostics": diagnostics})
    return {
        "regime": "T2 teacher physical state + self-generated same-turn prefix/history",
        "teacher_forcing": "physical state only",
        "self_generated_physical_state": False,
        **counter_metrics(counts),
        "state_effect_equivalence": {
            "numerator": effect_equivalent,
            "denominator": 719,
            "ratio": effect_equivalent / 719,
            "official_engine_isolated_differing_turns": differing,
        },
        "first_token_difference": first_token_difference,
        "first_effect_difference": first_effect_difference,
        "trace_file": f"{label}_t2_actions_and_trace.json.gz",
    }


def t3(replay: dict[str, Any], module: Any, runtime: Any, policy: Any, common: Any, label: str) -> dict[str, Any]:
    runtime.reset_runtime_state()
    policy.reset_runtime_state()
    emitted: list[dict[str, Any]] = []

    def focal(observation: Any, configuration: Any = None) -> dict[str, Any]:
        action = plain(module.agent(observation, configuration))
        emitted.append({"step": int(observation.step), "action": action})
        return action

    def opponent(observation: Any, configuration: Any = None) -> dict[str, Any]:
        del configuration
        return recorded_action(replay, int(observation.step), 1)

    configuration = {**replay["configuration"], "seed": int(replay["info"]["seed"])}
    environment = make("kaggriculture", configuration=configuration, info={"seed": int(replay["info"]["seed"])})
    states = environment.run([focal, opponent])
    replay_json = environment.toJSON()
    replay_file = OUTPUT / f"{label}_t3_replay.json.gz"
    write_gzip_json(replay_file, replay_json)
    counts: Counter[str] = Counter()
    first_token_difference = None
    first_state_difference = None
    first_cash_difference = None
    first_sale_difference = None
    exact_state_records = 0
    horizons = {}
    for index, (actual, expected) in enumerate(zip(states, replay["steps"], strict=True)):
        same = core_state(actual) == core_state(expected)
        exact_state_records += int(same)
        if not same and first_state_difference is None:
            first_state_difference = {
                "record_index": index,
                "teacher_cash": expected[0]["observation"]["farms"][0]["money"],
                "learner_cash": actual[0].observation.farms[0].money,
            }
        teacher_cash = expected[0]["observation"]["farms"][0]["money"]
        learner_cash = actual[0].observation.farms[0].money
        if teacher_cash != learner_cash and first_cash_difference is None:
            first_cash_difference = {"record_index": index, "teacher_cash": teacher_cash, "learner_cash": learner_cash}
        if index in {24, 96, 192, 719}:
            horizons[str(index)] = {
                "state_exact_at_horizon": same,
                "teacher_cash": teacher_cash,
                "learner_cash": learner_cash,
            }
    for row in emitted:
        step = row["step"]
        observation = restore_observation(replay["steps"][step], 0, step)
        actor_count = 1 + len(observation["farms"][0].get("hands", []))
        teacher = canonical_action(recorded_action(replay, step, 0), actor_count)
        predicted = canonical_action(row["action"], actor_count)
        counts.update(action_metrics(teacher, predicted, common))
        if teacher != predicted and first_token_difference is None:
            first_token_difference = {"step": step, "teacher": teacher, "predicted": predicted}
        teacher_sells = [order for order in teacher["market"] if order and order[0] == "SELL"]
        predicted_sells = [order for order in predicted["market"] if order and order[0] == "SELL"]
        if teacher_sells != predicted_sells and first_sale_difference is None:
            first_sale_difference = {"step": step, "teacher_sell": teacher_sells, "learner_sell": predicted_sells}
    diagnostics = plain(runtime.diagnostics())
    first_work_failure = None
    for record in diagnostics.get("trace", {}).get("0", diagnostics.get("trace", {}).get(0, [])):
        effect = record.get("effect", {})
        for actor in effect.get("actors", []):
            action = actor.get("action") or []
            if action and action[0] not in MOVE | {"PASS"} and actor.get("success") is False:
                first_work_failure = {"step": record.get("step"), "actor": actor}
                break
        if first_work_failure:
            break
    write_gzip_json(OUTPUT / f"{label}_t3_runtime_trace.json.gz", diagnostics)
    final = states[-1]
    return {
        "regime": "T3 self-generated physical state/history against fixed recorded opponent tape",
        "classification": "REPRODUCTION_DIAGNOSTIC; not unknown-opponent performance",
        "teacher_forcing": False,
        "self_generated_physical_state": True,
        **counter_metrics(counts),
        "state_record_exact": {
            "numerator": exact_state_records,
            "denominator": len(states),
            "ratio": exact_state_records / len(states),
        },
        "horizons": horizons,
        "first_token_difference": first_token_difference,
        "first_state_difference": first_state_difference,
        "first_work_failure": first_work_failure,
        "first_cash_difference": first_cash_difference,
        "first_sale_difference": first_sale_difference,
        "final_rewards": [final[index].reward for index in range(2)],
        "final_statuses": [final[index].status for index in range(2)],
        "recorded_teacher_rewards": replay["rewards"],
        "replay_file": str(replay_file.relative_to(EXPERIMENT)),
        "trace_file": f"{label}_t3_runtime_trace.json.gz",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agents", nargs="*", choices=sorted(AGENTS), default=sorted(AGENTS))
    args = parser.parse_args()
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty {OUTPUT}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    replay = json.loads(REPLAY_PATH.read_text(encoding="utf-8"))
    summaries = {}
    for label in args.agents:
        directory = AGENTS[label]
        module, runtime, policy, common = load_agent(directory, f"round9_t123_{label}")
        stage1 = t1(directory, policy, common)
        stage2 = t2(replay, module, runtime, policy, common, label)
        # Reload to guarantee T3 cannot inherit T2 module state.
        module, runtime, policy, common = load_agent(directory, f"round9_t123_free_{label}")
        stage3 = t3(replay, module, runtime, policy, common, label)
        summaries[label] = {"T1": stage1, "T2": stage2, "T3": stage3}
        write_json(OUTPUT / f"{label}_summary.json", summaries[label])
    write_json(
        OUTPUT / "summary.json",
        {
            "created_at_utc": now(),
            "source_episode": 109118332,
            "source_replay": str(REPLAY_PATH.relative_to(ROOT)),
            "source_replay_sha256": sha256(REPLAY_PATH),
            "stages": summaries,
            "new_learning_runs": 0,
            "new_real_opponent_games": 0,
            "kaggle_submissions": 0,
        },
    )


if __name__ == "__main__":
    main()
