"""Train and package the preregistered Round6 sequence-aware full-action BC candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tarfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
EXPERIMENT = ROOT / "experiments" / "learning_round6_20260922"
SOURCE_EXPERIMENT = ROOT / "experiments" / "learning_next_20260921"
SOURCE_DATASET = SOURCE_EXPERIMENT / "datasets" / "bc"
DATASET = EXPERIMENT / "datasets" / "sequence_bc_v1"
MODEL_DIR = EXPERIMENT / "models" / "sequence_bc_v1"
AGENT_MAIN = ROOT / "agents" / "learning_round6_20260922_v1" / "main.py"
COMMON = ROOT / "agents" / "learning_next_20260921" / "common.py"
ARCHIVE = ROOT / "artifacts" / "submissions" / "learning_round6_20260922_sequence_bc_v1.tar.gz"
TEACHER_ID = 56216119
TRAIN_SEED = 20260922
PREFIX_WIDTH = 88

from agents.learning_next_20260921.common import ACTOR_TOKENS, MARKET_TOKENS, action_token  # noqa: E402
from scripts.learning_next_pipeline import Adam, forward, save_model  # noqa: E402


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
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


def restore_observation(states: list[dict[str, Any]], seat: int, step: int) -> dict[str, Any]:
    public = dict(states[0].get("observation") or {})
    private = states[seat].get("observation") or {}
    public["player"] = seat
    public["private"] = private.get("private", {})
    public["remainingOverageTime"] = private.get(
        "remainingOverageTime", public.get("remainingOverageTime", 60)
    )
    public["step"] = step
    return public


def sampled_actor(episode_id: int, step: int, actor: int) -> bool:
    value = int(hashlib.sha256(f"{episode_id}:{step}:{actor}".encode()).hexdigest()[:8], 16)
    return value % 5 == 0


def prefix_features(prefix_tokens: list[str]) -> np.ndarray:
    counts = np.zeros(len(ACTOR_TOKENS), dtype=np.float32)
    for token in prefix_tokens:
        if token in ACTOR_TOKENS:
            counts[ACTOR_TOKENS.index(token)] += 1.0
    if prefix_tokens:
        counts /= len(prefix_tokens)
    previous = np.zeros(len(ACTOR_TOKENS), dtype=np.float32)
    if prefix_tokens and prefix_tokens[-1] in ACTOR_TOKENS:
        previous[ACTOR_TOKENS.index(prefix_tokens[-1])] = 1.0
    return np.concatenate((counts, previous))


def build_prefix_dataset() -> None:
    source = json.loads((SOURCE_EXPERIMENT / "source_manifest.json").read_text(encoding="utf-8"))
    split = json.loads((SOURCE_EXPERIMENT / "split_manifest.json").read_text(encoding="utf-8"))[
        "assignments"
    ]
    entries = [row for row in source["files"] if int(row["submission_id"]) == TEACHER_ID]
    expected = {
        name: np.load(SOURCE_DATASET / f"actor_y_{name}.npy", mmap_mode="r", allow_pickle=False)
        for name in ("train", "validation", "test")
    }
    DATASET.mkdir(parents=True, exist_ok=True)
    outputs = {
        name: np.lib.format.open_memmap(
            DATASET / f"actor_prefix_{name}.npy",
            mode="w+",
            dtype=np.float32,
            shape=(len(labels), PREFIX_WIDTH),
        )
        for name, labels in expected.items()
    }
    cursor = Counter()
    seats = Counter()
    for number, row in enumerate(entries, 1):
        path = ROOT / str(row["path"])
        if sha256(path) != row["sha256"]:
            raise RuntimeError(f"teacher replay hash mismatch: {path}")
        replay = json.loads(path.read_text(encoding="utf-8"))
        seat = int(row["seat"])
        episode_id = int(row["episode_id"])
        partition = str(split[str(episode_id)])
        seats[f"{partition}:seat{seat}"] += 1
        for step in range(len(replay["steps"]) - 1):
            observation = restore_observation(replay["steps"][step], seat, step)
            action = replay["steps"][step + 1][seat].get("action") or {}
            units = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
            actor_count = 1 + len(observation["farms"][seat].get("hands", []))
            prefix: list[str] = []
            for actor_index in range(min(actor_count, len(units))):
                token = action_token(units[actor_index])
                if sampled_actor(episode_id, step, actor_index) and token in ACTOR_TOKENS:
                    position = cursor[partition]
                    expected_token = int(expected[partition][position])
                    actual_token = ACTOR_TOKENS.index(token)
                    if expected_token != actual_token:
                        raise RuntimeError(
                            f"source row misalignment at {partition}[{position}]: "
                            f"expected={expected_token} actual={actual_token}"
                        )
                    outputs[partition][position] = prefix_features(prefix)
                    cursor[partition] += 1
                prefix.append(token)
        if number % 20 == 0:
            print(f"prefix build {number}/{len(entries)} rows={dict(cursor)}", flush=True)
    for name, labels in expected.items():
        outputs[name].flush()
        if cursor[name] != len(labels):
            raise RuntimeError(f"prefix row count mismatch for {name}: {cursor[name]} != {len(labels)}")
    write_json(
        DATASET / "dataset_manifest.json",
        {
            "created_at_utc": utc_now(),
            "teacher_submission": TEACHER_ID,
            "source_split_manifest_sha256": sha256(SOURCE_EXPERIMENT / "split_manifest.json"),
            "source_dataset_manifest_sha256": sha256(SOURCE_DATASET / "dataset_manifest.json"),
            "rows": {name: len(labels) for name, labels in expected.items()},
            "feature_width": PREFIX_WIDTH,
            "features": "normalized same-turn decoded-token counts plus immediately preceding decoded token",
            "both_seats": dict(seats),
            "alignment_verified_against_original_actor_labels": True,
        },
    )


class FeatureView:
    def __init__(
        self,
        base: np.ndarray,
        *,
        prefix: np.ndarray | None = None,
        rows: np.ndarray | None = None,
        token_ids: np.ndarray | None = None,
        token_width: int = 0,
    ) -> None:
        self.base = base
        self.prefix = prefix
        self.rows = rows
        self.token_ids = token_ids
        self.token_width = token_width
        self.width = int(base.shape[1]) + (int(prefix.shape[1]) if prefix is not None else 0) + token_width

    def __len__(self) -> int:
        return len(self.rows) if self.rows is not None else len(self.base)

    def get(self, positions: np.ndarray) -> np.ndarray:
        absolute = self.rows[positions] if self.rows is not None else positions
        parts = [np.asarray(self.base[absolute], dtype=np.float32)]
        if self.prefix is not None:
            parts.append(np.asarray(self.prefix[absolute], dtype=np.float32))
        if self.token_ids is not None:
            one_hot = np.zeros((len(absolute), self.token_width), dtype=np.float32)
            one_hot[np.arange(len(absolute)), np.asarray(self.token_ids[absolute], dtype=np.int64)] = 1.0
            parts.append(one_hot)
        return parts[0] if len(parts) == 1 else np.concatenate(parts, axis=1)


def feature_moments(view: FeatureView, chunk: int = 32768) -> tuple[np.ndarray, np.ndarray]:
    total = np.zeros(view.width, dtype=np.float64)
    square = np.zeros(view.width, dtype=np.float64)
    count = 0
    for start in range(0, len(view), chunk):
        positions = np.arange(start, min(len(view), start + chunk))
        values = view.get(positions).astype(np.float64)
        total += values.sum(axis=0)
        square += np.square(values).sum(axis=0)
        count += len(values)
    mean = total / max(1, count)
    variance = np.maximum(square / max(1, count) - np.square(mean), 1e-6)
    return mean.astype(np.float32), np.sqrt(variance).astype(np.float32)


def predict_batches(
    view: FeatureView,
    mean: np.ndarray,
    scale: np.ndarray,
    parameters: list[np.ndarray],
    chunk: int = 16384,
) -> np.ndarray:
    prediction = np.empty(len(view), dtype=np.int64)
    for start in range(0, len(view), chunk):
        positions = np.arange(start, min(len(view), start + chunk))
        values = (view.get(positions) - mean) / scale
        _hidden, logits = forward(values, parameters)
        prediction[start : start + len(positions)] = np.argmax(logits, axis=1)
    return prediction


def classification_metrics(truth: np.ndarray, prediction: np.ndarray, classes: list[str]) -> dict[str, Any]:
    known = truth >= 0
    confusion = np.zeros((len(classes), len(classes)), dtype=np.int64)
    np.add.at(confusion, (truth[known], prediction[known]), 1)
    recall = np.diag(confusion) / np.maximum(1, confusion.sum(axis=1))
    numeric = np.asarray([float(value) for value in classes]) if all(value.isdigit() for value in classes) else None
    result: dict[str, Any] = {
        "rows": int(len(truth)),
        "known_label_rows": int(known.sum()),
        "accuracy": float((prediction[known] == truth[known]).mean()) if known.any() else 0.0,
        "macro_recall": float(recall.mean()),
        "recall_by_class": {name: float(recall[index]) for index, name in enumerate(classes)},
        "confusion": confusion.tolist(),
    }
    if numeric is not None and known.any():
        result["quantity_mae"] = float(np.abs(numeric[prediction[known]] - numeric[truth[known]]).mean())
    return result


def validation_loss(
    view: FeatureView,
    truth: np.ndarray,
    mean: np.ndarray,
    scale: np.ndarray,
    parameters: list[np.ndarray],
    chunk: int = 16384,
) -> tuple[float, float]:
    loss = 0.0
    correct = 0
    count = 0
    for start in range(0, len(view), chunk):
        positions = np.arange(start, min(len(view), start + chunk))
        y = truth[positions]
        known = y >= 0
        if not known.any():
            continue
        values = (view.get(positions)[known] - mean) / scale
        y = y[known]
        _hidden, logits = forward(values, parameters)
        logits -= logits.max(axis=1, keepdims=True)
        probability = np.exp(np.clip(logits, -30, 30))
        probability /= probability.sum(axis=1, keepdims=True)
        loss += float(-np.log(np.maximum(probability[np.arange(len(y)), y], 1e-9)).sum())
        correct += int((np.argmax(probability, axis=1) == y).sum())
        count += len(y)
    return loss / max(1, count), correct / max(1, count)


def train_model(
    name: str,
    classes: list[str],
    views: dict[str, FeatureView],
    labels: dict[str, np.ndarray],
    *,
    hidden_width: int,
    weight_exponent: float,
    seed_offset: int,
) -> dict[str, Any]:
    mean, scale = feature_moments(views["train"])
    rng = np.random.default_rng(TRAIN_SEED + seed_offset)
    parameters = [
        rng.normal(0, math.sqrt(2 / views["train"].width), (views["train"].width, hidden_width)).astype(
            np.float32
        ),
        np.zeros(hidden_width, dtype=np.float32),
        rng.normal(0, math.sqrt(2 / hidden_width), (hidden_width, len(classes))).astype(np.float32),
        np.zeros(len(classes), dtype=np.float32),
    ]
    initial = [value.copy() for value in parameters]
    optimizer = Adam(parameters, lr=0.0015)
    train_labels = np.asarray(labels["train"], dtype=np.int64)
    counts = np.bincount(train_labels, minlength=len(classes)).astype(np.float32)
    weights = np.power(max(1.0, float(counts.max())) / np.maximum(counts, 1.0), weight_exponent)
    weights /= np.average(weights, weights=np.maximum(counts, 1.0))
    best_loss = float("inf")
    best: list[np.ndarray] | None = None
    bad_epochs = 0
    log_path = MODEL_DIR / "training_logs" / f"{name}.jsonl"
    if log_path.exists():
        raise FileExistsError(f"refusing to append to existing training log: {log_path}")
    append_jsonl(
        log_path,
        {
            "event": "training_start",
            "started_at_utc": utc_now(),
            "feature_width": views["train"].width,
            "hidden_width": hidden_width,
            "train_rows": len(views["train"]),
            "seed": TRAIN_SEED + seed_offset,
            "weight_exponent": weight_exponent,
        },
    )
    for epoch in range(1, 11):
        order = rng.permutation(len(views["train"]))
        train_loss = 0.0
        for start in range(0, len(order), 2048):
            positions = order[start : start + 2048]
            x = (views["train"].get(positions) - mean) / scale
            y = train_labels[positions]
            hidden, logits = forward(x, parameters)
            logits -= logits.max(axis=1, keepdims=True)
            probability = np.exp(np.clip(logits, -30, 30))
            probability /= probability.sum(axis=1, keepdims=True)
            sample_weight = weights[y]
            train_loss += float(
                (-np.log(np.maximum(probability[np.arange(len(y)), y], 1e-9)) * sample_weight).sum()
            )
            gradient = probability
            gradient[np.arange(len(y)), y] -= 1.0
            gradient *= (sample_weight / max(1, len(y)))[:, None]
            grad_w2 = hidden.T @ gradient
            grad_b2 = gradient.sum(axis=0)
            grad_hidden = (gradient @ parameters[2].T) * (hidden > 0)
            optimizer.step([x.T @ grad_hidden, grad_hidden.sum(axis=0), grad_w2, grad_b2])
        val_loss, val_accuracy = validation_loss(
            views["validation"], labels["validation"], mean, scale, parameters
        )
        record = {
            "epoch": epoch,
            "train_loss": train_loss / max(1, len(train_labels)),
            "validation_loss": val_loss,
            "validation_accuracy": val_accuracy,
            "optimizer_steps": optimizer.step_count,
        }
        append_jsonl(log_path, record)
        print(json.dumps({"model": name, **record}), flush=True)
        if val_loss < best_loss - 1e-5:
            best_loss = val_loss
            best = [value.copy() for value in parameters]
            bad_epochs = 0
        else:
            bad_epochs += 1
            if bad_epochs >= 2:
                break
    if best is None:
        raise RuntimeError(f"no checkpoint produced for {name}")
    path = MODEL_DIR / f"{name}.npz"
    save_model(
        path,
        mean,
        scale,
        best,
        classes,
        {
            "task": "round6 sequence-aware full-action behavioral cloning",
            "architecture": f"{views['train'].width}-{hidden_width}-{len(classes)} ReLU MLP",
            "seed": TRAIN_SEED + seed_offset,
            "train_rows": len(views["train"]),
            "validation_rows": len(views["validation"]),
            "test_rows": len(views["test"]),
            "optimizer_steps": optimizer.step_count,
            "best_validation_loss": best_loss,
            "class_weight_exponent": weight_exponent,
            "parameter_change_l2": float(
                math.sqrt(sum(float(np.square(a - b).sum()) for a, b in zip(best, initial, strict=True)))
            ),
        },
    )
    metrics = {}
    for partition in ("validation", "test"):
        prediction = predict_batches(views[partition], mean, scale, best)
        metrics[partition] = classification_metrics(labels[partition], prediction, classes)
    return {
        "model": str(path.relative_to(ROOT)),
        "model_sha256": sha256(path),
        "train_rows": len(views["train"]),
        "validation": metrics["validation"],
        "test": metrics["test"],
        "optimizer_steps": optimizer.step_count,
    }


def arrays(group: str, partition: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    return (
        np.load(SOURCE_DATASET / f"{group}_x_{partition}.npy", mmap_mode="r", allow_pickle=False),
        np.load(SOURCE_DATASET / f"{group}_y_{partition}.npy", mmap_mode="r", allow_pickle=False),
        np.load(SOURCE_DATASET / f"{group}_quantity_{partition}.npy", mmap_mode="r", allow_pickle=False),
    )


def quantity_views(
    group: str,
    source: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]],
    prefix: dict[str, np.ndarray] | None,
) -> tuple[list[str], dict[str, FeatureView], dict[str, np.ndarray]]:
    tokens = ACTOR_TOKENS if group == "actor" else MARKET_TOKENS
    applicable = {
        index
        for index, token in enumerate(tokens)
        if token.startswith(("PICKUP:", "PLACE:"))
        if group == "actor"
    }
    if group == "market":
        applicable = {index for index, token in enumerate(tokens) if token not in {"EOS", "HIRE", "BUY_LAND"}}
    rows = {
        partition: np.flatnonzero(np.isin(np.asarray(values[1]), np.asarray(sorted(applicable))))
        for partition, values in source.items()
    }
    train_quantities = np.asarray(source["train"][2][rows["train"]], dtype=np.int64)
    quantity_values = sorted(set(int(value) for value in train_quantities))
    lookup = {value: index for index, value in enumerate(quantity_values)}
    views = {}
    labels = {}
    for partition, values in source.items():
        x, token_y, quantity = values
        views[partition] = FeatureView(
            x,
            prefix=None if prefix is None else prefix[partition],
            rows=rows[partition],
            token_ids=token_y,
            token_width=len(tokens),
        )
        labels[partition] = np.asarray(
            [lookup.get(int(value), -1) for value in np.asarray(quantity[rows[partition]])], dtype=np.int64
        )
    return [str(value) for value in quantity_values], views, labels


def train() -> None:
    if not (DATASET / "dataset_manifest.json").is_file():
        build_prefix_dataset()
    prefix = {
        partition: np.load(DATASET / f"actor_prefix_{partition}.npy", mmap_mode="r", allow_pickle=False)
        for partition in ("train", "validation", "test")
    }
    actor_source = {partition: arrays("actor", partition) for partition in prefix}
    market_source = {partition: arrays("market", partition) for partition in prefix}
    actor_views = {
        partition: FeatureView(actor_source[partition][0], prefix=prefix[partition]) for partition in prefix
    }
    market_views = {partition: FeatureView(market_source[partition][0]) for partition in prefix}
    actor_labels = {partition: np.asarray(actor_source[partition][1]) for partition in prefix}
    market_labels = {partition: np.asarray(market_source[partition][1]) for partition in prefix}
    results = {
        "actor_token": train_model(
            "actor_token",
            list(ACTOR_TOKENS),
            actor_views,
            actor_labels,
            hidden_width=96,
            weight_exponent=0.5,
            seed_offset=1,
        ),
        "market_token": train_model(
            "market_token",
            list(MARKET_TOKENS),
            market_views,
            market_labels,
            hidden_width=96,
            weight_exponent=0.5,
            seed_offset=2,
        ),
    }
    actor_quantity_classes, actor_quantity_views, actor_quantity_labels = quantity_views(
        "actor", actor_source, prefix
    )
    market_quantity_classes, market_quantity_views, market_quantity_labels = quantity_views(
        "market", market_source, None
    )
    results["actor_quantity"] = train_model(
        "actor_quantity",
        actor_quantity_classes,
        actor_quantity_views,
        actor_quantity_labels,
        hidden_width=64,
        weight_exponent=0.0,
        seed_offset=3,
    )
    results["market_quantity"] = train_model(
        "market_quantity",
        market_quantity_classes,
        market_quantity_views,
        market_quantity_labels,
        hidden_width=64,
        weight_exponent=0.0,
        seed_offset=4,
    )
    write_json(
        EXPERIMENT / "candidate_v1_offline_metrics.json",
        {
            "created_at_utc": utc_now(),
            "candidate": "round6_sequence_bc_v1",
            "test_opened_only_after_validation_checkpoint_selection": True,
            "models": results,
        },
    )


def package() -> None:
    required: list[tuple[Path, str]] = [(AGENT_MAIN, "main.py"), (COMMON, "common.py")]
    for name in ("actor_token", "market_token", "actor_quantity", "market_quantity"):
        required.extend([(MODEL_DIR / f"{name}.npz", f"{name}.npz"), (MODEL_DIR / f"{name}.json", f"{name}.json")])
    missing = [str(path) for path, _arcname in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(missing)
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(ARCHIVE, "w:gz") as stream:
        for path, arcname in required:
            stream.add(path, arcname=arcname)
    members = []
    with tarfile.open(ARCHIVE, "r:gz") as stream:
        for member in sorted(stream.getmembers(), key=lambda value: value.name):
            extracted = stream.extractfile(member)
            content = extracted.read() if extracted is not None else b""
            members.append(
                {
                    "name": member.name,
                    "bytes": member.size,
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
    write_json(
        EXPERIMENT / "candidate_v1_archive_manifest.json",
        {
            "created_at_utc": utc_now(),
            "archive": str(ARCHIVE.relative_to(ROOT)),
            "archive_sha256": sha256(ARCHIVE),
            "members": members,
            "entrypoint": "main.py",
            "online_operations": 0,
        },
    )
    print(json.dumps({"archive": str(ARCHIVE), "sha256": sha256(ARCHIVE)}, indent=2), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "train", "package", "all"))
    args = parser.parse_args()
    if args.command in {"build", "all"}:
        build_prefix_dataset()
    if args.command in {"train", "all"}:
        train()
    if args.command in {"package", "all"}:
        package()


if __name__ == "__main__":
    main()
