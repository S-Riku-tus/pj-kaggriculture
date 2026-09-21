"""Reproducible data/build/train/deploy CLI for the learning-next study.

The command is intentionally resumable by task:
  inventory
  build --task b|a|bc
  train --task b|a|bc
  verify --task b|a|bc
  deploy --task b|a|bc

It never submits to Kaggle and never mutates V124/V125/V126 sources.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import time
import traceback
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.learning_next_20260921.common import (  # noqa: E402
    ACTOR_TOKENS,
    CROPS,
    MARKET_TOKENS,
    PRODUCTS,
    WORK_OPS,
    MarketHistory,
    SavedMLP,
    action_token,
    actor_feature_names,
    actor_features,
    bc_actor_feature_names,
    bc_actor_features,
    market_feature_names,
    market_features,
    market_token,
    state_feature_names,
    state_features,
    work_legal_ops,
)

EXPERIMENT = ROOT / "experiments" / "learning_next_20260921"
MODEL_DIR = EXPERIMENT / "models"
DATASET_DIR = EXPERIMENT / "datasets"
AGENT_DIR = ROOT / "agents" / "learning_next_20260921"
SOURCE_IDS = (56216119, 56361903, 56354460)
TEACHER_ID = 56216119
HORIZONS = (1, 4, 24)
TRAIN_SEED = 20260921


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def source_paths(submission_id: int) -> tuple[Path, Path]:
    replay = ROOT / "data" / "replays" / f"submission_{submission_id}"
    manifest = (
        ROOT
        / "data"
        / "submissions"
        / f"leaderboard_20260920_rank{SOURCE_IDS.index(submission_id) + 1}_submission_{submission_id}"
        / "manifest.csv"
    )
    return replay, manifest


def load_source_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for submission_id in SOURCE_IDS:
        replay_root, manifest_path = source_paths(submission_id)
        if not replay_root.is_dir() or not manifest_path.is_file():
            raise FileNotFoundError(f"missing source for submission {submission_id}")
        with manifest_path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                episode_id = int(row["episode_id"])
                path = replay_root / f"episode_{episode_id}.json"
                if not path.is_file():
                    continue
                rows.append(
                    {
                        "submission_id": submission_id,
                        "episode_id": episode_id,
                        "seat": int(row["submission_seat"]),
                        "result": row["result"],
                        "own_reward": float(row["own_reward"]),
                        "opponent_reward": float(row["opponent_reward"]),
                        "step_count": int(row["step_count"]),
                        "path": str(path.relative_to(ROOT)),
                    }
                )
    return rows


def split_assignments(episode_ids: list[int]) -> dict[int, str]:
    ordered = sorted(episode_ids, key=lambda value: hashlib.sha256(f"{TRAIN_SEED}:{value}".encode()).hexdigest())
    n = len(ordered)
    train_end, validation_end = int(n * 0.70), int(n * 0.85)
    return {
        episode_id: "train" if index < train_end else "validation" if index < validation_end else "test"
        for index, episode_id in enumerate(ordered)
    }


def inventory() -> None:
    rows = load_source_rows()
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    files: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        path = ROOT / row["path"]
        entry = dict(row)
        entry.update({"bytes": path.stat().st_size, "sha256": sha256(path)})
        files.append(entry)
        grouped[row["episode_id"]].append(entry)
        if index % 50 == 0:
            print(f"inventory {index}/{len(rows)}", flush=True)
    splits = split_assignments(list(grouped))
    source_manifest = {
        "created_at_utc": utc_now(),
        "source_type": "public Kaggle replay JSON already present locally",
        "submission_view_counts": dict(Counter(str(row["submission_id"]) for row in rows)),
        "source_appearances": len(rows),
        "unique_episodes": len(grouped),
        "duplicate_appearances": len(rows) - len(grouped),
        "files": files,
    }
    split_manifest = {
        "created_at_utc": utc_now(),
        "seed": TRAIN_SEED,
        "unit": "episode_id",
        "rule": "SHA256(seed:episode_id) ordering, first 70% train, next 15% validation, final 15% test",
        "counts": dict(Counter(splits.values())),
        "assignments": {str(key): value for key, value in sorted(splits.items())},
        "duplicate_constraint_verified": all(
            len({splits[row["episode_id"]] for row in values}) == 1 for values in grouped.values()
        ),
    }
    write_json(EXPERIMENT / "source_manifest.json", source_manifest)
    write_json(EXPERIMENT / "split_manifest.json", split_manifest)
    engine = (
        ROOT / ".venv" / "Lib" / "site-packages" / "kaggle_environments" / "envs" / "kaggriculture" / "kaggriculture.py"
    )
    environment = {
        "captured_at_utc": utc_now(),
        "python": sys.version,
        "platform": platform.platform(),
        "logical_cpus": os.cpu_count(),
        "numpy": np.__version__,
        "engine_source": str(engine),
        "engine_sha256": sha256(engine),
        "device": "cpu",
        "torch_available": False,
        "free_disk_bytes": shutil.disk_usage(ROOT).free,
    }
    try:
        import psutil

        environment["ram_total_bytes"] = psutil.virtual_memory().total
        environment["ram_available_bytes"] = psutil.virtual_memory().available
    except ImportError:
        pass
    write_json(EXPERIMENT / "environment.json", environment)
    print(
        json.dumps(
            {"source_appearances": len(rows), "unique_episodes": len(grouped), "splits": split_manifest["counts"]}
        ),
        flush=True,
    )


def load_index() -> tuple[dict[int, list[dict[str, Any]]], dict[int, str]]:
    if not (EXPERIMENT / "source_manifest.json").is_file():
        inventory()
    source = json.loads((EXPERIMENT / "source_manifest.json").read_text(encoding="utf-8"))
    split = json.loads((EXPERIMENT / "split_manifest.json").read_text(encoding="utf-8"))
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in source["files"]:
        grouped[int(row["episode_id"])].append(row)
    return grouped, {int(key): value for key, value in split["assignments"].items()}


def restore_observation(step_states: list[dict[str, Any]], seat: int, step: int) -> dict[str, Any]:
    public = dict(step_states[0].get("observation") or {})
    private_obs = step_states[seat].get("observation") or {}
    public["player"] = seat
    public["private"] = private_obs.get("private", {})
    public["remainingOverageTime"] = private_obs.get("remainingOverageTime", public.get("remainingOverageTime", 60))
    public["step"] = step
    return public


def requested_sells(action: Any) -> dict[str, int]:
    result = {item: 0 for item in PRODUCTS}
    if not isinstance(action, dict):
        return result
    for order in action.get("market") or []:
        if isinstance(order, list | tuple) and len(order) >= 3 and order[0] == "SELL" and order[1] in result:
            try:
                result[str(order[1])] += max(0, int(order[2]))
            except (TypeError, ValueError):
                pass
    return result


def teacher_entries(grouped: dict[int, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [row for values in grouped.values() for row in values if int(row["submission_id"]) == TEACHER_ID]


def _save_arrays(task: str, arrays: dict[str, list[Any]], metadata: dict[str, Any]) -> None:
    target = DATASET_DIR / task
    target.mkdir(parents=True, exist_ok=True)
    shapes: dict[str, list[int]] = {}
    for name, values in arrays.items():
        array = np.asarray(values)
        path = target / f"{name}.npy"
        np.save(path, array, allow_pickle=False)
        shapes[name] = list(array.shape)
        print(f"saved {path.relative_to(ROOT)} {array.shape} {array.dtype}", flush=True)
    metadata["arrays"] = shapes
    metadata["created_at_utc"] = utc_now()
    write_json(target / "dataset_manifest.json", metadata)


def build_b(grouped: dict[int, list[dict[str, Any]]], splits: dict[int, str]) -> None:
    arrays: dict[str, list[Any]] = defaultdict(list)
    mapping_evidence: dict[str, Any] = {}
    for number, (episode_id, appearances) in enumerate(sorted(grouped.items()), 1):
        path = ROOT / appearances[0]["path"]
        replay = json.loads(path.read_text(encoding="utf-8"))
        steps = replay.get("steps") or []
        if len(steps) < 2:
            continue
        known = {int(row["seat"]): str(row["submission_id"]) for row in appearances}
        histories = [MarketHistory(), MarketHistory()]
        split = splits[episode_id]
        sell = np.zeros((2, len(steps), len(PRODUCTS)), dtype=np.float32)
        for action_index in range(1, len(steps)):
            for action_seat in range(2):
                row_sells = requested_sells(steps[action_index][action_seat].get("action"))
                sell[action_seat, action_index] = [row_sells[item] for item in PRODUCTS]
        sell_prefix = np.cumsum(sell, axis=1)
        for step in range(len(steps) - 1):
            for seat in range(2):
                previous_action = steps[step][seat].get("action") if step > 0 else None
                previous_orders = previous_action.get("market", []) if isinstance(previous_action, dict) else []
                observation = restore_observation(steps[step], seat, step)
                histories[seat].update(observation, previous_orders)
                if step % 2:
                    continue
                quantities: list[float] = []
                opponent = 1 - seat
                for item_index, _item in enumerate(PRODUCTS):
                    for horizon in HORIZONS:
                        end = min(len(steps) - 1, step + horizon)
                        amount = sell_prefix[opponent, end, item_index] - sell_prefix[opponent, step, item_index]
                        quantities.append(float(amount))
                arrays[f"x_{split}"].append(state_features(observation, histories[seat]))
                arrays[f"event_{split}"].append([float(value > 0) for value in quantities])
                arrays[f"quantity_{split}"].append(quantities)
                arrays[f"family_{split}"].append(int(known.get(opponent, "0")))
        if number % 20 == 0:
            print(f"B build {number}/{len(grouped)} rows={len(arrays['x_train'])}", flush=True)
        if not mapping_evidence:
            for step in range(min(100, len(steps) - 1)):
                action = steps[step + 1][0].get("action") or {}
                op = (action.get("farmer") or ["PASS"])[0]
                if op in {"NORTH", "SOUTH", "EAST", "WEST", "PICKUP", "HARVEST"} or (step + 1) % 24 == 0:
                    mapping_evidence.setdefault(
                        op if op in {"NORTH", "SOUTH", "EAST", "WEST", "PICKUP", "HARVEST"} else "DAY_BOUNDARY",
                        {"episode_id": episode_id, "observation_index": step, "action_index": step + 1},
                    )
    metadata = {
        "task": "B opponent requested-SELL event and quantity",
        "source_unique_episodes": len(grouped),
        "episode_counts": dict(Counter(splits.values())),
        "row_stride": 2,
        "horizons": list(HORIZONS),
        "products": list(PRODUCTS),
        "label_semantics": "requested SELL quantity from steps[t+1:t+h+1], not claimed executed quantity",
        "feature_count": len(state_feature_names()),
        "mapping_evidence": mapping_evidence,
        "label_distribution": {
            key: int(np.asarray(value).sum()) for key, value in arrays.items() if key.startswith("event_")
        },
    }
    _save_arrays("b", arrays, metadata)


def build_a(grouped: dict[int, list[dict[str, Any]]], splits: dict[int, str]) -> None:
    entries = teacher_entries(grouped)
    arrays: dict[str, list[Any]] = defaultdict(list)
    coverage = Counter()
    label_counts: dict[str, Counter[str]] = defaultdict(Counter)
    priority = (
        "FEED",
        "HARVEST",
        "WATER",
        "CARE",
        "COLLECT_FERTILIZER",
        "FERTILIZE",
        "DROP",
        "PICKUP",
        "PLACE",
        "PLANT",
        "DIG",
    )
    for number, row in enumerate(entries, 1):
        replay = json.loads((ROOT / row["path"]).read_text(encoding="utf-8"))
        steps, seat, episode_id = replay["steps"], int(row["seat"]), int(row["episode_id"])
        split = splits[episode_id]
        history = MarketHistory()
        for step in range(len(steps) - 1):
            observation = restore_observation(steps[step], seat, step)
            previous = steps[step][seat].get("action") if step > 0 else None
            history.update(observation, previous.get("market", []) if isinstance(previous, dict) else [])
            action = steps[step + 1][seat].get("action") or {}
            units = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
            actor_count = 1 + len(observation["farms"][seat].get("hands", []))
            for actor_index in range(min(actor_count, len(units))):
                values = units[actor_index] if isinstance(units[actor_index], list | tuple) else ["PASS"]
                op = str(values[0]) if values else "PASS"
                if op not in WORK_OPS:
                    continue
                coverage["teacher_work_actions"] += 1
                legal = work_legal_ops(observation, actor_index)
                included = op in legal
                coverage["candidate_covered"] += int(included)
                if not included:
                    coverage[f"excluded:{op}"] += 1
                    continue
                baseline = next((candidate for candidate in priority if candidate in legal), op)
                arrays[f"x_{split}"].append(actor_features(observation, actor_index, history))
                arrays[f"y_{split}"].append(WORK_OPS.index(op))
                arrays[f"baseline_{split}"].append(WORK_OPS.index(baseline))
                label_counts[split][op] += 1
        if number % 20 == 0:
            print(f"A build {number}/{len(entries)} rows={len(arrays['x_train'])}", flush=True)
    metadata = {
        "task": "A executable work-task selection",
        "teacher_submission": TEACHER_ID,
        "teacher_episodes": len(entries),
        "episode_counts": dict(Counter(splits[int(row["episode_id"])] for row in entries)),
        "teacher_selection_fixed_before_test": True,
        "classes": list(WORK_OPS),
        "feature_count": len(actor_feature_names()),
        "candidate_coverage": dict(coverage),
        "label_distribution": {split: dict(counts) for split, counts in label_counts.items()},
        "quality_rule": (
            "completed public teacher episodes; only pre-action locally executable work labels; "
            "wins and losses retained without outcome as input"
        ),
    }
    _save_arrays("a", arrays, metadata)


def _sample_actor(episode_id: int, step: int, actor: int) -> bool:
    value = int(hashlib.sha256(f"{episode_id}:{step}:{actor}".encode()).hexdigest()[:8], 16)
    return value % 5 == 0


def build_bc(grouped: dict[int, list[dict[str, Any]]], splits: dict[int, str]) -> None:
    entries = teacher_entries(grouped)
    arrays: dict[str, list[Any]] = defaultdict(list)
    actor_counts: dict[str, Counter[str]] = defaultdict(Counter)
    market_counts: dict[str, Counter[str]] = defaultdict(Counter)
    excluded = Counter()
    eligible_actor = 0
    for number, row in enumerate(entries, 1):
        replay = json.loads((ROOT / row["path"]).read_text(encoding="utf-8"))
        steps, seat, episode_id = replay["steps"], int(row["seat"]), int(row["episode_id"])
        split = splits[episode_id]
        history = MarketHistory()
        for step in range(len(steps) - 1):
            observation = restore_observation(steps[step], seat, step)
            previous = steps[step][seat].get("action") if step > 0 else None
            history.update(observation, previous.get("market", []) if isinstance(previous, dict) else [])
            action = steps[step + 1][seat].get("action") or {}
            units = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
            actor_count = 1 + len(observation["farms"][seat].get("hands", []))
            for actor_index in range(min(actor_count, len(units))):
                eligible_actor += 1
                if not _sample_actor(episode_id, step, actor_index):
                    continue
                token = action_token(units[actor_index])
                if token not in ACTOR_TOKENS:
                    excluded[f"actor:{token}"] += 1
                    continue
                quantity = float(units[actor_index][2]) if len(units[actor_index]) >= 3 else 1.0
                prior_action = steps[step][seat].get("action") if step > 0 else {}
                prior_units = [
                    (prior_action or {}).get("farmer") or ["PASS"],
                    *((prior_action or {}).get("hands") or []),
                ]
                prior_token = action_token(prior_units[actor_index]) if actor_index < len(prior_units) else "PASS"
                arrays[f"actor_x_{split}"].append(bc_actor_features(observation, actor_index, prior_token, history))
                arrays[f"actor_y_{split}"].append(ACTOR_TOKENS.index(token))
                arrays[f"actor_quantity_{split}"].append(quantity)
                actor_counts[split][token] += 1
            if step % 2 == 0:
                orders = action.get("market") or []
                previous_token = "EOS"
                for slot in range(min(10, len(orders)) + 1):
                    order = orders[slot] if slot < len(orders) else []
                    token = market_token(order)
                    if token not in MARKET_TOKENS:
                        excluded[f"market:{token}"] += 1
                        token = "EOS"
                    quantity = float(order[2]) if isinstance(order, list | tuple) and len(order) >= 3 else 1.0
                    arrays[f"market_x_{split}"].append(market_features(observation, slot, previous_token, history))
                    arrays[f"market_y_{split}"].append(MARKET_TOKENS.index(token))
                    arrays[f"market_quantity_{split}"].append(quantity)
                    market_counts[split][token] += 1
                    previous_token = token
                    if token == "EOS":
                        break
        if number % 20 == 0:
            print(
                f"BC build {number}/{len(entries)} actor={len(arrays['actor_x_train'])} "
                f"market={len(arrays['market_x_train'])}",
                flush=True,
            )
    selected_actor = sum(len(value) for key, value in arrays.items() if key.startswith("actor_y_"))
    represented = selected_actor + sum(value for key, value in excluded.items() if key.startswith("actor:"))
    metadata = {
        "task": "independent structured behavioral cloning",
        "teacher_submission": TEACHER_ID,
        "teacher_episodes": len(entries),
        "episode_counts": dict(Counter(splits[int(row["episode_id"])] for row in entries)),
        "actor_classes": list(ACTOR_TOKENS),
        "market_classes": list(MARKET_TOKENS),
        "actor_feature_count": len(bc_actor_feature_names()),
        "actor_history": "previous actor action token one-hot; added after first closed-loop failure",
        "market_feature_count": len(market_feature_names()),
        "actor_eligible_rows": eligible_actor,
        "actor_deterministic_sampled_rows": selected_actor,
        "actor_representation_coverage": represented / max(1, selected_actor + sum(excluded.values())),
        "market_order_preserved": True,
        "excluded": dict(excluded),
        "actor_label_distribution": {split: dict(counts) for split, counts in actor_counts.items()},
        "market_label_distribution": {split: dict(counts) for split, counts in market_counts.items()},
    }
    _save_arrays("bc", arrays, metadata)


def build(task: str) -> None:
    grouped, splits = load_index()
    schema = {
        "created_at_utc": utc_now(),
        "forbidden_inputs": [
            "opponent private",
            "future observations",
            "replay seed",
            "episode id",
            "submission id",
            "final outcome",
            "future rating",
        ],
        "state": state_feature_names(),
        "actor": actor_feature_names(),
        "bc_actor": bc_actor_feature_names(),
        "market": market_feature_names(),
        "clock": "day*24+hour; explicit observation step is not trusted",
    }
    write_json(EXPERIMENT / "feature_schema.json", schema)
    if task == "b":
        build_b(grouped, splits)
    elif task == "a":
        build_a(grouped, splits)
    else:
        build_bc(grouped, splits)


def load_array(task: str, name: str) -> np.ndarray:
    return np.load(DATASET_DIR / task / f"{name}.npy", mmap_mode="r", allow_pickle=False)


def moments(x: np.ndarray, chunk: int = 65536) -> tuple[np.ndarray, np.ndarray]:
    total = np.zeros(x.shape[1], dtype=np.float64)
    square = np.zeros(x.shape[1], dtype=np.float64)
    count = 0
    for start in range(0, len(x), chunk):
        values = np.asarray(x[start : start + chunk], dtype=np.float64)
        total += values.sum(axis=0)
        square += np.square(values).sum(axis=0)
        count += len(values)
    mean = total / max(1, count)
    variance = np.maximum(square / max(1, count) - mean * mean, 1e-6)
    return mean.astype(np.float32), np.sqrt(variance).astype(np.float32)


class Adam:
    def __init__(self, parameters: list[np.ndarray], lr: float = 0.002) -> None:
        self.parameters = parameters
        self.lr = lr
        self.m = [np.zeros_like(value) for value in parameters]
        self.v = [np.zeros_like(value) for value in parameters]
        self.step_count = 0

    def step(self, gradients: list[np.ndarray]) -> None:
        self.step_count += 1
        for index, (parameter, gradient) in enumerate(zip(self.parameters, gradients, strict=True)):
            self.m[index] = 0.9 * self.m[index] + 0.1 * gradient
            self.v[index] = 0.999 * self.v[index] + 0.001 * np.square(gradient)
            corrected_m = self.m[index] / (1.0 - 0.9**self.step_count)
            corrected_v = self.v[index] / (1.0 - 0.999**self.step_count)
            parameter -= self.lr * corrected_m / (np.sqrt(corrected_v) + 1e-8)


def forward(x: np.ndarray, parameters: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    w1, b1, w2, b2 = parameters
    hidden = np.maximum(0.0, x @ w1 + b1)
    return hidden, hidden @ w2 + b2


def save_model(
    path: Path,
    mean: np.ndarray,
    scale: np.ndarray,
    parameters: list[np.ndarray],
    classes: list[str],
    metadata: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        path,
        mean=mean,
        scale=scale,
        w1=parameters[0],
        b1=parameters[1],
        w2=parameters[2],
        b2=parameters[3],
        classes=np.asarray(classes),
    )
    metadata.update({"checkpoint": str(path.relative_to(ROOT)), "sha256": sha256(path), "saved_at_utc": utc_now()})
    write_json(path.with_suffix(".json"), metadata)


def classifier_metrics(model: SavedMLP, x: np.ndarray, y: np.ndarray, chunk: int = 16384) -> dict[str, Any]:
    confusion = np.zeros((len(model.classes), len(model.classes)), dtype=np.int64)
    correct = 0
    for start in range(0, len(x), chunk):
        values = np.asarray(x[start : start + chunk])
        prediction = np.argmax(np.vstack([model.probabilities(row) for row in values]), axis=1)
        truth = np.asarray(y[start : start + chunk], dtype=np.int64)
        correct += int((prediction == truth).sum())
        np.add.at(confusion, (truth, prediction), 1)
    recall = np.diag(confusion) / np.maximum(1, confusion.sum(axis=1))
    return {
        "rows": len(y),
        "accuracy": correct / max(1, len(y)),
        "macro_recall": float(recall.mean()),
        "recall_by_class": {name: float(recall[index]) for index, name in enumerate(model.classes)},
        "confusion": confusion.tolist(),
    }


def train_classifier(task: str, prefix: str, classes: list[str], output_name: str) -> dict[str, Any]:
    x_train, y_train = load_array(task, f"{prefix}x_train"), load_array(task, f"{prefix}y_train")
    x_validation, y_validation = load_array(task, f"{prefix}x_validation"), load_array(task, f"{prefix}y_validation")
    x_test, y_test = load_array(task, f"{prefix}x_test"), load_array(task, f"{prefix}y_test")
    mean, scale = moments(x_train)
    rng = np.random.default_rng(TRAIN_SEED + len(prefix))
    hidden_width = 32
    parameters = [
        rng.normal(0, math.sqrt(2 / x_train.shape[1]), (x_train.shape[1], hidden_width)).astype(np.float32),
        np.zeros(hidden_width, dtype=np.float32),
        rng.normal(0, math.sqrt(2 / hidden_width), (hidden_width, len(classes))).astype(np.float32),
        np.zeros(len(classes), dtype=np.float32),
    ]
    initial = [value.copy() for value in parameters]
    optimizer = Adam(parameters)
    counts = np.bincount(np.asarray(y_train), minlength=len(classes)).astype(np.float32)
    weights = np.sqrt(max(1.0, float(counts.max())) / np.maximum(counts, 1.0))
    weights /= np.average(weights, weights=np.maximum(counts, 1.0))
    best_loss, best = float("inf"), None
    bad_epochs = 0
    log_path = EXPERIMENT / "training_logs" / f"{output_name}.jsonl"
    append_jsonl(
        log_path,
        {
            "event": "training_start",
            "started_at_utc": utc_now(),
            "feature_width": int(x_train.shape[1]),
            "train_rows": int(len(y_train)),
            "seed": TRAIN_SEED,
        },
    )
    for epoch in range(1, 9):
        order = rng.permutation(len(x_train))
        train_loss = 0.0
        for start in range(0, len(order), 2048):
            index = order[start : start + 2048]
            x = (np.asarray(x_train[index], dtype=np.float32) - mean) / scale
            y = np.asarray(y_train[index], dtype=np.int64)
            hidden, logits = forward(x, parameters)
            logits -= logits.max(axis=1, keepdims=True)
            probability = np.exp(np.clip(logits, -30, 30))
            probability /= probability.sum(axis=1, keepdims=True)
            sample_weight = weights[y]
            train_loss += float((-np.log(np.maximum(probability[np.arange(len(y)), y], 1e-9)) * sample_weight).sum())
            gradient = probability
            gradient[np.arange(len(y)), y] -= 1.0
            gradient *= (sample_weight / max(1, len(y)))[:, None]
            grad_w2 = hidden.T @ gradient
            grad_b2 = gradient.sum(axis=0)
            grad_hidden = (gradient @ parameters[2].T) * (hidden > 0)
            grad_w1 = x.T @ grad_hidden
            grad_b1 = grad_hidden.sum(axis=0)
            optimizer.step([grad_w1, grad_b1, grad_w2, grad_b2])
        validation_loss = 0.0
        validation_correct = 0
        for start in range(0, len(x_validation), 16384):
            x = (np.asarray(x_validation[start : start + 16384], dtype=np.float32) - mean) / scale
            y = np.asarray(y_validation[start : start + 16384], dtype=np.int64)
            _hidden, logits = forward(x, parameters)
            logits -= logits.max(axis=1, keepdims=True)
            probability = np.exp(np.clip(logits, -30, 30))
            probability /= probability.sum(axis=1, keepdims=True)
            validation_loss += float(-np.log(np.maximum(probability[np.arange(len(y)), y], 1e-9)).sum())
            validation_correct += int((np.argmax(probability, axis=1) == y).sum())
        validation_loss /= max(1, len(y_validation))
        row = {
            "epoch": epoch,
            "train_loss": train_loss / max(1, len(y_train)),
            "validation_loss": validation_loss,
            "validation_accuracy": validation_correct / max(1, len(y_validation)),
            "optimizer_steps": optimizer.step_count,
        }
        append_jsonl(log_path, row)
        print(json.dumps(row), flush=True)
        if validation_loss < best_loss - 1e-5:
            best_loss, best, bad_epochs = validation_loss, [value.copy() for value in parameters], 0
        else:
            bad_epochs += 1
            if bad_epochs >= 2:
                break
    assert best is not None
    parameters = best
    path = MODEL_DIR / f"{output_name}.npz"
    save_model(
        path,
        mean,
        scale,
        parameters,
        classes,
        {
            "task": task,
            "architecture": f"{x_train.shape[1]}-32-{len(classes)} ReLU MLP",
            "seed": TRAIN_SEED,
            "train_rows": len(y_train),
            "validation_rows": len(y_validation),
            "test_rows": len(y_test),
            "optimizer_steps": optimizer.step_count,
            "best_validation_loss": best_loss,
            "parameter_change_l2": float(
                math.sqrt(sum(float(np.square(a - b).sum()) for a, b in zip(parameters, initial, strict=True)))
            ),
        },
    )
    model = SavedMLP(path)
    return {
        "model": str(path.relative_to(ROOT)),
        "model_sha256": sha256(path),
        "train_rows": len(y_train),
        "validation": classifier_metrics(model, x_validation, y_validation),
        "test": classifier_metrics(model, x_test, y_test),
        "optimizer_steps": optimizer.step_count,
    }


def average_precision(y: np.ndarray, score: np.ndarray) -> float:
    positives = int(y.sum())
    if positives == 0:
        return 0.0
    order = np.argsort(-score)
    truth = y[order]
    precision = np.cumsum(truth) / np.arange(1, len(truth) + 1)
    return float((precision * truth).sum() / positives)


def b_metrics(events: np.ndarray, quantities: np.ndarray, outputs: np.ndarray) -> dict[str, Any]:
    width = events.shape[1]
    probability = 1.0 / (1.0 + np.exp(-np.clip(outputs[:, :width], -30, 30)))
    predicted_quantity = np.maximum(0.0, np.expm1(np.clip(outputs[:, width:], 0, 8)))
    result: dict[str, Any] = {
        "rows": len(events),
        "brier": float(np.square(probability - events).mean()),
        "quantity_mae": float(np.abs(predicted_quantity - quantities).mean()),
    }
    by_target = {}
    offset = 0
    for item in PRODUCTS:
        for horizon in HORIZONS:
            y, score = events[:, offset], probability[:, offset]
            prediction = score >= 0.5
            tp = float(((prediction == 1) & (y == 1)).sum())
            by_target[f"{item}:{horizon}"] = {
                "positive_rate": float(y.mean()),
                "pr_auc": average_precision(y, score),
                "precision": tp / max(1.0, float(prediction.sum())),
                "recall": tp / max(1.0, float(y.sum())),
                "brier": float(np.square(score - y).mean()),
                "quantity_mae": float(np.abs(predicted_quantity[:, offset] - quantities[:, offset]).mean()),
            }
            offset += 1
    result["by_target"] = by_target
    return result


def b_baseline_outputs(x: np.ndarray, simple: Mapping[str, Any], mode: str) -> np.ndarray:
    """Zero, train-frequency, or public-production heuristic predictions."""
    rows = len(x)
    width = len(PRODUCTS) * len(HORIZONS)
    outputs = np.zeros((rows, width * 2), dtype=np.float32)
    if mode == "zero":
        outputs[:, :width] = -30.0
        return outputs
    names = list(state_feature_names())
    player_index = names.index("player")
    hours = np.rint(np.asarray(x[:, names.index("hour")]) * 23).astype(int).clip(0, 23)
    players = np.rint(np.asarray(x[:, player_index])).astype(int).clip(0, 1)
    animal_for_product = {"EGG": "GOOSE", "MILK": "COW", "WOOL": "SHEEP"}
    offset = 0
    for item in PRODUCTS:
        for horizon in HORIZONS:
            probability = np.asarray(
                [simple["by_hour"][str(hour)][item][str(horizon)]["probability"] for hour in hours],
                dtype=np.float32,
            )
            quantity = np.asarray(
                [simple["by_hour"][str(hour)][item][str(horizon)]["expected_quantity"] for hour in hours],
                dtype=np.float32,
            )
            if mode == "production":
                ready_by_seat = np.stack(
                    [np.asarray(x[:, names.index(f"farm{seat}:public_yield:{item}")]) * 100.0 for seat in (0, 1)],
                    axis=1,
                )
                if item in CROPS:
                    count_name = f"crop:{item}"
                elif item in animal_for_product:
                    count_name = f"animal:{animal_for_product[item]}"
                else:
                    count_name = "animal"
                count_by_seat = np.stack(
                    [np.asarray(x[:, names.index(f"farm{seat}:{count_name}")]) * 100.0 for seat in (0, 1)],
                    axis=1,
                )
                phase_by_seat = np.stack(
                    [
                        np.asarray(x[:, names.index(f"farm{seat}:production_phase:{item}")])
                        for seat in (0, 1)
                    ],
                    axis=1,
                )
                opponent = 1 - players
                row_index = np.arange(rows)
                ready = ready_by_seat[row_index, opponent]
                count = count_by_seat[row_index, opponent]
                phase = phase_by_seat[row_index, opponent]
                public_signal = ready + count * np.minimum(1.0, horizon / 24.0) * (0.25 + phase)
                probability = 1.0 - (1.0 - probability) * np.exp(-public_signal / 8.0)
                quantity = quantity + public_signal
            probability = np.clip(probability, 1e-6, 1.0 - 1e-6)
            outputs[:, offset] = np.log(probability / (1.0 - probability))
            outputs[:, width + offset] = np.log1p(np.maximum(0.0, quantity))
            offset += 1
    return outputs


def b_group_metrics(events: np.ndarray, quantities: np.ndarray, outputs: np.ndarray) -> dict[str, float | int]:
    width = events.shape[1]
    probability = 1.0 / (1.0 + np.exp(-np.clip(outputs[:, :width], -30, 30)))
    predicted_quantity = np.maximum(0.0, np.expm1(np.clip(outputs[:, width:], 0, 8)))
    return {
        "rows": int(len(events)),
        "positive_rate": float(events.mean()),
        "brier": float(np.square(probability - events).mean()),
        "quantity_mae": float(np.abs(predicted_quantity - quantities).mean()),
    }


def predict_saved(model: SavedMLP, x: np.ndarray, chunk: int = 16384) -> np.ndarray:
    result = []
    for start in range(0, len(x), chunk):
        values = np.asarray(x[start : start + chunk], dtype=np.float32)
        normalized = (values - model.mean) / model.scale
        hidden = np.maximum(0.0, normalized @ model.w1 + model.b1)
        result.append(hidden @ model.w2 + model.b2)
    return np.concatenate(result, axis=0)


def train_b() -> dict[str, Any]:
    x_train = load_array("b", "x_train")
    event_train, quantity_train = load_array("b", "event_train"), load_array("b", "quantity_train")
    x_validation, event_validation, quantity_validation = (
        load_array("b", "x_validation"),
        load_array("b", "event_validation"),
        load_array("b", "quantity_validation"),
    )
    x_test, event_test, quantity_test = (
        load_array("b", "x_test"),
        load_array("b", "event_test"),
        load_array("b", "quantity_test"),
    )
    mean, scale = moments(x_train)
    width = event_train.shape[1]
    rng = np.random.default_rng(TRAIN_SEED)
    hidden_width = 32
    parameters = [
        rng.normal(0, math.sqrt(2 / x_train.shape[1]), (x_train.shape[1], hidden_width)).astype(np.float32),
        np.zeros(hidden_width, np.float32),
        rng.normal(0, math.sqrt(2 / hidden_width), (hidden_width, width * 2)).astype(np.float32),
        np.zeros(width * 2, np.float32),
    ]
    initial = [value.copy() for value in parameters]
    optimizer = Adam(parameters, lr=0.0015)
    positive = np.asarray(event_train).sum(axis=0)
    pos_weight = np.minimum(20.0, (len(event_train) - positive) / np.maximum(positive, 1.0)).astype(np.float32)
    best_loss, best, bad_epochs = float("inf"), None, 0
    log_path = EXPERIMENT / "training_logs" / "b_model.jsonl"
    append_jsonl(
        log_path,
        {
            "event": "training_start",
            "started_at_utc": utc_now(),
            "feature_width": int(x_train.shape[1]),
            "train_rows": int(len(x_train)),
            "seed": TRAIN_SEED,
        },
    )
    for epoch in range(1, 9):
        order = rng.permutation(len(x_train))
        total_loss = 0.0
        for start in range(0, len(order), 2048):
            index = order[start : start + 2048]
            x = (np.asarray(x_train[index], np.float32) - mean) / scale
            y_event = np.asarray(event_train[index], np.float32)
            y_quantity = np.log1p(np.asarray(quantity_train[index], np.float32))
            hidden, outputs = forward(x, parameters)
            logits, predicted_quantity = outputs[:, :width], outputs[:, width:]
            probability = 1.0 / (1.0 + np.exp(-np.clip(logits, -30, 30)))
            weights = 1.0 + y_event * (pos_weight - 1.0)
            bce = -(
                weights
                * (
                    y_event * np.log(np.maximum(probability, 1e-8))
                    + (1 - y_event) * np.log(np.maximum(1 - probability, 1e-8))
                )
            )
            quantity_error = predicted_quantity - y_quantity
            total_loss += float(bce.mean() + 0.1 * np.square(quantity_error).mean()) * len(index)
            gradient = np.concatenate(
                (weights * (probability - y_event) / width, 0.2 * quantity_error / width), axis=1
            ) / max(1, len(index))
            grad_w2 = hidden.T @ gradient
            grad_b2 = gradient.sum(axis=0)
            grad_hidden = (gradient @ parameters[2].T) * (hidden > 0)
            optimizer.step([x.T @ grad_hidden, grad_hidden.sum(axis=0), grad_w2, grad_b2])
        normalized = (np.asarray(x_validation, np.float32) - mean) / scale
        hidden, outputs = forward(normalized, parameters)
        probability = 1.0 / (1.0 + np.exp(-np.clip(outputs[:, :width], -30, 30)))
        validation_loss = float(
            np.square(probability - np.asarray(event_validation)).mean()
            + 0.1 * np.square(outputs[:, width:] - np.log1p(np.asarray(quantity_validation))).mean()
        )
        row = {
            "epoch": epoch,
            "train_loss": total_loss / max(1, len(x_train)),
            "validation_selection_loss": validation_loss,
            "optimizer_steps": optimizer.step_count,
        }
        append_jsonl(log_path, row)
        print(json.dumps(row), flush=True)
        if validation_loss < best_loss - 1e-6:
            best_loss, best, bad_epochs = validation_loss, [value.copy() for value in parameters], 0
        else:
            bad_epochs += 1
            if bad_epochs >= 2:
                break
    assert best is not None
    path = MODEL_DIR / "b_model.npz"
    targets = [f"event:{item}:{h}" for item in PRODUCTS for h in HORIZONS] + [
        f"log_quantity:{item}:{h}" for item in PRODUCTS for h in HORIZONS
    ]
    save_model(
        path,
        mean,
        scale,
        best,
        targets,
        {
            "task": "B",
            "architecture": f"{x_train.shape[1]}-32-{width * 2} ReLU multi-head MLP",
            "seed": TRAIN_SEED,
            "train_rows": len(x_train),
            "validation_rows": len(x_validation),
            "test_rows": len(x_test),
            "optimizer_steps": optimizer.step_count,
            "best_validation_loss": best_loss,
            "parameter_change_l2": float(
                math.sqrt(sum(float(np.square(a - b).sum()) for a, b in zip(best, initial, strict=True)))
            ),
        },
    )
    model = SavedMLP(path)
    simple: dict[str, Any] = {
        "format": "learning-b-hour-frequency-v1",
        "global": {},
        "by_hour": {str(hour): {} for hour in range(24)},
    }
    hours = np.rint(np.asarray(x_train[:, 1]) * 23).astype(int)
    offset = 0
    for item in PRODUCTS:
        simple["global"][item] = {}
        for hour in range(24):
            simple["by_hour"][str(hour)][item] = {}
        for horizon in HORIZONS:
            simple["global"][item][str(horizon)] = {
                "probability": float(np.asarray(event_train[:, offset]).mean()),
                "expected_quantity": float(np.asarray(quantity_train[:, offset]).mean()),
            }
            for hour in range(24):
                mask = hours == hour
                simple["by_hour"][str(hour)][item][str(horizon)] = {
                    "probability": float(np.asarray(event_train[mask, offset]).mean())
                    if mask.any()
                    else simple["global"][item][str(horizon)]["probability"],
                    "expected_quantity": float(np.asarray(quantity_train[mask, offset]).mean())
                    if mask.any()
                    else simple["global"][item][str(horizon)]["expected_quantity"],
                }
            offset += 1
    write_json(MODEL_DIR / "b_simple_model.json", simple)
    validation_outputs = predict_saved(model, x_validation)
    test_outputs = predict_saved(model, x_test)
    family_validation = np.asarray(load_array("b", "family_validation"))
    family_test = np.asarray(load_array("b", "family_test"))
    hour_index = list(state_feature_names()).index("hour")
    metrics = {
        "model": str(path.relative_to(ROOT)),
        "model_sha256": sha256(path),
        "optimizer_steps": optimizer.step_count,
        "validation": b_metrics(
            np.asarray(event_validation), np.asarray(quantity_validation), validation_outputs
        ),
        "test": b_metrics(np.asarray(event_test), np.asarray(quantity_test), test_outputs),
        "group_metrics": {
            split: {
                "by_opponent_family": {
                    str(int(family)): b_group_metrics(
                        events[families == family],
                        quantities[families == family],
                        outputs[families == family],
                    )
                    for family in np.unique(families)
                },
                "by_hour_band": {
                    f"{start:02d}-{start + 5:02d}": b_group_metrics(
                        events[(hours >= start) & (hours < start + 6)],
                        quantities[(hours >= start) & (hours < start + 6)],
                        outputs[(hours >= start) & (hours < start + 6)],
                    )
                    for start in (0, 6, 12, 18)
                },
            }
            for split, events, quantities, outputs, families, hours in (
                (
                    "validation",
                    np.asarray(event_validation),
                    np.asarray(quantity_validation),
                    validation_outputs,
                    family_validation,
                    np.rint(np.asarray(x_validation[:, hour_index]) * 23).astype(int),
                ),
                (
                    "test",
                    np.asarray(event_test),
                    np.asarray(quantity_test),
                    test_outputs,
                    family_test,
                    np.rint(np.asarray(x_test[:, hour_index]) * 23).astype(int),
                ),
            )
        },
        "baselines": {
            mode: {
                "validation": b_metrics(
                    np.asarray(event_validation),
                    np.asarray(quantity_validation),
                    b_baseline_outputs(x_validation, simple, mode),
                ),
                "test": b_metrics(
                    np.asarray(event_test),
                    np.asarray(quantity_test),
                    b_baseline_outputs(x_test, simple, mode),
                ),
            }
            for mode in ("zero", "frequency", "production")
        },
    }
    return metrics


def train(task: str) -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if task == "b":
        metrics = train_b()
    elif task == "a":
        metrics = train_classifier("a", "", list(WORK_OPS), "a_model")
        for split in ("validation", "test"):
            truth = load_array("a", f"y_{split}")
            baseline = load_array("a", f"baseline_{split}")
            metrics[f"{split}_deadline_baseline_accuracy"] = float((np.asarray(truth) == np.asarray(baseline)).mean())
    else:
        actor = train_classifier("bc", "actor_", list(ACTOR_TOKENS), "bc_actor_model")
        market = train_classifier("bc", "market_", list(MARKET_TOKENS), "bc_market_model")
        quantities: dict[str, dict[str, float]] = {"actor": {}, "market": {}}
        for group, classes in (("actor", ACTOR_TOKENS), ("market", MARKET_TOKENS)):
            labels = np.asarray(load_array("bc", f"{group}_y_train"))
            values = np.asarray(load_array("bc", f"{group}_quantity_train"))
            for index, name in enumerate(classes):
                selected = values[labels == index]
                quantities[group][name] = float(np.median(selected)) if len(selected) else 1.0
        write_json(MODEL_DIR / "bc_quantities.json", quantities)
        metrics = {
            "actor": actor,
            "market": market,
            "quantity_fit": "train-only per-token median",
            "optimizer_steps": actor["optimizer_steps"] + market["optimizer_steps"],
        }
    write_json(EXPERIMENT / f"offline_metrics_{task}.json", metrics)
    print(json.dumps({"task": task, "optimizer_steps": metrics.get("optimizer_steps")}), flush=True)


def deploy(task: str) -> None:
    mapping = {
        "b": ("b_model.npz", "b_model.json", "b_simple_model.json"),
        "a": ("a_model.npz", "a_model.json"),
        "bc": (
            "bc_actor_model.npz",
            "bc_actor_model.json",
            "bc_market_model.npz",
            "bc_market_model.json",
            "bc_quantities.json",
        ),
    }
    copied = []
    for name in mapping[task]:
        source, target = MODEL_DIR / name, AGENT_DIR / name
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copy2(source, target)
        copied.append({"path": str(target.relative_to(ROOT)), "sha256": sha256(target)})
    write_json(EXPERIMENT / f"deployed_{task}.json", {"copied_at_utc": utc_now(), "files": copied})


def verify(task: str) -> None:
    deploy(task)
    if task == "b":
        model_path, x_path = AGENT_DIR / "b_model.npz", DATASET_DIR / "b" / "x_validation.npy"
    elif task == "a":
        model_path, x_path = AGENT_DIR / "a_model.npz", DATASET_DIR / "a" / "x_validation.npy"
    else:
        model_path, x_path = AGENT_DIR / "bc_actor_model.npz", DATASET_DIR / "bc" / "actor_x_validation.npy"
    model, x = SavedMLP(model_path), np.load(x_path, mmap_mode="r", allow_pickle=False)
    expected = model.logits(np.asarray(x[0])).tolist()
    code = (
        "import json,numpy as np,sys; "
        "from agents.learning_next_20260921.common import SavedMLP; "
        "m=SavedMLP(sys.argv[1]); x=np.load(sys.argv[2],mmap_mode='r',allow_pickle=False); "
        "print(json.dumps(m.logits(np.asarray(x[0])).tolist()))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code, str(model_path), str(x_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    actual = json.loads(completed.stdout.strip()) if completed.returncode == 0 else []
    result = {
        "task": task,
        "checked_at_utc": utc_now(),
        "separate_process_exit_code": completed.returncode,
        "same_prediction": bool(np.allclose(expected, actual, rtol=1e-6, atol=1e-6)),
        "model_path": str(model_path.resolve()),
        "model_sha256": sha256(model_path),
        "stderr": completed.stderr[-2000:],
    }
    if not result["same_prediction"]:
        raise AssertionError(result)
    write_json(EXPERIMENT / f"reload_verification_{task}.json", result)
    print(json.dumps(result), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inventory")
    for name in ("build", "train", "verify", "deploy"):
        child = sub.add_parser(name)
        child.add_argument("--task", choices=("b", "a", "bc"), required=True)
    args = parser.parse_args()
    if args.command == "inventory":
        inventory()
    elif args.command == "build":
        build(args.task)
    elif args.command == "train":
        train(args.task)
    elif args.command == "verify":
        verify(args.task)
    else:
        deploy(args.task)


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
        append_jsonl(EXPERIMENT / "commands.jsonl", command)
        traceback.print_exc()
        raise
    command.update({"ended_at_utc": utc_now(), "duration_seconds": time.time() - started, "exit_code": 0})
    append_jsonl(EXPERIMENT / "commands.jsonl", command)
