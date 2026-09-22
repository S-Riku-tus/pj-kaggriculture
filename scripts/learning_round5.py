"""Train, audit, and package the bounded Round5 Kaggriculture study.

This script never submits to Kaggle and never mutates Round1--4 artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import tarfile
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments/learning_round5_20260921"
AGENT = ROOT / "agents/learning_round5_20260921"
ARCHIVES = ROOT / "artifacts/submissions"
ROUND4 = ROOT / "experiments/learning_round4_20260921"
SELECTED_MANIFEST = ROUND4 / "EPISODE_SPLIT_MANIFEST.json"
TEACHER_SUBMISSION = 56216119
TRAIN_SEED = 20260921
ROW_STRIDE = 3

import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.learning_next_20260921.common import action_token, market_token, token_action, token_order  # noqa: E402
from agents.learning_round5_20260921.action_codec import decode_action, encode_action, normalize_action  # noqa: E402
from agents.learning_round5_20260921.features import (  # noqa: E402
    FEATURE_NAMES,
    SKILLS,
    action_skill_set,
    label_skill,
    strategy_features,
)


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def json_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def restore_observation(step_states: list[dict[str, Any]], seat: int, step: int) -> dict[str, Any]:
    public = dict(step_states[0].get("observation") or {})
    private = step_states[seat].get("observation") or {}
    public["player"] = seat
    public["private"] = private.get("private", {})
    public["remainingOverageTime"] = private.get("remainingOverageTime", public.get("remainingOverageTime", 60))
    public["step"] = step
    return public


def selected_rows() -> list[dict[str, Any]]:
    return list(json.loads(SELECTED_MANIFEST.read_text(encoding="utf-8"))["selected"])


def load_replay(row: dict[str, Any]) -> dict[str, Any]:
    path = ROOT / row["path"]
    if sha256(path) != row["sha256"]:
        raise RuntimeError(f"teacher replay hash mismatch: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def build_dataset() -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    arrays: dict[str, list[Any]] = defaultdict(list)
    class_counts: dict[str, Counter[str]] = defaultdict(Counter)
    multi_intent = Counter()
    episode_rows = []
    codec_checked = 0
    for row in selected_rows():
        replay = load_replay(row)
        seat = int(row["seat"])
        local = Counter()
        for step in range(len(replay["steps"]) - 1):
            stored = replay["steps"][step + 1][seat].get("action") or {"farmer": ["PASS"], "hands": [], "market": []}
            if decode_action(encode_action(stored)) != normalize_action(stored):
                raise RuntimeError(f"lossless codec regression episode={row['episode']} step={step}")
            codec_checked += 1
            if step % ROW_STRIDE:
                continue
            observation = restore_observation(replay["steps"][step], seat, step)
            label = label_skill(observation, stored)
            intents = action_skill_set(observation, stored)
            multi_intent[len(intents)] += 1
            split = str(row["split"])
            arrays[f"x_{split}"].append(strategy_features(observation))
            arrays[f"y_{split}"].append(SKILLS.index(label))
            class_counts[split][label] += 1
            local[label] += 1
        episode_rows.append({"episode": row["episode"], "seat": seat, "split": row["split"], "labels": dict(local)})
    values = {key: np.asarray(value, dtype=np.float64 if key.startswith("x_") else np.int64) for key, value in arrays.items()}
    manifest = {
        "created_at_utc": now(),
        "task": "single-teacher strategy selection feeding typed candidate plans",
        "teacher_submission": TEACHER_SUBMISSION,
        "teacher_current_rank": "UNKNOWN",
        "private_teacher_implementation": "UNKNOWN",
        "source_split": str(SELECTED_MANIFEST.relative_to(ROOT)),
        "source_split_sha256": sha256(SELECTED_MANIFEST),
        "split_policy": "reused Round4 episode-level train/validation/test assignments; all are development-observed after this run",
        "row_stride": ROW_STRIDE,
        "feature_names": FEATURE_NAMES,
        "classes": SKILLS,
        "label_origin": "observed replay action; deterministic analyst label; simultaneous intent set retained separately",
        "multi_intent_cardinality": dict(multi_intent),
        "class_counts": {key: dict(value) for key, value in class_counts.items()},
        "shapes": {key: list(value.shape) for key, value in values.items()},
        "episode_rows": episode_rows,
        "lossless_codec_actions_checked": codec_checked,
        "hidden_inputs_used": [],
    }
    write_json(EXPERIMENT / "DATASET_MANIFEST.json", manifest)
    return values, manifest


def softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=1, keepdims=True)
    values = np.exp(np.clip(shifted, -30, 30))
    return values / np.maximum(values.sum(axis=1, keepdims=True), 1e-12)


def metrics(x: np.ndarray, y: np.ndarray, weights: np.ndarray, bias: np.ndarray, mean: np.ndarray, scale: np.ndarray) -> dict[str, Any]:
    probability = softmax(((x - mean) / scale) @ weights + bias)
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
        by_class[label] = {"precision": precision, "recall": recall, "f1": f1, "support": int(confusion[index, :].sum())}
    return {
        "rows": int(len(y)),
        "accuracy": float((prediction == y).mean()),
        "macro_f1": float(np.mean(f1s)),
        "cross_entropy": float(-np.log(np.maximum(probability[np.arange(len(y)), y], 1e-12)).mean()),
        "confusion": confusion.tolist(),
        "by_class": by_class,
    }


def train_linear(
    x_train: np.ndarray, y_train: np.ndarray, x_validation: np.ndarray, y_validation: np.ndarray, *, epochs: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[dict[str, Any]], int]:
    mean = x_train.mean(axis=0)
    scale = x_train.std(axis=0)
    scale[scale < 1e-5] = 1.0
    rng = np.random.default_rng(TRAIN_SEED)
    weights = rng.normal(0, 0.01, (x_train.shape[1], len(SKILLS)))
    initial = weights.copy()
    bias = np.zeros(len(SKILLS))
    count = np.bincount(y_train, minlength=len(SKILLS)).astype(np.float64)
    class_weight = np.minimum(8.0, len(y_train) / np.maximum(1.0, len(SKILLS) * count))
    velocity_w = np.zeros_like(weights)
    velocity_b = np.zeros_like(bias)
    best: tuple[float, np.ndarray, np.ndarray] | None = None
    log = []
    updates = 0
    for epoch in range(1, epochs + 1):
        order = rng.permutation(len(y_train))
        weighted_loss = 0.0
        for start in range(0, len(order), 512):
            indices = order[start : start + 512]
            x = (x_train[indices] - mean) / scale
            y = y_train[indices]
            probability = softmax(x @ weights + bias)
            row_weight = class_weight[y]
            weighted_loss += float((-np.log(np.maximum(probability[np.arange(len(y)), y], 1e-12)) * row_weight).sum())
            gradient = probability
            gradient[np.arange(len(y)), y] -= 1.0
            gradient *= row_weight[:, None] / max(1, len(y))
            velocity_w = 0.9 * velocity_w + x.T @ gradient + 1e-4 * weights
            velocity_b = 0.9 * velocity_b + gradient.sum(axis=0)
            learning_rate = 0.03 / math.sqrt(epoch)
            weights -= learning_rate * velocity_w
            bias -= learning_rate * velocity_b
            updates += 1
        validation = metrics(x_validation, y_validation, weights, bias, mean, scale)
        row = {"epoch": epoch, "train_weighted_loss": weighted_loss / len(y_train), "validation_cross_entropy": validation["cross_entropy"], "validation_accuracy": validation["accuracy"], "validation_macro_f1": validation["macro_f1"], "optimizer_updates": updates}
        log.append(row)
        if best is None or validation["cross_entropy"] < best[0]:
            best = (validation["cross_entropy"], weights.copy(), bias.copy())
    assert best is not None
    parameter_change = float(np.sqrt(np.square(best[1] - initial).sum() + np.square(best[2]).sum()))
    log[-1]["selected_parameter_change_l2"] = parameter_change
    return best[1], best[2], mean, scale, log, updates


def command_train(args: argparse.Namespace) -> None:
    arrays, manifest = build_dataset()
    weights, bias, mean, scale, log, updates = train_linear(
        arrays["x_train"], arrays["y_train"], arrays["x_validation"], arrays["y_validation"], epochs=args.epochs
    )
    validation = metrics(arrays["x_validation"], arrays["y_validation"], weights, bias, mean, scale)
    test = metrics(arrays["x_test"], arrays["y_test"], weights, bias, mean, scale)
    majority = int(np.bincount(arrays["y_train"], minlength=len(SKILLS)).argmax())
    baseline_prediction = np.full_like(arrays["y_test"], majority)
    baseline_accuracy = float((baseline_prediction == arrays["y_test"]).mean())
    baseline_f1 = float(np.mean([2 * ((baseline_prediction == i) & (arrays["y_test"] == i)).sum() / max(1, int((baseline_prediction == i).sum() + (arrays["y_test"] == i).sum())) for i in range(len(SKILLS))]))
    checkpoint = {
        "format": "round5-softmax-skill-selector-v1",
        "created_at_utc": now(),
        "teacher_submission": TEACHER_SUBMISSION,
        "feature_names": FEATURE_NAMES,
        "classes": SKILLS,
        "mean": mean.tolist(),
        "scale": scale.tolist(),
        "weights": weights.tolist(),
        "bias": bias.tolist(),
        "optimizer_updates": updates,
        "dataset_manifest_sha256": json_hash(manifest),
    }
    write_json(AGENT / "strategy_model.json", checkpoint)
    from agents.learning_round5_20260921.selector import SkillSelector

    selector = SkillSelector(AGENT / "strategy_model.json")
    first = selected_rows()[0]
    replay = load_replay(first)
    reload_scores = selector.scores(restore_observation(replay["steps"][0], int(first["seat"]), 0))
    parameter_change = float(log[-1]["selected_parameter_change_l2"])
    record = {
        "created_at_utc": now(),
        "command": f"python scripts/learning_round5.py train --epochs {args.epochs}",
        "teacher_submission": TEACHER_SUBMISSION,
        "checkpoint": str((AGENT / "strategy_model.json").relative_to(ROOT)),
        "checkpoint_sha256": sha256(AGENT / "strategy_model.json"),
        "optimizer_updates": updates,
        "parameter_change_l2": parameter_change,
        "full_training_log": log,
        "validation": validation,
        "test": test,
        "baseline_test": {"majority_class": SKILLS[majority], "accuracy": baseline_accuracy, "macro_f1": baseline_f1},
        "test_macro_f1_delta_vs_majority": test["macro_f1"] - baseline_f1,
        "reload_inference": {"calls": selector.inference_calls, "scores": reload_scores, "finite": all(math.isfinite(value) for value in reload_scores.values())},
    }
    write_json(EXPERIMENT / "TRAINING_RECORD.json", record)
    print(json.dumps({"checkpoint_sha256": record["checkpoint_sha256"], "updates": updates, "test": test, "reload": record["reload_inference"]}, indent=2))


def runtime_decode_action(action: dict[str, Any], quantities: dict[str, Any]) -> dict[str, Any]:
    actor_decoded = []
    for value in [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]:
        token = action_token(value)
        quantity = max(1, int(round(float(quantities.get("actor", {}).get(token, 1)))))
        actor_decoded.append(token_action(token, quantity))
    market_decoded = []
    for order in action.get("market") or []:
        token = market_token(order)
        quantity = max(1, int(round(float(quantities.get("market", {}).get(token, 1)))))
        market_decoded.append(token_order(token, quantity))
    return {"farmer": actor_decoded[0], "hands": actor_decoded[1:], "market": market_decoded}


def command_representation(_args: argparse.Namespace) -> None:
    quantities = json.loads((ROOT / "agents/learning_next_20260921/bc_quantities.json").read_text(encoding="utf-8"))
    total = exact = actor_total = actor_exact = market_total = market_exact = 0
    mismatch_causes = Counter()
    examples = []
    first_wheat = []
    for row in selected_rows():
        replay = load_replay(row)
        seat = int(row["seat"])
        for step in range(len(replay["steps"]) - 1):
            action = normalize_action(replay["steps"][step + 1][seat].get("action") or {})
            decoded = runtime_decode_action(action, quantities)
            total += 1
            exact += int(decoded == action)
            original_units = [action["farmer"], *action["hands"]]
            decoded_units = [decoded["farmer"], *decoded["hands"]]
            for before, after in zip(original_units, decoded_units, strict=True):
                actor_total += 1
                actor_exact += int(before == after)
                if before != after:
                    mismatch_causes["actor_quantity_compression" if action_token(before) == action_token(after) else "actor_token_unrepresentable"] += 1
            for before, after in zip(action["market"], decoded["market"], strict=True):
                market_total += 1
                market_exact += int(before == after)
                if before != after:
                    mismatch_causes["market_quantity_compression" if market_token(before) == market_token(after) else "market_token_unrepresentable"] += 1
                    if market_token(before) == "SELL:WHEAT" and len(first_wheat) < 12:
                        first_wheat.append({"episode": row["episode"], "seat": seat, "step": step, "teacher": before, "runtime_representation": after})
            if decoded != action and len(examples) < 20:
                examples.append({"episode": row["episode"], "seat": seat, "step": step, "teacher": action, "runtime_representation": decoded})
    round4_cards = json.loads((ROUND4 / "SKILL_CARDS.json").read_text(encoding="utf-8"))["cards"]
    sell_card = next(card for card in round4_cards if card["skill_id"] == "sell_and_reinvest")
    card_order = next(
        order
        for action in sell_card["observed_plan"]
        for order in action.get("market", [])
        if order[:2] == ["BUY_PRODUCT", "WHEAT"]
    )
    card_decoded = token_order(market_token(card_order), max(1, int(round(float(quantities["market"][market_token(card_order)])))))
    result = {
        "created_at_utc": now(),
        "scope": "teacher action -> BC token target -> median quantity decode; model classification error excluded",
        "teacher_joint_actions": total,
        "joint_exact": exact,
        "joint_exact_rate": exact / total,
        "actor_primitives": actor_total,
        "actor_exact": actor_exact,
        "actor_exact_rate": actor_exact / actor_total,
        "market_orders": market_total,
        "market_exact": market_exact,
        "market_exact_rate": market_exact / max(1, market_total),
        "mismatch_causes": dict(mismatch_causes),
        "lossless_json_codec": "separately verified; not the runtime BC output representation",
        "wheat_quantity_examples": first_wheat,
        "opening_wheat_5_to_3_diagnosis": {
            "round4_skill_card": str((ROUND4 / "SKILL_CARDS.json").relative_to(ROOT)),
            "teacher_observed_order": card_order,
            "runtime_decoded_order": card_decoded,
            "cause": "market_quantity_compression",
            "input_difference": "NOT_APPLICABLE: runtime BC quantity is a token-level fixed median and does not read observation features",
            "model_classification_error": "EXCLUDED: this audit starts from the correct teacher token",
        },
        "examples": examples,
    }
    write_json(EXPERIMENT / "ACTION_REPRESENTATION_AUDIT.json", result)
    print(json.dumps({key: result[key] for key in ("teacher_joint_actions", "joint_exact_rate", "actor_exact_rate", "market_exact_rate", "mismatch_causes")}, indent=2))


def compact_state(observation: dict[str, Any]) -> dict[str, Any]:
    seat = int(observation["player"])
    farm = observation["farms"][seat]
    animals = []
    crops = []
    for y, row in enumerate(farm["tiles"]):
        for x, tile in enumerate(row):
            if isinstance(tile, dict) and tile.get("animal"):
                animals.append({"x": x, "y": y, **tile})
            elif isinstance(tile, dict) and tile.get("kind") == "PLANT":
                crops.append({"x": x, "y": y, **tile})
    return {"step": observation["step"], "day": observation["day"], "hour": observation["hour"], "money": farm["money"], "positions": [farm["farmer"], *farm["hands"]], "private": observation["private"], "animals": animals, "crops": crops, "market": observation["market"]}


def _sequence_end(replay: dict[str, Any], seat: int, start: int, skill: str) -> tuple[int, str]:
    limit = min(len(replay["steps"]) - 2, start + (240 if skill == "ANIMAL_LIFECYCLE_REALIZATION" else 48))
    for step in range(start + 1, limit + 1):
        action = replay["steps"][step + 1][seat].get("action") or {}
        if skill == "ANIMAL_LIFECYCLE_REALIZATION" and any(order and order[0] == "SELL" and len(order) > 1 and order[1] in {"EGG", "MILK", "WOOL"} for order in action.get("market") or []):
            return step, "observed_animal_product_sale"
        if skill == "HARVEST_AND_LAND_CONVERSION" and step >= start + 6 and "HARVEST_AND_LAND_CONVERSION" not in action_skill_set(restore_observation(replay["steps"][step], seat, step), action):
            return step, "observed_harvest_burst_ended"
        if skill == "SELL_AND_REINVEST" and step >= start + 4 and any(order and str(order[0]).startswith("BUY_") for order in action.get("market") or []):
            return step, "observed_followup_purchase"
    return limit, "window_exhausted_without_completion"


def command_skills(_args: argparse.Namespace) -> None:
    sequences: dict[str, list[dict[str, Any]]] = {skill: [] for skill in SKILLS[1:]}
    used_episodes: dict[str, set[int]] = {skill: set() for skill in SKILLS[1:]}
    for row in [value for value in selected_rows() if value["split"] == "train"]:
        replay = load_replay(row)
        seat = int(row["seat"])
        episode = int(row["episode"])
        for step in range(len(replay["steps"]) - 1):
            observation = restore_observation(replay["steps"][step], seat, step)
            action = replay["steps"][step + 1][seat].get("action") or {}
            for skill in action_skill_set(observation, action):
                if skill not in sequences or episode in used_episodes[skill] or len(sequences[skill]) >= 4:
                    continue
                end, completion = _sequence_end(replay, seat, step, skill)
                actions = [{"step": index, "action": replay["steps"][index + 1][seat].get("action") or {}} for index in range(step, end + 1)]
                end_observation = restore_observation(replay["steps"][end + 1], seat, end + 1)
                sequences[skill].append({
                    "origin": "observed_teacher_replay_sequence",
                    "teacher_submission": TEACHER_SUBMISSION,
                    "episode": episode,
                    "seat": seat,
                    "split": "train/development",
                    "step_range": [step, end],
                    "start_state": compact_state(observation),
                    "ordered_joint_actions": actions,
                    "end_state": compact_state(end_observation),
                    "completion_observation": completion,
                    "completion_observed": not completion.startswith("window_exhausted"),
                })
                used_episodes[skill].add(episode)
    cards = []
    requirements = {
        "ANIMAL_LIFECYCLE_REALIZATION": {"condition": "animal exists and a production/held-yield path can finish before season end", "resources": ["typed animal target", "deadline", "feed/cash reservation", "actor assignment"], "completion": "animal product enters actor inventory, then shed, then an observed SELL realizes cash"},
        "HARVEST_AND_LAND_CONVERSION": {"condition": "typed crop/animal target has positive engine-harvestable yield", "resources": ["single-owner yield reservation", "actor capacity", "post-harvest route"], "completion": "issuing actor inventory receives the typed product; target yield is consumed once"},
        "SELL_AND_REINVEST": {"condition": "inventory is unreserved and purchases preserve accepted near-term obligations", "resources": ["ordered market slots", "per-unit cash ledger", "feed/cash reserves"], "completion": "inventory decreases, cash is realized, and the selected next investment remains fundable"},
    }
    for skill in SKILLS[1:]:
        seq = sequences[skill]
        cards.append({
            "skill_id": skill.lower(),
            "teacher_submission": TEACHER_SUBMISSION,
            "teacher_version_uncertainty": "private implementation and current rank UNKNOWN",
            "origin_separation": {"observed": "ordered_joint_actions and states", "analyst_inference": requirements[skill], "rule_corrections": "stored separately in runtime traces"},
            **requirements[skill],
            "positive_sequences": [value for value in seq if value["completion_observed"]],
            "incomplete_or_negative_sequences": [value for value in seq if not value["completion_observed"]],
        })
    result = {"created_at_utc": now(), "scope": "multi-episode continuous train/development sequences; not new holdout evidence", "cards": cards}
    write_json(EXPERIMENT / "SKILL_CARDS_CONTINUOUS.json", result)
    print(json.dumps({card["skill_id"]: {"positive": len(card["positive_sequences"]), "incomplete": len(card["incomplete_or_negative_sequences"])} for card in cards}, indent=2))


def command_inventory(_args: argparse.Namespace) -> None:
    reported = json.loads((ROUND4 / "EVIDENCE_HASHES.json").read_text(encoding="utf-8"))["files"]
    rows = []
    for raw, expected in reported.items():
        path = ROOT / raw.replace("\\", "/")
        rows.append({"path": raw, "exists": path.is_file(), "sha256": sha256(path) if path.is_file() else None, "reported_sha256": expected["sha256"], "bytes": path.stat().st_size if path.is_file() else None, "reported_bytes": expected["bytes"], "match": path.is_file() and sha256(path) == expected["sha256"] and path.stat().st_size == expected["bytes"]})
    engine = ROOT / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py"
    result = {
        "created_at_utc": now(),
        "explicit_manifest_not_git_diff": True,
        "round4_evidence_entries": rows,
        "all_23_recovered_and_matching": len(rows) == 23 and all(row["match"] for row in rows),
        "round4_source_files": [{"path": str(path.relative_to(ROOT)), "sha256": sha256(path), "bytes": path.stat().st_size} for path in sorted((ROOT / "agents/learning_round4_20260921").glob("*")) if path.is_file()],
        "round4_scripts_and_tests": [{"path": str(path.relative_to(ROOT)), "sha256": sha256(path), "bytes": path.stat().st_size} for path in [ROOT / "scripts/learning_round4.py", ROOT / "scripts/evaluate_round4_closed_loop.py", ROOT / "scripts/validate_round4_archive.py", ROOT / "scripts/finalize_round4.py", ROOT / "tests/test_learning_round4.py"]],
        "engine": {"path": str(engine.relative_to(ROOT)), "sha256": sha256(engine), "reported_match": sha256(engine) == "bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e", "package": "kaggle-environments==1.32.7"},
    }
    write_json(EXPERIMENT / "RECOVERED_ROUND4_MANIFEST.json", result)
    print(json.dumps({"all_23_recovered_and_matching": result["all_23_recovered_and_matching"], "engine": result["engine"]}, indent=2))


def command_package(_args: argparse.Namespace) -> None:
    manifest = json.loads((AGENT / "submission_manifest.json").read_text(encoding="utf-8"))
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    records = {}
    for arm in ("none", "rule", "learned"):
        entries = [*manifest["common"], *manifest[arm]]
        archive = ARCHIVES / f"learning_round5_20260921_{arm}.tar.gz"
        with tempfile.TemporaryDirectory(prefix=f"round5_{arm}_", dir=EXPERIMENT) as temp:
            stage = Path(temp)
            for row in entries:
                source = (AGENT / row["source"]).resolve()
                if not source.is_file():
                    raise FileNotFoundError(source)
                destination = stage / row["target"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            with tarfile.open(archive, "w:gz") as stream:
                for path in sorted(stage.rglob("*")):
                    if path.is_file():
                        stream.add(path, arcname=path.relative_to(stage).as_posix())
        records[arm] = {"path": str(archive.relative_to(ROOT)), "sha256": sha256(archive), "bytes": archive.stat().st_size, "members": [row["target"] for row in entries]}
    write_json(EXPERIMENT / "ARCHIVE_MANIFEST.json", {"created_at_utc": now(), "archives": records})
    print(json.dumps(records, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    train = sub.add_parser("train")
    train.add_argument("--epochs", type=int, default=18)
    sub.add_parser("representation")
    sub.add_parser("skills")
    sub.add_parser("inventory")
    sub.add_parser("package")
    args = parser.parse_args()
    {"train": command_train, "representation": command_representation, "skills": command_skills, "inventory": command_inventory, "package": command_package}[args.command](args)


if __name__ == "__main__":
    main()
