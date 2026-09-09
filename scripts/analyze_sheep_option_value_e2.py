"""Frozen lineage-held-out test of option features for Top Sheep expansion."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
from kaggle_environments.envs.kaggriculture import kaggriculture as engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evaluation.replay import action, observation  # noqa: E402

STATE_STEP = 216
LABEL_STEP = 288
PRIOR_START = 168
FEATURES = (
    "free_pasture_slots",
    "cash_after_two_sheep",
    "feed_surplus_3d_after_two_sheep",
    "prior_worker_slack_rate_48",
    "prior_mean_hands_48",
    "wool_minus_milk_residual_demand_72",
    "wool_minus_milk_price",
    "wool_minus_milk_market_scarcity",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _farm(obs: dict[str, Any], seat: int) -> dict[str, Any]:
    farms = list(obs.get("farms") or [])
    return farms[seat] if seat < len(farms) else {}


def _private_units(private: dict[str, Any], item: str) -> int:
    sources = [private.get("shed") or {}, *(private.get("inventories") or [])]
    return sum(max(0, int(source.get(item, 0) or 0)) for source in sources)


def _portfolio(farm: dict[str, Any]) -> Counter[str]:
    result: Counter[str] = Counter()
    for row in farm.get("tiles") or []:
        for tile in row or []:
            if not isinstance(tile, dict):
                continue
            if tile.get("animal"):
                result[str(tile["animal"])] += 1
            if tile.get("crop"):
                result[str(tile["crop"])] += 1
    return result


def _on_farm_yield(farm: dict[str, Any], product: str) -> int:
    total = 0
    for row in farm.get("tiles") or []:
        for tile in row or []:
            if not isinstance(tile, dict):
                continue
            tile_product = tile.get("crop")
            animal = tile.get("animal")
            if animal in engine.ANIMALS:
                tile_product = engine.ANIMALS[animal]["product"]
            if tile_product == product:
                total += max(0, int(tile.get("yield_units", 0) or 0))
    return total


def _gross_animal_production(farm: dict[str, Any], start_day: int, days: int) -> Counter[str]:
    result: Counter[str] = Counter()
    for row in farm.get("tiles") or []:
        for tile in row or []:
            if not isinstance(tile, dict) or tile.get("animal") not in engine.ANIMALS:
                continue
            animal = str(tile["animal"])
            spec = engine.ANIMALS[animal]
            for next_day in range(start_day + 1, start_day + days + 1):
                since_first = next_day - int(tile.get("placed_day", start_day) or 0) - int(
                    spec["first_yield_day"]
                )
                if since_first >= 0 and since_first % int(spec["interval"]) == 0:
                    result[str(spec["product"])] += 1
    return result


def _known_town_demand(obs: dict[str, Any], start: int, end: int) -> Counter[str]:
    result: Counter[str] = Counter()
    town = obs.get("town") or {}
    for step in range(start, end):
        if step % 4 == 0:
            for shop in town.get("unlocked_shops") or []:
                products = engine.SHOPS[str(shop)]
                multiplier = 2 if len(products) == 1 else 1
                for item in products:
                    result[item] += multiplier
        if step % 24 == 0:
            result.update(engine.TOWN_CENTER_PRODUCTS)
    return result


def _prior_worker_capacity(replay: dict[str, Any], seat: int) -> dict[str, float]:
    slots = 0
    active = 0
    hands = 0
    for step in range(PRIOR_START, STATE_STEP):
        obs = observation(replay, step, seat) or {}
        farm = _farm(obs, seat)
        hand_count = len(farm.get("hands") or [])
        actor_count = 1 + hand_count
        emitted = action(replay, step, seat)
        rows = [emitted.get("farmer") or ["PASS"], *(emitted.get("hands") or [])]
        rows = [*rows[:actor_count], *([["PASS"]] * max(0, actor_count - len(rows)))]
        slots += actor_count
        hands += hand_count
        active += sum(bool(row) and row[0] != "PASS" for row in rows)
    turns = STATE_STEP - PRIOR_START
    slack = slots - active
    return {
        "prior_worker_slots_48": float(slots),
        "prior_worker_active_actions_48": float(active),
        "prior_worker_slack_actions_48": float(slack),
        "prior_worker_slack_rate_48": slack / slots if slots else 0.0,
        "prior_mean_hands_48": hands / turns if turns else 0.0,
    }


def _features(replay: dict[str, Any], seat: int) -> dict[str, float]:
    obs = observation(replay, STATE_STEP, seat) or {}
    farm = _farm(obs, seat)
    opponent = _farm(obs, 1 - seat)
    private = obs.get("private") or {}
    portfolio = _portfolio(farm)
    pastures = [
        tile
        for row in farm.get("tiles") or []
        for tile in row or []
        if isinstance(tile, dict) and tile.get("kind") == "PASTURE"
    ]
    free_pastures = sum("animal" not in tile for tile in pastures)
    animals = sum(portfolio[animal] for animal in engine.ANIMALS)
    private_wheat = _private_units(private, "WHEAT")
    on_farm_wheat = _on_farm_yield(farm, "WHEAT")
    day = int(obs.get("day", STATE_STEP // 24) or 0)
    horizon_days = (LABEL_STEP - STATE_STEP) // 24
    demand = _known_town_demand(obs, STATE_STEP, LABEL_STEP)
    own_future = _gross_animal_production(farm, day, horizon_days)
    opponent_future = _gross_animal_production(opponent, day, horizon_days)
    residual = {}
    for product in ("WOOL", "MILK"):
        public_supply = (
            _on_farm_yield(farm, product)
            + _on_farm_yield(opponent, product)
            + own_future[product]
            + opponent_future[product]
        )
        residual[product] = float(demand[product] - public_supply)
    prices = (obs.get("market") or {}).get("prices") or {}
    inventories = (obs.get("market") or {}).get("inventory") or {}
    worker = _prior_worker_capacity(replay, seat)
    result = {
        "pasture_slots": float(len(pastures)),
        "placed_animals": float(animals),
        "free_pasture_slots": float(free_pastures),
        "pasture_capacity_utilization": animals / len(pastures) if pastures else 1.0,
        "cash": float(farm.get("money", 0) or 0),
        "cash_after_two_sheep": float(farm.get("money", 0) or 0) - 1000.0,
        "private_wheat": float(private_wheat),
        "on_farm_wheat_yield": float(on_farm_wheat),
        "feed_surplus_3d_after_two_sheep": float(
            private_wheat + on_farm_wheat - (animals + 2) * horizon_days
        ),
        "known_wool_demand_72": float(demand["WOOL"]),
        "known_milk_demand_72": float(demand["MILK"]),
        "wool_residual_demand_72": residual["WOOL"],
        "milk_residual_demand_72": residual["MILK"],
        "wool_minus_milk_residual_demand_72": residual["WOOL"] - residual["MILK"],
        "wool_minus_milk_price": float(prices.get("WOOL", 0) or 0)
        - float(prices.get("MILK", 0) or 0),
        "wool_minus_milk_market_scarcity": float(inventories.get("MILK", 0) or 0)
        - float(inventories.get("WOOL", 0) or 0),
        **worker,
    }
    return result


def _sigmoid(value: np.ndarray) -> np.ndarray:
    clipped = np.clip(value, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _fit_logistic(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    location = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < 1e-9] = 1.0
    standardized = (x - location) / scale
    design = np.column_stack([np.ones(len(x)), standardized])
    positives = max(1, int(y.sum()))
    negatives = max(1, len(y) - positives)
    weights = np.where(y == 1, len(y) / (2 * positives), len(y) / (2 * negatives))
    beta = np.zeros(design.shape[1], dtype=float)
    penalty = np.diag([0.0, *([1.0] * x.shape[1])])
    for _ in range(100):
        probability = _sigmoid(design @ beta)
        gradient = design.T @ (weights * (probability - y)) + penalty @ beta
        curvature = weights * probability * (1.0 - probability)
        hessian = design.T @ (design * curvature[:, None]) + penalty
        update = np.linalg.solve(hessian + np.eye(len(beta)) * 1e-9, gradient)
        beta -= update
        if float(np.max(np.abs(update))) < 1e-9:
            break
    return beta, location, scale


def _predict_logistic(
    beta: np.ndarray, location: np.ndarray, scale: np.ndarray, x: np.ndarray
) -> np.ndarray:
    standardized = (x - location) / scale
    design = np.column_stack([np.ones(len(x)), standardized])
    return _sigmoid(design @ beta)


def _auc(y: np.ndarray, probability: np.ndarray) -> float | None:
    positive = probability[y == 1]
    negative = probability[y == 0]
    if not len(positive) or not len(negative):
        return None
    favorable = sum(float(p > n) + 0.5 * float(p == n) for p in positive for n in negative)
    return favorable / (len(positive) * len(negative))


def _metrics(y: np.ndarray, probability: np.ndarray) -> dict[str, Any]:
    prediction = (probability >= 0.5).astype(int)
    tp = int(((prediction == 1) & (y == 1)).sum())
    fp = int(((prediction == 1) & (y == 0)).sum())
    tn = int(((prediction == 0) & (y == 0)).sum())
    fn = int(((prediction == 0) & (y == 1)).sum())
    sensitivity = tp / (tp + fn) if tp + fn else None
    specificity = tn / (tn + fp) if tn + fp else None
    return {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "accuracy": (tp + tn) / len(y),
        "sensitivity": sensitivity,
        "specificity": specificity,
        "balanced_accuracy": (
            (sensitivity + specificity) / 2
            if sensitivity is not None and specificity is not None
            else None
        ),
        "precision": tp / (tp + fp) if tp + fp else None,
        "brier_score": float(np.mean((probability - y) ** 2)),
        "roc_auc": _auc(y, probability),
    }


def _lineage_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["lineage"])].append(record)
    result = []
    all_feature_names = tuple(records[0]["features"])
    for lineage, selected in sorted(grouped.items()):
        labels = {bool(row["material_sheep_expansion"]) for row in selected}
        if len(labels) != 1:
            raise ValueError(f"mixed labels within lineage {lineage}: {labels}")
        result.append(
            {
                "lineage": lineage,
                "episodes": len(selected),
                "label": int(labels.pop()),
                "features": {
                    feature: mean(float(row["features"][feature]) for row in selected)
                    for feature in all_feature_names
                },
            }
        )
    return result


def _evaluate(lineages: list[dict[str, Any]]) -> dict[str, Any]:
    x = np.array([[row["features"][feature] for feature in FEATURES] for row in lineages])
    y = np.array([row["label"] for row in lineages], dtype=int)
    probabilities = np.zeros(len(lineages), dtype=float)
    for held_out in range(len(lineages)):
        training = np.array([index != held_out for index in range(len(lineages))])
        beta, location, scale = _fit_logistic(x[training], y[training])
        probabilities[held_out] = _predict_logistic(
            beta, location, scale, x[held_out : held_out + 1]
        )[0]
    full_beta, full_location, full_scale = _fit_logistic(x, y)
    mechanic_probability = np.array(
        [
            float(
                row["features"]["free_pasture_slots"] >= 2
                and row["features"]["cash_after_two_sheep"] >= 500
                and row["features"]["feed_surplus_3d_after_two_sheep"] >= 0
                and row["features"]["prior_worker_slack_actions_48"] >= 8
            )
            for row in lineages
        ]
    )
    predictions = []
    for index, row in enumerate(lineages):
        predictions.append(
            {
                "lineage": row["lineage"],
                "episodes": row["episodes"],
                "label": int(y[index]),
                "held_out_probability": float(probabilities[index]),
                "held_out_prediction": int(probabilities[index] >= 0.5),
                "mechanical_prediction": int(mechanic_probability[index]),
                "features": row["features"],
            }
        )
    return {
        "lineage_counts": {
            "total": len(lineages),
            "positive": int(y.sum()),
            "negative": int(len(y) - y.sum()),
        },
        "held_out_logistic": {
            "metrics": _metrics(y, probabilities),
            "full_data_standardized_coefficients_for_interpretation_only": {
                "intercept": float(full_beta[0]),
                **{
                    feature: float(full_beta[index + 1])
                    for index, feature in enumerate(FEATURES)
                },
            },
            "full_data_location": {
                feature: float(full_location[index]) for index, feature in enumerate(FEATURES)
            },
            "full_data_scale": {
                feature: float(full_scale[index]) for index, feature in enumerate(FEATURES)
            },
        },
        "mechanical_rule": {"metrics": _metrics(y, mechanic_probability)},
        "predictions": predictions,
    }


def _cohort_features(lineages: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for label, name in ((1, "material"), (0, "no_material")):
        selected = [row for row in lineages if row["label"] == label]
        result[name] = {
            "lineages": len(selected),
            "lineage_weighted_feature_means": {
                feature: mean(row["features"][feature] for row in selected)
                for feature in selected[0]["features"]
            },
        }
    result["material_minus_no_material"] = {
        feature: result["material"]["lineage_weighted_feature_means"][feature]
        - result["no_material"]["lineage_weighted_feature_means"][feature]
        for feature in result["material"]["lineage_weighted_feature_means"]
    }
    return result


def run(source: Path, preregistration: Path, output: Path) -> dict[str, Any]:
    prereg = json.loads(preregistration.read_text(encoding="utf-8"))
    if tuple(prereg["features"]) != FEATURES:
        raise ValueError("script feature order does not match frozen preregistration")
    payload = json.loads(source.read_text(encoding="utf-8"))
    rows = payload.get("rows_detail") or []
    selected = [
        row
        for row in rows
        if float(row["max_abs_z"]) <= 4.0 and float(row["predicted_tilt"]) >= 1.5
    ]
    records = []
    replay_hashes = []
    for row in selected:
        replay_path = ROOT / row["replay_path"]
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
        cow_delta = float(row["actual_cow_delta"])
        sheep_delta = float(row["actual_sheep_delta"])
        if cow_delta != 0.0 or sheep_delta < 0.0:
            raise ValueError(
                f"label cohort violates frozen component-delta scope: {row['episode_id']}"
            )
        records.append(
            {
                "label": row["label"],
                "source_name": row["source_name"],
                "episode_id": row["episode_id"],
                "lineage": row["lineage"],
                "seat": int(row["seat"]),
                "actual_cow_delta": cow_delta,
                "actual_sheep_delta": sheep_delta,
                "material_sheep_expansion": sheep_delta >= 1.0,
                "features": _features(replay, int(row["seat"])),
            }
        )
        replay_hashes.append((str(row["replay_path"]), _sha256(replay_path)))
    lineages = _lineage_rows(records)
    evaluation = _evaluate(lineages)
    metrics = evaluation["held_out_logistic"]["metrics"]
    counts = evaluation["lineage_counts"]
    rules = prereg["pass_rule"]
    checks = {
        "positive_lineages": counts["positive"] >= int(rules["minimum_positive_lineages"]),
        "negative_lineages": counts["negative"] >= int(rules["minimum_negative_lineages"]),
        "sensitivity": metrics["sensitivity"] >= float(rules["minimum_sensitivity"]),
        "specificity": metrics["specificity"] >= float(rules["minimum_specificity"]),
        "balanced_accuracy": metrics["balanced_accuracy"]
        >= float(rules["minimum_balanced_accuracy"]),
        "brier_score": metrics["brier_score"] <= float(rules["maximum_brier_score"]),
    }
    replay_manifest_digest = hashlib.sha256(
        "\n".join(f"{path}\t{digest}" for path, digest in sorted(replay_hashes)).encode()
    ).hexdigest()
    result = {
        "format": "kaggriculture-sheep-option-value-e2-result-v1",
        "created_at": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(),
        "hypothesis_id": prereg["hypothesis_id"],
        "dataset_role": "Development",
        "evidence_scope": (
            "lineage-held-out prediction of observed Top Sheep expansion; no causal or win-value claim"
        ),
        "provenance": {
            "source": str(source),
            "source_sha256": _sha256(source),
            "preregistration": str(preregistration),
            "preregistration_sha256": _sha256(preregistration),
            "analyzer": str(Path(__file__).resolve()),
            "analyzer_sha256": _sha256(Path(__file__).resolve()),
            "selected_replay_count": len(replay_hashes),
            "selected_replay_manifest_sha256": replay_manifest_digest,
        },
        "coverage": {
            "source_rows": len(rows),
            "triggered_episode_rows": len(records),
            **evaluation["lineage_counts"],
        },
        "component_delta_audit": {
            "cow_delta_distribution": dict(Counter(str(row["actual_cow_delta"]) for row in records)),
            "sheep_delta_distribution": dict(
                Counter(str(row["actual_sheep_delta"]) for row in records)
            ),
            "interpretation": "The positive label is Sheep expansion with Cow held flat.",
        },
        "cohort_features": _cohort_features(lineages),
        "evaluation": evaluation,
        "preregistered_pass_checks": checks,
        "preregistered_result": "PASS_E2_PREDICTION" if all(checks.values()) else "FAIL_E2_PREDICTION",
        "interpretation_guardrails": prereg["guardrails"],
        "records": records,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=False)
    target = output / "result.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "data" / "analysis" / "v113_strategy_gate_audit_v2.json",
    )
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=ROOT
        / "experiments"
        / "sheep_option_value_e2_20260902"
        / "preregistration.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "analysis" / "sheep_option_value_e2_20260902",
    )
    args = parser.parse_args()
    result = run(args.source.resolve(), args.preregistration.resolve(), args.output.resolve())
    print(
        json.dumps(
            {
                "coverage": result["coverage"],
                "held_out_metrics": result["evaluation"]["held_out_logistic"]["metrics"],
                "mechanical_metrics": result["evaluation"]["mechanical_rule"]["metrics"],
                "checks": result["preregistered_pass_checks"],
                "result": result["preregistered_result"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
