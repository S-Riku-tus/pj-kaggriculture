"""Train and validate a winner-log herd-growth gate before runtime use.

The gate never chooses an arbitrary herd target. It selects between V11's
deterministic target and the already-owned/current herd, using the 72-hour
winner state only as an offline label. Episode splits from the cached Top-3
corpus are preserved; threshold selection uses validation only.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v3.feature_schema import FEATURE_NAMES  # noqa: E402
from agents.v14 import main as v14  # noqa: E402
from scripts.train_v3_strategy import train_forest  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    TEACHERS,
    _manifest,
    _observation,
    _replay_path,
)

CACHE_FORMAT = "kaggriculture-v12-relative-rows-v2"
ANIMALS = ("COW", "SHEEP")


def _predict_tree(tree: list[Any], row: np.ndarray) -> float:
    node = tree
    while node[0] == "N":
        node = node[3] if row[int(node[1])] <= float(node[2]) else node[4]
    return float(node[1])


def _predict_forest(forest: list[list[Any]], x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    values = np.asarray(
        [[_predict_tree(tree, row) for tree in forest] for row in x],
        dtype=np.float64,
    )
    return np.mean(values, axis=1), np.std(values, axis=1)


def _loss(target: np.ndarray, actual: np.ndarray) -> np.ndarray:
    return np.sum(np.abs(target - actual), axis=1)


def _inventory_total(private: dict[str, Any], item: str) -> float:
    containers = [private.get("shed") or {}, *(private.get("inventories") or [])]
    return sum(max(0.0, float(container.get(item, 0) or 0)) for container in containers)


def _owned_current(rows: list[dict[str, Any]]) -> tuple[np.ndarray, dict[str, Any]]:
    """Recover executable freeze goals, including animals currently carried."""
    episode_paths: dict[str, Path] = {}
    for directory in TEACHERS.values():
        for manifest_row in _manifest(directory):
            episode_paths[str(manifest_row["episode_id"])] = _replay_path(manifest_row)
    row_indices: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        row_indices[str(row["episode_id"])].append(index)
    current = np.zeros((len(rows), len(ANIMALS)), dtype=np.float64)
    carried = np.zeros_like(current)
    missing_episodes: list[str] = []
    for episode_id, indices in row_indices.items():
        replay_path = episode_paths.get(episode_id)
        if replay_path is None or not replay_path.is_file():
            missing_episodes.append(episode_id)
            for index in indices:
                current[index] = [float(rows[index]["current"][animal]) for animal in ANIMALS]
            continue
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
        for index in indices:
            row = rows[index]
            observation = _observation(replay, int(row["day"]) * 24, int(row["seat"]))
            private = (observation or {}).get("private") or {}
            for animal_index, animal in enumerate(ANIMALS):
                placed = float(row["current"][animal])
                carried[index, animal_index] = _inventory_total(private, animal)
                current[index, animal_index] = placed + carried[index, animal_index]
    return current, {
        "definition": "placed herd plus shed and worker inventories",
        "rows_with_carried_animals": int(np.sum(np.sum(carried, axis=1) > 0)),
        "mean_carried_animals": round(float(np.mean(np.sum(carried, axis=1))), 6),
        "max_carried_animals": round(float(np.max(np.sum(carried, axis=1))), 6),
        "missing_episode_count": len(missing_episodes),
    }


def _report(
    mask: np.ndarray,
    current: np.ndarray,
    baseline: np.ndarray,
    actual: np.ndarray,
    prediction: np.ndarray,
    deviation: np.ndarray,
    threshold: float,
    uncertainty_limit: float,
    manifold_eligible: np.ndarray,
) -> dict[str, Any]:
    confident = deviation <= uncertainty_limit
    freeze_choice = (prediction > threshold) & confident & manifold_eligible
    freeze = mask & freeze_choice
    selected = np.where(freeze_choice[:, None], current, baseline)
    baseline_loss = _loss(baseline, actual)
    freeze_loss = _loss(current, actual)
    selected_loss = _loss(selected, actual)
    rows = int(np.sum(mask))
    frozen = int(np.sum(freeze))
    correct_freeze = int(np.sum(freeze & (freeze_loss <= baseline_loss)))
    return {
        "rows": rows,
        "freeze_rows": frozen,
        "freeze_rate": round(frozen / max(1, rows), 6),
        "freeze_precision": round(correct_freeze / max(1, frozen), 6),
        "manifold_eligible_rows": int(np.sum(mask & manifold_eligible)),
        "manifold_eligible_rate": round(float(np.mean(manifold_eligible[mask])), 6),
        "uncertainty_fallback_rows": int(np.sum(mask & manifold_eligible & ~confident)),
        "uncertainty_fallback_rate": round(float(np.mean((manifold_eligible & ~confident)[mask])), 6),
        "mean_absolute_herd_error": {
            "selected_gate": round(float(np.mean(selected_loss[mask])), 6),
            "v11_goal": round(float(np.mean(baseline_loss[mask])), 6),
            "unchanged": round(float(np.mean(freeze_loss[mask])), 6),
        },
        "per_animal_mae": {
            policy: {
                animal: round(float(np.mean(np.abs(values[mask, index] - actual[mask, index]))), 6)
                for index, animal in enumerate(ANIMALS)
            }
            for policy, values in (
                ("selected_gate", selected),
                ("v11_goal", baseline),
                ("unchanged", current),
            )
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=Path, default=Path("data/training/v12_relative_rows.json"))
    parser.add_argument("--trees", type=int, default=36)
    parser.add_argument("--depth", type=int, default=7)
    parser.add_argument("--min-leaf", type=int, default=64)
    parser.add_argument("--seed", type=int, default=20260829)
    parser.add_argument("--output", type=Path, default=Path("agents/v17/herd_gate_model.json"))
    parser.add_argument(
        "--validation-output",
        type=Path,
        default=Path("data/analysis/v17_herd_gate_validation.json"),
    )
    args = parser.parse_args()
    rows_path = args.rows if args.rows.is_absolute() else ROOT / args.rows
    cache = json.loads(rows_path.read_text(encoding="utf-8"))
    if cache.get("format") != CACHE_FORMAT:
        raise ValueError("rebuild the V12 row cache before training V17")
    rows = [row for row in cache["rows"] if bool(row["winner"]) and 6 <= int(row["day"]) <= 19]
    x = np.asarray([row["features"] for row in rows], dtype=np.float64)
    current, current_diagnostics = _owned_current(rows)
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
    manifold_confidence = np.asarray(
        [
            v14._distance_confidence(features.tolist(), int(row["day"]))[0]
            for row, features in zip(rows, x, strict=True)
        ],
        dtype=np.float64,
    )
    manifold_eligible = manifold_confidence >= v14.MIN_CONFIDENCE
    train_mask = split == "train"
    validation_mask = (split == "validation") & recovery
    test_mask = (split == "test") & recovery
    validation_eligible = validation_mask & manifold_eligible
    baseline_loss = _loss(baseline, actual)
    freeze_loss = _loss(current, actual)
    advantage = baseline_loss - freeze_loss
    weights = np.asarray(
        [1.2 if float(row["money_gap_ratio"]) < 0 else 1.0 for row in rows],
        dtype=np.float64,
    )

    # Keep one immutable forest across validation, test reporting, and runtime.
    # Adding validation episodes after threshold selection would make the
    # shipped model differ from the model whose threshold was validated.
    selection_forest = train_forest(
        x[train_mask],
        advantage[train_mask, None],
        weights[train_mask],
        trees=args.trees,
        depth=args.depth,
        min_leaf=args.min_leaf,
        seed=args.seed,
    )
    prediction, deviation = _predict_forest(selection_forest, x)
    uncertainty_limit = float(np.quantile(deviation[validation_eligible], 0.90))
    candidates = sorted(
        {round(float(value), 6) for value in np.quantile(prediction[validation_eligible], np.linspace(0.0, 1.0, 101))}
    )
    scored: list[tuple[float, float, float]] = []
    for threshold in candidates:
        freeze = (prediction > threshold) & (deviation <= uncertainty_limit) & manifold_eligible
        selected = np.where(freeze[:, None], current, baseline)
        loss = float(np.mean(_loss(selected, actual)[validation_mask]))
        freeze_rate = float(np.mean(freeze[validation_eligible]))
        scored.append((loss, freeze_rate, threshold))
    validation_baseline = float(np.mean(baseline_loss[validation_mask]))
    eligible = [row for row in scored if 0.05 <= row[1] <= 0.95 and row[0] < validation_baseline]
    enabled = bool(eligible)
    selected_loss, selected_rate, threshold = min(
        eligible or scored,
        key=lambda row: (row[0], abs(row[1] - 0.5), row[2]),
    )

    reports: dict[str, Any] = {}
    for name, mask in (
        ("validation_recovery", validation_mask),
        ("test_recovery", test_mask),
    ):
        reports[name] = _report(
            mask,
            current,
            baseline,
            actual,
            prediction,
            deviation,
            threshold,
            uncertainty_limit,
            manifold_eligible,
        )
        reports[name]["advantage_prediction_mae"] = round(float(np.mean(np.abs(prediction[mask] - advantage[mask]))), 6)
        reports[name]["uncertainty_p90_observed"] = round(float(np.quantile(deviation[mask], 0.90)), 6)

    model = {
        "format": "kaggriculture-v17-herd-gate-v1",
        "enabled": enabled,
        "selection": "validation recovery rows only; test reporting only",
        "manifold_min_confidence": v14.MIN_CONFIDENCE,
        "feature_names": list(FEATURE_NAMES),
        "animals": list(ANIMALS),
        "freeze_goal": current_diagnostics["definition"],
        "day_window": [6, 19],
        "threshold": threshold,
        "validation_selected_loss": selected_loss,
        "validation_freeze_rate": selected_rate,
        "uncertainty_limit": uncertainty_limit,
        "forest": selection_forest,
        "training": {
            "seed": args.seed,
            "trees": args.trees,
            "depth": args.depth,
            "min_leaf": args.min_leaf,
            "episode_split": {
                name: len({row["episode_id"] for row in rows if row["split"] == name})
                for name in ("train", "validation", "test")
            },
        },
    }
    validation = {
        "objective": "Choose V11 herd goal or current herd for the winner's 72-hour state",
        "current_alternative": current_diagnostics,
        "enabled": enabled,
        "threshold_selected_on": "validation_recovery",
        "threshold": threshold,
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
