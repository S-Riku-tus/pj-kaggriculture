"""Train preregistered Round7 Arm A (duration) and Arm B (capacity)."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.learning_next_20260921.common import ACTOR_TOKENS, MARKET_TOKENS  # noqa: E402
from scripts.learning_next_pipeline import Adam  # noqa: E402
from scripts.train_round6_sequence_bc import (  # noqa: E402
    FeatureView,
    arrays,
    feature_moments,
    quantity_views,
)

EXPERIMENT = ROOT / "experiments" / "learning_round7_20260922"
SOURCE_DATASET = ROOT / "experiments" / "learning_next_20260921" / "datasets" / "bc"
PREFIX_DATASET = ROOT / "experiments" / "learning_round6_20260922" / "datasets" / "sequence_bc_v1"
ROUND6_MODELS = ROOT / "experiments" / "learning_round6_20260922" / "models" / "sequence_bc_v1"
ARMS = {
    "arm_a_extended": {
        "seed": 20260922,
        "token_hidden": [96],
        "quantity_hidden": [64],
        "seed_offsets": [1, 2, 3, 4],
    },
    "arm_b_capacity": {
        "seed": 20261022,
        "token_hidden": [128, 64],
        "quantity_hidden": [96, 48],
        "seed_offsets": [1, 2, 3, 4],
    },
    "arm_a_extended_v1": {
        "seed": 20260922,
        "token_hidden": [96],
        "quantity_hidden": [64],
        "seed_offsets": [1, 2, 3, 4],
    },
}
MAX_EPOCHS = 50
PATIENCE = 5
BATCH_SIZE = 2048
LEARNING_RATE = 0.0015
MIN_DELTA = 1e-5


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def initialize(widths: list[int], seed: int | np.random.Generator) -> list[np.ndarray]:
    rng = seed if isinstance(seed, np.random.Generator) else np.random.default_rng(seed)
    parameters: list[np.ndarray] = []
    for input_width, output_width in zip(widths, widths[1:], strict=False):
        parameters.extend(
            (
                rng.normal(0, math.sqrt(2 / input_width), (input_width, output_width)).astype(np.float32),
                np.zeros(output_width, dtype=np.float32),
            )
        )
    return parameters


def forward(x: np.ndarray, parameters: list[np.ndarray]) -> tuple[list[np.ndarray], np.ndarray]:
    activations = [x]
    value = x
    layer_count = len(parameters) // 2
    for layer in range(layer_count):
        value = value @ parameters[2 * layer] + parameters[2 * layer + 1]
        if layer < layer_count - 1:
            value = np.maximum(0.0, value)
            activations.append(value)
    return activations, value


def gradients(
    activations: list[np.ndarray],
    logits: np.ndarray,
    truth: np.ndarray,
    weights: np.ndarray,
    parameters: list[np.ndarray],
) -> tuple[list[np.ndarray], float]:
    shifted = logits - logits.max(axis=1, keepdims=True)
    probability = np.exp(np.clip(shifted, -30, 30))
    probability /= probability.sum(axis=1, keepdims=True)
    sample_weight = weights[truth]
    loss = float((-np.log(np.maximum(probability[np.arange(len(truth)), truth], 1e-9)) * sample_weight).sum())
    gradient = probability
    gradient[np.arange(len(truth)), truth] -= 1.0
    gradient *= (sample_weight / max(1, len(truth)))[:, None]
    result: list[np.ndarray] = [np.empty(0, dtype=np.float32) for _ in parameters]
    layer_count = len(parameters) // 2
    for layer in range(layer_count - 1, -1, -1):
        layer_input = activations[layer]
        result[2 * layer] = layer_input.T @ gradient
        result[2 * layer + 1] = gradient.sum(axis=0)
        if layer > 0:
            gradient = (gradient @ parameters[2 * layer].T) * (activations[layer] > 0)
    return result, loss


def evaluate_loss(
    view: FeatureView,
    truth: np.ndarray,
    mean: np.ndarray,
    scale: np.ndarray,
    parameters: list[np.ndarray],
    *,
    chunk: int = 16384,
) -> tuple[float, float]:
    loss = 0.0
    correct = count = 0
    for start in range(0, len(view), chunk):
        positions = np.arange(start, min(len(view), start + chunk))
        y = truth[positions]
        known = y >= 0
        if not known.any():
            continue
        values = (view.get(positions)[known] - mean) / scale
        y = y[known]
        _activations, logits = forward(values, parameters)
        shifted = logits - logits.max(axis=1, keepdims=True)
        probability = np.exp(np.clip(shifted, -30, 30))
        probability /= probability.sum(axis=1, keepdims=True)
        loss += float(-np.log(np.maximum(probability[np.arange(len(y)), y], 1e-9)).sum())
        correct += int((np.argmax(probability, axis=1) == y).sum())
        count += len(y)
    return loss / max(1, count), correct / max(1, count)


def predict(
    view: FeatureView,
    mean: np.ndarray,
    scale: np.ndarray,
    parameters: list[np.ndarray],
    *,
    chunk: int = 16384,
) -> np.ndarray:
    result = np.empty(len(view), dtype=np.int64)
    for start in range(0, len(view), chunk):
        positions = np.arange(start, min(len(view), start + chunk))
        _activations, logits = forward((view.get(positions) - mean) / scale, parameters)
        result[start : start + len(positions)] = np.argmax(logits, axis=1)
    return result


def metrics(truth: np.ndarray, prediction: np.ndarray, classes: list[str]) -> dict[str, Any]:
    known = truth >= 0
    confusion = np.zeros((len(classes), len(classes)), dtype=np.int64)
    np.add.at(confusion, (truth[known], prediction[known]), 1)
    recalls = np.diag(confusion) / np.maximum(1, confusion.sum(axis=1))
    result: dict[str, Any] = {
        "rows": int(len(truth)),
        "known_label_rows": int(known.sum()),
        "accuracy": float((truth[known] == prediction[known]).mean()),
        "macro_recall": float(recalls.mean()),
        "recall_by_class": {name: float(recalls[index]) for index, name in enumerate(classes)},
        "confusion": confusion.tolist(),
    }
    if all(value.isdigit() for value in classes):
        numeric = np.asarray([int(value) for value in classes])
        actual = numeric[truth[known]]
        estimated = numeric[prediction[known]]
        result["quantity_mae"] = float(np.abs(actual - estimated).mean())
        result["quantity_hierarchy"] = {}
        for label, mask in (
            ("equal_1", actual == 1),
            ("at_least_2", actual >= 2),
            ("at_least_10", actual >= 10),
            ("at_least_15", actual >= 15),
        ):
            result["quantity_hierarchy"][label] = {
                "rows": int(mask.sum()),
                "exact_accuracy": float((actual[mask] == estimated[mask]).mean()) if mask.any() else None,
                "under": int((estimated[mask] < actual[mask]).sum()),
                "over": int((estimated[mask] > actual[mask]).sum()),
            }
    return result


def save_model(
    path: Path,
    mean: np.ndarray,
    scale: np.ndarray,
    parameters: list[np.ndarray],
    classes: list[str],
    metadata: dict[str, Any],
) -> None:
    arrays: dict[str, Any] = {
        "mean": mean,
        "scale": scale,
        "classes": np.asarray(classes),
    }
    for index in range(len(parameters) // 2):
        arrays[f"w{index + 1}"] = parameters[2 * index]
        arrays[f"b{index + 1}"] = parameters[2 * index + 1]
    np.savez_compressed(path, **arrays)
    write_json(path.with_suffix(".json"), metadata)


def round6_epoch10_comparison(name: str, parameters: list[np.ndarray]) -> dict[str, Any] | None:
    path = ROUND6_MODELS / f"{name}.npz"
    if len(parameters) != 4 or not path.is_file():
        return None
    with np.load(path, allow_pickle=False) as data:
        expected = [data["w1"], data["b1"], data["w2"], data["b2"]]
    differences = [float(np.max(np.abs(left - right))) for left, right in zip(parameters, expected, strict=True)]
    return {"max_abs_by_array": differences, "all_equal": all(value == 0 for value in differences)}


def train_head(
    arm: str,
    name: str,
    classes: list[str],
    views: dict[str, FeatureView],
    labels: dict[str, np.ndarray],
    *,
    hidden: list[int],
    weight_exponent: float,
    seed: int,
) -> dict[str, Any]:
    target = EXPERIMENT / "models" / arm
    target.mkdir(parents=True, exist_ok=True)
    log_path = target / "training_logs" / f"{name}.jsonl"
    model_path = target / f"{name}.npz"
    if log_path.exists() or model_path.exists():
        raise FileExistsError(f"refusing to overwrite prior training output for {arm}/{name}")
    mean, scale = feature_moments(views["train"])
    widths = [views["train"].width, *hidden, len(classes)]
    rng = np.random.default_rng(seed)
    parameters = initialize(widths, rng)
    initial = [value.copy() for value in parameters]
    optimizer = Adam(parameters, lr=LEARNING_RATE)
    train_labels = np.asarray(labels["train"], dtype=np.int64)
    counts = np.bincount(train_labels, minlength=len(classes)).astype(np.float32)
    class_weights = np.power(max(1.0, float(counts.max())) / np.maximum(counts, 1.0), weight_exponent)
    class_weights /= np.average(class_weights, weights=np.maximum(counts, 1.0))
    best_loss = float("inf")
    best_epoch = 0
    best: list[np.ndarray] | None = None
    bad_epochs = 0
    epoch10 = None
    started = time.perf_counter()
    append_jsonl(
        log_path,
        {
            "event": "training_start",
            "started_at_utc": utc_now(),
            "architecture": widths,
            "train_rows": len(views["train"]),
            "validation_rows": len(views["validation"]),
            "seed": seed,
            "maximum_epochs": MAX_EPOCHS,
            "patience": PATIENCE,
            "batch_size": BATCH_SIZE,
            "learning_rate": LEARNING_RATE,
            "weight_exponent": weight_exponent,
        },
    )
    for epoch in range(1, MAX_EPOCHS + 1):
        epoch_started = time.perf_counter()
        order = rng.permutation(len(views["train"]))
        train_loss = 0.0
        for start in range(0, len(order), BATCH_SIZE):
            positions = order[start : start + BATCH_SIZE]
            x = (views["train"].get(positions) - mean) / scale
            y = train_labels[positions]
            activations, logits = forward(x, parameters)
            grads, batch_loss = gradients(activations, logits, y, class_weights, parameters)
            train_loss += batch_loss
            optimizer.step(grads)
        validation_loss, validation_accuracy = evaluate_loss(
            views["validation"], labels["validation"], mean, scale, parameters
        )
        record = {
            "epoch": epoch,
            "train_loss": train_loss / max(1, len(train_labels)),
            "validation_loss": validation_loss,
            "validation_accuracy": validation_accuracy,
            "optimizer_steps": optimizer.step_count,
            "epoch_seconds": time.perf_counter() - epoch_started,
        }
        if arm in {"arm_a_extended", "arm_a_extended_v1"} and epoch == 10:
            epoch10 = round6_epoch10_comparison(name, parameters)
            record["round6_epoch10_comparison"] = epoch10
        append_jsonl(log_path, record)
        print(json.dumps({"arm": arm, "head": name, **record}), flush=True)
        if validation_loss < best_loss - MIN_DELTA:
            best_loss = validation_loss
            best_epoch = epoch
            best = [value.copy() for value in parameters]
            bad_epochs = 0
        else:
            bad_epochs += 1
            if bad_epochs >= PATIENCE:
                break
    if best is None:
        raise RuntimeError(f"no checkpoint for {arm}/{name}")
    parameter_count = int(sum(value.size for value in best))
    metadata = {
        "task": f"Round7 {arm} full-action behavioral cloning",
        "architecture": widths,
        "seed": seed,
        "train_rows": len(views["train"]),
        "validation_rows": len(views["validation"]),
        "diagnostic_test_rows": len(views["test"]),
        "optimizer_steps": optimizer.step_count,
        "best_epoch": best_epoch,
        "best_validation_loss": best_loss,
        "parameter_count": parameter_count,
        "class_weight_exponent": weight_exponent,
        "parameter_change_l2": float(
            math.sqrt(sum(float(np.square(a - b).sum()) for a, b in zip(best, initial, strict=True)))
        ),
        "training_seconds": time.perf_counter() - started,
        "round6_epoch10_comparison": epoch10,
        "old_test_role": "diagnostic_development; not checkpoint selection",
    }
    save_model(model_path, mean, scale, best, classes, metadata)
    partition_metrics = {}
    for partition in ("validation", "test"):
        prediction = predict(views[partition], mean, scale, best)
        partition_metrics[partition] = metrics(labels[partition], prediction, classes)
    return {
        "model": str(model_path.relative_to(ROOT)),
        "model_sha256": sha256(model_path),
        "metadata_sha256": sha256(model_path.with_suffix(".json")),
        "architecture": widths,
        "parameter_count": parameter_count,
        "best_epoch": best_epoch,
        "optimizer_steps": optimizer.step_count,
        "validation": partition_metrics["validation"],
        "diagnostic_test": partition_metrics["test"],
    }


def data_views() -> tuple[
    dict[str, dict[str, FeatureView]],
    dict[str, dict[str, np.ndarray]],
    dict[str, list[str]],
]:
    prefix = {
        partition: np.load(PREFIX_DATASET / f"actor_prefix_{partition}.npy", mmap_mode="r")
        for partition in ("train", "validation", "test")
    }
    actor_source = {partition: arrays("actor", partition) for partition in prefix}
    market_source = {partition: arrays("market", partition) for partition in prefix}
    actor_views = {partition: FeatureView(actor_source[partition][0], prefix=prefix[partition]) for partition in prefix}
    market_views = {partition: FeatureView(market_source[partition][0]) for partition in prefix}
    actor_labels = {partition: np.asarray(actor_source[partition][1]) for partition in prefix}
    market_labels = {partition: np.asarray(market_source[partition][1]) for partition in prefix}
    actor_quantity_classes, actor_quantity_views, actor_quantity_labels = quantity_views("actor", actor_source, prefix)
    market_quantity_classes, market_quantity_views, market_quantity_labels = quantity_views(
        "market", market_source, None
    )
    return (
        {
            "actor_token": actor_views,
            "market_token": market_views,
            "actor_quantity": actor_quantity_views,
            "market_quantity": market_quantity_views,
        },
        {
            "actor_token": actor_labels,
            "market_token": market_labels,
            "actor_quantity": actor_quantity_labels,
            "market_quantity": market_quantity_labels,
        },
        {
            "actor_token": list(ACTOR_TOKENS),
            "market_token": list(MARKET_TOKENS),
            "actor_quantity": actor_quantity_classes,
            "market_quantity": market_quantity_classes,
        },
    )


def train_arm(arm: str) -> None:
    config = ARMS[arm]
    views, labels, classes = data_views()
    results = {}
    for index, name in enumerate(("actor_token", "market_token", "actor_quantity", "market_quantity")):
        results[name] = train_head(
            arm,
            name,
            classes[name],
            views[name],
            labels[name],
            hidden=config["token_hidden"] if name.endswith("token") else config["quantity_hidden"],
            weight_exponent=0.5 if name.endswith("token") else 0.0,
            seed=int(config["seed"]) + int(config["seed_offsets"][index]),
        )
    write_json(
        EXPERIMENT / "models" / arm / "offline_metrics.json",
        {
            "created_at_utc": utc_now(),
            "arm": arm,
            "checkpoint_selection": "minimum validation loss per head",
            "old_test_opened_after_checkpoint_selection": True,
            "models": results,
            "total_parameter_count": sum(row["parameter_count"] for row in results.values()),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("arm", choices=tuple(ARMS))
    args = parser.parse_args()
    train_arm(args.arm)


if __name__ == "__main__":
    main()
