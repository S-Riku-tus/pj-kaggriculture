"""Test whether adversary public state improves prediction of Top-3 supply.

Rows are viewed from the other seat, so ``opponent_*`` describes the Top-3
target and ``own_*`` describes its adversary.  The target-only model sees the
Top agent, market, Town, joint history, and time.  The relative model also sees
the adversary farm and money.  A gain supports opponent-conditioned behavior;
it is not a causal estimate of changing our own portfolio.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_v22_opponent_supply_rows import FORMAT as ROW_FORMAT  # noqa: E402
from scripts.train_v3_strategy import train_forest  # noqa: E402
from scripts.train_v22_opponent_supply import (  # noqa: E402
    _metrics,
    _predict_forest,
    _raw_predictions,
    _threshold,
)

FORMAT = "kaggriculture-v22-top-response-ablation-v1"
TOP_SOURCES = ("rank1", "rank2", "rank3")


def _target_feature(name: str) -> bool:
    if name.startswith("own_") or name == "money_gap_ratio":
        return False
    return True


def _report(
    mask: np.ndarray,
    quantity: np.ndarray,
    prediction: np.ndarray,
    thresholds: np.ndarray,
    output_names: list[str],
) -> dict[str, Any]:
    event, amount = _raw_predictions(prediction, len(output_names))
    return _metrics(mask, quantity, event, amount, thresholds, output_names)


def _improvement(target_only: dict[str, Any], relative: dict[str, Any]) -> dict[str, float]:
    target_macro = target_only["macro"]
    relative_macro = relative["macro"]
    return {
        "event_average_precision_delta": (
            relative_macro["event_average_precision"] - target_macro["event_average_precision"]
        ),
        "event_f1_delta": relative_macro["event_f1"] - target_macro["event_f1"],
        "quantity_mae_reduction_fraction": (
            (target_macro["quantity_mae"] - relative_macro["quantity_mae"])
            / max(1e-12, target_macro["quantity_mae"])
        ),
        "quantity_wape_delta": relative_macro["quantity_wape"] - target_macro["quantity_wape"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rows", type=Path, default=Path("data/training/v22_opponent_supply_rows.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("data/analysis/v22_top_response_ablation.json")
    )
    parser.add_argument("--trees", type=int, default=16)
    parser.add_argument("--seed", type=int, default=20261021)
    args = parser.parse_args()
    rows_path = args.rows if args.rows.is_absolute() else ROOT / args.rows
    cache = json.loads(rows_path.read_text(encoding="utf-8"))
    if cache.get("format") != ROW_FORMAT:
        raise ValueError("rebuild V22 opponent-supply rows before the response ablation")

    all_rows = [row for row in cache["rows"] if row["target_source"] in TOP_SOURCES]
    feature_names = list(cache["feature_names"])
    target_indices = [index for index, name in enumerate(feature_names) if _target_feature(name)]
    items = list(cache["items"])
    horizons = [int(value) for value in cache["horizons"]]
    output_names = [f"h{horizon}_{item}" for horizon in horizons for item in items]
    x_full = np.asarray([row["features"] for row in all_rows], dtype=np.float64)
    x_target = x_full[:, target_indices]
    quantity = np.asarray(
        [
            [float(row["labels"][f"h{horizon}"][item]) for horizon in horizons for item in items]
            for row in all_rows
        ],
        dtype=np.float64,
    )
    target = np.concatenate(((quantity > 0).astype(np.float64), np.log1p(quantity)), axis=1)
    split = np.asarray([row["split"] for row in all_rows])
    source = np.asarray([row["target_source"] for row in all_rows])
    train = split == "train"
    validation = split == "validation"
    test = split == "test"
    weights = np.ones(len(all_rows), dtype=np.float64)
    for name in TOP_SOURCES:
        count = int(np.sum(train & (source == name)))
        if count:
            weights[source == name] = int(np.sum(train)) / (len(TOP_SOURCES) * count)

    predictions: dict[str, np.ndarray] = {}
    thresholds: dict[str, np.ndarray] = {}
    for name, matrix in (("target_only", x_target), ("relative", x_full)):
        print(f"training {name} with {matrix.shape[1]} features", flush=True)
        forest = train_forest(
            matrix[train],
            target[train],
            weights[train],
            trees=args.trees,
            depth=8,
            min_leaf=128,
            seed=args.seed,
        )
        prediction, _deviation = _predict_forest(forest, matrix)
        predictions[name] = prediction
        event, _amount = _raw_predictions(prediction, len(output_names))
        thresholds[name] = np.asarray(
            [
                _threshold(quantity[validation, output] > 0, event[validation, output])
                for output in range(len(output_names))
            ]
        )

    reports: dict[str, Any] = {}
    for split_name, mask in (("validation", validation), ("test", test)):
        reports[split_name] = {
            name: _report(mask, quantity, predictions[name], thresholds[name], output_names)
            for name in ("target_only", "relative")
        }
        reports[split_name]["relative_improvement"] = _improvement(
            reports[split_name]["target_only"], reports[split_name]["relative"]
        )
    for source_name in TOP_SOURCES:
        mask = test & (source == source_name)
        reports[f"test_{source_name}"] = {
            name: _report(mask, quantity, predictions[name], thresholds[name], output_names)
            for name in ("target_only", "relative")
        }
        reports[f"test_{source_name}"]["relative_improvement"] = _improvement(
            reports[f"test_{source_name}"]["target_only"],
            reports[f"test_{source_name}"]["relative"],
        )

    validation_gain = reports["validation"]["relative_improvement"]
    test_gain = reports["test"]["relative_improvement"]
    validation_support = bool(
        validation_gain["quantity_mae_reduction_fraction"] >= 0.01
        and validation_gain["event_average_precision_delta"] >= -0.002
    )
    untouched_test_confirmation = bool(
        validation_support
        and test_gain["quantity_mae_reduction_fraction"] > 0
        and test_gain["event_average_precision_delta"] >= -0.005
    )
    payload = {
        "format": FORMAT,
        "objective": "Does adversary public state add predictive information about Top-3 future supply?",
        "rows": len(all_rows),
        "episode_split": dict(cache["split_episodes"]),
        "split_disjoint": bool(cache["split_disjoint"]),
        "target_sources": {name: int(np.sum(source == name)) for name in TOP_SOURCES},
        "feature_ablation": {
            "target_only": [feature_names[index] for index in target_indices],
            "relative_added": [name for name in feature_names if not _target_feature(name)],
        },
        "predeclared_support_rule": (
            "validation quantity-MAE improves >=1% and AP delta >=-0.002; "
            "test confirms positive MAE gain and AP delta >=-0.005"
        ),
        "validation_support": validation_support,
        "untouched_test_confirmation": untouched_test_confirmation,
        "reports": reports,
        "interpretation": {
            "fact": "all features are public and all rows from one episode stay in one split",
            "inference": "a confirmed gain supports opponent-conditioned Top-3 behavior",
            "limit": "the ablation is predictive, not a causal value estimate for changing our policy",
        },
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "validation_support": validation_support,
                "untouched_test_confirmation": untouched_test_confirmation,
                "validation": validation_gain,
                "test": test_gain,
            },
            indent=2,
        )
    )
    print(f"result: {output}")


if __name__ == "__main__":
    main()
