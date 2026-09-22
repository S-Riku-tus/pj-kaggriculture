"""Build, train, package, and evaluate the Round4 research agents.

The script never submits to Kaggle and never edits Round3, C0, or prior
holdout ledgers.  Generated artifacts live under learning_round4_20260921.
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
import sys
import tarfile
import tempfile
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.learning_round4_20260921.action_codec import decode_action, encode_action, normalize_action  # noqa: E402
from agents.learning_round4_20260921.features import (  # noqa: E402
    FEATURE_NAMES,
    SKILLS,
    applicable_skills,
    label_skill,
    strategy_features,
)

STUDY = "learning_round4_20260921"
EXPERIMENT = ROOT / "experiments" / STUDY
AGENT = ROOT / "agents" / STUDY
ARCHIVES = ROOT / "artifacts" / "submissions"
TEACHER_SUBMISSION = 56216119
TRAIN_SEED = 20260921
SELECT_LIMITS = {"train": 24, "validation": 8, "test": 8}
ROW_STRIDE = 3
ENGINE = ROOT / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py"
SOURCE_MANIFEST = ROOT / "experiments/learning_next_20260921/source_manifest.json"
SOURCE_SPLIT = ROOT / "experiments/learning_next_20260921/split_manifest.json"
OPPONENTS = {
    "qeinstein_moev2": ROOT / "experiments/research_20260910/runtime/qeinstein_moev2/main.py",
    "smart_farm": ROOT / "experiments/research_20260918_v120/acquisition/smart_farm/decoded_main_1.py",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def load_sources() -> tuple[list[dict[str, Any]], dict[int, str]]:
    source = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    split = json.loads(SOURCE_SPLIT.read_text(encoding="utf-8"))
    rows = [row for row in source["files"] if int(row["submission_id"]) == TEACHER_SUBMISSION]
    assignments = {int(key): str(value) for key, value in split["assignments"].items()}
    return rows, assignments


def select_rows(rows: list[dict[str, Any]], assignments: Mapping[int, str]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        split = assignments[int(row["episode_id"])]
        grouped[split].append(row)
    selected: list[dict[str, Any]] = []
    for split, limit in SELECT_LIMITS.items():
        ordered = sorted(
            grouped[split],
            key=lambda row: hashlib.sha256(f"round4:{TRAIN_SEED}:{row['episode_id']}".encode()).hexdigest(),
        )
        selected.extend({**row, "split": split} for row in ordered[:limit])
    return selected


def restore_observation(step_states: list[dict[str, Any]], seat: int, step: int) -> dict[str, Any]:
    public = dict(step_states[0].get("observation") or {})
    private = step_states[seat].get("observation") or {}
    public["player"] = seat
    public["private"] = private.get("private", {})
    public["remainingOverageTime"] = private.get("remainingOverageTime", public.get("remainingOverageTime", 60))
    public["step"] = step
    return public


def command_inventory() -> None:
    rows, assignments = load_sources()
    selected = select_rows(rows, assignments)
    engine_hash = sha256(ENGINE)
    ledger = {
        "created_at_utc": utc_now(),
        "teacher_submission": TEACHER_SUBMISSION,
        "teacher_version": "UNKNOWN (submission id fixed; private source version unavailable)",
        "teacher_current_rank_status": "UNKNOWN (not re-queried on 2026-09-21 Round4 run)",
        "source_type": "public Kaggle replay JSON already present locally",
        "public_information_only": True,
        "opponent_private_used": False,
        "acquisition_reference": str(SOURCE_MANIFEST.relative_to(ROOT)),
        "acquisition_manifest_created_at_utc": json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))[
            "created_at_utc"
        ],
        "engine": {
            "path": str(ENGINE.relative_to(ROOT)),
            "sha256": engine_hash,
            "version": "kaggle-environments==1.32.7",
        },
        "episode_count": len(rows),
        "episodes": [
            {
                "episode": int(row["episode_id"]),
                "seat": int(row["seat"]),
                "result": row["result"],
                "steps": int(row["step_count"]),
                "path": row["path"],
                "sha256": row["sha256"],
                "split": assignments[int(row["episode_id"])],
                "selected_for_round4_training": any(
                    int(value["episode_id"]) == int(row["episode_id"]) for value in selected
                ),
            }
            for row in rows
        ],
    }
    split_manifest = {
        "created_at_utc": utc_now(),
        "unit": "episode_id",
        "teacher_submission": TEACHER_SUBMISSION,
        "source_split_manifest": str(SOURCE_SPLIT.relative_to(ROOT)),
        "source_rule": (
            "existing SHA256(seed:episode_id) 70/15/15 split; observed conditions are never returned to holdout"
        ),
        "full_counts": dict(Counter(assignments[int(row["episode_id"])] for row in rows)),
        "selected_limits_fixed_before_training": SELECT_LIMITS,
        "selected": [
            {
                "episode": int(row["episode_id"]),
                "seat": int(row["seat"]),
                "split": row["split"],
                "path": row["path"],
                "sha256": row["sha256"],
            }
            for row in selected
        ],
    }
    environment = {
        "captured_at_utc": utc_now(),
        "python": sys.version,
        "platform": platform.platform(),
        "logical_cpus": os.cpu_count(),
        "numpy": np.__version__,
        "engine_sha256": engine_hash,
        "device": "cpu",
        "paid_api_or_cloud_used": False,
    }
    write_json(EXPERIMENT / "TEACHER_LEDGER.json", ledger)
    write_json(EXPERIMENT / "EPISODE_SPLIT_MANIFEST.json", split_manifest)
    write_json(EXPERIMENT / "environment.json", environment)
    print(json.dumps({"teacher_episodes": len(rows), "selected": dict(Counter(row["split"] for row in selected))}))


def _example(
    observation: Mapping[str, Any], action: Mapping[str, Any], episode: int, seat: int, step: int
) -> dict[str, Any]:
    return {
        "episode": episode,
        "seat": seat,
        "step_range": [step, min(719, step + 8)],
        "observable_state_digest": json_hash({"features": strategy_features(observation), "step": step}),
        "observed_action": normalize_action(action),
    }


def build_dataset() -> tuple[dict[str, np.ndarray], dict[str, Any], list[dict[str, Any]]]:
    if not (EXPERIMENT / "EPISODE_SPLIT_MANIFEST.json").is_file():
        command_inventory()
    manifest = json.loads((EXPERIMENT / "EPISODE_SPLIT_MANIFEST.json").read_text(encoding="utf-8"))
    arrays: dict[str, list[Any]] = defaultdict(list)
    class_counts: dict[str, Counter[str]] = defaultdict(Counter)
    positives: dict[str, list[dict[str, Any]]] = defaultdict(list)
    counterexamples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    roundtrip_checked = 0
    roundtrip_failures: list[dict[str, Any]] = []
    per_episode: list[dict[str, Any]] = []
    for index, row in enumerate(manifest["selected"], 1):
        path = ROOT / row["path"]
        if sha256(path) != row["sha256"]:
            raise RuntimeError(f"teacher replay hash mismatch: {path}")
        replay = json.loads(path.read_text(encoding="utf-8"))
        seat = int(row["seat"])
        episode = int(row["episode"])
        local_counts: Counter[str] = Counter()
        for step in range(len(replay["steps"]) - 1):
            stored = replay["steps"][step + 1][seat].get("action") or {"farmer": ["PASS"], "hands": [], "market": []}
            encoded = encode_action(stored)
            decoded = decode_action(encoded)
            roundtrip_checked += 1
            if decoded != normalize_action(stored):
                roundtrip_failures.append({"episode": episode, "seat": seat, "step": step, "encoded": encoded})
            if step % ROW_STRIDE:
                continue
            observation = restore_observation(replay["steps"][step], seat, step)
            label = label_skill(observation, stored)
            split = str(row["split"])
            arrays[f"x_{split}"].append(strategy_features(observation))
            arrays[f"y_{split}"].append(SKILLS.index(label))
            class_counts[split][label] += 1
            local_counts[label] += 1
            applicability = applicable_skills(observation)
            if label != "NONE" and len(positives[label]) < 4:
                positives[label].append(_example(observation, stored, episode, seat, step))
            for skill, applicable in applicability.items():
                if applicable and label != skill and len(counterexamples[skill]) < 4:
                    counterexamples[skill].append(_example(observation, stored, episode, seat, step))
        per_episode.append({"episode": episode, "seat": seat, "split": row["split"], "labels": dict(local_counts)})
        print(f"dataset {index}/{len(manifest['selected'])} episode={episode} split={row['split']}", flush=True)
    if roundtrip_failures:
        raise RuntimeError(f"action roundtrip failed {len(roundtrip_failures)} times")
    output = {
        key: np.asarray(value, dtype=np.float32 if key.startswith("x_") else np.int64) for key, value in arrays.items()
    }
    dataset_manifest = {
        "created_at_utc": utc_now(),
        "task": "single-teacher executable strategy skill selection",
        "teacher_submission": TEACHER_SUBMISSION,
        "row_stride": ROW_STRIDE,
        "feature_names": FEATURE_NAMES,
        "classes": SKILLS,
        "class_counts": {key: dict(value) for key, value in class_counts.items()},
        "shapes": {key: list(value.shape) for key, value in output.items()},
        "episode_rows": per_episode,
        "label_origin": (
            "observed public replay action; inferred skill names are analyst labels, not teacher-authored intent"
        ),
        "hidden_inputs_used": [],
    }
    roundtrip = {
        "created_at_utc": utc_now(),
        "codec": "lossless-json-action-v1",
        "selected_episode_count": len(manifest["selected"]),
        "actions_checked": roundtrip_checked,
        "failures": roundtrip_failures,
        "quantities_preserved": True,
        "market_order_preserved": True,
        "all_ok": not roundtrip_failures,
    }
    cards = []
    card_details = {
        "ANIMAL_SERVICE_WITH_CONTINUATION": {
            "inferred_intent": (
                "INFERENCE: maintain animals through the daily deadline while preserving "
                "wheat and the next service route."
            ),
            "alternative_plans": [
                "buy wheat before shortage",
                "skip non-production-day care",
                "reassign target to another actor",
            ],
            "required_resources_and_deadlines": {"WHEAT": "one per effective FEED", "deadline": "day end"},
            "success_postconditions": [
                "target fed transition",
                "responsible actor wheat decreased",
                "remaining service wheat reserved",
            ],
            "abort_and_replan_conditions": ["target already served", "actor day identity changed", "wheat unavailable"],
        },
        "HARVEST_AND_LAND_CONVERSION": {
            "inferred_intent": (
                "INFERENCE: realize mature crop value and release land only when the engine harvest precondition holds."
            ),
            "alternative_plans": [
                "delay for additional one-time-crop yield",
                "water or fertilize first",
                "retain ongoing crop",
            ],
            "required_resources_and_deadlines": {
                "maturity": "crop-specific first_yield_day",
                "capacity": "end-day shed headroom considered separately",
            },
            "success_postconditions": ["actor crop inventory increased", "target tile or yield changed"],
            "abort_and_replan_conditions": ["immature crop", "zero yield", "target changed"],
        },
        "SELL_AND_REINVEST": {
            "inferred_intent": (
                "INFERENCE: convert inventory to cash and order the next investment "
                "without losing market quantity or order."
            ),
            "alternative_plans": [
                "wait for demand recovery",
                "sell a partial quantity",
                "reserve cash for feed or land",
            ],
            "required_resources_and_deadlines": {
                "inventory": "requested sell quantity",
                "cash": "ordered purchases",
                "order_slots": 10,
            },
            "success_postconditions": [
                "requested order remains exactly encoded",
                "cash and inventory deltas are observed",
            ],
            "abort_and_replan_conditions": ["inventory insufficient", "cash insufficient", "order cap exceeded"],
        },
    }
    for skill, details in card_details.items():
        examples = positives.get(skill, [])
        cards.append(
            {
                "skill_id": skill.lower(),
                "teacher_submission": TEACHER_SUBMISSION,
                "teacher_version_uncertainty": (
                    "private implementation/version unknown; submission id is the only fixed version key"
                ),
                "evidence": [
                    {key: value for key, value in example.items() if key in {"episode", "seat", "step_range"}}
                    for example in examples
                ],
                "observable_preconditions": ["derived only from focal public observation and focal private state"],
                "observed_plan": [example["observed_action"] for example in examples],
                **details,
                "counterexamples": counterexamples.get(skill, []),
            }
        )
    write_json(EXPERIMENT / "DATASET_MANIFEST.json", dataset_manifest)
    write_json(EXPERIMENT / "ACTION_ROUNDTRIP.json", roundtrip)
    write_json(EXPERIMENT / "SKILL_CARDS.json", {"cards": cards})
    return output, dataset_manifest, cards


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=1, keepdims=True)
    values = np.exp(np.clip(shifted, -30, 30))
    return values / np.maximum(values.sum(axis=1, keepdims=True), 1e-12)


def _metrics(
    x: np.ndarray, y: np.ndarray, weights: np.ndarray, bias: np.ndarray, mean: np.ndarray, scale: np.ndarray
) -> dict[str, Any]:
    probability = _softmax(((x - mean) / scale) @ weights + bias)
    prediction = probability.argmax(axis=1)
    confusion = np.zeros((len(SKILLS), len(SKILLS)), dtype=np.int64)
    for actual, predicted in zip(y, prediction, strict=True):
        confusion[int(actual), int(predicted)] += 1
    by_class = {}
    f1s = []
    for index, label in enumerate(SKILLS):
        tp = float(confusion[index, index])
        precision = tp / max(1.0, float(confusion[:, index].sum()))
        recall = tp / max(1.0, float(confusion[index, :].sum()))
        f1 = 2 * precision * recall / max(1e-12, precision + recall)
        f1s.append(f1)
        by_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": int(confusion[index, :].sum()),
        }
    return {
        "rows": int(len(y)),
        "accuracy": float((prediction == y).mean()),
        "macro_f1": float(np.mean(f1s)),
        "cross_entropy": float(-np.log(np.maximum(probability[np.arange(len(y)), y], 1e-12)).mean()),
        "confusion": confusion.tolist(),
        "by_class": by_class,
    }


def _train_linear(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_validation: np.ndarray,
    y_validation: np.ndarray,
    *,
    epochs: int,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[dict[str, Any]], int]:
    mean = x_train.mean(axis=0)
    scale = x_train.std(axis=0)
    scale[scale < 1e-5] = 1.0
    rng = np.random.default_rng(seed)
    weights = rng.normal(0, 0.01, (x_train.shape[1], len(SKILLS))).astype(np.float64)
    bias = np.zeros(len(SKILLS), dtype=np.float64)
    count = np.bincount(y_train, minlength=len(SKILLS)).astype(np.float64)
    class_weight = np.minimum(8.0, len(y_train) / np.maximum(1.0, len(SKILLS) * count))
    velocity_w = np.zeros_like(weights)
    velocity_b = np.zeros_like(bias)
    best: tuple[float, np.ndarray, np.ndarray] | None = None
    log: list[dict[str, Any]] = []
    updates = 0
    batch_size = 512
    for epoch in range(1, epochs + 1):
        order = rng.permutation(len(y_train))
        train_loss = 0.0
        for start in range(0, len(order), batch_size):
            indices = order[start : start + batch_size]
            x = (x_train[indices] - mean) / scale
            y = y_train[indices]
            probability = _softmax(x @ weights + bias)
            row_weight = class_weight[y]
            train_loss += float((-np.log(np.maximum(probability[np.arange(len(y)), y], 1e-12)) * row_weight).sum())
            gradient = probability
            gradient[np.arange(len(y)), y] -= 1.0
            gradient *= row_weight[:, None] / max(1, len(y))
            grad_w = x.T @ gradient + 1e-4 * weights
            grad_b = gradient.sum(axis=0)
            velocity_w = 0.9 * velocity_w + grad_w
            velocity_b = 0.9 * velocity_b + grad_b
            learning_rate = 0.03 / math.sqrt(epoch)
            weights -= learning_rate * velocity_w
            bias -= learning_rate * velocity_b
            updates += 1
        validation = _metrics(x_validation, y_validation, weights, bias, mean, scale)
        row = {
            "epoch": epoch,
            "train_weighted_loss": train_loss / max(1, len(y_train)),
            "validation": validation,
            "optimizer_updates": updates,
        }
        log.append(row)
        print(json.dumps(row), flush=True)
        if best is None or validation["cross_entropy"] < best[0]:
            best = (validation["cross_entropy"], weights.copy(), bias.copy())
    assert best is not None
    return best[1], best[2], mean, scale, log, updates


def command_train() -> None:
    arrays, dataset_manifest, _cards = build_dataset()
    x_train, y_train = arrays["x_train"], arrays["y_train"]
    x_validation, y_validation = arrays["x_validation"], arrays["y_validation"]
    x_test, y_test = arrays["x_test"], arrays["y_test"]

    sanity_size = min(512, len(y_train))
    sanity_w, sanity_b, sanity_mean, sanity_scale, sanity_log, sanity_updates = _train_linear(
        x_train[:sanity_size],
        y_train[:sanity_size],
        x_train[:sanity_size],
        y_train[:sanity_size],
        epochs=12,
        seed=TRAIN_SEED,
    )
    sanity = _metrics(x_train[:sanity_size], y_train[:sanity_size], sanity_w, sanity_b, sanity_mean, sanity_scale)

    initial_w = np.zeros((x_train.shape[1], len(SKILLS)), dtype=np.float64)
    initial_b = np.zeros(len(SKILLS), dtype=np.float64)
    weights, bias, mean, scale, log, updates = _train_linear(
        x_train, y_train, x_validation, y_validation, epochs=18, seed=TRAIN_SEED
    )
    validation = _metrics(x_validation, y_validation, weights, bias, mean, scale)
    test = _metrics(x_test, y_test, weights, bias, mean, scale)
    majority = int(np.bincount(y_train, minlength=len(SKILLS)).argmax())
    baseline_prediction = np.full_like(y_test, majority)
    baseline_accuracy = float((baseline_prediction == y_test).mean())
    baseline_macro_f1 = float(
        np.mean(
            [
                (2 * ((baseline_prediction == index) & (y_test == index)).sum())
                / max(1, int((baseline_prediction == index).sum() + (y_test == index).sum()))
                for index in range(len(SKILLS))
            ]
        )
    )
    parameter_change = float(np.sqrt(np.square(weights - initial_w).sum() + np.square(bias - initial_b).sum()))
    checkpoint = {
        "format": "round4-softmax-skill-selector-v1",
        "created_at_utc": utc_now(),
        "teacher_submission": TEACHER_SUBMISSION,
        "feature_names": FEATURE_NAMES,
        "classes": SKILLS,
        "mean": mean.tolist(),
        "scale": scale.tolist(),
        "weights": weights.tolist(),
        "bias": bias.tolist(),
        "optimizer_updates": updates,
        "dataset_manifest_sha256": json_hash(dataset_manifest),
    }
    write_json(AGENT / "strategy_model.json", checkpoint)
    checkpoint_hash = sha256(AGENT / "strategy_model.json")

    # A reload inference proves the serialized representation is executable.
    from agents.learning_round4_20260921.selector import SkillSelector

    reloaded = SkillSelector(AGENT / "strategy_model.json")
    first_manifest = json.loads((EXPERIMENT / "EPISODE_SPLIT_MANIFEST.json").read_text(encoding="utf-8"))["selected"][0]
    replay = json.loads((ROOT / first_manifest["path"]).read_text(encoding="utf-8"))
    reload_observation = restore_observation(replay["steps"][0], int(first_manifest["seat"]), 0)
    reload_scores = reloaded.scores(reload_observation)
    training = {
        "created_at_utc": utc_now(),
        "teacher_submission": TEACHER_SUBMISSION,
        "checkpoint": str((AGENT / "strategy_model.json").relative_to(ROOT)),
        "checkpoint_sha256": checkpoint_hash,
        "optimizer_updates": updates,
        "parameter_change_l2": parameter_change,
        "sanity": {"rows": sanity_size, "updates": sanity_updates, "metrics": sanity, "log": sanity_log},
        "full_training_log": log,
        "validation": validation,
        "test": test,
        "baseline_test": {
            "majority_class": SKILLS[majority],
            "accuracy": baseline_accuracy,
            "macro_f1": baseline_macro_f1,
        },
        "important_decision_metrics": test["by_class"],
        "reload_inference": {
            "calls": reloaded.inference_calls,
            "scores": reload_scores,
            "finite": all(math.isfinite(value) for value in reload_scores.values()),
        },
        "skill_macro_accuracy_delta": test["macro_f1"] - baseline_macro_f1,
        "action_changes": "measured in subsequent closed-loop run, not inferred from teacher-state accuracy",
    }
    write_json(EXPERIMENT / "TRAINING_RECORD.json", training)
    print(
        json.dumps(
            {
                "checkpoint_sha256": checkpoint_hash,
                "updates": updates,
                "test": test,
                "reload": training["reload_inference"],
            }
        )
    )


def _manifest_sources(kind: str) -> list[tuple[Path, str]]:
    manifest = json.loads((AGENT / "submission_manifest.json").read_text(encoding="utf-8"))
    result = []
    for row in manifest[kind]:
        source = (AGENT / row["source"]).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        result.append((source, str(row["target"])))
    return result


def command_package() -> None:
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    records = {}
    for kind in ("learned", "rule"):
        sources = _manifest_sources(kind)
        archive = ARCHIVES / f"{STUDY}_{kind}.tar.gz"
        with tempfile.TemporaryDirectory(prefix=f"{STUDY}_{kind}_", dir=EXPERIMENT) as temporary:
            stage = Path(temporary)
            for source, target in sources:
                destination = stage / target
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            with tarfile.open(archive, "w:gz") as stream:
                for path in sorted(stage.rglob("*")):
                    if path.is_file():
                        stream.add(path, arcname=path.relative_to(stage).as_posix())
        records[kind] = {
            "path": str(archive.relative_to(ROOT)),
            "sha256": sha256(archive),
            "bytes": archive.stat().st_size,
            "files": [
                {"path": target, "source": str(source.relative_to(ROOT)), "sha256": sha256(source)}
                for source, target in sources
            ],
        }
    write_json(EXPERIMENT / "ARCHIVE_MANIFEST.json", {"created_at_utc": utc_now(), "archives": records})
    print(json.dumps(records, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inventory", "train", "package"))
    args = parser.parse_args()
    {"inventory": command_inventory, "train": command_train, "package": command_package}[args.command]()


if __name__ == "__main__":
    main()
