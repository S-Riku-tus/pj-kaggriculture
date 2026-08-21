"""Distill Top-3 replay strategy into compact, pure-Python inference trees.

The model predicts the expert's one-day-ahead productive portfolio rather than
low-level movement actions.  Episode-level holdout prevents adjacent states of
the same game leaking into validation.  The generated JSON is loaded by V3 and
is small enough to ship inside a Kaggle submission.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v3.feature_schema import (  # noqa: E402
    FEATURE_NAMES,
    OUTPUT_NAMES,
    SCHEMA_VERSION,
    demand_profile,
    encode_observation,
    portfolio_label,
)

DEFAULT_OUTPUT = ROOT / "agents" / "v3" / "strategy_model.json"
EXPERTS = {
    "rank1": ROOT / "data" / "submissions" / "leaderboard_rank1_submission_55614463",
    "rank2": ROOT / "data" / "submissions" / "leaderboard_rank2_submission_55623460",
    "rank3": ROOT / "data" / "submissions" / "leaderboard_rank3_submission_55574890",
}
TEAM_TO_EXPERT = {
    "Ryo Hasegawa": "rank1",
    "Crop Dusta": "rank2",
    "tetsuya": "rank3",
}
GATE_FEATURE_NAMES = ("bias", "day", "milk_demand", "wool_demand", "strawberry_demand", "wool_minus_milk")


def _load_manifest(directory: Path) -> list[dict[str, str]]:
    with (directory / "manifest.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [row for row in rows if row.get("replay_status") in {"downloaded", "skipped_existing"}]


def _stable_episode_order(row: dict[str, str]) -> str:
    return hashlib.sha1(row["episode_id"].encode()).hexdigest()


def _observation(replay: dict[str, Any], step: int, seat: int) -> dict[str, Any] | None:
    steps = replay.get("steps", [])
    if not 0 <= step < len(steps) or not 0 <= seat < len(steps[step]):
        return None
    observation = steps[step][seat].get("observation")
    return observation if isinstance(observation, dict) else None


def _max_hands(replay: dict[str, Any], seat: int, start: int, stop: int) -> int:
    best = 0
    for step in range(start, min(stop, len(replay.get("steps", [])))):
        observation = _observation(replay, step, seat)
        if observation is None:
            continue
        farms = observation.get("farms", [])
        player = int(observation.get("player", seat))
        if 0 <= player < len(farms):
            best = max(best, len(farms[player].get("hands", []) or []))
    return best


def _episode_weight(row: dict[str, str]) -> float:
    own = float(row.get("own_reward") or 0)
    opponent = float(row.get("opponent_reward") or 0)
    margin_term = max(-0.15, min(0.25, (own - opponent) / 50000.0))
    win_term = 0.1 if row.get("result") == "win" else 0.0
    return 1.0 + margin_term + win_term


def _gate_features(obs: dict[str, Any], day: int) -> list[float]:
    demand = demand_profile(obs)
    milk = float(demand.get("MILK", 0))
    wool = float(demand.get("WOOL", 0))
    berry = float(demand.get("STRAWBERRY", 0))
    return [1.0, day / 29.0, milk / 8.0, wool / 8.0, berry / 8.0, (wool - milk) / 8.0]


def collect_datasets(
    max_episodes: int | None,
) -> tuple[dict[str, dict[str, np.ndarray]], list[dict[str, Any]], dict[str, Any]]:
    raw: dict[str, dict[str, list[Any]]] = {
        expert: {"x": [], "y": [], "w": [], "episode": []} for expert in EXPERTS
    }
    direct_games: dict[str, dict[str, Any]] = {}
    source_summary: dict[str, Any] = {}

    for expert, directory in EXPERTS.items():
        rows = sorted(_load_manifest(directory), key=_stable_episode_order)
        if max_episodes:
            rows = rows[:max_episodes]
        source_summary[expert] = {"directory": str(directory.relative_to(ROOT)), "episodes": len(rows)}
        for index, row in enumerate(rows, 1):
            replay_path = ROOT / "data" / row["replay_path"]
            with replay_path.open(encoding="utf-8") as handle:
                replay = json.load(handle)
            seat = int(row["submission_seat"])
            episode_id = row["episode_id"]
            weight = _episode_weight(row)

            for day in range(3, 24):
                current_step = day * 24
                future_step = (day + 1) * 24
                current = _observation(replay, current_step, seat)
                future = _observation(replay, future_step, seat)
                if current is None or future is None:
                    continue
                farms = future.get("farms", [])
                player = int(future.get("player", seat))
                if not 0 <= player < len(farms):
                    continue
                hands = _max_hands(replay, seat, current_step, future_step)
                raw[expert]["x"].append(encode_observation(current))
                raw[expert]["y"].append(portfolio_label(farms[player], hands=hands))
                raw[expert]["w"].append(weight)
                raw[expert]["episode"].append(int(episode_id))

            opponent_expert = TEAM_TO_EXPERT.get(row.get("opponent_team_name", ""))
            if opponent_expert and opponent_expert != expert and episode_id not in direct_games:
                winner = expert if row.get("result") == "win" else opponent_expert
                gate_rows = []
                for day in (8, 11, 14, 17, 20, 23):
                    obs = _observation(replay, day * 24, seat)
                    if obs is not None:
                        gate_rows.append(_gate_features(obs, day))
                direct_games[episode_id] = {
                    "experts": sorted((expert, opponent_expert)),
                    "winner": winner,
                    "rows": gate_rows,
                }

            del replay
            if index % 25 == 0 or index == len(rows):
                print(f"loaded {expert}: {index}/{len(rows)} episodes", flush=True)

    datasets: dict[str, dict[str, np.ndarray]] = {}
    for expert, values in raw.items():
        datasets[expert] = {
            "x": np.asarray(values["x"], dtype=np.float64),
            "y": np.asarray(values["y"], dtype=np.float64),
            "w": np.asarray(values["w"], dtype=np.float64),
            "episode": np.asarray(values["episode"], dtype=np.int64),
        }
    return datasets, list(direct_games.values()), source_summary


def _weighted_mean(y: np.ndarray, weights: np.ndarray) -> np.ndarray:
    return np.average(y, axis=0, weights=weights)


def _weighted_sse(y: np.ndarray, weights: np.ndarray, output_scale: np.ndarray) -> float:
    if len(y) == 0:
        return 0.0
    mean = _weighted_mean(y, weights)
    residual = (y - mean) / output_scale
    return float(np.sum(weights[:, None] * residual * residual))


def _build_tree(
    x: np.ndarray,
    y: np.ndarray,
    weights: np.ndarray,
    indices: np.ndarray,
    *,
    rng: np.random.Generator,
    depth: int,
    max_depth: int,
    min_leaf: int,
    max_features: int,
    output_scale: np.ndarray,
) -> list[Any]:
    leaf_value = _weighted_mean(y[indices], weights[indices])
    if depth >= max_depth or len(indices) < min_leaf * 2:
        return ["L", *[round(float(value), 5) for value in leaf_value]]

    feature_count = x.shape[1]
    candidates = rng.choice(feature_count, size=min(max_features, feature_count), replace=False)
    best: tuple[float, int, float, np.ndarray, np.ndarray] | None = None
    for feature in candidates:
        column = x[indices, feature]
        low = float(np.min(column))
        high = float(np.max(column))
        if high - low < 1e-9:
            continue
        quantiles = rng.uniform(0.12, 0.88, size=4)
        for threshold in np.unique(np.quantile(column, quantiles)):
            left_mask = column <= threshold
            left_count = int(np.sum(left_mask))
            right_count = len(indices) - left_count
            if left_count < min_leaf or right_count < min_leaf:
                continue
            left = indices[left_mask]
            right = indices[~left_mask]
            loss = _weighted_sse(y[left], weights[left], output_scale) + _weighted_sse(
                y[right], weights[right], output_scale
            )
            if best is None or loss < best[0]:
                best = (loss, int(feature), float(threshold), left, right)
    if best is None:
        return ["L", *[round(float(value), 5) for value in leaf_value]]

    _loss, feature, threshold, left, right = best
    return [
        "N",
        feature,
        round(threshold, 8),
        _build_tree(
            x,
            y,
            weights,
            left,
            rng=rng,
            depth=depth + 1,
            max_depth=max_depth,
            min_leaf=min_leaf,
            max_features=max_features,
            output_scale=output_scale,
        ),
        _build_tree(
            x,
            y,
            weights,
            right,
            rng=rng,
            depth=depth + 1,
            max_depth=max_depth,
            min_leaf=min_leaf,
            max_features=max_features,
            output_scale=output_scale,
        ),
    ]


def train_forest(
    x: np.ndarray,
    y: np.ndarray,
    weights: np.ndarray,
    *,
    trees: int,
    depth: int,
    min_leaf: int,
    seed: int,
) -> list[list[Any]]:
    rng = np.random.default_rng(seed)
    output_scale = np.maximum(1.0, np.std(y, axis=0))
    forest = []
    for tree_index in range(trees):
        bootstrap = rng.integers(0, len(x), size=len(x), endpoint=False)
        tree = _build_tree(
            x,
            y,
            weights,
            bootstrap,
            rng=rng,
            depth=0,
            max_depth=depth,
            min_leaf=min_leaf,
            max_features=max(8, int(math.sqrt(x.shape[1]) * 1.8)),
            output_scale=output_scale,
        )
        forest.append(tree)
        if (tree_index + 1) % 6 == 0 or tree_index + 1 == trees:
            print(f"  trained tree {tree_index + 1}/{trees}", flush=True)
    return forest


def _predict_tree(tree: list[Any], row: np.ndarray) -> np.ndarray:
    node = tree
    while node[0] == "N":
        node = node[3] if row[node[1]] <= node[2] else node[4]
    return np.asarray(node[1:], dtype=np.float64)


def predict_forest(forest: list[list[Any]], x: np.ndarray) -> np.ndarray:
    result = np.zeros((len(x), len(OUTPUT_NAMES)), dtype=np.float64)
    for row_index, row in enumerate(x):
        result[row_index] = np.mean([_predict_tree(tree, row) for tree in forest], axis=0)
    return result


def _day_baseline(train_x: np.ndarray, train_y: np.ndarray, valid_x: np.ndarray) -> np.ndarray:
    day_index = FEATURE_NAMES.index("day")
    train_days = np.rint(train_x[:, day_index] * 29).astype(int)
    valid_days = np.rint(valid_x[:, day_index] * 29).astype(int)
    overall = np.median(train_y, axis=0)
    by_day = {day: np.median(train_y[train_days == day], axis=0) for day in np.unique(train_days)}
    return np.asarray([by_day.get(day, overall) for day in valid_days])


def _mae(y: np.ndarray, prediction: np.ndarray) -> dict[str, float]:
    return {
        output: round(float(np.mean(np.abs(y[:, index] - prediction[:, index]))), 4)
        for index, output in enumerate(OUTPUT_NAMES)
    }


def _sigmoid(values: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(values, -30.0, 30.0)))


def _fit_gate_pair(rows: list[tuple[list[float], int, float]]) -> tuple[list[float], float]:
    x = np.asarray([row[0] for row in rows], dtype=np.float64)
    y = np.asarray([row[1] for row in rows], dtype=np.float64)
    weights = np.asarray([row[2] for row in rows], dtype=np.float64)
    coefficients = np.zeros(x.shape[1], dtype=np.float64)
    coefficients[0] = math.log((float(np.sum(weights * y)) + 1.0) / (float(np.sum(weights * (1.0 - y))) + 1.0))
    regularization = np.diag([0.25, 2.0, 2.0, 2.0, 2.0, 2.0])
    for _ in range(40):
        probabilities = _sigmoid(x @ coefficients)
        gradient = x.T @ (weights * (probabilities - y)) + regularization @ coefficients
        curvature = weights * probabilities * (1.0 - probabilities)
        hessian = x.T @ (curvature[:, None] * x) + regularization
        step = np.linalg.solve(hessian + np.eye(len(coefficients)) * 1e-8, gradient)
        coefficients -= step
        if float(np.max(np.abs(step))) < 1e-7:
            break
    accuracy = float(np.average((_sigmoid(x @ coefficients) >= 0.5) == y, weights=weights))
    return [round(float(value), 7) for value in coefficients], accuracy


def train_gate(direct_games: list[dict[str, Any]]) -> dict[str, Any]:
    pair_rows: dict[tuple[str, str], list[tuple[list[float], int, float]]] = defaultdict(list)
    pair_episodes: dict[tuple[str, str], int] = defaultdict(int)
    for game in direct_games:
        first, second = game["experts"]
        pair = (first, second)
        pair_episodes[pair] += 1
        row_weight = 1.0 / max(1, len(game["rows"]))
        label = int(game["winner"] == first)
        for features in game["rows"]:
            pair_rows[pair].append((features, label, row_weight))

    models: dict[str, Any] = {}
    for pair in (("rank1", "rank2"), ("rank1", "rank3"), ("rank2", "rank3")):
        rows = pair_rows.get(pair, [])
        key = f"{pair[0]}_vs_{pair[1]}"
        if rows:
            coefficients, accuracy = _fit_gate_pair(rows)
        else:
            coefficients, accuracy = [0.0] * len(GATE_FEATURE_NAMES), 0.5
        models[key] = {
            "first": pair[0],
            "second": pair[1],
            "coefficients": coefficients,
            "episodes": pair_episodes.get(pair, 0),
            "training_accuracy": round(accuracy, 4),
        }
    return {"feature_names": GATE_FEATURE_NAMES, "pair_models": models}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-episodes", type=int, help="deterministic cap per expert; default uses all replays")
    parser.add_argument("--trees", type=int, default=24)
    parser.add_argument("--depth", type=int, default=7)
    parser.add_argument("--min-leaf", type=int, default=24)
    parser.add_argument("--seed", type=int, default=20260821)
    args = parser.parse_args()

    datasets, direct_games, sources = collect_datasets(args.max_episodes)
    models: dict[str, Any] = {}
    metrics: dict[str, Any] = {}
    for expert_index, (expert, dataset) in enumerate(datasets.items()):
        x = dataset["x"]
        y = dataset["y"]
        weights = dataset["w"]
        episode = dataset["episode"]
        validation_mask = np.asarray([int(value) % 5 == 0 for value in episode])
        if not np.any(validation_mask) or np.all(validation_mask):
            validation_mask = np.arange(len(x)) % 5 == 0
        train_mask = ~validation_mask
        print(f"validating {expert}: train={int(np.sum(train_mask))} validation={int(np.sum(validation_mask))}")
        validation_forest = train_forest(
            x[train_mask],
            y[train_mask],
            weights[train_mask],
            trees=max(8, args.trees // 2),
            depth=args.depth,
            min_leaf=args.min_leaf,
            seed=args.seed + expert_index * 100,
        )
        prediction = predict_forest(validation_forest, x[validation_mask])
        baseline = _day_baseline(x[train_mask], y[train_mask], x[validation_mask])
        metrics[expert] = {
            "examples": len(x),
            "episodes": len(np.unique(episode)),
            "validation_examples": int(np.sum(validation_mask)),
            "model_mae": _mae(y[validation_mask], prediction),
            "day_median_baseline_mae": _mae(y[validation_mask], baseline),
        }
        print(f"training final {expert}: examples={len(x)}")
        models[expert] = train_forest(
            x,
            y,
            weights,
            trees=args.trees,
            depth=args.depth,
            min_leaf=args.min_leaf,
            seed=args.seed + expert_index * 100 + 50,
        )

    gate = train_gate(direct_games)
    payload = {
        "format": "kaggriculture-v3-extra-trees",
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now().astimezone().isoformat(),
        "training_seed": args.seed,
        "feature_names": FEATURE_NAMES,
        "output_names": OUTPUT_NAMES,
        "training_window": {"first_day": 3, "last_day": 23, "target_horizon_days": 1},
        "hyperparameters": {"trees": args.trees, "depth": args.depth, "min_leaf": args.min_leaf},
        "sources": sources,
        "metrics": metrics,
        "gate": gate,
        "forests": models,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"direct games: {len(direct_games)}")
    print(f"model: {output} ({output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
