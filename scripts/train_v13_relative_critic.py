"""Train an action-conditioned relative-value critic for Kaggriculture V13.

Rows are complete-episode split before fitting.  The critic sees only runtime
observation features plus a candidate's 24h/72h public portfolio trajectory.
It predicts relative-money changes at 24h, 72h, and final.  A state-only forest
is the calibration baseline; the action-conditioned critic is enabled only if
it improves every validation horizon without reducing final sign accuracy.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v3.feature_schema import FEATURE_NAMES  # noqa: E402
from scripts.train_v3_strategy import train_forest  # noqa: E402
from scripts.train_v12_relative_policy import CACHE_FORMAT, PORTFOLIO  # noqa: E402

FORMAT = "kaggriculture-v13-relative-critic-v1"
TARGET_NAMES = ("relative_delta_24", "relative_delta_72", "final_margin")
TARGET_SCALE = 10_000.0
ITEM_SCALE = {item: (16.0 if item in {"COW", "SHEEP"} else 50.0) for item in PORTFOLIO}
ACTION_FEATURE_NAMES = (
    *(f"h24_delta_{item}" for item in PORTFOLIO),
    *(f"h72_delta_{item}" for item in PORTFOLIO),
    *(f"h24_target_{item}" for item in PORTFOLIO),
    *(f"h72_target_{item}" for item in PORTFOLIO),
)


def action_features(current: dict[str, float], h24: dict[str, float], h72: dict[str, float]) -> list[float]:
    values: list[float] = []
    values.extend((float(h24[item]) - float(current[item])) / ITEM_SCALE[item] for item in PORTFOLIO)
    values.extend((float(h72[item]) - float(current[item])) / ITEM_SCALE[item] for item in PORTFOLIO)
    values.extend(float(h24[item]) / ITEM_SCALE[item] for item in PORTFOLIO)
    values.extend(float(h72[item]) / ITEM_SCALE[item] for item in PORTFOLIO)
    return values


def _predict_tree(tree: list[Any], row: np.ndarray) -> np.ndarray:
    node = tree
    while node[0] == "N":
        node = node[3] if row[int(node[1])] <= float(node[2]) else node[4]
    return np.asarray(node[1:], dtype=np.float64)


def _predict(forest: list[list[Any]], x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    prediction = np.zeros((len(x), len(TARGET_NAMES)), dtype=np.float64)
    deviation = np.zeros_like(prediction)
    for index, row in enumerate(x):
        trees = np.asarray([_predict_tree(tree, row) for tree in forest])
        prediction[index] = np.mean(trees, axis=0)
        deviation[index] = np.std(trees, axis=0)
    return prediction, deviation


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, Any]:
    if not len(actual):
        return {"examples": 0}
    result: dict[str, Any] = {"examples": len(actual), "targets": {}}
    for index, name in enumerate(TARGET_NAMES):
        residual = actual[:, index] - predicted[:, index]
        denominator = float(np.sum((actual[:, index] - np.mean(actual[:, index])) ** 2))
        result["targets"][name] = {
            "mae": round(float(np.mean(np.abs(residual))) * TARGET_SCALE, 4),
            "rmse": round(float(np.sqrt(np.mean(residual**2))) * TARGET_SCALE, 4),
            "r2": round(1.0 - float(np.sum(residual**2)) / max(1e-9, denominator), 6),
        }
    actual_final = actual[:, 2] > 0
    predicted_final = predicted[:, 2] > 0
    result["final_sign_accuracy"] = round(float(np.mean(actual_final == predicted_final)), 6)
    result["composite_mae"] = round(
        float(mean_value := np.mean([result["targets"][name]["mae"] for name in TARGET_NAMES])),
        4,
    )
    assert mean_value >= 0
    return result


def _candidate_profiles(validation_path: Path) -> dict[str, Any]:
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    result: dict[str, Any] = {}
    for key, branch in validation["branches"].items():
        candidates = {
            expert: {
                "support": candidate["support"],
                "profile": candidate["profile"],
            }
            for expert, candidate in branch["candidates"].items()
            if candidate["support"] >= 12
        }
        if candidates:
            result[key] = candidates
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=Path, default=Path("data/training/v12_relative_rows.json"))
    parser.add_argument(
        "--profiles",
        type=Path,
        default=Path("data/analysis/v12_relative_policy_validation.json"),
    )
    parser.add_argument("--trees", type=int, default=30)
    parser.add_argument("--depth", type=int, default=7)
    parser.add_argument("--min-leaf", type=int, default=80)
    parser.add_argument("--seed", type=int, default=20260827)
    parser.add_argument("--output", type=Path, default=Path("agents/v13/relative_critic_model.json"))
    parser.add_argument(
        "--validation-output",
        type=Path,
        default=Path("data/analysis/v13_relative_critic_validation.json"),
    )
    args = parser.parse_args()
    rows_path = args.rows if args.rows.is_absolute() else ROOT / args.rows
    cached = json.loads(rows_path.read_text(encoding="utf-8"))
    if cached.get("format") != CACHE_FORMAT:
        raise ValueError("rebuild the V12 row cache before training V13")
    rows = cached["rows"]

    state_x = np.asarray([row["features"] for row in rows], dtype=np.float64)
    action_x = np.asarray(
        [[*row["features"], *action_features(row["current"], row["h24"], row["h72"])] for row in rows],
        dtype=np.float64,
    )
    y = np.asarray(
        [[float(row[target]) / TARGET_SCALE for target in TARGET_NAMES] for row in rows],
        dtype=np.float64,
    )
    y = np.clip(y, -12.0, 12.0)
    splits = np.asarray([row["split"] for row in rows])
    training = splits == "train"
    weights = np.ones(int(np.sum(training)), dtype=np.float64)

    print("training state-only baseline", flush=True)
    state_forest = train_forest(
        state_x[training],
        y[training],
        weights,
        trees=args.trees,
        depth=args.depth,
        min_leaf=args.min_leaf,
        seed=args.seed,
    )
    state_prediction, _state_deviation = _predict(state_forest, state_x)
    print("training action-conditioned critic", flush=True)
    action_forest = train_forest(
        action_x[training],
        y[training],
        weights,
        trees=args.trees,
        depth=args.depth,
        min_leaf=args.min_leaf,
        seed=args.seed + 101,
    )
    action_prediction, _action_deviation = _predict(action_forest, action_x)
    print("training action-only residual critic", flush=True)
    residual_forest = train_forest(
        action_x[training, len(FEATURE_NAMES) :],
        y[training] - state_prediction[training],
        weights,
        trees=args.trees,
        depth=args.depth,
        min_leaf=args.min_leaf,
        seed=args.seed + 202,
    )
    residual_correction, residual_deviation = _predict(residual_forest, action_x[:, len(FEATURE_NAMES) :])
    residual_prediction = state_prediction + residual_correction
    reports: dict[str, Any] = {}
    for split in ("validation", "test"):
        mask = splits == split
        reports[split] = {
            "state_only": _metrics(y[mask], state_prediction[mask]),
            "action_conditioned": _metrics(y[mask], action_prediction[mask]),
            "residual_action": _metrics(y[mask], residual_prediction[mask]),
        }

    validation_state = reports["validation"]["state_only"]
    validation_action = reports["validation"]["residual_action"]
    enabled = (
        all(
            validation_action["targets"][target]["mae"] <= 0.98 * validation_state["targets"][target]["mae"]
            for target in TARGET_NAMES
        )
        and validation_action["final_sign_accuracy"] >= validation_state["final_sign_accuracy"]
    )
    normalized_deviation = np.mean(residual_deviation, axis=1)
    uncertainty_p90 = float(np.quantile(normalized_deviation[splits == "validation"], 0.9))
    profiles_path = args.profiles if args.profiles.is_absolute() else ROOT / args.profiles
    profiles = _candidate_profiles(profiles_path)
    payload = {
        "format": FORMAT,
        "created_at": datetime.now().astimezone().isoformat(),
        "enabled": bool(enabled),
        "state_feature_names": list(FEATURE_NAMES),
        "action_feature_names": list(ACTION_FEATURE_NAMES),
        "target_names": list(TARGET_NAMES),
        "target_scale": TARGET_SCALE,
        "forests": {"state": state_forest, "residual": residual_forest},
        "uncertainty_p90": round(uncertainty_p90, 6),
        "profiles": profiles,
        "source": cached["source"],
        "validation_summary": reports,
    }
    validation = {
        "objective": "Predict 24h, 72h, and final relative value from observable state plus macro trajectory",
        "selection_uses": "validation versus a separately fitted state-only forest; test is reporting only",
        "episode_split": {
            split: len({row["episode_id"] for row in rows if row["split"] == split})
            for split in ("train", "validation", "test")
        },
        "rows": len(rows),
        "enabled": bool(enabled),
        "reports": reports,
        "uncertainty_p90": round(uncertainty_p90, 6),
        "candidate_branches": len(profiles),
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    validation_output = (
        args.validation_output if args.validation_output.is_absolute() else ROOT / args.validation_output
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    validation_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    validation_output.write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"rows": len(rows), "enabled": enabled, "reports": reports}, indent=2))
    print(f"model: {output}")
    print(f"validation: {validation_output}")


if __name__ == "__main__":
    main()
