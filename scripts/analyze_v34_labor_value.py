"""Relate daily asset labor to public value signals and future outcomes.

The analysis is deliberately macro-level.  It attributes productive actions
and the immediately preceding movement to assets, then asks whether top-team
daily labor allocation is predictable from the day-start public state.  It
also measures whether realized allocation adds held-out information about
24-hour and 72-hour money-gap changes.  Neither result is a causal policy
value estimate, so the produced model is marked analytical-only.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from statistics import mean, median
from typing import Any

import numpy as np
from kaggle_environments.envs.kaggriculture import kaggriculture as game

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v3.feature_schema import BASE_PRICE, demand_profile, farm_summary  # noqa: E402
from scripts.analyze_v33_asset_labor import (  # noqa: E402
    ASSETS,
    MOVEMENT,
    _actions,
    _asset,
    _farm,
    _future_asset,
    _positions,
)
from scripts.train_v12_relative_policy import (  # noqa: E402
    _manifest,
    _observation,
    _replay_path,
    _split,
)

FORMAT = "kaggriculture-v34-daily-labor-value-v1"
ROW_CACHE_FORMAT = "kaggriculture-v34-daily-labor-rows-v4"
SOURCES = {
    "v11": ROOT / "data/submissions/v11_submission_55787906",
    "rank1": ROOT / "data/submissions/leaderboard_rank1_submission_55614463",
    "rank2": ROOT / "data/submissions/leaderboard_rank2_submission_55623460",
    "rank3": ROOT / "data/submissions/leaderboard_rank3_submission_55574890",
}
TOP_SOURCES = {"rank1", "rank2", "rank3"}
DAYS = tuple(range(11, 21))
VALUE_PRODUCTS = ("WHEAT", "FERTILIZER", "MILK", "WOOL")

STATE_FEATURES = (
    "day_scaled",
    "money_log",
    "money_gap_ratio",
    "hands_scaled",
    "utilization",
    "cow_scaled",
    "sheep_scaled",
    "cow_capacity_share",
    "crop_scaled",
    "unwatered_scaled",
    "unfed_scaled",
    "ready_yield_scaled",
    "opp_cow_scaled",
    "opp_sheep_scaled",
    "demand_milk_scaled",
    "demand_wool_scaled",
    "price_wheat_scaled",
    "price_fertilizer_scaled",
    "price_milk_scaled",
    "price_wool_scaled",
    "cow_public_value_share",
)
LABOR_FEATURES = (
    "animal_labor_share",
    "cow_labor_share",
    "cow_labor_excess_vs_value",
    "pass_rate",
    "unattributed_movement_rate",
)
RIDGE_GRID = (0.0, 0.1, 1.0, 10.0, 100.0)


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * quantile
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - position) + ordered[high] * (position - low)


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "median": 0.0, "p10": 0.0, "p90": 0.0}
    return {
        "mean": mean(values),
        "median": median(values),
        "p10": _percentile(values, 0.10),
        "p90": _percentile(values, 0.90),
    }


def _gap(obs: dict[str, Any], seat: int) -> float:
    farms = obs.get("farms") or []
    player = int(obs.get("player", seat))
    if len(farms) < 2 or not 0 <= player < len(farms):
        return 0.0
    return float(farms[player].get("money", 0) or 0) - float(
        farms[1 - player].get("money", 0) or 0
    )


def _money(obs: dict[str, Any], seat: int) -> float:
    farm = _farm(obs, seat)
    return float(farm.get("money", 0) or 0)


def _market_actions(
    replay: dict[str, Any], decision_step: int, seat: int
) -> list[list[Any]]:
    stored = decision_step + 1
    steps = replay.get("steps") or []
    if not 0 <= stored < len(steps):
        return []
    action = steps[stored][seat].get("action") or {}
    value = action.get("market") or []
    if value and isinstance(value[0], str):
        return [list(value)]
    return [list(order) for order in value if isinstance(order, list)]


def _public_value(prices: dict[str, float]) -> dict[str, float]:
    """Return a steady-state gross-margin-per-field-action proxy.

    A fully fed/cared mature Cow yields 3 MILK every two days; a Sheep yields
    4 WOOL every three.  Both consume one WHEAT/day and can make one
    FERTILIZER/day.  The action denominators include FEED, CARE, fertilizer
    collection, and the minimum harvest frequency that avoids capacity loss.
    Capital, establishment, routing, storage, and opponent impact are omitted.
    """
    wheat = prices["WHEAT"]
    fertilizer = prices["FERTILIZER"]
    cow_margin = 1.5 * prices["MILK"] + fertilizer - wheat
    sheep_margin = (4.0 / 3.0) * prices["WOOL"] + fertilizer - wheat
    cow_per_action = cow_margin / 3.25
    sheep_per_action = sheep_margin / (10.0 / 3.0)
    positive_cow = max(0.0, cow_per_action)
    positive_sheep = max(0.0, sheep_per_action)
    total = positive_cow + positive_sheep
    share = positive_cow / total if total > 0 else 0.5
    return {
        "cow_margin_per_day_proxy": cow_margin,
        "sheep_margin_per_day_proxy": sheep_margin,
        "cow_margin_per_field_action_proxy": cow_per_action,
        "sheep_margin_per_field_action_proxy": sheep_per_action,
        "cow_public_value_share": share,
    }


def _day_row(
    replay: dict[str, Any], seat: int, episode_id: str, source: str, day: int
) -> dict[str, Any] | None:
    start_step = day * 24
    stop_step = (day + 1) * 24
    start = _observation(replay, start_step, seat)
    end_24 = _observation(replay, stop_step, seat)
    end_72 = _observation(replay, (day + 3) * 24, seat)
    if start is None or end_24 is None or end_72 is None:
        return None

    productive: Counter[str] = Counter()
    movement: Counter[str] = Counter()
    operations: Counter[str] = Counter()
    unattributed: Counter[str] = Counter()
    sales: Counter[str] = Counter()
    price_values: dict[str, list[float]] = {item: [] for item in VALUE_PRODUCTS}
    town_units: Counter[str] = Counter()
    total_unit_turns = 0

    for step in range(start_step, stop_step):
        obs = _observation(replay, step, seat)
        if obs is None:
            continue
        prices = (obs.get("market") or {}).get("prices") or {}
        for item in VALUE_PRODUCTS:
            price_values[item].append(float(prices.get(item, BASE_PRICE[item]) or 0))
        if step % 4 == 0:
            for shop in (obs.get("town") or {}).get("unlocked_shops", []) or []:
                products = game.SHOPS.get(str(shop), [])
                multiplier = 2 if len(products) == 1 else 1
                for item in products:
                    town_units[item] += multiplier
        if step % 24 == 0:
            town_units.update(game.TOWN_CENTER_PRODUCTS)

        farm = _farm(obs, seat)
        positions = _positions(farm)
        actions = _actions(replay, step, seat)
        total_unit_turns += len(actions)
        for unit, action in enumerate(actions):
            op = str(action[0]) if action else "PASS"
            if op == "PASS":
                unattributed["pass"] += 1
                continue
            if op in MOVEMENT:
                target = _future_asset(replay, seat, step, unit)
                if target is None:
                    unattributed["movement"] += 1
                else:
                    movement[target] += 1
                continue
            target = _asset(action, farm, positions[unit]) if unit < len(positions) else None
            if target is None:
                unattributed["productive"] += 1
            else:
                productive[target] += 1
                operations[f"{target}:{op}"] += 1

        for market_action in _market_actions(replay, step, seat):
            if len(market_action) >= 3 and str(market_action[0]) == "SELL":
                try:
                    sales[str(market_action[1])] += max(0, int(market_action[2]))
                except (TypeError, ValueError):
                    pass

    mean_prices = {
        item: mean(values) if values else float(BASE_PRICE[item])
        for item, values in price_values.items()
    }
    observed_start_prices = (start.get("market") or {}).get("prices") or {}
    start_prices = {
        item: float(observed_start_prices.get(item, BASE_PRICE[item]) or 0)
        for item in VALUE_PRODUCTS
    }
    value = _public_value(start_prices)
    farm = _farm(start, seat)
    farms = start.get("farms") or []
    player = int(start.get("player", seat))
    opponent = farms[1 - player] if len(farms) >= 2 else {}
    own_summary = farm_summary(farm, day)
    opponent_summary = farm_summary(opponent, day)
    demand = demand_profile(start)

    labor = {
        asset: float(productive[asset] + movement[asset]) for asset in ASSETS
    }
    animal_labor = labor["COW"] + labor["SHEEP"]
    attributed_labor = sum(labor.values())
    cow_labor_share = labor["COW"] / animal_labor if animal_labor else 0.5
    animal_count = own_summary["animals"]["COW"] + own_summary["animals"]["SHEEP"]
    cow_capacity_share = (
        own_summary["animals"]["COW"] / animal_count if animal_count else 0.5
    )
    money_start = _money(start, seat)
    gap_start = _gap(start, seat)
    return {
        "source": source,
        "episode_id": episode_id,
        "split": _split(episode_id),
        "day": day,
        "result": "win"
        if float((replay.get("rewards") or [0, 0])[seat] or 0)
        > float((replay.get("rewards") or [0, 0])[1 - seat] or 0)
        else "loss",
        "money_start": money_start,
        "money_delta_24h": _money(end_24, seat) - money_start,
        "money_delta_72h": _money(end_72, seat) - money_start,
        "gap_start": gap_start,
        "gap_delta_24h": _gap(end_24, seat) - gap_start,
        "gap_delta_72h": _gap(end_72, seat) - gap_start,
        "hands": len(farm.get("hands") or []),
        "own_summary": own_summary,
        "opponent_summary": opponent_summary,
        "demand": dict(demand),
        "town_units_today": dict(town_units),
        "start_prices": start_prices,
        "mean_prices": mean_prices,
        "public_value": value,
        "productive": dict(productive),
        "movement": dict(movement),
        "operations": dict(operations),
        "sales": dict(sales),
        "unattributed": dict(unattributed),
        "labor": labor,
        "total_unit_turns": total_unit_turns,
        "animal_labor_share": animal_labor / max(1.0, attributed_labor),
        "cow_labor_share": cow_labor_share,
        "cow_capacity_share": cow_capacity_share,
        "cow_labor_excess_vs_value": cow_labor_share - value["cow_public_value_share"],
        "pass_rate": unattributed["pass"] / max(1, total_unit_turns),
        "unattributed_movement_rate": unattributed["movement"] / max(1, total_unit_turns),
    }


def _features(row: dict[str, Any], include_labor: bool = False) -> list[float]:
    own = row["own_summary"]
    opponent = row["opponent_summary"]
    money = float(row["money_start"])
    gap = float(row["gap_start"])
    crops = sum(float(value) for value in own["crops"].values())
    values = {
        "day_scaled": float(row["day"]) / 30.0,
        "money_log": math.log1p(max(0.0, money)) / 12.0,
        "money_gap_ratio": gap / max(1.0, 2.0 * money - gap),
        "hands_scaled": float(row["hands"]) / 12.0,
        "utilization": float(own["utilization"]),
        "cow_scaled": float(own["animals"]["COW"]) / 12.0,
        "sheep_scaled": float(own["animals"]["SHEEP"]) / 12.0,
        "cow_capacity_share": float(row["cow_capacity_share"]),
        "crop_scaled": crops / 75.0,
        "unwatered_scaled": float(own["unwatered"]) / 75.0,
        "unfed_scaled": float(own["unfed"]) / 24.0,
        "ready_yield_scaled": float(own["ready_yield"]) / 30.0,
        "opp_cow_scaled": float(opponent["animals"]["COW"]) / 12.0,
        "opp_sheep_scaled": float(opponent["animals"]["SHEEP"]) / 12.0,
        "demand_milk_scaled": float(row["demand"].get("MILK", 0)) / 8.0,
        "demand_wool_scaled": float(row["demand"].get("WOOL", 0)) / 16.0,
        **{
            f"price_{item.lower()}_scaled": float(row["start_prices"][item])
            / float(BASE_PRICE[item])
            for item in VALUE_PRODUCTS
        },
        "cow_public_value_share": float(row["public_value"]["cow_public_value_share"]),
        **{name: float(row[name]) for name in LABOR_FEATURES},
    }
    names = STATE_FEATURES + (LABOR_FEATURES if include_labor else ())
    return [values[name] for name in names]


def _metric(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    errors = np.abs(actual - predicted)
    residual = float(np.sum((actual - predicted) ** 2))
    centered = float(np.sum((actual - np.mean(actual)) ** 2))
    return {
        "mae": float(np.mean(errors)),
        "p90_absolute_error": float(np.quantile(errors, 0.90)),
        "r2": 1.0 - residual / centered if centered > 0 else 0.0,
    }


def _ridge_fit(x: np.ndarray, y: np.ndarray, alpha: float) -> dict[str, Any]:
    x_mean = np.mean(x, axis=0)
    x_scale = np.std(x, axis=0)
    x_scale[x_scale < 1e-9] = 1.0
    normalized = (x - x_mean) / x_scale
    y_mean = float(np.mean(y))
    centered = y - y_mean
    gram = normalized.T @ normalized
    penalty = np.eye(gram.shape[0]) * alpha
    coefficient = np.linalg.pinv(gram + penalty) @ normalized.T @ centered
    return {
        "x_mean": x_mean,
        "x_scale": x_scale,
        "y_mean": y_mean,
        "coefficient": coefficient,
    }


def _ridge_predict(model: dict[str, Any], x: np.ndarray) -> np.ndarray:
    normalized = (x - model["x_mean"]) / model["x_scale"]
    return model["y_mean"] + normalized @ model["coefficient"]


def _fit_selected(
    train_rows: list[dict[str, Any]],
    validation_rows: list[dict[str, Any]],
    test_rows: list[dict[str, Any]],
    target: str,
    include_labor: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    x_train = np.asarray([_features(row, include_labor) for row in train_rows])
    y_train = np.asarray([float(row[target]) for row in train_rows])
    x_validation = np.asarray([_features(row, include_labor) for row in validation_rows])
    y_validation = np.asarray([float(row[target]) for row in validation_rows])
    candidates = []
    for alpha in RIDGE_GRID:
        model = _ridge_fit(x_train, y_train, alpha)
        prediction = _ridge_predict(model, x_validation)
        candidates.append((float(np.mean(np.abs(y_validation - prediction))), alpha))
    validation_mae, selected = min(candidates, key=lambda pair: pair[0])

    fit_rows = train_rows + validation_rows
    x_fit = np.asarray([_features(row, include_labor) for row in fit_rows])
    y_fit = np.asarray([float(row[target]) for row in fit_rows])
    model = _ridge_fit(x_fit, y_fit, selected)
    x_test = np.asarray([_features(row, include_labor) for row in test_rows])
    y_test = np.asarray([float(row[target]) for row in test_rows])
    prediction = _ridge_predict(model, x_test)
    baseline = np.full_like(y_test, median(y_fit))
    return model, {
        "target": target,
        "features": list(STATE_FEATURES + (LABOR_FEATURES if include_labor else ())),
        "selected_ridge_alpha": selected,
        "selection_validation_mae": validation_mae,
        "test": _metric(y_test, prediction),
        "constant_median_test": _metric(y_test, baseline),
    }


def _macro_target_model(
    train_rows: list[dict[str, Any]],
    validation_rows: list[dict[str, Any]],
    test_rows: list[dict[str, Any]],
    external_rows: list[dict[str, Any]],
    target: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    model, report = _fit_selected(
        train_rows, validation_rows, test_rows, target, include_labor=False
    )
    x_test = np.asarray([_features(row) for row in test_rows])
    actual_test = np.asarray([float(row[target]) for row in test_rows])
    if target == "cow_labor_share":
        simple_test = np.asarray([float(row["cow_capacity_share"]) for row in test_rows])
        simple_name = "current_capacity_share"
    else:
        phase_medians = {
            phase: median(
                [float(row[target]) for row in train_rows if _phase(row["day"]) == phase]
            )
            for phase in ("11-13", "14-17", "18-20")
        }
        simple_test = np.asarray([phase_medians[_phase(row["day"])] for row in test_rows])
        simple_name = "train_phase_median"
    report["simple_baseline"] = {
        "name": simple_name,
        "test": _metric(actual_test, simple_test),
    }
    external_prediction = _ridge_predict(
        model, np.asarray([_features(row) for row in external_rows])
    )
    external_actual = np.asarray([float(row[target]) for row in external_rows])
    delta = external_actual - external_prediction
    report["v11_external_teacher_gap_actual_minus_prediction"] = _stats(delta.tolist())
    report["v11_external_actual"] = _stats(external_actual.tolist())
    report["v11_external_predicted_top_target"] = _stats(external_prediction.tolist())
    report["v11_external_teacher_gap_by_phase"] = {
        phase: _stats(
            [
                float(row[target]) - float(prediction)
                for row, prediction in zip(external_rows, external_prediction, strict=True)
                if _phase(int(row["day"])) == phase
            ]
        )
        for phase in ("11-13", "14-17", "18-20")
    }
    test_prediction = _ridge_predict(model, x_test)
    report["top_test_by_source"] = {
        source: {
            "rows": sum(row["source"] == source for row in test_rows),
            "actual": _stats(
                [float(row[target]) for row in test_rows if row["source"] == source]
            ),
            "prediction": _stats(
                [
                    float(prediction)
                    for row, prediction in zip(test_rows, test_prediction, strict=True)
                    if row["source"] == source
                ]
            ),
            "error_actual_minus_prediction": _stats(
                [
                    float(row[target]) - float(prediction)
                    for row, prediction in zip(test_rows, test_prediction, strict=True)
                    if row["source"] == source
                ]
            ),
        }
        for source in sorted(TOP_SOURCES)
    }
    report["test_prediction_count"] = len(x_test)
    return model, report


def _phase(day: int) -> str:
    if day <= 13:
        return "11-13"
    if day <= 17:
        return "14-17"
    return "18-20"


def _group_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "rows": len(rows),
        "episodes": len({row["episode_id"] for row in rows}),
        "animal_labor_share": _stats([row["animal_labor_share"] for row in rows]),
        "cow_labor_share": _stats([row["cow_labor_share"] for row in rows]),
        "cow_capacity_share": _stats([row["cow_capacity_share"] for row in rows]),
        "cow_public_value_share": _stats(
            [row["public_value"]["cow_public_value_share"] for row in rows]
        ),
        "cow_labor_excess_vs_value": _stats(
            [row["cow_labor_excess_vs_value"] for row in rows]
        ),
        "pass_rate": _stats([row["pass_rate"] for row in rows]),
        "gap_delta_24h": _stats([row["gap_delta_24h"] for row in rows]),
        "gap_delta_72h": _stats([row["gap_delta_72h"] for row in rows]),
    }


def _operation_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    operations: Counter[str] = Counter()
    movement: Counter[str] = Counter()
    asset_days: Counter[str] = Counter()
    for row in rows:
        operations.update(row["operations"])
        movement.update(row["movement"])
        summary = row["own_summary"]
        for asset in ASSETS:
            group = "animals" if asset in {"COW", "SHEEP"} else "crops"
            asset_days[asset] += int(summary[group][asset])
    result: dict[str, Any] = {}
    for asset in ASSETS:
        denominator = max(1, asset_days[asset])
        by_operation = {
            key.split(":", 1)[1]: count / denominator
            for key, count in sorted(operations.items())
            if key.startswith(f"{asset}:")
        }
        result[asset] = {
            "asset_days": asset_days[asset],
            "productive_per_asset_day": sum(
                count for key, count in operations.items() if key.startswith(f"{asset}:")
            )
            / denominator,
            "movement_per_asset_day": movement[asset] / denominator,
            "by_productive_operation_per_asset_day": by_operation,
        }
    return result


def _ood_report(
    train_rows: list[dict[str, Any]],
    validation_rows: list[dict[str, Any]],
    test_rows: list[dict[str, Any]],
    external_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    raw_train = np.asarray([_features(row) for row in train_rows])
    center = np.mean(raw_train, axis=0)
    scale = np.std(raw_train, axis=0)
    scale[scale < 1e-9] = 1.0
    train = (raw_train - center) / scale
    train_norm = np.sum(train * train, axis=1)

    def distances(rows: list[dict[str, Any]]) -> np.ndarray:
        values = (np.asarray([_features(row) for row in rows]) - center) / scale
        result = []
        for start in range(0, len(values), 256):
            chunk = values[start : start + 256]
            squared = (
                np.sum(chunk * chunk, axis=1)[:, None]
                + train_norm[None, :]
                - 2.0 * chunk @ train.T
            )
            result.extend(np.sqrt(np.maximum(0.0, np.min(squared, axis=1))))
        return np.asarray(result)

    validation = distances(validation_rows)
    threshold = float(np.quantile(validation, 0.95))

    def report(rows: list[dict[str, Any]]) -> dict[str, Any]:
        values = distances(rows)
        return {
            "rows": len(rows),
            "distance": _stats(values.tolist()),
            "ood_fraction": float(np.mean(values > threshold)),
        }

    return {
        "method": "standardized nearest distance to a top-train state",
        "threshold": threshold,
        "threshold_source": "95th percentile of top validation",
        "top_validation": report(validation_rows),
        "top_test": report(test_rows),
        "v11_external": report(external_rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=Path("data/analysis/v34_daily_labor_value.json")
    )
    parser.add_argument(
        "--row-cache",
        type=Path,
        default=Path("data/training/v34_daily_labor_rows.json"),
    )
    parser.add_argument("--rebuild-cache", action="store_true")
    args = parser.parse_args()

    row_cache = args.row_cache if args.row_cache.is_absolute() else ROOT / args.row_cache
    rows: list[dict[str, Any]] = []
    if row_cache.is_file() and not args.rebuild_cache:
        cached = json.loads(row_cache.read_text(encoding="utf-8"))
        if cached.get("format") == ROW_CACHE_FORMAT:
            rows = list(cached.get("rows") or [])
            print(f"loaded row cache: {row_cache}", flush=True)
    if not rows:
        seen: set[tuple[str, str, int]] = set()
        for source, directory in SOURCES.items():
            manifests = _manifest(directory)
            for index, manifest in enumerate(manifests, start=1):
                if index == 1 or index % 25 == 0:
                    print(f"[{source} {index}/{len(manifests)}]", flush=True)
                seat = int(manifest["submission_seat"])
                episode_id = str(manifest["episode_id"])
                key = (source, episode_id, seat)
                if key in seen:
                    continue
                seen.add(key)
                replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
                for day in DAYS:
                    row = _day_row(replay, seat, episode_id, source, day)
                    if row is not None:
                        rows.append(row)
        row_cache.parent.mkdir(parents=True, exist_ok=True)
        row_cache.write_text(
            json.dumps({"format": ROW_CACHE_FORMAT, "rows": rows}, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"wrote row cache: {row_cache}", flush=True)

    top = [row for row in rows if row["source"] in TOP_SOURCES]
    top_train = [row for row in top if row["split"] == "train"]
    top_validation = [row for row in top if row["split"] == "validation"]
    top_test = [row for row in top if row["split"] == "test"]
    v11 = [row for row in rows if row["source"] == "v11"]

    animal_model, animal_report = _macro_target_model(
        top_train,
        top_validation,
        top_test,
        v11,
        "animal_labor_share",
    )
    cow_model, cow_report = _macro_target_model(
        top_train, top_validation, top_test, v11, "cow_labor_share"
    )
    del animal_model, cow_model

    outcome_reports: dict[str, Any] = {}
    for target in ("gap_delta_24h", "gap_delta_72h"):
        _state_model, state_report = _fit_selected(
            top_train, top_validation, top_test, target, include_labor=False
        )
        _labor_model, labor_report = _fit_selected(
            top_train, top_validation, top_test, target, include_labor=True
        )
        del _state_model, _labor_model
        state_mae = state_report["test"]["mae"]
        labor_mae = labor_report["test"]["mae"]
        outcome_reports[target] = {
            "state_only": state_report,
            "state_plus_realized_labor": labor_report,
            "held_out_mae_gain_fraction": (state_mae - labor_mae) / max(1e-9, state_mae),
        }

    payload = {
        "format": FORMAT,
        "runtime_policy_enabled": False,
        "objective": (
            "test whether top daily asset-labor goals are observation-predictable and "
            "whether realized labor contains held-out information about future money gaps"
        ),
        "data": {
            "rows": len(rows),
            "episodes": len({row["episode_id"] for row in rows}),
            "source_rows": dict(Counter(row["source"] for row in rows)),
            "top_split_rows": dict(Counter(row["split"] for row in top)),
            "episode_disjoint_split": True,
            "days": list(DAYS),
        },
        "source_summary": {
            source: _group_summary([row for row in rows if row["source"] == source])
            for source in SOURCES
        },
        "operation_summary": {
            source: _operation_summary([row for row in rows if row["source"] == source])
            for source in SOURCES
        },
        "phase_summary": {
            cohort: {
                phase: _group_summary(
                    [row for row in cohort_rows if _phase(int(row["day"])) == phase]
                )
                for phase in ("11-13", "14-17", "18-20")
            }
            for cohort, cohort_rows in {"top": top, "v11": v11}.items()
        },
        "macro_target_models": {
            "animal_labor_share": animal_report,
            "cow_labor_share": cow_report,
        },
        "future_gap_models": outcome_reports,
        "ood": _ood_report(top_train, top_validation, top_test, v11),
        "interpretation_limits": [
            "realized labor is post-decision and its outcome association is not causal policy value",
            "the public value proxy omits capital, establishment delay, routing, storage, and opponent impact",
            "teacher-target agreement alone does not justify a runtime override",
            "V11 is an external policy distribution, not another draw from the top-team population",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
