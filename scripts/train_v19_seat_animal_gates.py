"""Train seat-aware, animal-specific intraday herd gates for V19."""

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

from scripts.build_v18_intraday_herd_rows import (  # noqa: E402
    ANIMALS,
)
from scripts.build_v18_intraday_herd_rows import (  # noqa: E402
    FORMAT as ROW_FORMAT,
)
from scripts.train_v3_strategy import train_forest  # noqa: E402
from scripts.train_v17_herd_gate import _predict_forest  # noqa: E402
from scripts.train_v18_intraday_herd_gate import (  # noqa: E402
    MIN_PROFILE_CONFIDENCE,
    _profile_confidence,
    _profiles,
)

MODEL_FORMAT = "kaggriculture-v19-seat-animal-gates-v1"


def _report(
    mask: np.ndarray,
    current: np.ndarray,
    baseline: np.ndarray,
    actual: np.ndarray,
    freeze: np.ndarray,
    profile_eligible: np.ndarray,
) -> dict[str, Any]:
    selected = np.where(freeze, current, baseline)
    selected_error = np.abs(selected - actual)
    baseline_error = np.abs(baseline - actual)
    current_error = np.abs(current - actual)
    result: dict[str, Any] = {
        "rows": int(np.sum(mask)),
        "profile_eligible_rate": round(float(np.mean(profile_eligible[mask])), 6),
        "mean_absolute_herd_error": {
            "selected_gates": round(float(np.mean(np.sum(selected_error[mask], axis=1))), 6),
            "v11_goal": round(float(np.mean(np.sum(baseline_error[mask], axis=1))), 6),
            "unchanged": round(float(np.mean(np.sum(current_error[mask], axis=1))), 6),
        },
        "animals": {},
    }
    for index, animal in enumerate(ANIMALS):
        chosen = mask & freeze[:, index]
        correct = chosen & (current_error[:, index] <= baseline_error[:, index])
        result["animals"][animal] = {
            "freeze_rows": int(np.sum(chosen)),
            "freeze_rate": round(float(np.mean(freeze[mask, index])), 6),
            "freeze_precision": round(float(np.sum(correct) / max(1, np.sum(chosen))), 6),
            "mae": {
                "selected_gate": round(float(np.mean(selected_error[mask, index])), 6),
                "v11_goal": round(float(np.mean(baseline_error[mask, index])), 6),
                "unchanged": round(float(np.mean(current_error[mask, index])), 6),
            },
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rows",
        type=Path,
        default=Path("data/training/v18_intraday_herd_rows.json"),
    )
    parser.add_argument("--trees", type=int, default=30)
    parser.add_argument("--depth", type=int, default=7)
    parser.add_argument("--min-leaf", type=int, default=128)
    parser.add_argument("--seed", type=int, default=20260831)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("agents/v19/seat_animal_gate_model.json"),
    )
    parser.add_argument(
        "--validation-output",
        type=Path,
        default=Path("data/analysis/v19_seat_animal_gate_validation.json"),
    )
    args = parser.parse_args()
    rows_path = args.rows if args.rows.is_absolute() else ROOT / args.rows
    cache = json.loads(rows_path.read_text(encoding="utf-8"))
    if cache.get("format") != ROW_FORMAT:
        raise ValueError("rebuild the V18 intraday row cache before training V19")
    rows = cache["rows"]
    feature_names = [*cache["feature_names"], "seat"]
    x = np.asarray([[*row["features"], float(row["seat"])] for row in rows], dtype=np.float64)
    current = np.asarray(
        [[float(row["current_owned"][animal]) for animal in ANIMALS] for row in rows],
        dtype=np.float64,
    )
    baseline = np.asarray(
        [[float(row["baseline"][animal]) for animal in ANIMALS] for row in rows],
        dtype=np.float64,
    )
    actual = np.asarray(
        [[float(row["h72"][animal]) for animal in ANIMALS] for row in rows],
        dtype=np.float64,
    )
    split = np.asarray([row["split"] for row in rows])
    recovery = np.asarray([float(row["money_gap_ratio"]) < 0 for row in rows])
    seats = np.asarray([int(row["seat"]) for row in rows])
    hours = np.asarray([int(row["hour"]) for row in rows])
    final_margin = np.asarray([float(row["final_margin"]) for row in rows])
    train_mask = split == "train"
    validation_mask = (split == "validation") & recovery
    test_mask = (split == "test") & recovery
    profiles = _profiles(rows, x, train_mask, feature_names)
    profile_confidence = _profile_confidence(rows, x, profiles)
    profile_eligible = profile_confidence >= MIN_PROFILE_CONFIDENCE
    validation_eligible = validation_mask & profile_eligible
    baseline_error = np.abs(baseline - actual)
    current_error = np.abs(current - actual)
    advantages = baseline_error - current_error
    weights = np.asarray(
        [1.2 if float(row["money_gap_ratio"]) < 0 else 1.0 for row in rows],
        dtype=np.float64,
    )

    forests: dict[str, list[list[Any]]] = {}
    predictions = np.zeros_like(advantages)
    deviations = np.zeros_like(advantages)
    thresholds: dict[str, float] = {}
    uncertainty_limits: dict[str, float] = {}
    animal_enabled: dict[str, bool] = {}
    selection: dict[str, Any] = {}
    for animal_index, animal in enumerate(ANIMALS):
        print(f"training {animal}", flush=True)
        forest = train_forest(
            x[train_mask],
            advantages[train_mask, animal_index, None],
            weights[train_mask],
            trees=args.trees,
            depth=args.depth,
            min_leaf=args.min_leaf,
            seed=args.seed + animal_index * 100,
        )
        prediction, deviation = _predict_forest(forest, x)
        forests[animal] = forest
        predictions[:, animal_index] = prediction
        deviations[:, animal_index] = deviation
        uncertainty_limit = float(np.quantile(deviation[validation_eligible], 0.90))
        candidates = sorted(
            {
                round(float(value), 6)
                for value in np.quantile(prediction[validation_eligible], np.linspace(0.0, 1.0, 101))
            }
        )
        scored: list[tuple[float, float, float]] = []
        for threshold in candidates:
            freeze = (prediction > threshold) & (deviation <= uncertainty_limit) & profile_eligible
            selected = np.where(freeze, current[:, animal_index], baseline[:, animal_index])
            loss = float(np.mean(np.abs(selected - actual[:, animal_index])[validation_mask]))
            freeze_rate = float(np.mean(freeze[validation_eligible]))
            scored.append((loss, freeze_rate, threshold))
        validation_baseline = float(np.mean(baseline_error[validation_mask, animal_index]))
        required_improvement = max(0.01, validation_baseline * 0.02)
        eligible_scores = [
            score
            for score in scored
            if 0.05 <= score[1] <= 0.95 and score[0] <= validation_baseline - required_improvement
        ]
        enabled = bool(eligible_scores)
        loss, freeze_rate, threshold = min(
            eligible_scores or scored,
            key=lambda score: (score[0], abs(score[1] - 0.5), score[2]),
        )
        animal_enabled[animal] = enabled
        thresholds[animal] = threshold
        uncertainty_limits[animal] = uncertainty_limit
        selection[animal] = {
            "enabled": enabled,
            "validation_selected_mae": loss,
            "validation_v11_mae": validation_baseline,
            "required_improvement": required_improvement,
            "validation_freeze_rate": freeze_rate,
        }

    freeze = np.zeros_like(advantages, dtype=bool)
    for animal_index, animal in enumerate(ANIMALS):
        if animal_enabled[animal]:
            freeze[:, animal_index] = (
                (predictions[:, animal_index] > thresholds[animal])
                & (deviations[:, animal_index] <= uncertainty_limits[animal])
                & profile_eligible
            )
    report_masks: list[tuple[str, np.ndarray]] = [
        ("validation_recovery", validation_mask),
        ("test_recovery", test_mask),
        ("test_recovery_seat_0", test_mask & (seats == 0)),
        ("test_recovery_seat_1", test_mask & (seats == 1)),
    ]
    for hour in sorted(set(hours[test_mask])):
        report_masks.append((f"test_recovery_hour_{hour}", test_mask & (hours == hour)))
    bottom_threshold = float(np.quantile(final_margin[test_mask], 0.25))
    report_masks.append(("test_recovery_bottom_margin_quartile", test_mask & (final_margin <= bottom_threshold)))
    reports = {name: _report(mask, current, baseline, actual, freeze, profile_eligible) for name, mask in report_masks}
    enabled = any(animal_enabled.values())
    model = {
        "format": MODEL_FORMAT,
        "enabled": enabled,
        "selection": "per-animal validation recovery rows only; test reporting only",
        "feature_names": feature_names,
        "animals": list(ANIMALS),
        "animal_enabled": animal_enabled,
        "freeze_goal": "placed herd plus shed and worker inventories",
        "day_window": [6, 19],
        "thresholds": thresholds,
        "uncertainty_limits": uncertainty_limits,
        "profile_min_confidence": MIN_PROFILE_CONFIDENCE,
        "profiles": profiles,
        "forests": forests,
        "training": {
            "seed": args.seed,
            "trees_per_animal": args.trees,
            "depth": args.depth,
            "min_leaf": args.min_leaf,
            "episode_split": cache["split_episodes"],
            "rows": len(rows),
        },
    }
    validation = {
        "objective": "Choose V11 or owned target independently for Cow and Sheep",
        "enabled": enabled,
        "selection": selection,
        "bottom_margin_quartile_threshold": bottom_threshold,
        "reports": reports,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    validation_output = (
        args.validation_output if args.validation_output.is_absolute() else ROOT / args.validation_output
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    validation_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(model, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    validation_output.write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    print(f"model: {output}")
    print(f"validation: {validation_output}")


if __name__ == "__main__":
    main()
