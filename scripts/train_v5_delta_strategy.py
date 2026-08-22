"""Train an episode-held-out model of Top-agent short-horizon decisions.

V3 predicts an absolute portfolio one day ahead.  This experiment instead
learns the *change* from the current portfolio and the high-level actions that
produce it over the next 24 turns.  Sampling every six turns produces useful
within-day examples, while splitting by episode prevents adjacent states from
the same match leaking into validation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v3.feature_schema import FEATURE_NAMES, encode_observation, portfolio_label  # noqa: E402
from scripts.train_v3_strategy import (  # noqa: E402
    _episode_weight,
    _observation,
    _predict_tree,
    train_forest,
)

EXPERTS = {
    "rank1": ROOT / "data" / "submissions" / "leaderboard_rank1_submission_55614463",
    "rank2": ROOT / "data" / "submissions" / "leaderboard_rank2_submission_55623460",
    "rank3": ROOT / "data" / "submissions" / "leaderboard_rank3_submission_55574890",
}
PORTFOLIO_NAMES = ("WHEAT", "STRAWBERRY", "MELON", "COW", "SHEEP", "HANDS", "LAND")
INTENT_NAMES = (
    "BUY_COW",
    "BUY_SHEEP",
    "BUY_LAND",
    "PLANT_WHEAT",
    "PLANT_STRAWBERRY",
    "BUILD_PASTURE",
    "DIG",
)
OUTPUT_NAMES = tuple(f"DELTA_{name}" for name in PORTFOLIO_NAMES) + INTENT_NAMES
DELTA_FEATURE_NAMES = (*FEATURE_NAMES, "hour", "hours_left_in_day")


def _manifest_rows(directory: Path) -> list[dict[str, str]]:
    with (directory / "manifest.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows = [row for row in rows if row.get("replay_status") in {"downloaded", "skipped_existing"}]
    return sorted(rows, key=lambda row: hashlib.sha1(row["episode_id"].encode()).hexdigest())


def _own_farm(observation: dict[str, Any], seat: int) -> dict[str, Any] | None:
    farms = observation.get("farms", [])
    player = int(observation.get("player", seat))
    return farms[player] if 0 <= player < len(farms) else None


def _quantity(order: list[Any]) -> int:
    for value in reversed(order[1:]):
        if isinstance(value, int | float):
            return max(1, int(value))
    return 1


def _intent_label(replay: dict[str, Any], seat: int, start: int, horizon: int) -> list[float]:
    counts = {name: 0 for name in INTENT_NAMES}
    steps = replay.get("steps", [])
    # The action chosen from steps[t].observation is persisted at steps[t + 1].action.
    for action_step in range(start + 1, min(len(steps), start + horizon + 1)):
        action = steps[action_step][seat].get("action")
        if not isinstance(action, dict):
            continue
        field_actions = [action.get("farmer"), *(action.get("hands", []) or [])]
        for field_action in field_actions:
            if not isinstance(field_action, list) or not field_action:
                continue
            verb = str(field_action[0])
            if verb == "PLANT" and len(field_action) > 1:
                key = f"PLANT_{field_action[1]}"
                if key in counts:
                    counts[key] += 1
            elif verb in {"BUILD_PASTURE", "DIG"}:
                counts[verb] += 1
        for order in action.get("market", []) or []:
            if not isinstance(order, list) or not order:
                continue
            verb = str(order[0])
            if verb == "BUY_ANIMAL" and len(order) > 1:
                key = f"BUY_{order[1]}"
                if key in counts:
                    counts[key] += _quantity(order)
            elif verb == "BUY_LAND":
                counts["BUY_LAND"] += _quantity(order)
    return [float(counts[name]) for name in INTENT_NAMES]


def collect_dataset(
    expert: str,
    *,
    horizon: int,
    stride: int,
    max_episodes: int | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    directory = EXPERTS[expert]
    rows = _manifest_rows(directory)
    if max_episodes:
        rows = rows[:max_episodes]
    features: list[list[float]] = []
    labels: list[list[float]] = []
    weights: list[float] = []
    episodes: list[int] = []
    for index, row in enumerate(rows, 1):
        replay_path = ROOT / "data" / row["replay_path"]
        with replay_path.open(encoding="utf-8") as handle:
            replay = json.load(handle)
        seat = int(row["submission_seat"])
        episode_id = int(row["episode_id"])
        last_start = min(23 * 24, len(replay.get("steps", [])) - horizon)
        for step in range(3 * 24, last_start, stride):
            current = _observation(replay, step, seat)
            future = _observation(replay, step + horizon, seat)
            if current is None or future is None:
                continue
            current_farm = _own_farm(current, seat)
            future_farm = _own_farm(future, seat)
            if current_farm is None or future_farm is None:
                continue
            current_portfolio = np.asarray(portfolio_label(current_farm), dtype=np.float64)
            future_portfolio = np.asarray(portfolio_label(future_farm), dtype=np.float64)
            hour = int(current.get("hour", step % 24))
            encoded = [*encode_observation(current), hour / 23.0, (23 - hour) / 23.0]
            label = [*(future_portfolio - current_portfolio), *_intent_label(replay, seat, step, horizon)]
            features.append(encoded)
            labels.append([float(value) for value in label])
            weights.append(_episode_weight(row))
            episodes.append(episode_id)
        if index % 25 == 0 or index == len(rows):
            print(f"loaded {expert}: {index}/{len(rows)} episodes", flush=True)
    source = {
        "expert": expert,
        "directory": str(directory.relative_to(ROOT)),
        "episodes": len(rows),
        "horizon_turns": horizon,
        "stride_turns": stride,
    }
    return (
        np.asarray(features, dtype=np.float64),
        np.asarray(labels, dtype=np.float64),
        np.asarray(weights, dtype=np.float64),
        np.asarray(episodes, dtype=np.int64),
        source,
    )


def _predict(forest: list[list[Any]], features: np.ndarray) -> np.ndarray:
    return np.asarray(
        [np.mean([_predict_tree(tree, row) for tree in forest], axis=0) for row in features],
        dtype=np.float64,
    )


def _temporal_baseline(
    train_x: np.ndarray, train_y: np.ndarray, valid_x: np.ndarray
) -> np.ndarray:
    day_index = DELTA_FEATURE_NAMES.index("day")
    hour_index = DELTA_FEATURE_NAMES.index("hour")
    train_keys = np.column_stack(
        (
            np.rint(train_x[:, day_index] * 29).astype(int),
            np.rint(train_x[:, hour_index] * 23).astype(int),
        )
    )
    valid_keys = np.column_stack(
        (
            np.rint(valid_x[:, day_index] * 29).astype(int),
            np.rint(valid_x[:, hour_index] * 23).astype(int),
        )
    )
    overall = np.median(train_y, axis=0)
    by_time = {
        tuple(key): np.median(train_y[np.all(train_keys == key, axis=1)], axis=0)
        for key in np.unique(train_keys, axis=0)
    }
    return np.asarray([by_time.get(tuple(key), overall) for key in valid_keys])


def _mae(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    return {
        name: round(float(np.mean(np.abs(actual[:, index] - predicted[:, index]))), 4)
        for index, name in enumerate(OUTPUT_NAMES)
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expert", choices=tuple(EXPERTS), default="rank1")
    parser.add_argument("--horizon", type=int, default=24)
    parser.add_argument("--stride", type=int, default=6)
    parser.add_argument("--max-episodes", type=int)
    parser.add_argument("--trees", type=int, default=24)
    parser.add_argument("--depth", type=int, default=8)
    parser.add_argument("--min-leaf", type=int, default=36)
    parser.add_argument("--seed", type=int, default=20260822)
    parser.add_argument("--output", type=Path, default=Path("data/models/v5_delta_strategy.json"))
    parser.add_argument("--dataset", type=Path, default=Path("data/training/v5_delta_strategy.npz"))
    args = parser.parse_args()

    x, y, weights, episode, source = collect_dataset(
        args.expert,
        horizon=args.horizon,
        stride=args.stride,
        max_episodes=args.max_episodes,
    )
    if not len(x):
        raise SystemExit("no training examples were collected")
    validation_mask = np.asarray([value % 5 == 0 for value in episode])
    if not np.any(validation_mask) or np.all(validation_mask):
        validation_mask = np.arange(len(x)) % 5 == 0
    train_mask = ~validation_mask
    print(
        f"validation split: train={int(np.sum(train_mask))}, "
        f"validation={int(np.sum(validation_mask))}",
        flush=True,
    )
    validation_forest = train_forest(
        x[train_mask],
        y[train_mask],
        weights[train_mask],
        trees=max(8, args.trees // 2),
        depth=args.depth,
        min_leaf=args.min_leaf,
        seed=args.seed,
    )
    model_prediction = _predict(validation_forest, x[validation_mask])
    temporal_prediction = _temporal_baseline(x[train_mask], y[train_mask], x[validation_mask])
    actual = y[validation_mask]
    metrics = {
        "model_mae": _mae(actual, model_prediction),
        "day_hour_median_mae": _mae(actual, temporal_prediction),
        "zero_change_mae": _mae(actual, np.zeros_like(actual)),
    }
    model_macro = float(np.mean(np.abs(actual - model_prediction)))
    baseline_macro = float(np.mean(np.abs(actual - temporal_prediction)))
    metrics["macro_mae"] = {
        "model": round(model_macro, 5),
        "day_hour_median": round(baseline_macro, 5),
        "model_to_baseline_ratio": round(model_macro / max(1e-9, baseline_macro), 5),
    }

    print(f"training final forest: examples={len(x)}", flush=True)
    forest = train_forest(
        x,
        y,
        weights,
        trees=args.trees,
        depth=args.depth,
        min_leaf=args.min_leaf,
        seed=args.seed + 50,
    )
    payload = {
        "format": "kaggriculture-v5-delta-extra-trees",
        "created_at": datetime.now().astimezone().isoformat(),
        "training_seed": args.seed,
        "feature_names": DELTA_FEATURE_NAMES,
        "output_names": OUTPUT_NAMES,
        "source": source,
        "examples": len(x),
        "validation_episodes": int(len(np.unique(episode[validation_mask]))),
        "hyperparameters": {
            "trees": args.trees,
            "depth": args.depth,
            "min_leaf": args.min_leaf,
        },
        "metrics": metrics,
        "forest": forest,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    dataset = args.dataset if args.dataset.is_absolute() else ROOT / args.dataset
    output.parent.mkdir(parents=True, exist_ok=True)
    dataset.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    np.savez_compressed(
        dataset,
        x=x,
        y=y,
        weights=weights,
        episode=episode,
        feature_names=np.asarray(DELTA_FEATURE_NAMES),
        output_names=np.asarray(OUTPUT_NAMES),
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"dataset: {dataset} ({dataset.stat().st_size} bytes)")
    print(f"model: {output} ({output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
