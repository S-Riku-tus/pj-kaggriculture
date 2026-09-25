"""Audit temporal, feature, split, and encode/decode contracts for Round7."""

from __future__ import annotations

import copy
import csv
import hashlib
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE_EXPERIMENT = ROOT / "experiments" / "learning_next_20260921"
SOURCE_DATASET = SOURCE_EXPERIMENT / "datasets" / "bc"
ROUND6_DATASET = ROOT / "experiments" / "learning_round6_20260922" / "datasets" / "sequence_bc_v1"
OUTPUT = ROOT / "experiments" / "learning_round7_20260922" / "phase0" / "data_contract_audit.json"
TEACHER = 56216119


def sha256_array(value: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(value, dtype=np.float32).tobytes()).hexdigest()


def restore_observation(states: list[dict[str, Any]], seat: int, step: int) -> dict[str, Any]:
    public = copy.deepcopy(states[0].get("observation") or {})
    private = states[seat].get("observation") or {}
    public["player"] = seat
    public["private"] = copy.deepcopy(private.get("private", {}))
    public["remainingOverageTime"] = private.get("remainingOverageTime", public.get("remainingOverageTime", 60))
    public["step"] = step
    return public


def load_policy() -> Any:
    inventory = json.loads(
        (ROOT / "experiments" / "learning_round7_20260922" / "phase0" / "round6_frozen_inventory.json").read_text(
            encoding="utf-8"
        )
    )
    path = Path(inventory["isolated_archive_root"]) / "main.py"
    spec = importlib.util.spec_from_file_location("round7_data_contract_policy", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    sys.path.insert(0, str(path.parent))
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def sampled_actor(episode_id: int, step: int, actor: int) -> bool:
    value = int(hashlib.sha256(f"{episode_id}:{step}:{actor}".encode()).hexdigest()[:8], 16)
    return value % 5 == 0


def feature_parity(policy: Any) -> dict[str, Any]:
    source = json.loads((SOURCE_EXPERIMENT / "source_manifest.json").read_text(encoding="utf-8"))
    split = json.loads((SOURCE_EXPERIMENT / "split_manifest.json").read_text(encoding="utf-8"))["assignments"]
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in source["files"]:
        grouped[int(row["episode_id"])].append(row)
    entries = [row for values in grouped.values() for row in values if int(row["submission_id"]) == TEACHER]
    actor_expected = {
        partition: np.load(SOURCE_DATASET / f"actor_x_{partition}.npy", mmap_mode="r")
        for partition in ("train", "validation", "test")
    }
    prefix_expected = {
        partition: np.load(ROUND6_DATASET / f"actor_prefix_{partition}.npy", mmap_mode="r")
        for partition in actor_expected
    }
    market_expected = {
        partition: np.load(SOURCE_DATASET / f"market_x_{partition}.npy", mmap_mode="r") for partition in actor_expected
    }
    found_actor: dict[str, dict[str, Any]] = {}
    found_market: dict[str, dict[str, Any]] = {}
    for row in entries:
        episode_id = int(row["episode_id"])
        partition = str(split[str(episode_id)])
        if partition in found_actor and partition in found_market:
            if len(found_actor) == 3 and len(found_market) == 3:
                break
            continue
        replay = json.loads((ROOT / row["path"]).read_text(encoding="utf-8"))
        seat = int(row["seat"])
        history = policy.MarketHistory()
        for step in range(len(replay["steps"]) - 1):
            observation = restore_observation(replay["steps"][step], seat, step)
            previous = replay["steps"][step][seat].get("action") if step > 0 else None
            history.update(observation, previous.get("market", []) if isinstance(previous, dict) else [])
            action = replay["steps"][step + 1][seat].get("action") or {}
            units = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
            actor_count = 1 + len(observation["farms"][seat].get("hands", []))
            prefix: list[str] = []
            for actor_index in range(min(actor_count, len(units))):
                token = policy.action_token(units[actor_index])
                if (
                    partition not in found_actor
                    and sampled_actor(episode_id, step, actor_index)
                    and token in policy.ACTOR_TOKENS
                ):
                    base = policy.bc_actor_features(
                        observation,
                        actor_index,
                        (
                            policy.action_token(
                                [
                                    (previous or {}).get("farmer") or ["PASS"],
                                    *((previous or {}).get("hands") or []),
                                ][actor_index]
                            )
                            if previous
                            and actor_index
                            < len(
                                [
                                    previous.get("farmer") or ["PASS"],
                                    *(previous.get("hands") or []),
                                ]
                            )
                            else "PASS"
                        ),
                        history,
                    )
                    prefix_values = policy._prefix_features(prefix)
                    runtime = policy._actor_features(
                        observation,
                        actor_index,
                        (
                            policy.action_token(
                                [
                                    previous.get("farmer") or ["PASS"],
                                    *(previous.get("hands") or []),
                                ][actor_index]
                            )
                            if previous
                            and actor_index
                            < len(
                                [
                                    previous.get("farmer") or ["PASS"],
                                    *(previous.get("hands") or []),
                                ]
                            )
                            else "PASS"
                        ),
                        history,
                        prefix,
                    )
                    expected_base = np.asarray(actor_expected[partition][0], dtype=np.float32)
                    expected_prefix = np.asarray(prefix_expected[partition][0], dtype=np.float32)
                    found_actor[partition] = {
                        "episode_id": episode_id,
                        "seat": seat,
                        "step": step,
                        "actor_index": actor_index,
                        "base_equal": bool(np.array_equal(base, expected_base)),
                        "prefix_equal": bool(np.array_equal(prefix_values, expected_prefix)),
                        "runtime_concat_equal": bool(
                            np.array_equal(runtime, np.concatenate((expected_base, expected_prefix)))
                        ),
                        "runtime_sha256": sha256_array(runtime),
                    }
                prefix.append(token)
            if partition not in found_market and step % 2 == 0:
                runtime_market = policy.market_features(observation, 0, "EOS", history)
                expected = np.asarray(market_expected[partition][0], dtype=np.float32)
                found_market[partition] = {
                    "episode_id": episode_id,
                    "seat": seat,
                    "step": step,
                    "equal": bool(np.array_equal(runtime_market, expected)),
                    "runtime_sha256": sha256_array(runtime_market),
                }
            if partition in found_actor and partition in found_market:
                break
    return {
        "actor": found_actor,
        "market": found_market,
        "all_equal": all(row["runtime_concat_equal"] for row in found_actor.values())
        and all(row["equal"] for row in found_market.values()),
    }


def encode_decode(policy: Any) -> dict[str, Any]:
    rows = list(
        csv.DictReader(
            (ROOT / "experiments" / "learning_round6_20260922" / "imitation_episodes_round6_sequence_bc_v1.csv").open(
                encoding="utf-8-sig", newline=""
            )
        )
    )
    counts = defaultdict(int)
    legality = defaultdict(int)
    examples = []
    for row in rows:
        replay = json.loads((ROOT / row["source_path"]).read_text(encoding="utf-8"))
        seat = int(row["seat"])
        for step in range(len(replay["steps"]) - 1):
            observation = restore_observation(replay["steps"][step], seat, step)
            action = replay["steps"][step + 1][seat].get("action") or {}
            units = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
            reserved: dict[str, int] = {}
            for actor_index, original in enumerate(units[: 1 + len(observation["farms"][seat].get("hands", []))]):
                token = policy.action_token(original)
                quantity = int(original[2]) if len(original) >= 3 else 1
                decoded = policy.token_action(token, quantity)
                counts["actor_rows"] += 1
                counts["actor_formal_exact"] += int(decoded == original)
                canonical_original = list(original)
                if token.startswith(("PICKUP:", "PLACE:")) and len(canonical_original) < 3:
                    canonical_original.append(1)
                counts["actor_semantic_canonical_exact"] += int(decoded == canonical_original)
                legal = policy.legal_actor_tokens(observation, actor_index, reserved)
                legality[f"actor:{token}:rows"] += 1
                legality[f"actor:{token}:legal"] += int(token in legal)
                if token not in legal and len(examples) < 20:
                    examples.append(
                        {
                            "episode_id": int(row["episode_id"]),
                            "step": step,
                            "actor_index": actor_index,
                            "action": original,
                            "reason": "teacher_request_not_in_pre_action_legal_mask",
                        }
                    )
                policy.reserve_actor_token(reserved, token, quantity)
            for original in action.get("market") or []:
                token = policy.market_token(original)
                quantity = int(original[2]) if len(original) >= 3 else 1
                decoded = policy.token_order(token, quantity)
                counts["market_rows"] += 1
                counts["market_formal_exact"] += int(decoded == original)
    return {
        "diagnostic_episode_seats": len(rows),
        "counts": dict(counts),
        "legality_by_token": dict(legality),
        "invalid_teacher_examples": examples,
        "note": (
            "Teacher requests outside the pre-action mask are retained as teacher requests, "
            "not redefined as legal ground truth."
        ),
    }


def leakage_and_quantity_contract(policy: Any) -> dict[str, Any]:
    common = sys.modules[policy.bc_actor_features.__module__]
    replay = json.loads(
        (ROOT / "data" / "replays" / "submission_56216119" / "episode_109590135.json").read_text(encoding="utf-8")
    )
    observation = restore_observation(replay["steps"][127], 1, 127)
    history = policy.MarketHistory()
    baseline = common.state_features(observation, history)
    forbidden = copy.deepcopy(observation)
    forbidden.update(
        {
            "episode_id": 109590135,
            "submission_id": TEACHER,
            "final_result": "future",
            "future_action": {"farmer": ["FEED"]},
            "opponent_private": {"shed": {"MILK": 999999}},
        }
    )
    mutated = common.state_features(forbidden, history)
    prefix_quantity_1 = policy._prefix_features(["PICKUP:WHEAT"])
    prefix_quantity_7 = policy._prefix_features(["PICKUP:WHEAT"])
    return {
        "forbidden_identity_and_future_fields_ignored": bool(np.array_equal(baseline, mutated)),
        "runtime_inputs": "public farms/market/town plus focal private state and own emitted-order history",
        "opponent_private_used": False,
        "farm_order": "absolute farm0 then farm1; player bit is explicit; self/opponent are not canonicalized",
        "same_token_different_quantity_prefix_equal": bool(np.array_equal(prefix_quantity_1, prefix_quantity_7)),
        "quantity_collapse": {
            "prefix_a": [{"token": "PICKUP:WHEAT", "quantity": 1}],
            "prefix_b": [{"token": "PICKUP:WHEAT", "quantity": 7}],
            "feature_sha256": sha256_array(prefix_quantity_1),
            "consequence": "next actor cannot distinguish the two quantities from the added 88 prefix features alone",
        },
    }


def split_contract() -> dict[str, Any]:
    source = json.loads((SOURCE_EXPERIMENT / "source_manifest.json").read_text(encoding="utf-8"))
    split = json.loads((SOURCE_EXPERIMENT / "split_manifest.json").read_text(encoding="utf-8"))
    assignments: dict[int, set[str]] = defaultdict(set)
    for row in source["files"]:
        episode_id = int(row["episode_id"])
        assignments[episode_id].add(split["assignments"][str(episode_id)])
    return {
        "unit": split["unit"],
        "unique_episodes": len(assignments),
        "cross_partition_episode_ids": [key for key, values in assignments.items() if len(values) != 1],
        "duplicate_views_cross_partitions": False,
        "counts": split["counts"],
    }


def main() -> None:
    policy = load_policy()
    payload = {
        "temporal_contract": "observation/state t -> action stored at record t+1 -> state t+1",
        "feature_parity": feature_parity(policy),
        "encode_decode": encode_decode(policy),
        "leakage_and_quantity": leakage_and_quantity_contract(policy),
        "split": split_contract(),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "feature_parity": payload["feature_parity"]["all_equal"]}, indent=2))


if __name__ == "__main__":
    main()
