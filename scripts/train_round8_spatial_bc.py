"""Build, train, and verify the Round8 position-sensitive independent BC.

The source is one real replay family already present in the repository.  Rows
are observation[t] -> action[t+1]; no outcome, future shop, future action, or
opponent-private value is an input.  The script refuses to overwrite outputs.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from kaggle_environments.envs.kaggriculture import kaggriculture as engine

ROOT = Path(__file__).resolve().parents[1]
AGENT_SOURCE = ROOT / "agents" / "round8_execution_reset_20260922"
if str(AGENT_SOURCE) not in sys.path:
    sys.path.insert(0, str(AGENT_SOURCE))

import common  # noqa: E402
import spatial  # noqa: E402

EXPERIMENT = ROOT / "experiments" / "round8_execution_reset_20260922"
PHASE = EXPERIMENT / "phase_c_spatial"
DATASET = PHASE / "dataset_v2"
MODEL_COLLECTION = PHASE / "models_v5"
SOURCE_EXPERIMENT = ROOT / "experiments" / "learning_next_20260921"
TEACHER_ID = 56216119
PARTITION_LIMITS = {"train": 12, "validation": 4, "test": 4}
PUBLIC_DEVELOPMENT = {111952429, 111953595, 111954710}
ACTOR_BASE_WIDTH = len(common.bc_actor_feature_names())
MARKET_BASE_WIDTH = len(common.market_feature_names())
ACTOR_WIDTH = (
    ACTOR_BASE_WIDTH
    + 2 * len(common.ACTOR_TOKENS)
    + spatial.PREFIX_EXTRA_WIDTH
    + spatial.GRID_WIDTH
    + spatial.ROSTER_WIDTH
)
MARKET_WIDTH = MARKET_BASE_WIDTH + spatial.GRID_WIDTH + spatial.ROSTER_WIDTH


def utc_now() -> str:
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


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


def restore_observation(states: list[dict[str, Any]], seat: int, step: int) -> dict[str, Any]:
    public = copy.deepcopy(states[0].get("observation") or states[1].get("observation") or {})
    private = states[seat].get("observation") or {}
    public["player"] = seat
    public["private"] = copy.deepcopy(private.get("private", {}))
    public["remainingOverageTime"] = private.get(
        "remainingOverageTime", public.get("remainingOverageTime", 60)
    )
    public["step"] = step
    public["day"] = step // 24
    public["hour"] = step % 24
    return public


def _selected_entries() -> list[dict[str, Any]]:
    source_path = SOURCE_EXPERIMENT / "source_manifest.json"
    split_path = SOURCE_EXPERIMENT / "split_manifest.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    assignments = json.loads(split_path.read_text(encoding="utf-8"))["assignments"]
    choices: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in source["files"]:
        episode = int(row["episode_id"])
        if int(row["submission_id"]) != TEACHER_ID or episode in PUBLIC_DEVELOPMENT:
            continue
        if int(row.get("step_count", 0)) != 720:
            continue
        partition = str(assignments[str(episode)])
        item = dict(row)
        item["partition"] = partition
        item["selection_key"] = hashlib.sha256(f"round8-spatial:{episode}".encode()).hexdigest()
        choices[partition].append(item)
    result: list[dict[str, Any]] = []
    for partition, limit in PARTITION_LIMITS.items():
        rows = sorted(choices[partition], key=lambda value: value["selection_key"])
        if len(rows) < limit:
            raise RuntimeError(f"not enough {partition} episodes: {len(rows)} < {limit}")
        result.extend(rows[:limit])
    return result


def _sample_actor(episode: int, step: int, actor: int, overfit_episode: int) -> bool:
    if episode == overfit_episode and step < 96:
        return True
    value = int(hashlib.sha256(f"round8:{episode}:{step}:{actor}".encode()).hexdigest()[:8], 16)
    return value % 5 == 0


def _target_identity(observation: dict[str, Any], index: int) -> dict[str, Any]:
    farm, position, _inventory, tile = common.actor_context(observation, index)
    del farm
    value = tile if isinstance(tile, dict) else {}
    return {
        "position": list(position),
        "kind": value.get("kind"),
        "resource": value.get("crop", value.get("animal")),
        "generation": value.get("planted_day", value.get("placed_day")),
        "yield_units": int(value.get("yield_units", 0)),
    }


def _actor_fingerprint(observation: dict[str, Any], index: int) -> str:
    seat = int(observation["player"])
    farm = observation["farms"][seat]
    positions = [farm["farmer"], *farm.get("hands", [])]
    position = positions[index]
    x, y = int(position[0]), int(position[1])
    inventories = observation["private"].get("inventories", [])
    value = {
        "position": position,
        "tile": farm["tiles"][y][x],
        "inventory": inventories[index] if index < len(inventories) else {},
        "shed": observation["private"].get("shed", {}),
        "seeds": observation["private"].get("seeds", {}),
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _blocked_plants(units: list[list[Any]], seeds: dict[str, Any]) -> set[str]:
    demand = Counter(
        str(action[1])
        for action in units
        if isinstance(action, list) and len(action) >= 2 and action[0] == "PLANT"
    )
    return {crop for crop, count in demand.items() if count > int(seeds.get(crop, 0))}


def _apply_teacher_prefix(
    shadow: dict[str, Any], index: int, action: list[Any], blocked: set[str]
) -> tuple[list[Any], bool]:
    resolved = copy.deepcopy(action)
    if len(resolved) >= 2 and resolved[0] == "PLANT" and resolved[1] in blocked:
        resolved = ["PASS"]
    before = _actor_fingerprint(shadow, index)
    seat = int(shadow["player"])
    engine._apply_unit_action(
        shadow["farms"][seat],
        shadow["private"],
        index,
        resolved,
        10,
        int(shadow["day"]),
        24,
        100,
    )
    return resolved, before != _actor_fingerprint(shadow, index)


def _actor_feature(
    observation: dict[str, Any],
    index: int,
    previous_token: str,
    history: common.MarketHistory,
    prefix: list[dict[str, Any]],
    shared: np.ndarray,
) -> np.ndarray:
    result = np.concatenate(
        (
            common.bc_actor_features(observation, index, previous_token, history),
            spatial.prefix_token_features(prefix),
            spatial.prefix_extra_features(prefix),
            shared,
        )
    ).astype(np.float32)
    if result.size != ACTOR_WIDTH:
        raise ValueError(f"actor width {result.size} != {ACTOR_WIDTH}")
    return result


def _market_feature(
    observation: dict[str, Any],
    slot: int,
    previous_token: str,
    history: common.MarketHistory,
    shared: np.ndarray,
) -> np.ndarray:
    result = np.concatenate((common.market_features(observation, slot, previous_token, history), shared)).astype(
        np.float32
    )
    if result.size != MARKET_WIDTH:
        raise ValueError(f"market width {result.size} != {MARKET_WIDTH}")
    return result


def _save_array(name: str, value: list[Any], dtype: Any) -> dict[str, Any]:
    path = DATASET / f"{name}.npy"
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    array = np.asarray(value, dtype=dtype)
    np.save(path, array, allow_pickle=False)
    return {"path": str(path.relative_to(ROOT)), "sha256": sha256(path), "shape": list(array.shape)}


def build_dataset() -> None:
    if DATASET.exists():
        raise FileExistsError(f"refusing to overwrite dataset directory {DATASET}")
    DATASET.mkdir(parents=True)
    entries = _selected_entries()
    train_episodes = [int(row["episode_id"]) for row in entries if row["partition"] == "train"]
    overfit_episode = train_episodes[0]
    arrays: dict[str, list[Any]] = defaultdict(list)
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    roundtrip = Counter()
    clock_checks = Counter()
    max_actors = 0
    selected_manifest = []
    for number, row in enumerate(entries, 1):
        path = ROOT / str(row["path"])
        actual_hash = sha256(path)
        if actual_hash != row["sha256"]:
            raise RuntimeError(f"replay hash mismatch: {path}")
        replay = json.loads(path.read_text(encoding="utf-8"))
        steps = replay["steps"]
        if len(steps) != 720:
            raise RuntimeError(f"episode {row['episode_id']} has {len(steps)} states, expected 720")
        seat = int(row["seat"])
        episode = int(row["episode_id"])
        partition = str(row["partition"])
        history = common.MarketHistory()
        episode_decisions = 0
        for step in range(719):
            observation = restore_observation(steps[step], seat, step)
            clock_checks["states"] += 1
            clock_checks["seat1_without_saved_step"] += int(
                seat == 1 and "step" not in (steps[step][seat].get("observation") or {})
            )
            if observation["day"] * 24 + observation["hour"] != step:
                raise RuntimeError(f"clock mismatch episode={episode} step={step}")
            previous = steps[step][seat].get("action") if step > 0 else None
            history.update(observation, previous.get("market", []) if isinstance(previous, dict) else [])
            action = steps[step + 1][seat].get("action") or {}
            units = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
            actor_count = 1 + len(observation["farms"][seat].get("hands", []))
            max_actors = max(max_actors, actor_count)
            if len(units) != actor_count:
                raise RuntimeError(
                    f"actor order mismatch episode={episode} step={step}: {len(units)} != {actor_count}"
                )
            shared = spatial.shared_spatial_features(observation)
            prior_action = steps[step][seat].get("action") if step > 0 else {}
            prior_units = [
                (prior_action or {}).get("farmer") or ["PASS"],
                *((prior_action or {}).get("hands") or []),
            ]
            shadow = copy.deepcopy(observation)
            blocked = _blocked_plants(units, shadow["private"].get("seeds", {}))
            prefix: list[dict[str, Any]] = []
            for actor_index, unit in enumerate(units):
                token = common.action_token(unit)
                quantity = int(unit[2]) if len(unit) >= 3 else 1
                prior_token = (
                    common.action_token(prior_units[actor_index]) if actor_index < len(prior_units) else "PASS"
                )
                target = _target_identity(shadow, actor_index)
                if _sample_actor(episode, step, actor_index, overfit_episode):
                    feature = _actor_feature(
                        observation, actor_index, prior_token, history, prefix, shared
                    )
                    arrays[f"actor_x_{partition}"].append(feature)
                    arrays[f"actor_y_{partition}"].append(common.ACTOR_TOKENS.index(token))
                    arrays[f"actor_q_{partition}"].append(quantity)
                    arrays[f"actor_episode_{partition}"].append(episode)
                    arrays[f"actor_step_{partition}"].append(step)
                    arrays[f"actor_index_{partition}"].append(actor_index)
                    counts[f"actor:{partition}"][token] += 1
                decoded = common.token_action(token, quantity)
                if decoded != unit:
                    roundtrip[f"actor:{token}"] += 1
                resolved, effect = _apply_teacher_prefix(shadow, actor_index, unit, blocked)
                prefix.append(spatial.make_prefix_entry(token, quantity, target, effect, resolved))
            orders = action.get("market") or []
            previous_token = "EOS"
            for slot in range(min(10, len(orders)) + 1):
                order = orders[slot] if slot < len(orders) else []
                token = common.market_token(order)
                quantity = int(order[2]) if isinstance(order, list | tuple) and len(order) >= 3 else 1
                arrays[f"market_x_{partition}"].append(
                    _market_feature(observation, slot, previous_token, history, shared)
                )
                arrays[f"market_y_{partition}"].append(common.MARKET_TOKENS.index(token))
                arrays[f"market_q_{partition}"].append(quantity)
                arrays[f"market_episode_{partition}"].append(episode)
                arrays[f"market_step_{partition}"].append(step)
                arrays[f"market_slot_{partition}"].append(slot)
                counts[f"market:{partition}"][token] += 1
                if token != "EOS" and common.token_order(token, quantity) != order:
                    roundtrip[f"market:{token}"] += 1
                previous_token = token
                if token == "EOS":
                    break
            episode_decisions += 1
        if episode_decisions != 719:
            raise RuntimeError(f"episode {episode}: {episode_decisions} decisions, expected 719")
        selected_manifest.append(
            {
                "episode_id": episode,
                "seat": seat,
                "partition": partition,
                "states": len(steps),
                "decisions": episode_decisions,
                "path": str(path.relative_to(ROOT)),
                "sha256": actual_hash,
            }
        )
        print(f"dataset {number}/{len(entries)} episode={episode} split={partition}", flush=True)
    if roundtrip:
        raise RuntimeError(f"decoder round-trip failures: {dict(roundtrip)}")
    files = {}
    for partition in PARTITION_LIMITS:
        for group in ("actor", "market"):
            files[f"{group}_x_{partition}"] = _save_array(
                f"{group}_x_{partition}", arrays[f"{group}_x_{partition}"], np.float32
            )
            files[f"{group}_y_{partition}"] = _save_array(
                f"{group}_y_{partition}", arrays[f"{group}_y_{partition}"], np.int16
            )
            files[f"{group}_q_{partition}"] = _save_array(
                f"{group}_q_{partition}", arrays[f"{group}_q_{partition}"], np.int16
            )
            files[f"{group}_episode_{partition}"] = _save_array(
                f"{group}_episode_{partition}", arrays[f"{group}_episode_{partition}"], np.int64
            )
            files[f"{group}_step_{partition}"] = _save_array(
                f"{group}_step_{partition}", arrays[f"{group}_step_{partition}"], np.int16
            )
            suffix = "index" if group == "actor" else "slot"
            files[f"{group}_{suffix}_{partition}"] = _save_array(
                f"{group}_{suffix}_{partition}", arrays[f"{group}_{suffix}_{partition}"], np.int16
            )
    write_json(
        DATASET / "dataset_manifest.json",
        {
            "created_at_utc": utc_now(),
            "task": "position-sensitive independent structured behavioral cloning",
            "teacher_submission": TEACHER_ID,
            "teacher_family_count": 1,
            "source_manifest": str((SOURCE_EXPERIMENT / "source_manifest.json").relative_to(ROOT)),
            "source_manifest_sha256": sha256(SOURCE_EXPERIMENT / "source_manifest.json"),
            "source_split_manifest": str((SOURCE_EXPERIMENT / "split_manifest.json").relative_to(ROOT)),
            "source_split_manifest_sha256": sha256(SOURCE_EXPERIMENT / "split_manifest.json"),
            "selection": "SHA256(round8-spatial:episode_id), first N within pre-existing episode split",
            "limits": PARTITION_LIMITS,
            "excluded_public_development_episodes": sorted(PUBLIC_DEVELOPMENT),
            "mapping": "replay state/observation[t] -> saved action[t+1]",
            "change_from_dataset_v1": (
                "market rows are now retained at every decision step; v1 sampled only even steps and omitted "
                "the step-1 hire sequence, which caused closed-loop repetition of the step-0 purchases"
            ),
            "format_verified": "720 saved states / 719 decisions per episode",
            "seat_clock": "step reconstructed as day*24+hour for both seats",
            "episode_separated": True,
            "overfit_probe_episode": overfit_episode,
            "feature_schema": spatial.schema(),
            "actor_feature_width": ACTOR_WIDTH,
            "market_feature_width": MARKET_WIDTH,
            "normalization": (
                "semantic bounded/log features from common.py and spatial.py; categorical one-hot; "
                "training does not divide categorical/constant columns by empirical tiny std"
            ),
            "runtime_inputs_excluded": [
                "opponent private state",
                "future shop",
                "future action",
                "outcome/win/loss",
            ],
            "same_turn_prefix": "token, raw requested quantity, target identity/generation, fixed-engine effect",
            "market_order_and_eos_preserved": True,
            "raw_request_quantity_preserved": True,
            "actual_fill_not_substituted_for_request": True,
            "roundtrip_failures": dict(roundtrip),
            "max_actor_count": max_actors,
            "clock_checks": dict(clock_checks),
            "label_counts": {key: dict(value) for key, value in counts.items()},
            "episodes": selected_manifest,
            "files": files,
        },
    )


class Adam:
    def __init__(self, parameters: list[np.ndarray], lr: float = 0.0015) -> None:
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


def _init_parameters(width: int, hidden: tuple[int, int], classes: int, rng: np.random.Generator) -> list[np.ndarray]:
    first, second = hidden
    return [
        rng.normal(0, math.sqrt(2 / width), (width, first)).astype(np.float32),
        np.zeros(first, dtype=np.float32),
        rng.normal(0, math.sqrt(2 / first), (first, second)).astype(np.float32),
        np.zeros(second, dtype=np.float32),
        rng.normal(0, math.sqrt(2 / second), (second, classes)).astype(np.float32),
        np.zeros(classes, dtype=np.float32),
    ]


def _forward(x: np.ndarray, parameters: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    first = np.maximum(0.0, x @ parameters[0] + parameters[1])
    second = np.maximum(0.0, first @ parameters[2] + parameters[3])
    return first, second, second @ parameters[4] + parameters[5]


def _loss_accuracy(
    x: np.ndarray, y: np.ndarray, parameters: list[np.ndarray], chunk: int = 4096
) -> tuple[float, float]:
    total_loss = 0.0
    correct = 0
    count = 0
    for start in range(0, len(y), chunk):
        values = np.asarray(x[start : start + chunk], dtype=np.float32)
        truth = np.asarray(y[start : start + chunk], dtype=np.int64)
        known = truth >= 0
        if not known.any():
            continue
        _first, _second, logits = _forward(values[known], parameters)
        logits -= logits.max(axis=1, keepdims=True)
        probability = np.exp(np.clip(logits, -30, 30))
        probability /= probability.sum(axis=1, keepdims=True)
        target = truth[known]
        total_loss += float(-np.log(np.maximum(probability[np.arange(len(target)), target], 1e-9)).sum())
        correct += int((probability.argmax(axis=1) == target).sum())
        count += len(target)
    return total_loss / max(1, count), correct / max(1, count)


def _metrics(x: np.ndarray, y: np.ndarray, parameters: list[np.ndarray], classes: list[str]) -> dict[str, Any]:
    truth = np.asarray(y, dtype=np.int64)
    known = truth >= 0
    prediction = np.full(len(truth), -1, dtype=np.int64)
    for start in range(0, len(truth), 4096):
        _a, _b, logits = _forward(np.asarray(x[start : start + 4096], dtype=np.float32), parameters)
        prediction[start : start + len(logits)] = logits.argmax(axis=1)
    confusion = np.zeros((len(classes), len(classes)), dtype=np.int64)
    np.add.at(confusion, (truth[known], prediction[known]), 1)
    recall = np.diag(confusion) / np.maximum(1, confusion.sum(axis=1))
    result: dict[str, Any] = {
        "rows": int(len(truth)),
        "known_rows": int(known.sum()),
        "accuracy": float((prediction[known] == truth[known]).mean()) if known.any() else 0.0,
        "macro_recall": float(recall.mean()),
        "recall_by_class": {name: float(recall[index]) for index, name in enumerate(classes)},
        "confusion": confusion.tolist(),
    }
    if all(value.isdigit() for value in classes) and known.any():
        numeric = np.asarray([int(value) for value in classes])
        result["quantity_mae"] = float(np.abs(numeric[prediction[known]] - numeric[truth[known]]).mean())
    return result


def _train_classifier(
    name: str,
    classes: list[str],
    x: dict[str, np.ndarray],
    y: dict[str, np.ndarray],
    output: Path,
    seed: int,
    *,
    max_epochs: int = 40,
    patience: int = 5,
    hidden: tuple[int, int] = (96, 48),
    batch_size: int = 512,
    weight_exponent: float = 0.25,
) -> dict[str, Any]:
    path = output / f"{name}.npz"
    log_path = output / "training_logs" / f"{name}.jsonl"
    if path.exists() or log_path.exists():
        raise FileExistsError(f"refusing to overwrite {path} or {log_path}")
    output.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    parameters = _init_parameters(int(x["train"].shape[1]), hidden, len(classes), rng)
    initial = [value.copy() for value in parameters]
    optimizer = Adam(parameters)
    train_y = np.asarray(y["train"], dtype=np.int64)
    counts = np.bincount(train_y, minlength=len(classes)).astype(np.float32)
    weights = np.power(max(1.0, float(counts.max())) / np.maximum(counts, 1.0), weight_exponent)
    weights /= np.average(weights, weights=np.maximum(counts, 1.0))
    feature_min = np.min(x["train"], axis=0)
    feature_max = np.max(x["train"], axis=0)
    append_jsonl(
        log_path,
        {
            "event": "training_start",
            "created_at_utc": utc_now(),
            "seed": seed,
            "architecture": [int(x["train"].shape[1]), *hidden, len(classes)],
            "train_rows": len(train_y),
            "normalization": "fixed encoder semantics; mean=0 scale=1 including categorical/constant columns",
            "feature_range": {
                "min": float(feature_min.min()),
                "max": float(feature_max.max()),
                "constant_columns": int((feature_min == feature_max).sum()),
            },
            "max_epochs": max_epochs,
            "patience": patience,
            "class_weight_exponent": weight_exponent,
        },
    )
    best_loss = float("inf")
    best_parameters: list[np.ndarray] | None = None
    best_epoch = best_step = 0
    bad_epochs = 0
    for epoch in range(1, max_epochs + 1):
        order = rng.permutation(len(train_y))
        weighted_loss = 0.0
        for start in range(0, len(order), batch_size):
            positions = order[start : start + batch_size]
            batch_x = np.asarray(x["train"][positions], dtype=np.float32)
            batch_y = train_y[positions]
            first, second, logits = _forward(batch_x, parameters)
            logits -= logits.max(axis=1, keepdims=True)
            probability = np.exp(np.clip(logits, -30, 30))
            probability /= probability.sum(axis=1, keepdims=True)
            sample_weight = weights[batch_y]
            weighted_loss += float(
                (-np.log(np.maximum(probability[np.arange(len(batch_y)), batch_y], 1e-9)) * sample_weight).sum()
            )
            gradient = probability
            gradient[np.arange(len(batch_y)), batch_y] -= 1.0
            gradient *= (sample_weight / max(1, len(batch_y)))[:, None]
            grad_w3 = second.T @ gradient
            grad_b3 = gradient.sum(axis=0)
            grad_second = (gradient @ parameters[4].T) * (second > 0)
            grad_w2 = first.T @ grad_second
            grad_b2 = grad_second.sum(axis=0)
            grad_first = (grad_second @ parameters[2].T) * (first > 0)
            optimizer.step(
                [batch_x.T @ grad_first, grad_first.sum(axis=0), grad_w2, grad_b2, grad_w3, grad_b3]
            )
        val_loss, val_accuracy = _loss_accuracy(x["validation"], y["validation"], parameters)
        record = {
            "epoch": epoch,
            "train_weighted_loss": weighted_loss / max(1, len(train_y)),
            "validation_loss": val_loss,
            "validation_accuracy": val_accuracy,
            "optimizer_steps": optimizer.step_count,
        }
        append_jsonl(log_path, record)
        print(json.dumps({"model": name, **record}), flush=True)
        if val_loss < best_loss - 1e-4:
            best_loss = val_loss
            best_parameters = [value.copy() for value in parameters]
            best_epoch = epoch
            best_step = optimizer.step_count
            bad_epochs = 0
        else:
            bad_epochs += 1
            if bad_epochs >= patience:
                break
    if best_parameters is None:
        raise RuntimeError(f"no checkpoint for {name}")
    mean = np.zeros(x["train"].shape[1], dtype=np.float32)
    scale = np.ones(x["train"].shape[1], dtype=np.float32)
    np.savez(
        path,
        mean=mean,
        scale=scale,
        w1=best_parameters[0],
        b1=best_parameters[1],
        w2=best_parameters[2],
        b2=best_parameters[3],
        w3=best_parameters[4],
        b3=best_parameters[5],
        classes=np.asarray(classes),
    )
    metadata = {
        "created_at_utc": utc_now(),
        "task": name,
        "checkpoint": str(path.relative_to(ROOT)),
        "sha256": sha256(path),
        "architecture": [int(x["train"].shape[1]), *hidden, len(classes)],
        "seed": seed,
        "train_rows": int(len(y["train"])),
        "validation_rows": int(len(y["validation"])),
        "test_rows": int(len(y["test"])),
        "epochs_run": epoch,
        "best_epoch": best_epoch,
        "optimizer_steps_total": optimizer.step_count,
        "optimizer_steps_at_checkpoint": best_step,
        "best_validation_loss": best_loss,
        "class_weight_exponent": weight_exponent,
        "parameter_change_l2": float(
            math.sqrt(
                sum(
                    float(np.square(current - original).sum())
                    for current, original in zip(best_parameters, initial, strict=True)
                )
            )
        ),
        "validation": _metrics(x["validation"], y["validation"], best_parameters, classes),
        "test": _metrics(x["test"], y["test"], best_parameters, classes),
    }
    write_json(path.with_suffix(".json"), metadata)
    return metadata


def _load(group: str, field: str, partition: str) -> np.ndarray:
    return np.load(DATASET / f"{group}_{field}_{partition}.npy", mmap_mode="r", allow_pickle=False)


def _token_views(
    group: str, *, early_repeat: int = 1
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray], list[str]]:
    classes = list(common.ACTOR_TOKENS if group == "actor" else common.MARKET_TOKENS)
    x = {partition: _load(group, "x", partition) for partition in PARTITION_LIMITS}
    y = {partition: _load(group, "y", partition) for partition in PARTITION_LIMITS}
    if early_repeat > 1:
        steps = _load(group, "step", "train")
        early = np.flatnonzero(steps < 24)
        x["train"] = np.concatenate(
            (np.asarray(x["train"]), *[np.asarray(x["train"][early])] * (early_repeat - 1)), axis=0
        )
        y["train"] = np.concatenate(
            (np.asarray(y["train"]), *[np.asarray(y["train"][early])] * (early_repeat - 1)), axis=0
        )
    return x, y, classes


def _quantity_views(group: str) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray], list[str]]:
    tokens = common.ACTOR_TOKENS if group == "actor" else common.MARKET_TOKENS
    applicable = (
        {index for index, token in enumerate(tokens) if token.startswith(("PICKUP:", "PLACE:"))}
        if group == "actor"
        else {index for index, token in enumerate(tokens) if token not in {"EOS", "HIRE", "BUY_LAND"}}
    )
    train_token = _load(group, "y", "train")
    train_quantity = _load(group, "q", "train")
    train_rows = np.flatnonzero(np.isin(train_token, np.asarray(sorted(applicable))))
    values = sorted(set(int(value) for value in np.asarray(train_quantity[train_rows])))
    lookup = {value: index for index, value in enumerate(values)}
    x: dict[str, np.ndarray] = {}
    y: dict[str, np.ndarray] = {}
    for partition in PARTITION_LIMITS:
        base = _load(group, "x", partition)
        token = _load(group, "y", partition)
        quantity = _load(group, "q", partition)
        rows = np.flatnonzero(np.isin(token, np.asarray(sorted(applicable))))
        one_hot = np.zeros((len(rows), len(tokens)), dtype=np.float32)
        one_hot[np.arange(len(rows)), np.asarray(token[rows], dtype=np.int64)] = 1.0
        x[partition] = np.concatenate((np.asarray(base[rows], dtype=np.float32), one_hot), axis=1)
        y[partition] = np.asarray([lookup.get(int(value), -1) for value in quantity[rows]], dtype=np.int64)
    return x, y, [str(value) for value in values]


def train(seed: int) -> None:
    if not (DATASET / "dataset_manifest.json").is_file():
        raise FileNotFoundError("build the dataset first")
    output = MODEL_COLLECTION / f"seed_{seed}"
    if output.exists():
        raise FileExistsError(f"refusing to overwrite model directory {output}")
    results = {}
    for offset, (name, group, quantity) in enumerate(
        (
            ("actor_token", "actor", False),
            ("market_token", "market", False),
            ("actor_quantity", "actor", True),
            ("market_quantity", "market", True),
        )
    ):
        x, y, classes = (
            _quantity_views(group)
            if quantity
            else _token_views(group, early_repeat=8)
        )
        results[name] = _train_classifier(
            name,
            classes,
            x,
            y,
            output,
            seed + 101 * offset,
            weight_exponent=0.0 if name == "market_token" else 0.25,
        )
    reload_checks = {}
    import model_compat

    for name in results:
        model = model_compat.SavedMLP(output / f"{name}.npz")
        reload_checks[name] = {
            "classes": len(model.classes),
            "layers": [list(weight.shape) for weight, _bias in model.layers],
            "finite_probability": bool(
                np.isfinite(model.probabilities(np.zeros(model.mean.shape, dtype=np.float32))).all()
            ),
        }
    write_json(
        output / "training_summary.json",
        {
            "created_at_utc": utc_now(),
            "seed": seed,
            "dataset_manifest_sha256": sha256(DATASET / "dataset_manifest.json"),
            "actual_optimizer_updates": True,
            "target_task_augmentation": (
                "actor-token and market-token train rows with step<24 repeated 8x; same teacher episodes and labels; "
                "market recovery added after v3 repeated HIRE; actor recovery added after v5 diverged at record 2"
            ),
            "models": results,
            "reload_and_inference": reload_checks,
        },
    )


def overfit_probe(seed: int) -> None:
    manifest = json.loads((DATASET / "dataset_manifest.json").read_text(encoding="utf-8"))
    episode = int(manifest["overfit_probe_episode"])
    x_all = _load("actor", "x", "train")
    y_all = _load("actor", "y", "train")
    episodes = _load("actor", "episode", "train")
    steps = _load("actor", "step", "train")
    rows = np.flatnonzero((episodes == episode) & (steps < 96))
    x = np.asarray(x_all[rows], dtype=np.float32)
    y = np.asarray(y_all[rows], dtype=np.int64)
    output = PHASE / "overfit_probe_v2"
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    rng = np.random.default_rng(seed)
    parameters = _init_parameters(x.shape[1], (256, 128), len(common.ACTOR_TOKENS), rng)
    optimizer = Adam(parameters, lr=0.0015)
    curve = []
    for epoch in range(1, 401):
        order = rng.permutation(len(y))
        for start in range(0, len(order), 64):
            index = order[start : start + 64]
            batch_x, batch_y = x[index], y[index]
            first, second, logits = _forward(batch_x, parameters)
            logits -= logits.max(axis=1, keepdims=True)
            probability = np.exp(np.clip(logits, -30, 30))
            probability /= probability.sum(axis=1, keepdims=True)
            gradient = probability
            gradient[np.arange(len(batch_y)), batch_y] -= 1.0
            gradient /= max(1, len(batch_y))
            grad_w3 = second.T @ gradient
            grad_second = (gradient @ parameters[4].T) * (second > 0)
            grad_w2 = first.T @ grad_second
            grad_first = (grad_second @ parameters[2].T) * (first > 0)
            optimizer.step(
                [
                    batch_x.T @ grad_first,
                    grad_first.sum(axis=0),
                    grad_w2,
                    grad_second.sum(axis=0),
                    grad_w3,
                    gradient.sum(axis=0),
                ]
            )
        loss, accuracy = _loss_accuracy(x, y, parameters)
        curve.append({"epoch": epoch, "loss": loss, "accuracy": accuracy, "optimizer_steps": optimizer.step_count})
        if accuracy >= 0.98:
            break
    output.mkdir(parents=True)
    for row in curve:
        append_jsonl(output / "curve.jsonl", row)
    write_json(
        output / "result.json",
        {
            "created_at_utc": utc_now(),
            "purpose": "capacity/sanity check only; not evidence of generalization or game strength",
            "episode_id": episode,
            "interval": "steps 0..95",
            "rows": len(y),
            "seed": seed,
            "architecture": [x.shape[1], 256, 128, len(common.ACTOR_TOKENS)],
            "change_from_v1": (
                "same rows and 98% criterion; batch 256->64, hidden 128/64->256/128, "
                "maximum updates increased because v1 loss was still falling"
            ),
            "epochs": epoch,
            "optimizer_steps": optimizer.step_count,
            "final_loss": loss,
            "final_accuracy": accuracy,
            "passed_preregistered_98_percent": accuracy >= 0.98,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build")
    probe = sub.add_parser("overfit")
    probe.add_argument("--seed", type=int, default=20260922)
    training = sub.add_parser("train")
    training.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    if args.command == "build":
        build_dataset()
    elif args.command == "overfit":
        overfit_probe(args.seed)
    else:
        train(args.seed)


if __name__ == "__main__":
    main()
