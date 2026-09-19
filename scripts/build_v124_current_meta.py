#!/usr/bin/env python3
"""Build V124's current-meta continuation and opponent-sale models.

The continuation library uses the winner of each completed V123 live game,
restricted to opponents initially rated at least 1600 and a day-12 portfolio
within five assets of V123.  The runtime artifact contains anonymous source
indices, observations, and following actions only.

The sale model is trained separately on V123 live observations.  Its target is
whether the opponent sells the same premium product when our recorded route
would sell it on the next turn.  Runtime features use only public state and
opponent sales inferred from shared-market changes.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.util
import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parents[1]
SUBMISSIONS = ("56346060", "56346090")
OPENING_END = 288
ANIMAL_CHECKPOINT = 360
EXPANSION_CHECKPOINT = 480
MINIMUM_OPPONENT_RATING = 1600.0
MAX_DAY12_PORTFOLIO_DISTANCE = 5
PREMIUM = ("STRAWBERRY", "MILK", "WOOL")
BASE_PRICE = {"STRAWBERRY": 120.0, "MILK": 160.0, "WOOL": 200.0}
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", type=Path, default=ROOT / "agents/v121/main.py")
    parser.add_argument("--opening-model", type=Path, default=ROOT / "agents/v121/model.json.gz")
    parser.add_argument("--policy-model", type=Path, default=ROOT / "agents/v124/policy_model.json.gz")
    parser.add_argument("--sale-model", type=Path, default=ROOT / "agents/v124/opponent_sell_model.json")
    parser.add_argument("--metadata", type=Path, default=ROOT / "agents/v124/model_metadata.json")
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "experiments/research_20260919_v124/model_build.json",
    )
    return parser.parse_args()


def load_policy(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("v124_build_policy", path.resolve())
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_observation(value: Mapping[str, Any], step: int) -> dict[str, Any]:
    result = dict(value)
    result["step"] = step
    return result


def normalized_action(value: Any) -> dict[str, Any]:
    raw = mapping(value)
    return {
        "farmer": list(raw.get("farmer") or ["PASS"]),
        "hands": [list(action or ["PASS"]) for action in raw.get("hands") or []],
        "market": [list(order) for order in raw.get("market") or []],
    }


def replay_path(submission_id: str, episode_id: int) -> Path:
    return ROOT / "data/replays" / f"v123_submission_{submission_id}" / f"episode_{episode_id}.json"


def portfolio(policy: Any, observation: Mapping[str, Any], seat: int) -> Counter[str]:
    farms = list(observation.get("farms") or [])
    farm = mapping(farms[seat]) if 0 <= seat < len(farms) else {}
    counts: Counter[str] = Counter()
    for raw in policy.base._board(farm):
        tile = mapping(raw)
        if tile.get("crop"):
            counts[str(tile["crop"])] += 1
        if tile.get("animal"):
            counts[str(tile["animal"])] += 1
    return counts


def portfolio_distance(policy: Any, observation: Mapping[str, Any], left: int, right: int) -> int:
    left_counts = portfolio(policy, observation, left)
    right_counts = portfolio(policy, observation, right)
    return sum(abs(left_counts[item] - right_counts[item]) for item in (*policy.base.CROPS, *policy.base.ANIMALS))


def animal_route(policy: Any, observation: Mapping[str, Any], seat: int) -> int:
    counts = portfolio(policy, observation, seat)
    if counts["GOOSE"] == 0 and counts["SHEEP"] >= 8:
        return policy.WOOL
    if counts["COW"] >= 9 and counts["SHEEP"] <= 6:
        return policy.MILK
    return policy.BALANCED


def expansion_route(policy: Any, observation: Mapping[str, Any], seat: int) -> int:
    farms = list(observation.get("farms") or [])
    farm = mapping(farms[seat]) if 0 <= seat < len(farms) else {}
    counts = portfolio(policy, observation, seat)
    return int(len(set(farm.get("unlocked_quadrants") or [])) >= 4 and counts["TOMATO"] >= 8)


def opponent_rating(episode: Mapping[str, str], seat: int) -> float:
    return float(episode.get(f"agent_{1 - seat}_initial_score") or 0.0)


def live_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for submission_id in SUBMISSIONS:
        directory = ROOT / "data/submissions" / f"v123_submission_{submission_id}"
        episodes = {integer(row["episode_id"]): row for row in read_csv(directory / "episodes.csv")}
        for row in read_csv(directory / "manifest.csv"):
            episode_id = integer(row.get("episode_id"), -1)
            if (
                row.get("episode_state") != "COMPLETED"
                or row.get("replay_status") != "downloaded"
                or integer(row.get("step_count")) < 720
                or row.get("result") not in {"win", "loss"}
                or episode_id not in episodes
            ):
                continue
            seat = integer(row.get("submission_seat"))
            records.append(
                {
                    **row,
                    "submission_id": submission_id,
                    "episode_id": episode_id,
                    "seat": seat,
                    "opponent_initial_rating": opponent_rating(episodes[episode_id], seat),
                    "replay_path": replay_path(submission_id, episode_id),
                }
            )
    return records


def build_policy_model(
    policy: Any,
    records: Sequence[Mapping[str, Any]],
    opening_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with gzip.open(opening_path.resolve(), "rt", encoding="utf-8") as stream:
        opening = json.load(stream)
    steps: list[list[list[Any]]] = [[] for _ in range(719)]
    for step in range(OPENING_END):
        steps[step] = list((opening.get("steps") or [])[step] or [])

    selected: list[tuple[Mapping[str, Any], dict[str, Any], int, int]] = []
    for row in records:
        if float(row["opponent_initial_rating"]) < MINIMUM_OPPONENT_RATING:
            continue
        replay = read_json(Path(row["replay_path"]))
        own_seat = integer(row["seat"])
        teacher_seat = own_seat if row["result"] == "win" else 1 - own_seat
        observation = canonical_observation(replay["steps"][OPENING_END][own_seat]["observation"], OPENING_END)
        distance = portfolio_distance(policy, observation, own_seat, teacher_seat)
        if distance <= MAX_DAY12_PORTFOLIO_DISTANCE:
            selected.append((row, replay, teacher_seat, distance))

    selected.sort(key=lambda value: (integer(value[0]["episode_id"]), value[2]))
    provenance: list[dict[str, Any]] = []
    for source, (row, replay, teacher_seat, distance) in enumerate(selected):
        replay_steps = replay.get("steps") or []
        animal_observation = canonical_observation(
            replay_steps[ANIMAL_CHECKPOINT][teacher_seat].get("observation") or {}, ANIMAL_CHECKPOINT
        )
        expansion_observation = canonical_observation(
            replay_steps[EXPANSION_CHECKPOINT][teacher_seat].get("observation") or {}, EXPANSION_CHECKPOINT
        )
        animal = animal_route(policy, animal_observation, teacher_seat)
        expansion = expansion_route(policy, expansion_observation, teacher_seat)
        provenance.append(
            {
                "source": source,
                "teacher_origin": "v123" if teacher_seat == integer(row["seat"]) else "winning_opponent",
                "opponent_rating_band": int(float(row["opponent_initial_rating"]) // 50 * 50),
                "day12_portfolio_distance": distance,
                "animal_route": animal,
                "expansion": bool(expansion),
            }
        )
        for step in range(OPENING_END, 719):
            observation = canonical_observation(replay_steps[step][teacher_seat].get("observation") or {}, step)
            action = normalized_action(replay_steps[step + 1][teacher_seat].get("action"))
            steps[step].append(
                [
                    policy.base.unit_count(observation),
                    source,
                    animal,
                    expansion,
                    policy.base.feature_vector(observation),
                    action,
                ]
            )

    model = {
        "format": policy.MODEL_FORMAT,
        "feature_length": policy.FEATURE_LENGTH,
        "beam_size": 6,
        "gate_steps": [288, 360, 432, 480, 576, 648],
        "steps": steps,
    }
    return model, provenance


def sell_quantity(action: Mapping[str, Any], item: str) -> int:
    return sum(
        max(0, integer(order[2]))
        for order in action.get("market") or []
        if isinstance(order, list | tuple) and len(order) >= 3 and order[0] == "SELL" and str(order[1]) == item
    )


def town_drain(observation: Mapping[str, Any], item: str, step: int) -> int:
    quantity = 0
    if step % 4 == 0:
        shops = list(mapping(observation.get("town")).get("unlocked_shops") or [])
        for shop in shops:
            products = SHOP_PRODUCTS.get(str(shop), ())
            if item in products:
                quantity += 2 if len(products) == 1 else 1
    if step % 24 == 0:
        quantity += 1
    return quantity


def inferred_opponent_sale(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
    own_action: Mapping[str, Any],
    item: str,
    previous_step: int,
) -> int:
    previous_market = mapping(mapping(previous.get("market")).get("inventory"))
    current_market = mapping(mapping(current.get("market")).get("inventory"))
    delta = integer(current_market.get(item), 10_000) - integer(previous_market.get(item), 10_000)
    previous_price = integer(mapping(mapping(previous.get("market")).get("prices")).get(item))
    own_available = integer(mapping(mapping(previous.get("private")).get("shed")).get(item))
    own_supply = min(own_available, sell_quantity(own_action, item)) if previous_price > 1 else 0
    return max(0, delta - own_supply + town_drain(previous, item, previous_step))


def farm_stats(farm: Mapping[str, Any], item: str) -> tuple[int, int, int, int]:
    asset = {"MILK": "COW", "WOOL": "SHEEP"}.get(item, item)
    count = total_yield = ready = serviced = 0
    for row in farm.get("tiles") or []:
        for raw in row or []:
            tile = mapping(raw)
            if tile.get("crop") != asset and tile.get("animal") != asset:
                continue
            count += 1
            quantity = max(0, integer(tile.get("yield_units")))
            total_yield += quantity
            ready += int(quantity > 0)
            serviced += int(bool(tile.get("watered_today") or tile.get("fed_today")))
    return count, total_yield, ready, serviced


def sale_features(
    observation: Mapping[str, Any],
    step: int,
    item: str,
    history: Mapping[str, Sequence[tuple[int, int]]],
    money_history: Mapping[int, int],
    planned: int,
    available: int,
) -> list[float]:
    seat = 1 if integer(observation.get("player")) == 1 else 0
    farms = list(observation.get("farms") or [])
    own = mapping(farms[seat]) if seat < len(farms) else {}
    opponent = mapping(farms[1 - seat]) if len(farms) > 1 else {}
    opponent_asset, opponent_yield, opponent_ready, opponent_service = farm_stats(opponent, item)
    own_asset, own_yield, own_ready, _own_service = farm_stats(own, item)
    market = mapping(observation.get("market"))
    market_inventory = integer(mapping(market.get("inventory")).get(item), 10_000)
    price = float(mapping(market.get("prices")).get(item, 0) or 0)
    shops = list(mapping(observation.get("town")).get("unlocked_shops") or [])
    demand = sum(item in SHOP_PRODUCTS.get(str(shop), ()) for shop in shops)
    events = list(history.get(item) or [])
    gaps = [step - event_step for event_step, quantity in events if event_step <= step and quantity > 0]
    gap = min(gaps) if gaps else 96
    recent = [
        sum(quantity for event_step, quantity in events if step - window < event_step <= step)
        for window in (1, 2, 4, 8, 12, 24, 48)
    ]
    opponent_money = integer(opponent.get("money"))
    own_money = integer(own.get("money"))
    previous_money = integer(money_history.get(max(0, step - 1)), opponent_money)
    previous_four_money = integer(money_history.get(max(0, step - 4)), opponent_money)
    features = [
        1.0,
        step / 720.0,
        (step // 24) / 30.0,
        opponent_asset / 20.0,
        opponent_yield / 50.0,
        opponent_ready / 20.0,
        opponent_service / 20.0,
        own_asset / 20.0,
        own_yield / 50.0,
        own_ready / 20.0,
        abs(opponent_asset - own_asset) / 20.0,
        (opponent_money - own_money) / 100_000.0,
        opponent_money / 100_000.0,
        (opponent_money - previous_money) / 10_000.0,
        (opponent_money - previous_four_money) / 20_000.0,
        (market_inventory - 10_000) / 1_000.0,
        price / BASE_PRICE[item],
        demand / 8.0,
        min(gap, 96) / 96.0,
        *(quantity / 50.0 for quantity in recent),
        min(planned, 100) / 50.0,
        min(available, 100) / 50.0,
    ]
    features.extend(float(step % 24 == hour) for hour in range(24))
    features.extend(float(step // 24 == day) for day in range(30))
    return features


def sale_samples(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for row in records:
        replay = read_json(Path(row["replay_path"]))
        replay_steps = replay.get("steps") or []
        seat = integer(row["seat"])
        history: dict[str, list[tuple[int, int]]] = defaultdict(list)
        money_history: dict[int, int] = {}
        for step in range(1, 718):
            previous = canonical_observation(replay_steps[step - 1][seat].get("observation") or {}, step - 1)
            current = canonical_observation(replay_steps[step][seat].get("observation") or {}, step)
            own_previous_action = normalized_action(replay_steps[step][seat].get("action"))
            opponent_index = 1 - seat
            farms = list(current.get("farms") or [])
            opponent = mapping(farms[opponent_index]) if opponent_index < len(farms) else {}
            money_history[step] = integer(opponent.get("money"))
            for item in PREMIUM:
                quantity = inferred_opponent_sale(previous, current, own_previous_action, item, step - 1)
                if quantity:
                    history[item].append((step, quantity))
            if step < OPENING_END:
                continue
            shed = mapping(mapping(current.get("private")).get("shed"))
            current_action = normalized_action(replay_steps[step + 1][seat].get("action"))
            next_action = normalized_action(replay_steps[step + 2][seat].get("action"))
            opponent_next = normalized_action(replay_steps[step + 2][opponent_index].get("action"))
            for item in PREMIUM:
                planned = sell_quantity(next_action, item)
                available = integer(shed.get(item))
                price = integer(mapping(mapping(current.get("market")).get("prices")).get(item))
                if (
                    sell_quantity(current_action, item)
                    or planned < 2
                    or available < 2
                    or price <= 1
                    or len(current_action.get("market") or []) >= 10
                    or town_drain(current, item, step) > 0
                    or town_drain(current, item, step + 1) > 0
                ):
                    continue
                samples.append(
                    {
                        "submission": str(row["submission_id"]),
                        "item": item,
                        "label": int(sell_quantity(opponent_next, item) > 0),
                        "features": sale_features(current, step, item, history, money_history, planned, available),
                    }
                )
    return samples


def fit_logistic(rows: Sequence[Mapping[str, Any]], regularization: float = 20.0) -> dict[str, Any]:
    matrix = np.asarray([row["features"] for row in rows], dtype=np.float64)
    target = np.asarray([row["label"] for row in rows], dtype=np.float64)
    mean = matrix.mean(axis=0)
    scale = matrix.std(axis=0)
    mean[0] = 0.0
    scale[0] = 1.0
    scale = np.where(scale < 1e-8, 1.0, scale)
    normalized = (matrix - mean) / scale

    def objective(weights: np.ndarray) -> tuple[float, np.ndarray]:
        linear = np.clip(normalized @ weights, -30.0, 30.0)
        probabilities = 1.0 / (1.0 + np.exp(-linear))
        loss = float(np.mean(np.logaddexp(0.0, linear) - target * linear))
        loss += regularization * float(np.sum(weights[1:] ** 2)) / (2.0 * len(target))
        gradient = normalized.T @ (probabilities - target) / len(target)
        gradient[1:] += regularization * weights[1:] / len(target)
        return loss, gradient

    initial = np.zeros(matrix.shape[1], dtype=np.float64)
    prevalence = float(target.mean())
    initial[0] = math.log((prevalence + 1e-4) / (1.0 - prevalence + 1e-4))
    result = minimize(
        lambda weights: objective(weights),
        initial,
        jac=True,
        method="L-BFGS-B",
        options={"maxiter": 500},
    )
    if not result.success:
        raise RuntimeError(f"sale model did not converge: {result.message}")
    return {
        "rows": len(rows),
        "positive_rate": prevalence,
        "mean": mean.tolist(),
        "scale": scale.tolist(),
        "weights": result.x.tolist(),
    }


def score_model(model: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], threshold: float) -> dict[str, Any]:
    if not rows:
        return {"rows": 0, "selected": 0, "precision": 0.0, "recall": 0.0}
    matrix = np.asarray([row["features"] for row in rows], dtype=np.float64)
    target = np.asarray([row["label"] for row in rows], dtype=np.int64)
    mean = np.asarray(model["mean"], dtype=np.float64)
    scale = np.asarray(model["scale"], dtype=np.float64)
    weights = np.asarray(model["weights"], dtype=np.float64)
    probabilities = 1.0 / (1.0 + np.exp(-np.clip(((matrix - mean) / scale) @ weights, -30.0, 30.0)))
    selected = probabilities >= threshold
    true_positive = int(np.sum(selected & (target == 1)))
    false_positive = int(np.sum(selected & (target == 0)))
    false_negative = int(np.sum(~selected & (target == 1)))
    return {
        "rows": len(rows),
        "selected": int(selected.sum()),
        "precision": true_positive / max(1, true_positive + false_positive),
        "recall": true_positive / max(1, true_positive + false_negative),
    }


def build_sale_model(samples: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    threshold = 0.60
    models: dict[str, Any] = {}
    holdout: dict[str, Any] = {}
    for item in PREMIUM:
        item_rows = [row for row in samples if row["item"] == item]
        models[item] = fit_logistic(item_rows)
        splits = []
        for train_submission, test_submission in ((SUBMISSIONS[0], SUBMISSIONS[1]), (SUBMISSIONS[1], SUBMISSIONS[0])):
            train = [row for row in item_rows if row["submission"] == train_submission]
            test = [row for row in item_rows if row["submission"] == test_submission]
            split_model = fit_logistic(train)
            splits.append(
                {
                    "train_submission": train_submission,
                    "test_submission": test_submission,
                    **score_model(split_model, test, threshold),
                }
            )
        holdout[item] = splits
    payload = {
        "format": "v124-opponent-sell-v1",
        "items": list(PREMIUM),
        "feature_length": len(samples[0]["features"]),
        "threshold": threshold,
        "models": models,
    }
    return payload, holdout


def main() -> int:
    args = parse_args()
    policy = load_policy(args.agent)
    records = live_records()
    policy_model, provenance = build_policy_model(policy, records, args.opening_model)
    encoded = json.dumps(policy_model, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    compressed = gzip.compress(encoded, compresslevel=9, mtime=0)
    args.policy_model.parent.mkdir(parents=True, exist_ok=True)
    args.policy_model.write_bytes(compressed)

    samples = sale_samples(records)
    sale_model, holdout = build_sale_model(samples)
    args.sale_model.write_text(
        json.dumps(sale_model, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    report = {
        "format": "v124-current-meta-build-v1",
        "live_games": len(records),
        "minimum_opponent_rating": MINIMUM_OPPONENT_RATING,
        "maximum_day12_portfolio_distance": MAX_DAY12_PORTFOLIO_DISTANCE,
        "selected_continuations": len(provenance),
        "teacher_origins": dict(Counter(row["teacher_origin"] for row in provenance)),
        "rating_bands": dict(Counter(str(row["opponent_rating_band"]) for row in provenance)),
        "route_counts": dict(Counter(f"{row['animal_route']}:{int(row['expansion'])}" for row in provenance)),
        "policy_model_bytes": len(compressed),
        "policy_model_sha256": hashlib.sha256(compressed).hexdigest(),
        "sale_samples": len(samples),
        "sale_holdout": holdout,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    metadata = {
        "format": policy.MODEL_FORMAT,
        "description": "Current-meta, state-compatible winning continuations from V123 live games.",
        "runtime_excludes": [
            "episode ids",
            "submission ids",
            "team names",
            "exact ratings",
            "rewards and outcomes",
            "future observations",
        ],
        "selection_rule": (
            "completed V123 live game; opponent initial rating >=1600; day-12 winner/V123 portfolio L1 <=5; "
            "winner continuation only"
        ),
        "anonymous_provenance": provenance,
        "policy_model_sha256": report["policy_model_sha256"],
        "sale_model_format": sale_model["format"],
    }
    args.metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
