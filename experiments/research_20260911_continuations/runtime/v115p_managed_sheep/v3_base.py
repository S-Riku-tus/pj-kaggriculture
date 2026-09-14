"""Kaggriculture V3: Top-3 expert-distilled hybrid agent.

The opening and liquidation phases are deterministic.  Between them, three
compact regression forests imitate the one-day-ahead portfolios of the public
Rank 1/2/3 agents.  A pairwise gate learned from their direct matches selects
the useful expert regime.  V2's safety-oriented task system turns those macro
targets into legal field and market actions.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

if "__file__" in globals():
    MODULE_DIR = Path(__file__).resolve().parent
else:
    # kaggle-environments executes main.py from source without defining
    # ``__file__``. It appends the extracted submission directory to sys.path,
    # but the process working directory may be somewhere else.
    _runtime_candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd() / "agents" / "v3",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (candidate / "feature_schema.py").is_file()
            and (candidate / "v2_base.py").is_file()
            and (candidate / "strategy_model.json").is_file()
        ),
        Path.cwd(),
    )
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import feature_schema as schema  # noqa: E402

FEATURE_NAMES = schema.FEATURE_NAMES
OUTPUT_NAMES = schema.OUTPUT_NAMES
SCHEMA_VERSION = schema.SCHEMA_VERSION
demand_profile = schema.demand_profile
encode_observation = schema.encode_observation


def _load_base_module():
    packaged = MODULE_DIR / "v2_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v2" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v3_base", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V2 planner base: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load_base_module()


def _load_model() -> dict[str, Any] | None:
    path = MODULE_DIR / "strategy_model.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if payload.get("schema_version") != SCHEMA_VERSION:
        return None
    if tuple(payload.get("feature_names", ())) != FEATURE_NAMES:
        return None
    if tuple(payload.get("output_names", ())) != OUTPUT_NAMES:
        return None
    return payload


MODEL = _load_model()


# Rank 1's public replays use this same 24-turn choreography in every sampled
# game.  It is shifted by one entry in replay JSON because steps[0] is the
# initial placeholder; index 0 here is the actual hour-0 action.
OPENING_ACTIONS: tuple[dict[str, Any], ...] = (
    {
        "farmer": ["BUILD_PASTURE"],
        "hands": [],
        "market": [
            ["HIRE"],
            ["HIRE"],
            ["HIRE"],
            ["HIRE"],
            ["HIRE"],
            ["BUY_ANIMAL", "SHEEP", 2],
            ["BUY_ANIMAL", "COW", 2],
            ["BUY_SEED", "MELON", 11],
            ["BUY_SEED", "WHEAT", 6],
            ["BUY_PRODUCT", "WHEAT", 4],
        ],
    },
    {
        "farmer": ["PICKUP", "COW", 1],
        "hands": [["WEST"], ["NORTH"], ["NORTH"], ["NORTH"], ["WEST"]],
        "market": [["SELL", "WHEAT", 4]],
    },
    {
        "farmer": ["PLACE", "COW"],
        "hands": [["WEST"], ["NORTH"], ["WEST"], ["BUILD_PASTURE"], ["WEST"]],
        "market": [],
    },
    {
        "farmer": ["WEST"],
        "hands": [["BUILD_PASTURE"], ["NORTH"], ["NORTH"], ["SOUTH"], ["NORTH"]],
        "market": [["BUY_PRODUCT", "WHEAT", 1]],
    },
    {
        "farmer": ["WEST"],
        "hands": [["EAST"], ["PLANT", "WHEAT"], ["WEST"], ["PICKUP", "COW", 1], ["BUILD_PASTURE"]],
        "market": [],
    },
    {
        "farmer": ["PLANT", "WHEAT"],
        "hands": [["PICKUP", "SHEEP", 1], ["WATER"], ["NORTH"], ["NORTH"], ["EAST"]],
        "market": [],
    },
    {
        "farmer": ["WATER"],
        "hands": [["WEST"], ["NORTH"], ["PLANT", "WHEAT"], ["PLACE", "COW"], ["SOUTH"]],
        "market": [],
    },
    {
        "farmer": ["NORTH"],
        "hands": [["PLACE", "SHEEP"], ["PLANT", "WHEAT"], ["WATER"], ["NORTH"], ["PICKUP", "SHEEP", 1]],
        "market": [["BUY_PRODUCT", "WHEAT", 1]],
    },
    {
        "farmer": ["PLANT", "WHEAT"],
        "hands": [["WEST"], ["WATER"], ["WEST"], ["NORTH"], ["WEST"]],
        "market": [["BUY_PRODUCT", "WHEAT", 1]],
    },
    {
        "farmer": ["WATER"],
        "hands": [["NORTH"], ["WEST"], ["NORTH"], ["NORTH"], ["NORTH"]],
        "market": [],
    },
    {
        "farmer": ["WEST"],
        "hands": [["WEST"], ["NORTH"], ["PLANT", "MELON"], ["PLANT", "MELON"], ["PLACE", "SHEEP"]],
        "market": [],
    },
    {
        "farmer": ["WEST"],
        "hands": [["NORTH"], ["PLANT", "MELON"], ["WATER"], ["WATER"], ["WEST"]],
        "market": [["BUY_PRODUCT", "WHEAT", 1]],
    },
    {
        "farmer": ["PLANT", "MELON"],
        "hands": [["PLANT", "MELON"], ["WATER"], ["NORTH"], ["WEST"], ["NORTH"]],
        "market": [],
    },
    {
        "farmer": ["WATER"],
        "hands": [["WATER"], ["WEST"], ["PLANT", "MELON"], ["WEST"], ["WEST"]],
        "market": [],
    },
    {
        "farmer": ["NORTH"],
        "hands": [["WEST"], ["WEST"], ["WATER"], ["WEST"], ["NORTH"]],
        "market": [],
    },
    {
        "farmer": ["PLANT", "MELON"],
        "hands": [["NORTH"], ["WEST"], ["SOUTH"], ["PLANT", "MELON"], ["PLANT", "MELON"]],
        "market": [],
    },
    {
        "farmer": ["WATER"],
        "hands": [["PLANT", "MELON"], ["PLANT", "MELON"], ["SOUTH"], ["WATER"], ["WATER"]],
        "market": [],
    },
    {
        "farmer": ["EAST"],
        "hands": [["WATER"], ["WATER"], ["SOUTH"], ["SOUTH"], ["EAST"]],
        "market": [],
    },
    {
        "farmer": ["EAST"],
        "hands": [["EAST"], ["EAST"], ["WEST"], ["EAST"], ["SOUTH"]],
        "market": [],
    },
    {
        "farmer": ["EAST"],
        "hands": [["EAST"], ["SOUTH"], ["SOUTH"], ["SOUTH"], ["EAST"]],
        "market": [],
    },
    {
        "farmer": ["SOUTH"],
        "hands": [["SOUTH"], ["EAST"], ["PLANT", "WHEAT"], ["EAST"], ["SOUTH"]],
        "market": [],
    },
    {
        "farmer": ["EAST"],
        "hands": [["EAST"], ["SOUTH"], ["WATER"], ["SOUTH"], ["EAST"]],
        "market": [],
    },
    {
        "farmer": ["PASS"],
        "hands": [["SOUTH"], ["EAST"], ["EAST"], ["EAST"], ["PASS"]],
        "market": [],
    },
    {
        "farmer": ["PASS"],
        "hands": [["EAST"], ["SOUTH"], ["EAST"], ["PASS"], ["PASS"]],
        "market": [],
    },
)


def _predict_tree(tree: list[Any], features: list[float]) -> list[float]:
    node = tree
    while node[0] == "N":
        node = node[3] if features[int(node[1])] <= float(node[2]) else node[4]
    return [float(value) for value in node[1:]]


def _predict_forest(forest: list[list[Any]], features: list[float]) -> list[float]:
    predictions = [_predict_tree(tree, features) for tree in forest]
    if not predictions:
        return [0.0] * len(OUTPUT_NAMES)
    return [sum(row[index] for row in predictions) / len(predictions) for index in range(len(OUTPUT_NAMES))]


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-min(30.0, value))
        return 1.0 / (1.0 + z)
    z = math.exp(max(-30.0, value))
    return z / (1.0 + z)


def _gate_features(obs: Any, day: int) -> list[float]:
    demand = demand_profile(obs)
    milk = float(demand.get("MILK", 0))
    wool = float(demand.get("WOOL", 0))
    berry = float(demand.get("STRAWBERRY", 0))
    return [1.0, day / 29.0, milk / 8.0, wool / 8.0, berry / 8.0, (wool - milk) / 8.0]


def _expert_weights(obs: Any, day: int) -> dict[str, float]:
    prior = {"rank1": 0.50, "rank2": 0.30, "rank3": 0.20}
    if MODEL is None or day < 3:
        return prior
    gate = MODEL.get("gate", {})
    features = _gate_features(obs, day)
    scores = {expert: math.log(weight) for expert, weight in prior.items()}
    for pair_model in gate.get("pair_models", {}).values():
        first = pair_model.get("first")
        second = pair_model.get("second")
        coefficients = pair_model.get("coefficients", [])
        episodes = int(pair_model.get("episodes", 0))
        if first not in scores or second not in scores or len(coefficients) != len(features) or episodes == 0:
            continue
        probability = _sigmoid(sum(float(coef) * value for coef, value in zip(coefficients, features, strict=True)))
        evidence = min(1.0, episodes / 12.0)
        scores[first] += evidence * (probability - 0.5) * 2.0
        scores[second] += evidence * (0.5 - probability) * 2.0

    # The first shops reveal only a fraction of the final regime.  Blend the
    # learned gate in gradually instead of overreacting to one early draw.
    information = min(1.0, max(0.0, (day - 3) / 7.0))
    temperature = 0.42
    maximum = max(scores.values())
    learned = {expert: math.exp((score - maximum) / temperature) for expert, score in scores.items()}
    total = sum(learned.values())
    learned = {expert: value / total for expert, value in learned.items()}
    mixed = {expert: (1.0 - information) * prior[expert] + information * learned[expert] for expert in prior}
    normalizer = sum(mixed.values())
    return {expert: value / normalizer for expert, value in mixed.items()}


def _model_prediction(obs: Any, day: int) -> tuple[dict[str, float], dict[str, float]] | None:
    if MODEL is None or not 3 <= day <= 23:
        return None
    features = encode_observation(obs)
    weights = _expert_weights(obs, day)
    expert_predictions = {
        expert: _predict_forest(MODEL.get("forests", {}).get(expert, []), features) for expert in weights
    }
    if any(not prediction for prediction in expert_predictions.values()):
        return None
    dominant = max(weights, key=weights.get)
    # A mostly hard gate avoids averaging genuinely different policies, while
    # a small blend makes regime boundaries stable from turn to turn.
    blend = {
        expert: 0.82 * float(expert == dominant) + 0.18 * weights[expert] for expert in weights
    }
    prediction = {
        output: sum(blend[expert] * expert_predictions[expert][index] for expert in weights)
        for index, output in enumerate(OUTPUT_NAMES)
    }
    return prediction, weights


def _strategy_targets(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
) -> tuple[dict[str, int], dict[str, int], int, int, dict[str, float]]:
    day = base._as_int(base._get(obs, "day", 0))
    summary = base._farm_summary(farm)
    opponent = base._opponent_summary(opponent_farm)
    demand = base._demand_profile(obs)
    prices = base._get(base._get(obs, "market", {}) or {}, "prices", {}) or {}
    weights = _expert_weights(obs, day)

    if day <= 2:
        wheat = (6, 6, 7)[day]
        crops = {"WHEAT": wheat, "CARROT": 0, "TOMATO": 0, "STRAWBERRY": 0, "MELON": 11}
        animals = {"GOOSE": 0, "COW": 2, "SHEEP": 2}
        return animals, crops, base._target_hands(day), 1, weights

    learned = _model_prediction(obs, day)
    if learned is None:
        animals = base._desired_animals(day, summary["animals"], opponent, demand, prices)
        crops = base._desired_crops(day, summary["crops"], summary["animal_total"], opponent, demand, prices)
        return animals, crops, base._target_hands(day), min(3, summary["unlocked"] + 1), weights

    prediction, weights = learned
    cow = max(summary["animals"]["COW"], min(18, round(prediction["COW"])))
    sheep = max(summary["animals"]["SHEEP"], min(11, round(prediction["SHEEP"])))
    if day >= 21:
        cow = summary["animals"]["COW"]
        sheep = summary["animals"]["SHEEP"]
    animals = {"GOOSE": 0, "COW": cow, "SHEEP": sheep}

    feed_floor = math.ceil((cow + sheep) * 1.15)
    wheat = max(6, feed_floor, min(55, round(prediction["WHEAT"])))
    strawberry = max(0, min(48, round(prediction["STRAWBERRY"])))
    melon = max(0, min(16, round(prediction["MELON"])))
    if day >= 21:
        strawberry = summary["crops"]["STRAWBERRY"]
        melon = summary["crops"]["MELON"]
    crops = {"WHEAT": wheat, "CARROT": 0, "TOMATO": 0, "STRAWBERRY": strawberry, "MELON": melon}
    hands = max(3, min(13, round(prediction["HANDS"])))
    land = max(summary["unlocked"], min(3, round(prediction["LAND"])))
    return animals, crops, hands, land, weights


def _hungarian(cost: list[list[int]]) -> list[int]:
    """Return the selected column for each row of an n<=m cost matrix."""
    rows = len(cost)
    columns = len(cost[0]) if rows else 0
    if not rows or rows > columns:
        return []
    u = [0] * (rows + 1)
    v = [0] * (columns + 1)
    p = [0] * (columns + 1)
    way = [0] * (columns + 1)
    for row in range(1, rows + 1):
        p[0] = row
        column0 = 0
        minimum = [10**12] * (columns + 1)
        used = [False] * (columns + 1)
        while True:
            used[column0] = True
            row0 = p[column0]
            delta = 10**12
            column1 = 0
            for column in range(1, columns + 1):
                if used[column]:
                    continue
                current = cost[row0 - 1][column - 1] - u[row0] - v[column]
                if current < minimum[column]:
                    minimum[column] = current
                    way[column] = column0
                if minimum[column] < delta:
                    delta = minimum[column]
                    column1 = column
            for column in range(columns + 1):
                if used[column]:
                    u[p[column]] += delta
                    v[column] -= delta
                else:
                    minimum[column] -= delta
            column0 = column1
            if p[column0] == 0:
                break
        while True:
            column1 = way[column0]
            p[column0] = p[column1]
            column0 = column1
            if column0 == 0:
                break
    assignment = [-1] * rows
    for column in range(1, columns + 1):
        if p[column]:
            assignment[p[column] - 1] = column - 1
    return assignment


def _assign_tasks(
    positions: list[tuple[int, int]], inventories: list[Any], tasks: list[dict[str, Any]]
) -> list[list[Any]]:
    """Assign equal-priority jobs globally, then emit one route step per unit."""
    actions: list[list[Any]] = [["PASS"] for _ in positions]
    free = set(range(len(positions)))
    by_priority: dict[int, list[dict[str, Any]]] = {}
    for task in tasks:
        by_priority.setdefault(int(task["priority"]), []).append(task)

    impossible = 10**8
    dummy = 10**6
    for priority in sorted(by_priority, reverse=True):
        if not free:
            break
        priority_tasks = by_priority[priority]
        units = sorted(free)
        chosen: list[tuple[int, dict[str, Any]]] = []
        if len(units) <= len(priority_tasks):
            columns: list[dict[str, Any] | None] = [*priority_tasks, *([None] * len(units))]
            cost = []
            for unit in units:
                row = []
                for task in columns:
                    if task is None:
                        row.append(dummy)
                    elif not base._can_do(task, unit, inventories[unit]):
                        row.append(impossible)
                    else:
                        row.append(base._manhattan(positions[unit], task["pos"]) * 100 + unit)
                cost.append(row)
            for row, column in enumerate(_hungarian(cost)):
                if 0 <= column < len(priority_tasks) and cost[row][column] < dummy:
                    chosen.append((units[row], priority_tasks[column]))
        else:
            columns: list[int | None] = [*units, *([None] * len(priority_tasks))]
            cost = []
            for task in priority_tasks:
                row = []
                for unit in columns:
                    if unit is None:
                        row.append(dummy)
                    elif not base._can_do(task, unit, inventories[unit]):
                        row.append(impossible)
                    else:
                        row.append(base._manhattan(positions[unit], task["pos"]) * 100 + unit)
                cost.append(row)
            for row, column in enumerate(_hungarian(cost)):
                if 0 <= column < len(units) and cost[row][column] < dummy:
                    chosen.append((units[column], priority_tasks[row]))

        for unit, task in chosen:
            if unit not in free:
                continue
            actions[unit] = (
                list(task["action"])
                if positions[unit] == task["pos"]
                else base._movement(positions[unit], task["pos"], unit)
            )
            free.remove(unit)
    return actions


def _shape_market(
    orders: list[list[Any]],
    obs: Any,
    farm: Any,
    private: Any,
    target_hands: int,
    target_land: int,
    weights: dict[str, float],
) -> list[list[Any]]:
    day = base._as_int(base._get(obs, "day", 0))
    hands_now = len(base._get(farm, "hands", []) or [])
    filtered: list[list[Any]] = []
    planned_hands = hands_now
    for order in orders:
        if order[0] == "HIRE":
            if planned_hands >= target_hands:
                continue
            planned_hands += 1
        if order[0] == "BUY_LAND" and len(base._get(farm, "unlocked_quadrants", []) or []) >= target_land:
            continue
        filtered.append(list(order))

    shed = base._get(private, "shed", {}) or {}
    pressure = base._inventory_total(shed) >= 72
    cash_hungry = float(base._get(farm, "money", 0) or 0) < (1200 if day <= 12 else 250)
    if day < 27 and not pressure and not cash_hungry:
        batches = {
            "MILK": round(4.6 * weights["rank1"] + 3.8 * weights["rank2"] + 5.8 * weights["rank3"]),
            "WOOL": round(4.5 * weights["rank1"] + 4.1 * weights["rank2"] + 7.8 * weights["rank3"]),
            "STRAWBERRY": round(7.2 * weights["rank1"] + 5.3 * weights["rank2"] + 9.2 * weights["rank3"]),
            "MELON": round(9.1 * weights["rank1"] + 6.8 * weights["rank2"] + 11.0 * weights["rank3"]),
        }
        for order in filtered:
            if order[0] == "SELL" and order[1] in batches:
                order[2] = min(order[2], max(1, batches[order[1]]))
            elif order[0] == "SELL" and order[1] == "FERTILIZER":
                keep = round(6 + 12 * weights["rank2"] + 5 * weights["rank3"])
                order[2] = min(order[2], max(0, base._inventory_count(shed, "FERTILIZER") - keep))
        filtered = [order for order in filtered if len(order) < 3 or order[2] > 0]
    return filtered[:10]


def _safe_opening(obs: Any, farm: Any) -> dict[str, Any] | None:
    day = base._as_int(base._get(obs, "day", 0))
    hour = base._as_int(base._get(obs, "hour", 0))
    if day != 0 or not 0 <= hour < len(OPENING_ACTIONS):
        return None
    expected_hands = 0 if hour == 0 else 5
    if len(base._get(farm, "hands", []) or []) != expected_hands:
        return None
    return copy.deepcopy(OPENING_ACTIONS[hour])


def agent(obs: Any) -> dict[str, Any]:
    """Return a safe field action driven by learned Top-3 macro targets."""
    safe = base._safe_observation(obs)
    if safe is None:
        return {"farmer": ["PASS"], "hands": [], "market": []}
    farm, opponent_farm, private = safe
    opening = _safe_opening(obs, farm)
    if opening is not None:
        return opening

    summary = base._farm_summary(farm)
    animal_targets, crop_targets, target_hands, target_land, weights = _strategy_targets(
        obs, farm, opponent_farm, private
    )
    positions = [tuple(base._get(farm, "farmer", [0, 0]))]
    positions.extend(tuple(position) for position in (base._get(farm, "hands", []) or []))
    raw_inventories = list(base._get(private, "inventories", []) or [])
    inventories = [raw_inventories[index] if index < len(raw_inventories) else {} for index in range(len(positions))]
    tasks = base._field_tasks(
        obs,
        farm,
        private,
        positions,
        inventories,
        summary,
        animal_targets,
        crop_targets,
    )
    actions = _assign_tasks(positions, inventories, tasks)
    market = base._market_plan(obs, farm, private, summary, animal_targets, crop_targets)
    market = _shape_market(market, obs, farm, private, target_hands, target_land, weights)
    return {
        "farmer": actions[0] if actions else ["PASS"],
        "hands": actions[1:],
        "market": market,
    }
