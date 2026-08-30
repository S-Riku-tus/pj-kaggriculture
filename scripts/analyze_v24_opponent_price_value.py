"""Test the marginal price information in the V22 supply predictor.

This is an intentionally favorable component test: actual future market
inventory is decomposed into an oracle baseline containing every realized
factor except the target seat's effective sales.  Predicted opponent sales are
then added back and converted to price.  Failure here rejects runtime use;
success is necessary but not sufficient because a deployed agent does not
know the oracle baseline or its own future realized flow.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from kaggle_environments.envs.kaggriculture import kaggriculture as game

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_v18_intraday_herd_rows import _episode_sources  # noqa: E402
from scripts.build_v22_opponent_supply_rows import FORMAT as ROW_FORMAT  # noqa: E402
from scripts.train_v12_relative_policy import _observation  # noqa: E402
from scripts.train_v22_opponent_supply import _predict_forest, _raw_predictions  # noqa: E402

FORMAT = "kaggriculture-v24-opponent-price-value-v1"
MODEL_FORMAT = "kaggriculture-v22-opponent-supply-model-v1"


def _effective_sell_prefix(replay: dict[str, Any], items: list[str]) -> dict[int, dict[str, list[int]]]:
    """Attribute units that actually entered market inventory to each seat."""
    steps = replay.get("steps") or []
    result = {seat: {item: [0] * (len(steps) + 1) for item in items} for seat in range(2)}
    for decision_step in range(len(steps)):
        for seat in range(2):
            for item in items:
                result[seat][item][decision_step + 1] = result[seat][item][decision_step]
        recorded = decision_step + 1
        if recorded >= len(steps):
            continue
        observations = [_observation(replay, decision_step, seat) for seat in range(2)]
        if any(obs is None for obs in observations):
            continue
        actions = [steps[recorded][seat].get("action") or {} for seat in range(2)]
        orders = [(action.get("market") or [])[:10] for action in actions]
        stocks = [
            {
                item: int((((obs or {}).get("private") or {}).get("shed") or {}).get(item, 0) or 0)
                for item in items
            }
            for obs in observations
        ]
        market = (observations[0] or {}).get("market") or {}
        initial_inventory = market.get("inventory") or {}
        for item in items:
            inventory = int(initial_inventory.get(item, game.MARKET_PARAMS[item]["I0"]) or 0)
            for order_index in range(10):
                remaining = [0, 0]
                for seat in range(2):
                    if order_index >= len(orders[seat]):
                        continue
                    order = orders[seat][order_index]
                    if (
                        isinstance(order, list)
                        and len(order) >= 3
                        and order[0] == "SELL"
                        and str(order[1]) == item
                    ):
                        remaining[seat] = max(0, int(order[2] or 0))
                while any(remaining[seat] > 0 and stocks[seat][item] > 0 for seat in range(2)):
                    price = game.market_price(item, inventory)
                    committed = False
                    for seat in range(2):
                        if remaining[seat] <= 0 or stocks[seat][item] <= 0:
                            continue
                        remaining[seat] -= 1
                        stocks[seat][item] -= 1
                        committed = True
                        if price > 1:
                            inventory += 1
                            result[seat][item][decision_step + 1] += 1
                    if not committed:
                        break
    return result


def _price(item: str, inventory: float) -> float:
    return float(game.market_price(item, int(round(inventory))))


def _metrics(
    mask: np.ndarray,
    actual: np.ndarray,
    predictions: dict[str, np.ndarray],
    output_names: list[str],
    items: list[str],
) -> dict[str, Any]:
    report: dict[str, Any] = {"rows": int(np.sum(mask)), "outputs": {}}
    for output, name in enumerate(output_names):
        item = items[output % len(items)]
        base = float(game.MARKET_PARAMS[item]["base"])
        truth = actual[mask, output]
        cell = {}
        for method, values in predictions.items():
            errors = np.abs(truth - values[mask, output])
            cell[method] = {
                "mae": float(np.mean(errors)),
                "normalized_mae": float(np.mean(errors / base)),
                "exact_price_rate": float(np.mean(errors == 0)),
            }
        report["outputs"][name] = cell
    for method in predictions:
        report.setdefault("macro", {})[method] = {
            "normalized_mae": float(
                np.mean([value[method]["normalized_mae"] for value in report["outputs"].values()])
            ),
            "exact_price_rate": float(
                np.mean([value[method]["exact_price_rate"] for value in report["outputs"].values()])
            ),
        }
    baseline = report["macro"]["constant_supply"]["normalized_mae"]
    predicted = report["macro"]["predicted_supply"]["normalized_mae"]
    report["predicted_vs_constant"] = {
        "normalized_mae_reduction_fraction": (baseline - predicted) / max(1e-12, baseline),
        "exact_price_rate_delta": (
            report["macro"]["predicted_supply"]["exact_price_rate"]
            - report["macro"]["constant_supply"]["exact_price_rate"]
        ),
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rows", type=Path, default=Path("data/training/v22_opponent_supply_rows.json")
    )
    parser.add_argument(
        "--model", type=Path, default=Path("data/models/v22_opponent_supply_model.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("data/analysis/v24_opponent_price_value.json")
    )
    args = parser.parse_args()
    rows_path = args.rows if args.rows.is_absolute() else ROOT / args.rows
    model_path = args.model if args.model.is_absolute() else ROOT / args.model
    cache = json.loads(rows_path.read_text(encoding="utf-8"))
    model = json.loads(model_path.read_text(encoding="utf-8"))
    if cache.get("format") != ROW_FORMAT or model.get("format") != MODEL_FORMAT:
        raise ValueError("V22 rows/model format mismatch")
    rows = cache["rows"]
    items = list(cache["items"])
    horizons = [int(value) for value in cache["horizons"]]
    output_names = [f"h{horizon}_{item}" for horizon in horizons for item in items]
    x = np.asarray([row["features"] for row in rows], dtype=np.float64)
    raw_prediction, _deviation = _predict_forest(model["forest"], x)
    event, quantity_prediction = _raw_predictions(raw_prediction, len(output_names))
    thresholds = np.asarray(
        [float(model["event_thresholds"][name]) for name in output_names], dtype=np.float64
    )
    predicted_quantity = np.where(event >= thresholds, quantity_prediction, 0.0)
    split = np.asarray([row["split"] for row in rows])
    train = split == "train"
    validation = split == "validation"
    test = split == "test"

    actual_effective = np.zeros_like(predicted_quantity)
    actual_price = np.zeros_like(predicted_quantity)
    oracle_without_target_inventory = np.zeros_like(predicted_quantity)
    row_indices: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        row_indices[str(row["episode_id"])].append(index)
    episode_paths, _sources = _episode_sources()
    for episode_index, episode_id in enumerate(sorted(row_indices), start=1):
        if episode_index == 1 or episode_index % 25 == 0:
            print(f"[{episode_index}/{len(row_indices)}] episode {episode_id}", flush=True)
        replay = json.loads(episode_paths[episode_id].read_text(encoding="utf-8"))
        prefix = _effective_sell_prefix(replay, items)
        step_count = len(replay.get("steps") or [])
        for row_index in row_indices[episode_id]:
            row = rows[row_index]
            start = int(row["day"]) * 24 + int(row["hour"])
            target_seat = int(row["target_seat"])
            own_seat = int(row["own_seat"])
            for horizon_index, horizon in enumerate(horizons):
                stop = min(start + horizon, step_count - 1)
                future = _observation(replay, stop, own_seat)
                if future is None:
                    continue
                future_market = future.get("market") or {}
                for item_index, item in enumerate(items):
                    output = horizon_index * len(items) + item_index
                    effective = prefix[target_seat][item][stop] - prefix[target_seat][item][start]
                    inventory = float((future_market.get("inventory") or {}).get(item, 0) or 0)
                    actual_effective[row_index, output] = effective
                    actual_price[row_index, output] = float(
                        (future_market.get("prices") or {}).get(item, 1) or 1
                    )
                    oracle_without_target_inventory[row_index, output] = inventory - effective

    constant_quantity = np.mean(actual_effective[train], axis=0)
    no_supply_price = np.zeros_like(actual_price)
    constant_price = np.zeros_like(actual_price)
    predicted_price = np.zeros_like(actual_price)
    for output, _name in enumerate(output_names):
        item = items[output % len(items)]
        for row_index in range(len(rows)):
            baseline = oracle_without_target_inventory[row_index, output]
            no_supply_price[row_index, output] = _price(item, baseline)
            constant_price[row_index, output] = _price(item, baseline + constant_quantity[output])
            predicted_price[row_index, output] = _price(
                item, baseline + predicted_quantity[row_index, output]
            )
    predictions = {
        "no_target_supply": no_supply_price,
        "constant_supply": constant_price,
        "predicted_supply": predicted_price,
    }
    reports = {
        "validation": _metrics(validation, actual_price, predictions, output_names, items),
        "test": _metrics(test, actual_price, predictions, output_names, items),
    }
    validation_gain = reports["validation"]["predicted_vs_constant"][
        "normalized_mae_reduction_fraction"
    ]
    test_gain = reports["test"]["predicted_vs_constant"]["normalized_mae_reduction_fraction"]
    validation_support = bool(validation_gain >= 0.01)
    test_confirmation = bool(validation_support and test_gain > 0)
    payload = {
        "format": FORMAT,
        "objective": "marginal future-price information from predicted opponent declared supply",
        "component_test": (
            "oracle future inventory with target effective sales removed; favorable and non-deployable"
        ),
        "rows": len(rows),
        "split_disjoint": bool(cache["split_disjoint"]),
        "validation_support": validation_support,
        "untouched_test_confirmation": test_confirmation,
        "reports": reports,
        "interpretation": {
            "fact": "validation decides support and the episode-disjoint test confirms only",
            "limit": (
                "success is not deployable price accuracy because own future flow, Town interaction, "
                "and other realized factors are supplied by the oracle baseline"
            ),
            "runtime": "disabled regardless of this component result",
        },
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "validation_support": validation_support,
                "untouched_test_confirmation": test_confirmation,
                "validation": reports["validation"]["predicted_vs_constant"],
                "test": reports["test"]["predicted_vs_constant"],
            },
            indent=2,
        )
    )
    print(f"result: {output}")


if __name__ == "__main__":
    main()
