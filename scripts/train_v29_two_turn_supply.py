"""Train and hold out a public two-turn opponent-sale forecaster."""

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

from scripts.build_v29_two_turn_supply_rows import FORMAT as ROW_FORMAT  # noqa: E402
from scripts.train_v3_strategy import train_forest  # noqa: E402
from scripts.train_v22_opponent_supply import (  # noqa: E402
    _candidate_score,
    _metrics,
    _predict_forest,
    _raw_predictions,
    _threshold,
)

MODEL_FORMAT = "kaggriculture-v29-two-turn-supply-model-v1"


def _is_history(name: str) -> bool:
    return (
        name.startswith("own_money_delta_")
        or name.startswith("opponent_money_delta_")
        or name.startswith("joint_market_flow_")
        or name.startswith("opponent_asset_delta_")
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rows", type=Path, default=Path("data/training/v29_two_turn_supply_rows.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("data/models/v29_two_turn_supply_model.json")
    )
    parser.add_argument(
        "--validation-output",
        type=Path,
        default=Path("data/analysis/v29_two_turn_supply_validation.json"),
    )
    parser.add_argument("--trees", type=int, default=18)
    parser.add_argument("--seed", type=int, default=20261101)
    args = parser.parse_args()
    rows_path = args.rows if args.rows.is_absolute() else ROOT / args.rows
    cache = json.loads(rows_path.read_text(encoding="utf-8"))
    if cache.get("format") != ROW_FORMAT:
        raise ValueError("rebuild V29 two-turn rows before training")
    rows = cache["rows"]
    all_feature_names = list(cache["feature_names"])
    items = list(cache["items"])
    output_names = [f"h2_{item}" for item in items]
    all_x = np.asarray([row["features"] for row in rows], dtype=np.float64)
    quantity = np.asarray(
        [[float(row["labels"][item]) for item in items] for row in rows],
        dtype=np.float64,
    )
    event = (quantity > 0).astype(np.float64)
    target = np.concatenate((event, np.log1p(quantity)), axis=1)
    split = np.asarray([row["split"] for row in rows])
    train_mask = split == "train"
    validation_mask = split == "validation"
    test_mask = split == "test"
    weights = np.ones(len(rows), dtype=np.float64)
    stateless = [index for index, name in enumerate(all_feature_names) if not _is_history(name)]
    candidates = (
        {"features": "stateless", "indices": stateless, "depth": 6, "min_leaf": 128},
        {"features": "full_history", "indices": list(range(len(all_feature_names))), "depth": 6, "min_leaf": 128},
        {"features": "full_history", "indices": list(range(len(all_feature_names))), "depth": 8, "min_leaf": 64},
    )
    forests: list[list[list[Any]]] = []
    predictions: list[np.ndarray] = []
    deviations: list[np.ndarray] = []
    candidate_reports: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        print(
            f"training candidate {index + 1}/{len(candidates)}: "
            f"{candidate['features']} depth={candidate['depth']} leaf={candidate['min_leaf']}",
            flush=True,
        )
        indices = candidate["indices"]
        x = all_x[:, indices]
        forest = train_forest(
            x[train_mask],
            target[train_mask],
            weights[train_mask],
            trees=args.trees,
            depth=int(candidate["depth"]),
            min_leaf=int(candidate["min_leaf"]),
            seed=args.seed + index * 100,
        )
        prediction, deviation = _predict_forest(forest, x)
        score = _candidate_score(validation_mask, quantity, prediction, len(output_names))
        candidate_reports.append(
            {
                "features": candidate["features"],
                "feature_count": len(indices),
                "depth": candidate["depth"],
                "min_leaf": candidate["min_leaf"],
                "validation_score": score,
            }
        )
        forests.append(forest)
        predictions.append(prediction)
        deviations.append(deviation)
    selected_index = min(
        range(len(candidates)), key=lambda index: candidate_reports[index]["validation_score"]
    )
    selected = candidates[selected_index]
    prediction = predictions[selected_index]
    deviation = deviations[selected_index]
    forest = forests[selected_index]
    event_score, quantity_score = _raw_predictions(prediction, len(output_names))
    thresholds = np.asarray(
        [
            _threshold(quantity[validation_mask, index] > 0, event_score[validation_mask, index])
            for index in range(len(output_names))
        ]
    )
    uncertainty_limit = float(np.quantile(np.mean(deviation[validation_mask], axis=1), 0.90))
    uncertainty = np.mean(deviation, axis=1)
    reports = {
        "validation": _metrics(
            validation_mask,
            quantity,
            event_score,
            quantity_score,
            thresholds,
            output_names,
        ),
        "test": _metrics(
            test_mask,
            quantity,
            event_score,
            quantity_score,
            thresholds,
            output_names,
        ),
        "test_confident_90pct_validation_limit": _metrics(
            test_mask & (uncertainty <= uncertainty_limit),
            quantity,
            event_score,
            quantity_score,
            thresholds,
            output_names,
        ),
    }
    selected_indices = list(selected["indices"])
    model = {
        "format": MODEL_FORMAT,
        "analytical_only": True,
        "runtime_enabled": False,
        "feature_mode": selected["features"],
        "feature_names": [all_feature_names[index] for index in selected_indices],
        "output_names": output_names,
        "event_thresholds": thresholds.tolist(),
        "uncertainty_limit": uncertainty_limit,
        "selected_hyperparameters": candidate_reports[selected_index],
        "forest": forest,
        "training": {
            "rows": len(rows),
            "train_rows": int(np.sum(train_mask)),
            "validation_rows": int(np.sum(validation_mask)),
            "test_rows": int(np.sum(test_mask)),
            "episode_split": cache["split_episodes"],
            "split_disjoint": cache["split_disjoint"],
        },
    }
    validation = {
        "format": "kaggriculture-v29-two-turn-supply-validation-v1",
        "objective": "public prediction of opponent current+next-turn SELL quantity",
        "candidate_reports": candidate_reports,
        "selected_index": selected_index,
        "reports": reports,
        "selection_note": "hyperparameters use validation episodes; test is untouched",
        "runtime": "analytical only until external V11 and closed-loop value pass",
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    validation_output = (
        args.validation_output
        if args.validation_output.is_absolute()
        else ROOT / args.validation_output
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    validation_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(model, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    validation_output.write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"selected": candidate_reports[selected_index], "reports": reports}, ensure_ascii=False, indent=2))
    print(f"model: {output}")
    print(f"validation: {validation_output}")


if __name__ == "__main__":
    main()
