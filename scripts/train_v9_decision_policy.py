"""Train V9's Rank-1 macro-intent and market-decision forests.

The split is by complete episode: three hash buckets train, one calibrates
thresholds/selection, and one remains an untouched test set.  V8's current
rules are evaluated on the same held-out observations.  A learned decision is
enabled in the runtime payload only when it improves its calibration split;
the test metrics are reported but never used for selection.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v9.main import (  # noqa: E402
    BINARY_INTENTS,
    DECISION_FORMAT,
    INTENT_FEATURE_NAMES,
    INTENT_NAMES,
    MARKET_FEATURE_NAMES,
    MARKET_ITEMS,
    _intent_features,
    _market_features,
    base,
    v4,
    v8,
)
from scripts.train_v3_strategy import train_forest  # noqa: E402

SOURCE = ROOT / "data" / "submissions" / "leaderboard_rank1_submission_55614463"


def _rows() -> list[dict[str, str]]:
    with (SOURCE / "manifest.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [
        row
        for row in rows
        if row.get("replay_status") in {"downloaded", "skipped_existing"}
        and row.get("opponent_team_name") != row.get("team_name")
    ]


def _replay_path(row: dict[str, str]) -> Path:
    relative = Path(row["replay_path"])
    direct = ROOT / relative
    return direct if direct.is_file() else ROOT / "data" / relative


def _split(episode_id: str) -> str:
    digest = hashlib.sha1(f"v9-decision-holdout:{episode_id}".encode()).digest()
    bucket = int.from_bytes(digest[:2], "big") % 5
    if bucket == 0:
        return "validation"
    if bucket == 1:
        return "test"
    return "train"


def _episode_weight(row: dict[str, str]) -> float:
    own = max(0.0, float(row.get("own_reward") or 0))
    opponent = max(0.0, float(row.get("opponent_reward") or 0))
    share = own / max(1.0, own + opponent)
    return min(1.18, max(0.84, 1.0 + 1.35 * (share - 0.5)))


def _observation(replay: dict[str, Any], step: int, seat: int) -> dict[str, Any] | None:
    steps = replay.get("steps", [])
    if not 0 <= step < len(steps) or not 0 <= seat < len(steps[step]):
        return None
    observation = steps[step][seat].get("observation")
    return observation if isinstance(observation, dict) else None


def _action(replay: dict[str, Any], observation_step: int, seat: int) -> dict[str, Any]:
    action_step = observation_step + 1
    steps = replay.get("steps", [])
    if not 0 <= action_step < len(steps) or not 0 <= seat < len(steps[action_step]):
        return {"farmer": ["PASS"], "hands": [], "market": []}
    action = steps[action_step][seat].get("action")
    return action if isinstance(action, dict) else {"farmer": ["PASS"], "hands": [], "market": []}


def _parts(obs: dict[str, Any], seat: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    farms = obs.get("farms", []) or []
    player = int(obs.get("player", seat))
    if not 0 <= player < len(farms):
        return None
    opponent = farms[1 - player] if len(farms) > 1 else farms[player]
    return farms[player], opponent, obs.get("private", {}) or {}


def _market_quantity(actions: list[dict[str, Any]], verb: str, item: str | None = None) -> int:
    total = 0
    for action in actions:
        for order in action.get("market", []) or []:
            if not isinstance(order, list) or not order or order[0] != verb:
                continue
            if item is not None and (len(order) < 2 or order[1] != item):
                continue
            total += 1 if verb in {"BUY_LAND", "HIRE"} else max(0, base._as_int(order[2] if len(order) > 2 else 0))
    return total


def _field_quantity(actions: list[dict[str, Any]], verb: str, item: str | None = None) -> int:
    total = 0
    for action in actions:
        unit_actions = [action.get("farmer", ["PASS"]), *(action.get("hands", []) or [])]
        for unit_action in unit_actions:
            if not isinstance(unit_action, list) or not unit_action or unit_action[0] != verb:
                continue
            if item is not None and (len(unit_action) < 2 or unit_action[1] != item):
                continue
            total += 1
    return total


def _intent_label(
    obs: dict[str, Any],
    farm: dict[str, Any],
    private: dict[str, Any],
    next12: list[dict[str, Any]],
    next24: list[dict[str, Any]],
) -> list[float]:
    cow = _market_quantity(next12, "BUY_ANIMAL", "COW")
    sheep = _market_quantity(next12, "BUY_ANIMAL", "SHEEP")
    strawberry = _field_quantity(next12, "PLANT", "STRAWBERRY")
    wheat = _field_quantity(next12, "PLANT", "WHEAT")
    day = base._as_int(obs.get("day", 0))
    owned = sum(v4._owned_animals(farm, private, animal) for animal in ("COW", "SHEEP"))
    money = float(farm.get("money", 0) or 0)
    wait_eligible = day < 21 and owned < 16 and money >= 400
    return [
        float(cow > 0),
        float(sheep > 0),
        float(wait_eligible and cow + sheep == 0),
        float(_market_quantity(next24, "BUY_LAND") > 0),
        float(_field_quantity(next12, "BUILD_PASTURE") > 0),
        float(strawberry > 0),
        float(wheat > 0),
        float(cow),
        float(sheep),
        float(strawberry),
        float(wheat),
    ]


def _intent_baseline(
    obs: dict[str, Any], farm: dict[str, Any], opponent: dict[str, Any], private: dict[str, Any]
) -> list[float]:
    animals, crops, _hands, land, _weights, pastures = v8._strategy_targets(obs, farm, opponent, private)
    summary = base._farm_summary(farm)
    owned = {animal: v4._owned_animals(farm, private, animal) for animal in ("COW", "SHEEP")}
    cow = max(0, animals["COW"] - owned["COW"])
    sheep = max(0, animals["SHEEP"] - owned["SHEEP"])
    day = base._as_int(obs.get("day", 0))
    wait_eligible = day < 21 and sum(owned.values()) < 16 and float(farm.get("money", 0) or 0) >= 400
    strawberry = max(0, crops["STRAWBERRY"] - summary["crops"]["STRAWBERRY"])
    wheat = max(0, crops["WHEAT"] - summary["crops"]["WHEAT"])
    return [
        float(cow > 0),
        float(sheep > 0),
        float(wait_eligible and cow + sheep == 0),
        float(land > summary["unlocked"]),
        float(pastures > v8._pasture_count(farm)),
        float(strawberry > 0),
        float(wheat > 0),
        float(cow),
        float(sheep),
        float(strawberry),
        float(wheat),
    ]


def collect_dataset(max_episodes: int | None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    intent: dict[str, list[Any]] = defaultdict(list)
    market: dict[str, list[Any]] = defaultdict(list)
    episodes = _rows()
    if max_episodes is not None:
        episodes = episodes[:max_episodes]
    split_episodes: Counter[str] = Counter()
    teacher_actions: Counter[str] = Counter()

    for index, row in enumerate(episodes, 1):
        replay = json.loads(_replay_path(row).read_text(encoding="utf-8"))
        seat = int(row["submission_seat"])
        split = _split(row["episode_id"])
        split_episodes[split] += 1
        weight = _episode_weight(row)
        steps = replay.get("steps", [])
        for step in range(3 * 24, min(27 * 24, len(steps) - 25), 4):
            obs = _observation(replay, step, seat)
            if obs is None:
                continue
            parts = _parts(obs, seat)
            if parts is None:
                continue
            farm, opponent, private = parts
            next24 = [_action(replay, future, seat) for future in range(step, step + 24)]
            next12 = next24[:12]
            label = _intent_label(obs, farm, private, next12, next24)
            intent["x"].append(_intent_features(obs, farm, opponent, private))
            intent["y"].append(label)
            intent["baseline"].append(_intent_baseline(obs, farm, opponent, private))
            intent["weight"].append(weight)
            intent["split"].append(split)
            intent["episode"].append(row["episode_id"])
            intent["shop_count"].append(len((obs.get("town", {}) or {}).get("unlocked_shops", []) or []))

        for step in range(5 * 24, min(27 * 24, len(steps) - 1)):
            obs = _observation(replay, step, seat)
            if obs is None:
                continue
            parts = _parts(obs, seat)
            if parts is None:
                continue
            farm, opponent, private = parts
            actual = _action(replay, step, seat)
            summary = base._farm_summary(farm)
            baseline_orders = base._market_sales(obs, farm, private, summary["animal_total"])
            actual_sales = {
                order[1]: base._as_int(order[2])
                for order in (actual.get("market", []) or [])
                if isinstance(order, list) and len(order) >= 3 and order[0] == "SELL"
            }
            baseline_sales = {
                order[1]: base._as_int(order[2])
                for order in baseline_orders
                if isinstance(order, list) and len(order) >= 3 and order[0] == "SELL"
            }
            shed = private.get("shed", {}) or {}
            intent_prefix = _intent_features(obs, farm, opponent, private)
            for item in MARKET_ITEMS:
                stock = base._inventory_count(shed, item)
                if stock <= 0:
                    continue
                quantity = min(stock, max(0, actual_sales.get(item, 0)))
                baseline_quantity = min(stock, max(0, baseline_sales.get(item, 0)))
                market["x"].append(_market_features(obs, farm, opponent, private, item, intent_prefix))
                market["y"].append([float(quantity > 0), quantity / stock])
                market["baseline"].append([float(baseline_quantity > 0), baseline_quantity / stock])
                market["weight"].append(weight)
                market["split"].append(split)
                market["episode"].append(row["episode_id"])
                market["item"].append(item)
                market["demand"].append(int(base._demand_profile(obs).get(item, 0)))
                market["day"].append(base._as_int(obs.get("day", 0)))
                market["hour"].append(base._as_int(obs.get("hour", 0)))
                if quantity:
                    teacher_actions[f"SELL_{item}"] += 1
        if index % 10 == 0 or index == len(episodes):
            print(f"loaded {index}/{len(episodes)}", flush=True)

    intent_arrays = {
        key: np.asarray(value, dtype=np.float64)
        for key, value in intent.items()
        if key in {"x", "y", "baseline", "weight", "shop_count"}
    }
    intent_arrays.update({key: value for key, value in intent.items() if key not in intent_arrays})
    market_arrays = {
        key: np.asarray(value, dtype=np.float64)
        for key, value in market.items()
        if key in {"x", "y", "baseline", "weight", "demand", "day", "hour"}
    }
    market_arrays.update({key: value for key, value in market.items() if key not in market_arrays})
    source = {
        "directory": str(SOURCE.relative_to(ROOT)),
        "episodes": len(episodes),
        "episode_split": dict(split_episodes),
        "intent_examples": len(intent["x"]),
        "market_examples": len(market["x"]),
        "teacher_sell_events": dict(teacher_actions),
    }
    return intent_arrays, market_arrays, source


def _predict_tree(tree: list[Any], row: np.ndarray) -> np.ndarray:
    node = tree
    while node[0] == "N":
        node = node[3] if row[int(node[1])] <= float(node[2]) else node[4]
    return np.asarray(node[1:], dtype=np.float64)


def _predict(forest: list[list[Any]], x: np.ndarray, outputs: int) -> tuple[np.ndarray, np.ndarray]:
    means = np.zeros((len(x), outputs), dtype=np.float64)
    deviations = np.zeros_like(means)
    for index, row in enumerate(x):
        predictions = np.asarray([_predict_tree(tree, row) for tree in forest])
        means[index] = np.mean(predictions, axis=0)
        deviations[index] = np.std(predictions, axis=0)
    return means, deviations


def _best_threshold(y: np.ndarray, probability: np.ndarray) -> float:
    best = (-1.0, 0.5)
    for threshold in np.linspace(0.15, 0.85, 29):
        predicted = probability >= threshold
        positive = y >= 0.5
        tp = float(np.sum(predicted & positive))
        tn = float(np.sum(~predicted & ~positive))
        fp = float(np.sum(predicted & ~positive))
        fn = float(np.sum(~predicted & positive))
        recall = tp / max(1.0, tp + fn)
        specificity = tn / max(1.0, tn + fp)
        precision = tp / max(1.0, tp + fp)
        f1 = 2 * precision * recall / max(1e-9, precision + recall)
        score = 0.65 * (recall + specificity) / 2 + 0.35 * f1
        if score > best[0]:
            best = (score, float(threshold))
    return round(best[1], 4)


def _binary_metrics(y: np.ndarray, probability: np.ndarray, threshold: float) -> dict[str, float]:
    probability = np.clip(probability, 0.0, 1.0)
    predicted = probability >= threshold
    positive = y >= 0.5
    tp = float(np.sum(predicted & positive))
    tn = float(np.sum(~predicted & ~positive))
    fp = float(np.sum(predicted & ~positive))
    fn = float(np.sum(~predicted & positive))
    recall = tp / max(1.0, tp + fn)
    specificity = tn / max(1.0, tn + fp)
    precision = tp / max(1.0, tp + fp)
    return {
        "examples": int(len(y)),
        "prevalence": round(float(np.mean(positive)), 6),
        "accuracy": round((tp + tn) / max(1.0, tp + tn + fp + fn), 6),
        "balanced_accuracy": round((recall + specificity) / 2, 6),
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(2 * precision * recall / max(1e-9, precision + recall), 6),
        "brier": round(float(np.mean((probability - positive.astype(float)) ** 2)), 6),
    }


def _mask(values: list[str], split: str) -> np.ndarray:
    return np.asarray([value == split for value in values], dtype=bool)


def _intent_report(
    dataset: dict[str, Any], predictions: np.ndarray, thresholds: dict[str, float]
) -> dict[str, Any]:
    report: dict[str, Any] = {"validation": {}, "test": {}, "quantity_mae": {}}
    for split in ("validation", "test"):
        mask = _mask(dataset["split"], split)
        for index, name in enumerate(BINARY_INTENTS):
            report[split][name] = {
                "model": _binary_metrics(dataset["y"][mask, index], predictions[mask, index], thresholds[name]),
                "v8": _binary_metrics(dataset["y"][mask, index], dataset["baseline"][mask, index], 0.5),
            }
        report["quantity_mae"][split] = {
            name: {
                "model": round(float(np.mean(np.abs(dataset["y"][mask, index] - predictions[mask, index]))), 6),
                "v8": round(
                    float(np.mean(np.abs(dataset["y"][mask, index] - dataset["baseline"][mask, index]))), 6
                ),
            }
            for index, name in enumerate(INTENT_NAMES[7:], start=7)
        }
    test_mask = _mask(dataset["split"], "test")
    shop_count = dataset["shop_count"]
    report["test_by_shop_visibility"] = {}
    for label, lower, upper in (("1-3", 1, 3), ("4-6", 4, 6), ("7-8", 7, 8)):
        mask = test_mask & (shop_count >= lower) & (shop_count <= upper)
        if not np.any(mask):
            continue
        report["test_by_shop_visibility"][label] = {
            name: {
                "model": _binary_metrics(dataset["y"][mask, index], predictions[mask, index], thresholds[name]),
                "v8": _binary_metrics(dataset["y"][mask, index], dataset["baseline"][mask, index], 0.5),
            }
            for index, name in enumerate(BINARY_INTENTS)
        }
    episodes = np.asarray(dataset["episode"])
    failures = []
    for episode in sorted(set(episodes[test_mask])):
        mask = test_mask & (episodes == episode)
        failures.append(
            {
                "episode_id": str(episode),
                "examples": int(np.sum(mask)),
                "model_binary_brier": round(
                    float(np.mean((predictions[mask, :7] - dataset["y"][mask, :7]) ** 2)), 6
                ),
                "v8_binary_brier": round(
                    float(np.mean((dataset["baseline"][mask, :7] - dataset["y"][mask, :7]) ** 2)), 6
                ),
            }
        )
    report["worst_test_episodes"] = sorted(
        failures, key=lambda row: row["model_binary_brier"], reverse=True
    )[:10]
    return report


def _market_report(
    dataset: dict[str, Any], predictions: np.ndarray, thresholds: dict[str, float]
) -> dict[str, Any]:
    report: dict[str, Any] = {"validation": {}, "test": {}}
    items = np.asarray(dataset["item"])
    for split in ("validation", "test"):
        split_mask = _mask(dataset["split"], split)
        for item in MARKET_ITEMS:
            mask = split_mask & (items == item)
            report[split][item] = {
                "model": _binary_metrics(dataset["y"][mask, 0], predictions[mask, 0], thresholds[item]),
                "v8": _binary_metrics(dataset["y"][mask, 0], dataset["baseline"][mask, 0], 0.5),
                "fraction_mae_model": round(float(np.mean(np.abs(dataset["y"][mask, 1] - predictions[mask, 1]))), 6),
                "fraction_mae_v8": round(
                    float(np.mean(np.abs(dataset["y"][mask, 1] - dataset["baseline"][mask, 1]))), 6
                ),
            }
    test_mask = _mask(dataset["split"], "test")
    demand = dataset["demand"]
    day = dataset["day"]
    report["test_by_demand"] = {}
    for demand_label, demand_mask in (("zero", demand <= 0), ("positive", demand > 0)):
        report["test_by_demand"][demand_label] = {}
        for item in MARKET_ITEMS:
            mask = test_mask & demand_mask & (items == item)
            if not np.any(mask):
                continue
            report["test_by_demand"][demand_label][item] = {
                "model": _binary_metrics(dataset["y"][mask, 0], predictions[mask, 0], thresholds[item]),
                "v8": _binary_metrics(dataset["y"][mask, 0], dataset["baseline"][mask, 0], 0.5),
            }
    report["test_by_time"] = {}
    for label, lower, upper in (("day5-11", 5, 11), ("day12-19", 12, 19), ("day20-26", 20, 26)):
        phase_mask = test_mask & (day >= lower) & (day <= upper)
        report["test_by_time"][label] = {}
        for item in MARKET_ITEMS:
            mask = phase_mask & (items == item)
            if not np.any(mask):
                continue
            report["test_by_time"][label][item] = {
                "model": _binary_metrics(dataset["y"][mask, 0], predictions[mask, 0], thresholds[item]),
                "v8": _binary_metrics(dataset["y"][mask, 0], dataset["baseline"][mask, 0], 0.5),
            }
    episodes = np.asarray(dataset["episode"])
    failures = []
    for episode in sorted(set(episodes[test_mask])):
        mask = test_mask & (episodes == episode)
        failures.append(
            {
                "episode_id": str(episode),
                "examples": int(np.sum(mask)),
                "model_binary_brier": round(
                    float(np.mean((predictions[mask, 0] - dataset["y"][mask, 0]) ** 2)), 6
                ),
                "v8_binary_brier": round(
                    float(np.mean((dataset["baseline"][mask, 0] - dataset["y"][mask, 0]) ** 2)), 6
                ),
            }
        )
    report["worst_test_episodes"] = sorted(
        failures, key=lambda row: row["model_binary_brier"], reverse=True
    )[:10]
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trees", type=int, default=30)
    parser.add_argument("--depth", type=int, default=7)
    parser.add_argument("--intent-min-leaf", type=int, default=36)
    parser.add_argument("--market-min-leaf", type=int, default=52)
    parser.add_argument("--seed", type=int, default=20260824)
    parser.add_argument("--max-episodes", type=int)
    parser.add_argument("--output", type=Path, default=Path("agents/v9/decision_policy_model.json"))
    parser.add_argument(
        "--validation-output",
        type=Path,
        default=Path("data/analysis/v9_decision_policy_validation.json"),
    )
    args = parser.parse_args()

    intent, market, source = collect_dataset(args.max_episodes)
    intent_train = _mask(intent["split"], "train")
    market_train = _mask(market["split"], "train")

    print("training intent forest", flush=True)
    intent_forest = train_forest(
        intent["x"][intent_train],
        intent["y"][intent_train],
        intent["weight"][intent_train],
        trees=args.trees,
        depth=args.depth,
        min_leaf=args.intent_min_leaf,
        seed=args.seed,
    )
    print("training market forest", flush=True)
    market_weights = market["weight"][market_train].copy()
    positives = market["y"][market_train, 0] >= 0.5
    positive_boost = min(5.0, max(1.0, float(np.sum(~positives)) / max(1.0, float(np.sum(positives)))))
    market_weights[positives] *= positive_boost
    market_forest = train_forest(
        market["x"][market_train],
        market["y"][market_train],
        market_weights,
        trees=args.trees,
        depth=args.depth,
        min_leaf=args.market_min_leaf,
        seed=args.seed + 101,
    )

    intent_prediction, intent_deviation = _predict(intent_forest, intent["x"], len(INTENT_NAMES))
    market_prediction, market_deviation = _predict(market_forest, market["x"], 2)
    validation_mask_intent = _mask(intent["split"], "validation")
    validation_mask_market = _mask(market["split"], "validation")
    intent_thresholds = {
        name: _best_threshold(
            intent["y"][validation_mask_intent, index],
            intent_prediction[validation_mask_intent, index],
        )
        for index, name in enumerate(BINARY_INTENTS)
    }
    market_items = np.asarray(market["item"])
    market_thresholds = {
        item: _best_threshold(
            market["y"][validation_mask_market & (market_items == item), 0],
            market_prediction[validation_mask_market & (market_items == item), 0],
        )
        for item in MARKET_ITEMS
    }

    intent_report = _intent_report(intent, intent_prediction, intent_thresholds)
    market_report = _market_report(market, market_prediction, market_thresholds)
    intent_selection = {
        name: (
            intent_report["validation"][name]["model"]["balanced_accuracy"]
            >= intent_report["validation"][name]["v8"]["balanced_accuracy"] + 0.015
            and intent_report["validation"][name]["model"]["f1"]
            >= intent_report["validation"][name]["v8"]["f1"]
        )
        for name in BINARY_INTENTS
    }
    market_selection = {
        item: (
            market_report["validation"][item]["model"]["examples"] >= 50
            and market_report["validation"][item]["model"]["prevalence"] >= 0.01
            and market_report["validation"][item]["model"]["prevalence"] <= 0.99
            and
            market_report["validation"][item]["model"]["balanced_accuracy"]
            >= market_report["validation"][item]["v8"]["balanced_accuracy"] + 0.015
            and market_report["validation"][item]["model"]["f1"]
            >= market_report["validation"][item]["v8"]["f1"]
        )
        for item in MARKET_ITEMS
    }

    intent_scales = np.maximum(0.05, np.std(intent["y"][intent_train], axis=0))
    market_scales = np.maximum(0.05, np.std(market["y"][market_train], axis=0))
    intent_uncertainty = np.mean(intent_deviation / intent_scales, axis=1)
    market_uncertainty = np.mean(market_deviation / market_scales, axis=1)
    uncertainty_p90 = {
        "intent": round(float(np.quantile(intent_uncertainty[validation_mask_intent], 0.9)), 6),
        "market": round(float(np.quantile(market_uncertainty[validation_mask_market], 0.9)), 6),
    }

    validation = {
        "objective": "episode-held-out Rank-1 macro-decision fidelity; V8 rules are the baseline",
        "source": source,
        "selection_uses": "validation split only; test split is untouched reporting",
        "intent": intent_report,
        "market": market_report,
        "selection": {"intent": intent_selection, "market": market_selection},
        "thresholds": {"intent": intent_thresholds, "market": market_thresholds},
        "positive_market_weight": round(positive_boost, 6),
    }
    payload = {
        "format": DECISION_FORMAT,
        "created_at": datetime.now().astimezone().isoformat(),
        "training_seed": args.seed,
        "intent_feature_names": list(INTENT_FEATURE_NAMES),
        "market_feature_names": list(MARKET_FEATURE_NAMES),
        "intent_names": list(INTENT_NAMES),
        "market_items": list(MARKET_ITEMS),
        "forests": {"intent": intent_forest, "market": market_forest},
        "output_scales": {
            "intent": [round(float(value), 6) for value in intent_scales],
            "market": [round(float(value), 6) for value in market_scales],
        },
        "uncertainty_p90": uncertainty_p90,
        "thresholds": {"intent": intent_thresholds, "market": market_thresholds},
        "selection": {"intent": intent_selection, "market": market_selection},
        "source": source,
        "validation_summary": {
            "intent_test": intent_report["test"],
            "market_test": market_report["test"],
        },
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    validation_output = (
        args.validation_output if args.validation_output.is_absolute() else ROOT / args.validation_output
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    validation_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    validation_output.write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"model: {output} ({output.stat().st_size} bytes)")
    print(f"validation: {validation_output}")
    print("intent selection:", intent_selection)
    print("market selection:", market_selection)


if __name__ == "__main__":
    main()
