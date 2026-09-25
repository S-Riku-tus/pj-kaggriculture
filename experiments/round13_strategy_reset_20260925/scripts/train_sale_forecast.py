"""Train and evaluate a small public-observation opponent-sale forecast.

Ground-truth fills may use the saved opponent private state after the fact.  No
private value is included in the feature vector.  Ambiguous same-item
BUY_PRODUCT-before-SELL labels are excluded rather than converted to zero.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import math
import random
import time
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ROUND13 = Path(__file__).resolve().parents[1]
ROUND12 = ROOT / "experiments/round12_causal_repairs_20260925"
PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER")
HORIZONS = (1, 4, 12)
BASE = {"WHEAT": 25, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120, "MELON": 250, "EGG": 50, "MILK": 160, "WOOL": 200, "FERTILIZER": 100}
ANIMAL_PRODUCT = {"GOOSE": "EGG", "COW": "MILK", "SHEEP": "WOOL"}
FEATURE_NAMES = (
    "step_fraction",
    "hour_fraction",
    "inventory_delta_i0",
    "price_ratio",
    "opponent_producer_tiles",
    "own_producer_tiles",
    "shop_instances_demanding_item",
    "inventory_change_1",
    "price_change_1",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-min(value, 40.0))
        return 1.0 / (1.0 + z)
    z = math.exp(max(value, -40.0))
    return z / (1.0 + z)


def split_for(path: str) -> str:
    # Family-disjoint test and later-factorial validation.  Whole episodes are
    # assigned; adjacent rows from one game can never cross splits.
    if "/order_book/" in path or "/metav4/" in path:
        return "test"
    if "factorial_development" in path and "/v57/" in path:
        return "val"
    return "train"


def family_for(path: str) -> str:
    for family in ("order_book", "metav4", "v57", "B1"):
        if f"/{family}/" in path:
            return family
    return "B1"


def replay_seat(path: str) -> int:
    return int(path.rsplit("_seat_", 1)[1].split(".", 1)[0])


def producer_count(observation: dict, player: int, item: str) -> int:
    total = 0
    for row in observation["farms"][player]["tiles"]:
        for tile in row:
            if not isinstance(tile, dict):
                continue
            if tile.get("crop") == item:
                total += 1
            if ANIMAL_PRODUCT.get(tile.get("animal")) == item:
                total += 1
    return total


def demanding_shops(observation: dict, item: str) -> int:
    shops = {
        "BAKERY": ("EGG", "WHEAT"),
        "PIZZA_SHOP": ("MILK", "TOMATO", "WHEAT"),
        "BRUNCH_SPOT": ("EGG", "WHEAT", "STRAWBERRY"),
        "YARN_STORE": ("WOOL",),
        "ICE_CREAM_SHOP": ("STRAWBERRY", "MILK", "WHEAT"),
        "PET_CAFE": ("CARROT",),
        "SMOOTHIE_SHOP": ("STRAWBERRY", "MILK"),
        "FARMERS_MARKET": ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY"),
    }
    return sum(item in shops.get(shop, ()) for shop in observation["town"]["unlocked_shops"])


def features(observation: dict, previous: dict | None, seat: int, item: str) -> tuple[float, ...]:
    opponent = 1 - seat
    inventory = float(observation["market"]["inventory"][item])
    price = float(observation["market"]["prices"][item])
    previous_inventory = inventory if previous is None else float(previous["market"]["inventory"][item])
    previous_price = price if previous is None else float(previous["market"]["prices"][item])
    return (
        float(observation["step"]) / 719.0,
        float(observation["hour"]) / 23.0,
        (inventory - 10000.0) / 500.0,
        price / BASE[item],
        float(producer_count(observation, opponent, item)) / 50.0,
        float(producer_count(observation, seat, item)) / 50.0,
        float(demanding_shops(observation, item)) / 8.0,
        (inventory - previous_inventory) / 100.0,
        (price - previous_price) / BASE[item],
    )


def filled_sales(record: dict, opponent: int) -> dict[str, int | None]:
    from kaggle_environments.envs.kaggriculture import kaggriculture as official

    observation = record["observations"][opponent]
    action = record["actions"][opponent]
    farm = copy.deepcopy(observation["farms"][opponent])
    private = copy.deepcopy(observation["private"])
    commands = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
    demand = Counter(command[1] for command in commands if isinstance(command, list) and len(command) >= 2 and command[0] == "PLANT")
    blocked = {crop for crop, amount in demand.items() if amount > private["seeds"].get(crop, 0)}
    for actor, command in enumerate(commands):
        if isinstance(command, list) and len(command) >= 2 and command[0] == "PLANT" and command[1] in blocked:
            command = ["PASS"]
        official._apply_unit_action(farm, private, actor, command, 10, int(observation["day"]), 24, 100)
    stock = {key: int(value) for key, value in private["shed"].items()}
    output: dict[str, int | None] = {item: 0 for item in PRODUCTS}
    bought_before = set()
    for order in (action.get("market") or [])[:10]:
        if not isinstance(order, list) or not order:
            continue
        if order[0] == "BUY_PRODUCT" and len(order) >= 3 and order[1] in ("WHEAT", "FERTILIZER"):
            bought_before.add(order[1])
        elif order[0] == "SELL" and len(order) >= 3 and order[1] in output:
            item = order[1]
            if item in bought_before:
                output[item] = None
                continue
            if output[item] is None:
                continue
            fill = min(max(0, int(order[2])), max(0, stock.get(item, 0)))
            output[item] = int(output[item]) + fill
            stock[item] = max(0, stock.get(item, 0) - fill)
    return output


def episode_samples(path: Path, relative: str, stride: int) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        replay = json.load(stream)
    seat = replay_seat(relative)
    opponent = 1 - seat
    decisions = replay["decisions"]
    sales = [filled_sales(record, opponent) for record in decisions]
    output = []
    previous = None
    for index, record in enumerate(decisions):
        observation = record["observations"][seat]
        if index % stride:
            previous = observation
            continue
        for item in PRODUCTS:
            labels = {}
            quantities = {}
            for horizon in HORIZONS:
                window = sales[index : min(len(sales), index + horizon)]
                values = [entry[item] for entry in window]
                if len(window) < horizon or any(value is None for value in values):
                    labels[str(horizon)] = None
                    quantities[str(horizon)] = None
                else:
                    quantity = sum(int(value) for value in values)
                    labels[str(horizon)] = int(quantity > 0)
                    quantities[str(horizon)] = quantity
            output.append(
                {
                    "episode": relative,
                    "split": split_for(relative),
                    "family": family_for(relative),
                    "step": int(record["step"]),
                    "hour_bucket": int(observation["hour"]) // 4,
                    "item": item,
                    "features": features(observation, previous, seat, item),
                    "labels": labels,
                    "quantities": quantities,
                    "inventory": int(observation["market"]["inventory"][item]),
                }
            )
        previous = observation
    return output


def fit_logistic(rows: list[dict], horizon: int) -> dict:
    values = [row for row in rows if row["labels"][str(horizon)] is not None]
    dimension = len(FEATURE_NAMES)
    means = [sum(row["features"][index] for row in values) / len(values) for index in range(dimension)]
    stds = []
    for index in range(dimension):
        variance = sum((row["features"][index] - means[index]) ** 2 for row in values) / len(values)
        stds.append(max(math.sqrt(variance), 1e-8))
    weights = [0.0] * (dimension + 1)
    indices = list(range(len(values)))
    rng = random.Random(130925 + horizon)
    for epoch in range(5):
        rng.shuffle(indices)
        rate = 0.04 / (1.0 + epoch * 0.5)
        for row_index in indices:
            row = values[row_index]
            vector = [(row["features"][index] - means[index]) / stds[index] for index in range(dimension)]
            prediction = sigmoid(weights[0] + sum(weight * value for weight, value in zip(weights[1:], vector)))
            error = prediction - float(row["labels"][str(horizon)])
            weights[0] -= rate * error
            for index, value in enumerate(vector, start=1):
                weights[index] -= rate * (error * value + 1e-5 * weights[index])
    return {"means": means, "stds": stds, "weights": weights, "train_rows": len(values)}


def predict(model: dict, row: dict) -> float:
    vector = [
        (row["features"][index] - model["means"][index]) / model["stds"][index]
        for index in range(len(FEATURE_NAMES))
    ]
    return sigmoid(model["weights"][0] + sum(weight * value for weight, value in zip(model["weights"][1:], vector)))


def quantile(values: list[int], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return float(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stride", type=int, default=4)
    args = parser.parse_args()
    index = json.loads((ROUND12 / "replays/INDEX.json").read_text(encoding="utf-8"))
    paths = [relative for panel in index["panels"] for relative in panel["replays"]]
    if len(paths) != 129:
        raise RuntimeError(f"expected 129 indexed games, found {len(paths)}")
    samples = []
    for number, relative in enumerate(paths, start=1):
        samples.extend(episode_samples(ROUND12 / relative, relative, args.stride))
        if number % 16 == 0 or number == len(paths):
            print(f"loaded {number}/{len(paths)} episodes", flush=True)
    train = [row for row in samples if row["split"] == "train"]
    models = {}
    frequencies = {}
    quantity_tables = {}
    for item in PRODUCTS:
        for horizon in HORIZONS:
            key = f"{item}:{horizon}"
            subset = [row for row in train if row["item"] == item]
            models[key] = fit_logistic(subset, horizon)
            cells: dict[str, list[dict]] = defaultdict(list)
            for row in subset:
                if row["labels"][str(horizon)] is not None:
                    cells[str(row["hour_bucket"])].append(row)
            frequencies[key] = {}
            quantity_tables[key] = {}
            for bucket in range(6):
                values = cells.get(str(bucket), [])
                labels = [int(row["labels"][str(horizon)]) for row in values]
                quantities = [int(row["quantities"][str(horizon)]) for row in values]
                positive = [value for value in quantities if value > 0]
                frequencies[key][str(bucket)] = (sum(labels) + 1.0) / (len(labels) + 2.0)
                quantity_tables[key][str(bucket)] = {
                    "mean_positive": sum(positive) / len(positive) if positive else 0.0,
                    "q90": quantile(quantities, 0.90),
                }
    artifact = {
        "schema_version": 1,
        "feature_names": FEATURE_NAMES,
        "products": PRODUCTS,
        "horizons": HORIZONS,
        "stride": args.stride,
        "models": models,
        "time_frequency": frequencies,
        "quantity_tables": quantity_tables,
        "split_rule": "test=order_book/metav4 families; val=later factorial v57; train=remaining whole episodes",
    }
    # Normalize dictionary keys through JSON before writing.  The in-memory
    # count tables use integer hour buckets, while JSON correctly reloads all
    # object keys as strings; comparing those two representations directly is
    # not a persistence failure.
    persisted_artifact = json.loads(json.dumps(artifact, separators=(",", ":")))
    model_path = ROUND13 / "models/sale_forecast.json"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(json.dumps(persisted_artifact, separators=(",", ":")) + "\n", encoding="utf-8")
    reloaded = json.loads(model_path.read_text(encoding="utf-8"))
    from kaggle_environments.envs.kaggriculture import kaggriculture as official

    metrics = {}
    examples = []
    inference_count = 0
    started = time.perf_counter()
    for horizon in HORIZONS:
        accum = defaultdict(float)
        count = 0
        by_item = defaultdict(lambda: defaultdict(float))
        by_item_count = Counter()
        for row in samples:
            if row["split"] != "test" or row["labels"][str(horizon)] is None:
                continue
            key = f"{row['item']}:{horizon}"
            baseline_probability = reloaded["time_frequency"][key][str(row["hour_bucket"])]
            probability = predict(reloaded["models"][key], row)
            actual = int(row["labels"][str(horizon)])
            quantity = int(row["quantities"][str(horizon)])
            table = reloaded["quantity_tables"][key][str(row["hour_bucket"])]
            baseline_quantity = baseline_probability * table["mean_positive"]
            model_quantity = probability * table["mean_positive"]
            baseline_impact = official.market_price(row["item"], int(round(row["inventory"] + baseline_quantity))) - official.market_price(row["item"], row["inventory"])
            model_impact = official.market_price(row["item"], int(round(row["inventory"] + model_quantity))) - official.market_price(row["item"], row["inventory"])
            actual_impact = official.market_price(row["item"], row["inventory"] + quantity) - official.market_price(row["item"], row["inventory"])
            values = {
                "baseline_brier": (baseline_probability - actual) ** 2,
                "model_brier": (probability - actual) ** 2,
                "baseline_quantity_mae": abs(baseline_quantity - quantity),
                "model_quantity_mae": abs(model_quantity - quantity),
                "interval_coverage": float(0 <= quantity <= table["q90"]),
                "baseline_price_impact_mae": abs(baseline_impact - actual_impact),
                "model_price_impact_mae": abs(model_impact - actual_impact),
            }
            for name, value in values.items():
                accum[name] += value
                by_item[row["item"]][name] += value
            by_item_count[row["item"]] += 1
            count += 1
            inference_count += 1
            error = abs(probability - actual)
            examples.append(
                {
                    "error": error,
                    "episode": row["episode"],
                    "step": row["step"],
                    "item": row["item"],
                    "horizon": horizon,
                    "actual_event": actual,
                    "actual_quantity": quantity,
                    "baseline_probability": baseline_probability,
                    "model_probability": probability,
                }
            )
        metrics[str(horizon)] = {
            "test_predictions": count,
            **{name: value / count for name, value in accum.items()},
            "by_item": {
                item: {name: value / by_item_count[item] for name, value in values.items()}
                for item, values in sorted(by_item.items())
            },
        }
    inference_seconds = time.perf_counter() - started
    split_episodes = Counter(split_for(path) for path in paths)
    split_rows = Counter(row["split"] for row in samples)
    unknown_labels = {
        str(horizon): sum(row["labels"][str(horizon)] is None for row in samples)
        for horizon in HORIZONS
    }
    report = {
        "source_indexed_games": len(paths),
        "source_index_sha256": sha256(ROUND12 / "replays/INDEX.json"),
        "episode_splits": dict(split_episodes),
        "sample_rows": dict(split_rows),
        "unknown_labels_excluded": unknown_labels,
        "features_are_public_only": True,
        "private_state_use": "ground-truth filled-sale labels only",
        "fit_preprocessing": "train episodes only",
        "model_sha256": sha256(model_path),
        "model_bytes": model_path.stat().st_size,
        "reload_verified": persisted_artifact == reloaded,
        "runtime_inferences": inference_count,
        "runtime_seconds": inference_seconds,
        "mean_microseconds_per_inference": 1e6 * inference_seconds / max(1, inference_count),
        "policy_decisions_influenced": 0,
        "reactive_score_delta_vs_B1": None,
        "metrics": metrics,
        "largest_model_errors": sorted(examples, key=lambda value: -value["error"])[:12],
    }
    output = ROUND13 / "metrics/sale_forecast/report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
