"""Train and audit V111's public-state 24/72-hour strategy model.

The model predicts future *portfolio goals*, not field actions.  Training rows
come only from the three leaderboard teacher submissions.  Replays are split
as whole games and, separately, by action-stream lineage so one copied policy
cannot appear on both sides of the lineage evaluation.

The submitted policy uses only the lineage-split 72-hour model.  Its output is
allowed to choose a compatible complete route at the two route boundaries, or
to request a bounded Cow/Sheep substitution inside an already-planned Pasture
transaction.  Movement, feeding, placement geometry, and market feasibility
remain deterministic runtime checks.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODEL_OUTPUT = ROOT / "agents/v111/strategy_model.json"
REPORT_OUTPUT = ROOT / "data/analysis/v111_strategy_training.json"
ROWS_OUTPUT = ROOT / "data/analysis/v111_strategy_rows.jsonl"
TEACHERS = {
    "rank1": ROOT / "data/submissions/leaderboard_rank1_submission_55614463",
    "rank2": ROOT / "data/submissions/leaderboard_rank2_submission_55623460",
    "rank3": ROOT / "data/submissions/leaderboard_rank3_submission_55574890",
}
V110 = ROOT / "data/submissions/v110_submission_55903573"

PORTFOLIO = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "COW", "SHEEP")
PRODUCT = {
    "WHEAT": "WHEAT",
    "CARROT": "CARROT",
    "TOMATO": "TOMATO",
    "STRAWBERRY": "STRAWBERRY",
    "MELON": "MELON",
    "COW": "MILK",
    "SHEEP": "WOOL",
}
TARGET_SCALE = np.asarray((20.0, 12.0, 6.0, 18.0, 8.0, 5.0, 5.0), dtype=np.float64)
BASE_PRICE = {
    "WHEAT": 25.0,
    "CARROT": 35.0,
    "TOMATO": 60.0,
    "STRAWBERRY": 120.0,
    "MELON": 250.0,
    "MILK": 160.0,
    "WOOL": 200.0,
}
MARKET_SCALE = {
    "WHEAT": 400.0,
    "CARROT": 450.0,
    "TOMATO": 200.0,
    "STRAWBERRY": 100.0,
    "MELON": 300.0,
    "MILK": 122.0,
    "WOOL": 105.0,
}
SHOP_PRODUCTS = {
    "BAKERY": ("EGG", "WHEAT"),
    "PIZZA_SHOP": ("MILK", "TOMATO", "WHEAT"),
    "BRUNCH_SPOT": ("EGG", "WHEAT", "STRAWBERRY"),
    "YARN_STORE": ("WOOL",),
    "ICE_CREAM_SHOP": ("STRAWBERRY", "MILK", "WHEAT"),
    "PET_CAFE": ("CARROT",),
    "SMOOTHIE_SHOP": ("STRAWBERRY", "MILK"),
    "FARMERS_MARKET": ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY"),
}
DECISION_STEPS = (88, 153, 216, 288, 360, 432)
HORIZONS = (24, 72)
RIDGE_GRID = (0.1, 1.0, 10.0, 100.0)
ROUTE_THRESHOLDS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5)


def _manifest(directory: Path) -> list[dict[str, str]]:
    with (directory / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        return [
            row
            for row in csv.DictReader(handle)
            if row.get("replay_status") in {"downloaded", "skipped_existing"}
            and int(float(row.get("step_count") or 0)) >= 719
        ]


def _replay_path(row: dict[str, str]) -> Path:
    direct = ROOT / str(row["replay_path"])
    return direct if direct.is_file() else ROOT / "data" / str(row["replay_path"])


def _observation(replay: dict[str, Any], step: int, seat: int) -> dict[str, Any] | None:
    steps = replay.get("steps") or []
    if not (0 <= step < len(steps)) or not (0 <= seat < len(steps[step])):
        return None
    observation = (steps[step][seat] or {}).get("observation")
    return observation if isinstance(observation, dict) else None


def _action(replay: dict[str, Any], decision_step: int, seat: int) -> dict[str, Any]:
    """Return the action selected from decision state ``decision_step``."""
    steps = replay.get("steps") or []
    stored_step = decision_step + 1
    if not (0 <= stored_step < len(steps)) or not (0 <= seat < len(steps[stored_step])):
        return {}
    action = (steps[stored_step][seat] or {}).get("action")
    return action if isinstance(action, dict) else {}


def _iter_tiles(farm: dict[str, Any]):
    for row in farm.get("tiles") or []:
        for tile in row or []:
            if isinstance(tile, dict):
                yield tile


def _portfolio(farm: dict[str, Any]) -> dict[str, float]:
    counts: Counter[str] = Counter()
    for tile in _iter_tiles(farm):
        crop = tile.get("crop")
        animal = tile.get("animal")
        if crop in PORTFOLIO:
            counts[str(crop)] += 1
        if animal in PORTFOLIO:
            counts[str(animal)] += 1
    return {item: float(counts[item]) for item in PORTFOLIO}


def _demand_per_day(shops: list[str], product: str) -> float:
    demand = 1.0  # Town center.
    for shop in shops:
        products = SHOP_PRODUCTS.get(str(shop), ())
        if product in products:
            demand += 12.0 if len(products) == 1 else 6.0
    return demand


def _clone_distance(own: dict[str, Any], opponent: dict[str, Any]) -> float:
    own_assets = _portfolio(own)
    opponent_assets = _portfolio(opponent)
    distance = sum(abs(own_assets[item] - opponent_assets[item]) for item in PORTFOLIO)
    distance += 2.0 * abs(len(own.get("hands") or []) - len(opponent.get("hands") or []))
    distance += 3.0 * abs(
        len(set(own.get("unlocked_quadrants") or []))
        - len(set(opponent.get("unlocked_quadrants") or []))
    )
    return float(distance)


def _feature_names() -> list[str]:
    names = [
        "day",
        "remaining_days",
        "own_money",
        "opponent_money",
        "money_gap",
        "own_hands",
        "opponent_hands",
        "own_land",
        "opponent_land",
        "shop_count",
        "clone_distance",
    ]
    names.extend(f"own_{item.lower()}" for item in PORTFOLIO)
    names.extend(f"opponent_{item.lower()}" for item in PORTFOLIO)
    for item in PORTFOLIO:
        product = PRODUCT[item]
        names.extend(
            (
                f"demand_{product.lower()}_per_day",
                f"price_{product.lower()}_ratio",
                f"inventory_{product.lower()}_scaled",
            )
        )
    return names


FEATURES = _feature_names()


def _features(obs: dict[str, Any], seat: int, step: int) -> list[float] | None:
    farms = obs.get("farms") or []
    if len(farms) < 2 or not (0 <= seat < 2):
        return None
    own = farms[seat]
    opponent = farms[1 - seat]
    if not isinstance(own, dict) or not isinstance(opponent, dict):
        return None
    own_assets = _portfolio(own)
    opponent_assets = _portfolio(opponent)
    shops = [str(value) for value in ((obs.get("town") or {}).get("unlocked_shops") or [])]
    market = obs.get("market") or {}
    prices = market.get("prices") or {}
    inventory = market.get("inventory") or {}
    own_money = float(own.get("money") or 0.0)
    opponent_money = float(opponent.get("money") or 0.0)
    values = [
        step / 24.0,
        (719 - step) / 24.0,
        own_money,
        opponent_money,
        own_money - opponent_money,
        float(len(own.get("hands") or [])),
        float(len(opponent.get("hands") or [])),
        float(len(set(own.get("unlocked_quadrants") or []))),
        float(len(set(opponent.get("unlocked_quadrants") or []))),
        float(len(shops)),
        _clone_distance(own, opponent),
    ]
    values.extend(own_assets[item] for item in PORTFOLIO)
    values.extend(opponent_assets[item] for item in PORTFOLIO)
    for item in PORTFOLIO:
        product = PRODUCT[item]
        values.extend(
            (
                _demand_per_day(shops, product),
                float(prices.get(product, BASE_PRICE[product]) or 0.0) / BASE_PRICE[product],
                (float(inventory.get(product, 10_000) or 10_000) - 10_000.0)
                / MARKET_SCALE[product],
            )
        )
    if len(values) != len(FEATURES) or not all(math.isfinite(value) for value in values):
        return None
    return values


def _canonical_action(action: dict[str, Any]) -> str:
    actors = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
    fields = Counter(json.dumps(list(value or ["PASS"]), separators=(",", ":")) for value in actors)
    payload = {
        "field": sorted(fields.items()),
        "market": [list(value) for value in (action.get("market") or [])],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _lineage_hashes(replay: dict[str, Any], seat: int) -> dict[int, str]:
    checkpoints = (24, 100, 200, 400)
    digest = hashlib.sha1()
    result: dict[int, str] = {}
    maximum = min(checkpoints[-1], len(replay.get("steps") or []) - 1)
    for step in range(maximum):
        digest.update(_canonical_action(_action(replay, step, seat)).encode("utf-8"))
        digest.update(b"\n")
        completed = step + 1
        if completed in checkpoints:
            result[completed] = digest.copy().hexdigest()[:16]
    return result


def _episode_split(episode_id: str) -> str:
    bucket = int(hashlib.sha1(f"v111-episode:{episode_id}".encode()).hexdigest()[:8], 16) % 10
    return "train" if bucket < 6 else "validation" if bucket < 8 else "test"


def _lineage_split(lineage: str) -> str:
    bucket = int(hashlib.sha1(f"v111-lineage:{lineage}".encode()).hexdigest()[:8], 16) % 10
    return "train" if bucket < 6 else "validation" if bucket < 8 else "test"


def _teacher_rows() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    corpus: dict[str, Any] = {}
    seen: set[tuple[str, int]] = set()
    for label, directory in TEACHERS.items():
        source_rows = 0
        episodes = 0
        lineage_counts: Counter[str] = Counter()
        for manifest in _manifest(directory):
            episode_id = str(manifest["episode_id"])
            seat = int(manifest["submission_seat"])
            if (episode_id, seat) in seen:
                continue
            seen.add((episode_id, seat))
            replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
            lineages = _lineage_hashes(replay, seat)
            lineage24 = lineages[24]
            lineage100 = lineages[100]
            lineage200 = lineages[200]
            lineage400 = lineages[400]
            lineage_counts[lineage200] += 1
            episodes += 1
            for step in DECISION_STEPS:
                current = _observation(replay, step, seat)
                if current is None:
                    continue
                features = _features(current, seat, step)
                if features is None:
                    continue
                farms = current.get("farms") or []
                current_portfolio = _portfolio(farms[seat])
                targets: dict[str, list[float]] = {}
                for horizon in HORIZONS:
                    future = _observation(replay, min(719, step + horizon), seat)
                    if future is None:
                        break
                    future_farms = future.get("farms") or []
                    if not (0 <= seat < len(future_farms)):
                        break
                    future_portfolio = _portfolio(future_farms[seat])
                    targets[str(horizon)] = [
                        future_portfolio[item] - current_portfolio[item] for item in PORTFOLIO
                    ]
                if len(targets) != len(HORIZONS):
                    continue
                rows.append(
                    {
                        "source": label,
                        "episode_id": episode_id,
                        "seat": seat,
                        "step": step,
                        "result": str(manifest.get("result") or "unknown"),
                        "lineage24": lineage24,
                        "lineage100": lineage100,
                        "lineage200": lineage200,
                        "lineage400": lineage400,
                        "episode_split": _episode_split(episode_id),
                        "lineage_split": _lineage_split(lineage200),
                        "shops": [
                            str(value)
                            for value in ((current.get("town") or {}).get("unlocked_shops") or [])
                        ],
                        "features": features,
                        "targets": targets,
                    }
                )
                source_rows += 1
        corpus[label] = {
            "episodes": episodes,
            "rows": source_rows,
            "lineage200_distinct": len(lineage_counts),
            "lineage200_largest": lineage_counts.most_common(5),
        }
    return rows, corpus


def _fit(rows: list[dict[str, Any]], protocol: str) -> tuple[dict[str, Any], dict[str, Any]]:
    split_key = f"{protocol}_split"
    train = [row for row in rows if row[split_key] == "train"]
    validation = [row for row in rows if row[split_key] == "validation"]
    test = [row for row in rows if row[split_key] == "test"]
    if not train or not validation or not test:
        raise RuntimeError(
            f"{protocol} split is empty: train={len(train)} validation={len(validation)} test={len(test)}"
        )
    x_train = np.asarray([row["features"] for row in train], dtype=np.float64)
    feature_mean = x_train.mean(axis=0)
    feature_std = x_train.std(axis=0)
    feature_std[feature_std < 1e-9] = 1.0

    def design(selected: list[dict[str, Any]]) -> np.ndarray:
        raw = np.asarray([row["features"] for row in selected], dtype=np.float64)
        normalized = (raw - feature_mean) / feature_std
        return np.column_stack((np.ones(len(selected), dtype=np.float64), normalized))

    x_train_design = design(train)
    models: dict[str, Any] = {}
    evaluations: dict[str, Any] = {}
    for horizon in HORIZONS:
        y_train = np.asarray([row["targets"][str(horizon)] for row in train], dtype=np.float64)
        y_train_scaled = y_train / TARGET_SCALE
        ridge_scores = []
        for ridge in RIDGE_GRID:
            penalty = np.eye(x_train_design.shape[1], dtype=np.float64) * ridge
            penalty[0, 0] = 0.0
            coefficients = np.linalg.solve(
                x_train_design.T @ x_train_design + penalty,
                x_train_design.T @ y_train_scaled,
            )
            validation_prediction = design(validation) @ coefficients * TARGET_SCALE
            validation_target = np.asarray(
                [row["targets"][str(horizon)] for row in validation], dtype=np.float64
            )
            mae = float(np.mean(np.abs(validation_prediction - validation_target) / TARGET_SCALE))
            ridge_scores.append((mae, ridge, coefficients))
        validation_mae, ridge, coefficients = min(ridge_scores, key=lambda value: (value[0], value[1]))
        models[str(horizon)] = {
            "ridge": ridge,
            "coefficients": coefficients.tolist(),
        }
        horizon_eval: dict[str, Any] = {"selected_ridge": ridge, "validation_mae": validation_mae}
        for split_name, selected in (("train", train), ("validation", validation), ("test", test)):
            prediction = design(selected) @ coefficients * TARGET_SCALE
            target = np.asarray([row["targets"][str(horizon)] for row in selected], dtype=np.float64)
            model_mae = float(np.mean(np.abs(prediction - target) / TARGET_SCALE))
            zero_mae = float(np.mean(np.abs(target) / TARGET_SCALE))
            target_tilt = target[:, -1] - target[:, -2]
            predicted_tilt = prediction[:, -1] - prediction[:, -2]
            material = np.abs(target_tilt) >= 1.0
            direction = (
                float(np.mean(np.sign(target_tilt[material]) == np.sign(predicted_tilt[material])))
                if material.any()
                else 0.0
            )
            horizon_eval[split_name] = {
                "rows": len(selected),
                "model_normalized_mae": model_mae,
                "zero_change_normalized_mae": zero_mae,
                "mae_improvement": zero_mae - model_mae,
                "material_animal_tilt_rows": int(material.sum()),
                "animal_tilt_direction_accuracy": direction,
            }
        evaluations[str(horizon)] = horizon_eval

    h72_coefficients = np.asarray(models["72"]["coefficients"], dtype=np.float64)
    validation_prediction = design(validation) @ h72_coefficients * TARGET_SCALE
    validation_target = np.asarray([row["targets"]["72"] for row in validation], dtype=np.float64)
    predicted_tilt = validation_prediction[:, -1] - validation_prediction[:, -2]
    target_tilt = validation_target[:, -1] - validation_target[:, -2]

    def route_label(value: float, threshold: float) -> str:
        if value >= threshold:
            return "wool"
        if value <= -threshold:
            return "milk"
        return "neutral"

    threshold_rows = []
    for threshold in ROUTE_THRESHOLDS:
        actual = [route_label(float(value), 1.0) for value in target_tilt]
        predicted = [route_label(float(value), threshold) for value in predicted_tilt]
        labels = ("milk", "neutral", "wool")
        recalls = []
        for label in labels:
            indices = [index for index, value in enumerate(actual) if value == label]
            if indices:
                recalls.append(mean(predicted[index] == label for index in indices))
        balanced = mean(recalls) if recalls else 0.0
        threshold_rows.append(
            {
                "threshold": threshold,
                "balanced_accuracy": balanced,
                "accuracy": mean(left == right for left, right in zip(actual, predicted, strict=True)),
                "non_neutral_predictions": sum(value != "neutral" for value in predicted),
            }
        )
    selected_threshold = max(
        threshold_rows,
        key=lambda row: (row["balanced_accuracy"], row["accuracy"], -row["threshold"]),
    )["threshold"]

    train_z = np.abs((x_train - feature_mean) / feature_std)
    max_z = np.max(train_z, axis=1)
    h72_train_prediction = x_train_design @ h72_coefficients * TARGET_SCALE
    h72_train_target = np.asarray([row["targets"]["72"] for row in train], dtype=np.float64)
    tilt_residual = np.abs(
        (h72_train_prediction[:, -1] - h72_train_prediction[:, -2])
        - (h72_train_target[:, -1] - h72_train_target[:, -2])
    )
    model = {
        "format": "kaggriculture-v111-strategy-model-v1",
        "protocol": protocol,
        "features": FEATURES,
        "targets": list(PORTFOLIO),
        "target_scales": TARGET_SCALE.tolist(),
        "feature_mean": feature_mean.tolist(),
        "feature_std": feature_std.tolist(),
        "models": models,
        "animal_tilt_threshold": float(selected_threshold),
        "ood_max_abs_z": float(max(3.0, np.quantile(max_z, 0.99))),
        "tilt_residual_p75": float(np.quantile(tilt_residual, 0.75)),
        "decision_steps": list(DECISION_STEPS),
    }
    evaluation = {
        "split_counts": Counter(row[split_key] for row in rows),
        "split_episodes": {
            split: len({row["episode_id"] for row in rows if row[split_key] == split})
            for split in ("train", "validation", "test")
        },
        "split_lineages": {
            split: len({row["lineage200"] for row in rows if row[split_key] == split})
            for split in ("train", "validation", "test")
        },
        "horizons": evaluations,
        "route_threshold_validation": threshold_rows,
        "selected_animal_tilt_threshold": selected_threshold,
        "ood_max_abs_z": model["ood_max_abs_z"],
        "tilt_residual_p75": model["tilt_residual_p75"],
    }
    evaluation["split_counts"] = dict(evaluation["split_counts"])
    return model, evaluation


def _predict(model: dict[str, Any], features: list[float], horizon: int = 72) -> tuple[np.ndarray, float]:
    raw = np.asarray(features, dtype=np.float64)
    center = np.asarray(model["feature_mean"], dtype=np.float64)
    scale = np.asarray(model["feature_std"], dtype=np.float64)
    z = (raw - center) / scale
    design = np.concatenate(([1.0], z))
    coefficients = np.asarray(model["models"][str(horizon)]["coefficients"], dtype=np.float64)
    target_scale = np.asarray(model["target_scales"], dtype=np.float64)
    return design @ coefficients * target_scale, float(np.max(np.abs(z)))


def _v110_clone_confidence(replay: dict[str, Any], seat: int, target_step: int) -> int:
    confidence = 0
    for step in (4, 24, *range(48, target_step + 1, 24)):
        if step > target_step:
            break
        obs = _observation(replay, step, seat)
        if obs is None:
            continue
        farms = obs.get("farms") or []
        if len(farms) < 2:
            continue
        distance = _clone_distance(farms[seat], farms[1 - seat])
        if distance <= 1:
            confidence = min(8, confidence + 1)
        elif distance <= 4:
            confidence = max(0, confidence - 1)
        else:
            confidence = max(0, confidence - 3)
    return confidence


def _v110_audit(model: dict[str, Any]) -> dict[str, Any]:
    records = []
    result_counts: Counter[str] = Counter()
    for manifest in _manifest(V110):
        episode_id = str(manifest["episode_id"])
        seat = int(manifest["submission_seat"])
        replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
        result = str(manifest.get("result") or "unknown")
        result_counts[result] += 1
        margin = float(manifest.get("own_reward") or 0) - float(manifest.get("opponent_reward") or 0)
        for step in DECISION_STEPS:
            obs = _observation(replay, step, seat)
            if obs is None:
                continue
            features = _features(obs, seat, step)
            if features is None:
                continue
            prediction, max_z = _predict(model, features)
            tilt = float(prediction[-1] - prediction[-2])
            threshold = float(model["animal_tilt_threshold"])
            route = "wool" if tilt >= threshold else "milk" if tilt <= -threshold else "neutral"
            shops = [str(value) for value in ((obs.get("town") or {}).get("unlocked_shops") or [])]
            records.append(
                {
                    "episode_id": episode_id,
                    "result": result,
                    "margin": margin,
                    "step": step,
                    "shops": shops,
                    "clone_confidence": _v110_clone_confidence(replay, seat, step),
                    "predicted_animal_tilt": tilt,
                    "route_goal": route,
                    "max_abs_z": max_z,
                    "in_support": max_z <= float(model["ood_max_abs_z"]),
                }
            )
    supported = [record for record in records if record["in_support"]]
    activations = [record for record in supported if record["route_goal"] != "neutral"]
    return {
        "episodes": sum(result_counts.values()),
        "results": dict(result_counts),
        "rows": len(records),
        "supported_rows": len(supported),
        "activation_rows": len(activations),
        "activation_episodes": len({record["episode_id"] for record in activations}),
        "activation_by_result": dict(Counter(record["result"] for record in activations)),
        "activation_by_goal": dict(Counter(record["route_goal"] for record in activations)),
        "clone_activation_rows": sum(record["clone_confidence"] >= 2 for record in activations),
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-output", type=Path, default=MODEL_OUTPUT)
    parser.add_argument("--report-output", type=Path, default=REPORT_OUTPUT)
    parser.add_argument("--rows-output", type=Path, default=ROWS_OUTPUT)
    args = parser.parse_args()
    model_output = args.model_output if args.model_output.is_absolute() else ROOT / args.model_output
    report_output = args.report_output if args.report_output.is_absolute() else ROOT / args.report_output
    rows_output = args.rows_output if args.rows_output.is_absolute() else ROOT / args.rows_output

    rows, corpus = _teacher_rows()
    rows_output.parent.mkdir(parents=True, exist_ok=True)
    rows_output.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows
        ),
        encoding="utf-8",
    )
    episode_model, episode_evaluation = _fit(rows, "episode")
    lineage_model, lineage_evaluation = _fit(rows, "lineage")
    # Production deliberately uses the anti-leakage lineage model.  The
    # episode model remains a separately reported robustness comparison.
    production_model = lineage_model
    production_model.update(
        {
            "created_at": datetime.now().astimezone().isoformat(),
            "teacher_sources": {name: str(path.relative_to(ROOT)) for name, path in TEACHERS.items()},
            "selection": "lineage-held-out model; thresholds selected on lineage validation only",
            "rating_claim": "unverified",
            "row_cache": str(rows_output.relative_to(ROOT)),
        }
    )
    audit = _v110_audit(production_model)
    report = {
        "format": "kaggriculture-v111-strategy-training-v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "teacher_corpus": corpus,
        "teacher_rows": len(rows),
        "episode_protocol": episode_evaluation,
        "lineage_protocol": lineage_evaluation,
        "production_protocol": "lineage",
        "v110_observational_audit": audit,
        "interpretation": {
            "known": "features and 24/72-hour portfolio targets are replay-derived from complete teacher games",
            "generalization": "games never cross episode splits; h200 action lineages never cross lineage splits",
            "runtime_scope": (
                "model chooses macro animal tilt only; deterministic code must prove execution feasibility"
            ),
            "limit": "teacher agreement and V110 playback are observational, not a causal reward or rating estimate",
        },
    }
    model_output.parent.mkdir(parents=True, exist_ok=True)
    report_output.parent.mkdir(parents=True, exist_ok=True)
    model_output.write_text(json.dumps(production_model, ensure_ascii=False, indent=2), encoding="utf-8")
    report_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "teacher_corpus": corpus,
                "teacher_rows": len(rows),
                "episode_protocol": episode_evaluation,
                "lineage_protocol": lineage_evaluation,
                "v110_audit": {key: value for key, value in audit.items() if key != "records"},
                "model": str(model_output),
                "report": str(report_output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
