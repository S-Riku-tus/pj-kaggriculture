"""Train V8's confidence-gated, multi-horizon expert strategy atlas.

Rank 1 supplies the coherent primary trajectory.  All three leading teams
supply the observation manifold used for confidence gating.  Labels are
absolute maximum-owned portfolio anchors over the next 24 and 72 turns; they
are deliberately not action deltas, because applying a learned delta on every
turn causes repeated purchases after the agent leaves the expert trajectory.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v8.main import (  # noqa: E402
    POLICY_FEATURE_NAMES,
    POLICY_FORMAT,
    TARGET_NAMES,
    _pasture_count,
    _policy_features,
    base,
    v7,
)
from scripts.train_v3_strategy import train_forest  # noqa: E402

EXPERTS = {
    "rank1": ROOT / "data" / "submissions" / "leaderboard_rank1_submission_55614463",
    "rank2": ROOT / "data" / "submissions" / "leaderboard_rank2_submission_55623460",
    "rank3": ROOT / "data" / "submissions" / "leaderboard_rank3_submission_55574890",
}
PRIMARY_EXPERT = "rank1"
HORIZONS = {"h24": 24, "h72": 72}
PROFILE_FEATURE_NAMES = (
    "money_log",
    "land",
    "utilization",
    "hands",
    "own_crop_WHEAT",
    "own_crop_CARROT",
    "own_crop_TOMATO",
    "own_crop_STRAWBERRY",
    "own_crop_MELON",
    "own_animal_COW",
    "own_animal_SHEEP",
    "own_empty_structures",
    "own_unwatered",
    "own_unfed",
    "money_share",
    "productive_linear",
    "capacity_gap",
    "pastures_linear",
    "wheat_stock_linear",
    "feed_coverage",
)


def _manifest_rows(directory: Path) -> list[dict[str, str]]:
    with (directory / "manifest.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [
        row
        for row in rows
        if row.get("replay_status") in {"downloaded", "skipped_existing"}
        and row.get("opponent_team_name") != row.get("team_name")
    ]


def _stable_order(row: dict[str, str]) -> str:
    return hashlib.sha1(row["episode_id"].encode()).hexdigest()


def _replay_path(row: dict[str, str]) -> Path:
    relative = Path(row["replay_path"])
    direct = ROOT / relative
    return direct if direct.is_file() else ROOT / "data" / relative


def _observation(replay: dict[str, Any], step: int, seat: int) -> dict[str, Any] | None:
    steps = replay.get("steps", [])
    if not 0 <= step < len(steps) or not 0 <= seat < len(steps[step]):
        return None
    observation = steps[step][seat].get("observation")
    return observation if isinstance(observation, dict) else None


def _safe_parts(obs: dict[str, Any], seat: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    farms = obs.get("farms", [])
    player = int(obs.get("player", seat))
    if not 0 <= player < len(farms):
        return None
    opponent = farms[1 - player] if len(farms) > 1 else farms[player]
    private = obs.get("private", {}) or {}
    return farms[player], opponent, private


def _portfolio(obs: dict[str, Any], seat: int) -> np.ndarray | None:
    parts = _safe_parts(obs, seat)
    if parts is None:
        return None
    farm, _opponent, private = parts
    summary = base._farm_summary(farm)
    values = [float(summary["crops"].get(crop, 0)) for crop in TARGET_NAMES[:5]]
    values.extend(float(base._all_animal_count(farm, private, animal)) for animal in ("COW", "SHEEP"))
    values.extend(
        (
            float(len(farm.get("hands", []) or [])),
            float(summary["unlocked"]),
            float(_pasture_count(farm)),
        )
    )
    return np.asarray(values, dtype=np.float64)


def _safe_target(obs: dict[str, Any], seat: int) -> np.ndarray | None:
    parts = _safe_parts(obs, seat)
    if parts is None:
        return None
    farm, opponent, private = parts
    animals, crops, hands, land, _weights, pastures = v7._strategy_targets(obs, farm, opponent, private)
    return np.asarray(
        [
            *(float(crops.get(crop, 0)) for crop in TARGET_NAMES[:5]),
            float(animals["COW"]),
            float(animals["SHEEP"]),
            float(hands),
            float(land),
            float(pastures),
        ],
        dtype=np.float64,
    )


def _episode_weight(row: dict[str, str]) -> float:
    own = max(0.0, float(row.get("own_reward") or 0))
    opponent = max(0.0, float(row.get("opponent_reward") or 0))
    share = own / max(1.0, own + opponent)
    # Outcome information is a gentle preference, not permission to discard
    # difficult-but-valid expert states.
    return min(1.20, max(0.82, 1.0 + 1.5 * (share - 0.5)))


def _validation_episode(episode_id: str) -> bool:
    digest = hashlib.sha1(f"v8-holdout:{episode_id}".encode()).digest()
    return int.from_bytes(digest[:2], "big") % 5 == 0


def collect_dataset(
    *,
    stride: int,
    max_episodes: int | None,
) -> tuple[dict[str, np.ndarray], dict[str, list[list[float]]], dict[str, Any]]:
    primary: dict[str, list[Any]] = {
        "x": [],
        "h24": [],
        "h72": [],
        "safe": [],
        "weight": [],
        "episode": [],
        "validation": [],
    }
    profiles: dict[str, list[list[float]]] = defaultdict(list)
    source: dict[str, Any] = {}
    profile_indices = [POLICY_FEATURE_NAMES.index(name) for name in PROFILE_FEATURE_NAMES]

    for expert, directory in EXPERTS.items():
        rows = sorted(_manifest_rows(directory), key=_stable_order)
        if max_episodes:
            rows = rows[:max_episodes]
        source[expert] = {
            "directory": str(directory.relative_to(ROOT)),
            "episodes": len(rows),
        }
        for episode_index, row in enumerate(rows, 1):
            with _replay_path(row).open(encoding="utf-8") as handle:
                replay = json.load(handle)
            seat = int(row["submission_seat"])
            observations = [_observation(replay, step, seat) for step in range(len(replay.get("steps", [])))]
            portfolios = [_portfolio(obs, seat) if obs is not None else None for obs in observations]
            for step in range(3 * 24, min(27 * 24, len(observations)), stride):
                obs = observations[step]
                if obs is None:
                    continue
                parts = _safe_parts(obs, seat)
                if parts is None:
                    continue
                farm, opponent, private = parts
                features = _policy_features(obs, farm, opponent, private)
                day = int(obs.get("day", step // 24))
                hour = int(obs.get("hour", step % 24))
                key = f"{day}:{min(3, max(0, hour // 6))}"
                profiles[key].append([features[index] for index in profile_indices])

                if expert != PRIMARY_EXPERT:
                    continue
                labels: dict[str, np.ndarray] = {}
                for horizon_name, horizon in HORIZONS.items():
                    stop = min(len(portfolios), step + horizon + 1)
                    future = [value for value in portfolios[step:stop] if value is not None]
                    if not future:
                        break
                    labels[horizon_name] = np.max(np.vstack(future), axis=0)
                if len(labels) != len(HORIZONS):
                    continue
                safe = _safe_target(obs, seat)
                if safe is None:
                    continue
                primary["x"].append(features)
                primary["h24"].append(labels["h24"])
                primary["h72"].append(labels["h72"])
                primary["safe"].append(safe)
                primary["weight"].append(_episode_weight(row))
                primary["episode"].append(int(row["episode_id"]))
                primary["validation"].append(_validation_episode(row["episode_id"]))

            if episode_index % 25 == 0 or episode_index == len(rows):
                print(f"loaded {expert}: {episode_index}/{len(rows)}", flush=True)
            del replay, observations, portfolios

    arrays = {
        "x": np.asarray(primary["x"], dtype=np.float64),
        "h24": np.asarray(primary["h24"], dtype=np.float64),
        "h72": np.asarray(primary["h72"], dtype=np.float64),
        "safe": np.asarray(primary["safe"], dtype=np.float64),
        "weight": np.asarray(primary["weight"], dtype=np.float64),
        "episode": np.asarray(primary["episode"], dtype=np.int64),
        "validation": np.asarray(primary["validation"], dtype=np.bool_),
    }
    source["stride_turns"] = stride
    source["primary_expert"] = PRIMARY_EXPERT
    source["examples"] = len(arrays["x"])
    source["profile_examples"] = sum(len(rows) for rows in profiles.values())
    return arrays, profiles, source


def _predict_rows(forest: list[list[Any]], x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    means: list[np.ndarray] = []
    deviations: list[np.ndarray] = []
    for row in x:
        tree_rows = np.asarray([_predict_tree(tree, row) for tree in forest], dtype=np.float64)
        means.append(np.mean(tree_rows, axis=0))
        deviations.append(np.std(tree_rows, axis=0))
    return np.asarray(means), np.asarray(deviations)


def _predict_tree(tree: list[Any], row: np.ndarray) -> list[float]:
    node = tree
    while node[0] == "N":
        node = node[3] if row[int(node[1])] <= float(node[2]) else node[4]
    return [float(value) for value in node[1:]]


def _time_baseline(train_x: np.ndarray, train_y: np.ndarray, valid_x: np.ndarray) -> np.ndarray:
    day_index = POLICY_FEATURE_NAMES.index("day")
    block_index = POLICY_FEATURE_NAMES.index("hour_block")
    train_keys = np.column_stack(
        (
            np.rint(train_x[:, day_index] * 29).astype(int),
            np.rint(train_x[:, block_index] * 3).astype(int),
        )
    )
    valid_keys = np.column_stack(
        (
            np.rint(valid_x[:, day_index] * 29).astype(int),
            np.rint(valid_x[:, block_index] * 3).astype(int),
        )
    )
    overall = np.median(train_y, axis=0)
    by_time = {
        tuple(key): np.median(train_y[np.all(train_keys == key, axis=1)], axis=0)
        for key in np.unique(train_keys, axis=0)
    }
    return np.asarray([by_time.get(tuple(key), overall) for key in valid_keys])


def _metrics(actual: np.ndarray, prediction: np.ndarray) -> dict[str, Any]:
    errors = np.abs(actual - prediction)
    per_target = {
        name: round(float(np.mean(errors[:, index])), 4)
        for index, name in enumerate(TARGET_NAMES)
    }
    scales = np.asarray([30, 12, 8, 30, 11, 10, 8, 12, 3, 14], dtype=np.float64)
    importance = np.asarray([1.0, 1.6, 1.8, 1.6, 1.4, 2.2, 2.2, 1.6, 4.0, 2.0])
    weighted = float(np.mean((errors / scales) * importance))
    return {"mae": per_target, "critical_normalized_mae": round(weighted, 6)}


def _percentile(values: np.ndarray, probability: float) -> float:
    return float(np.quantile(values, probability)) if len(values) else 0.0


def _build_profiles(profile_rows: dict[str, list[list[float]]]) -> dict[str, Any]:
    feature_indices = [POLICY_FEATURE_NAMES.index(name) for name in PROFILE_FEATURE_NAMES]
    result: dict[str, Any] = {}
    for key, rows in sorted(profile_rows.items()):
        matrix = np.asarray(rows, dtype=np.float64)
        center = np.median(matrix, axis=0)
        mad = np.median(np.abs(matrix - center), axis=0) * 1.4826
        iqr = (np.quantile(matrix, 0.75, axis=0) - np.quantile(matrix, 0.25, axis=0)) / 1.349
        scale = np.maximum(np.maximum(mad, iqr), 0.035)
        z = np.minimum(8.0, np.abs(matrix - center) / scale)
        distances = np.sqrt(np.mean(z * z, axis=1))
        result[key] = {
            "examples": len(rows),
            "feature_indices": feature_indices,
            "center": [round(float(value), 7) for value in center],
            "scale": [round(float(value), 7) for value in scale],
            "distance_p50": round(_percentile(distances, 0.50), 6),
            "distance_p90": round(_percentile(distances, 0.90), 6),
            "distance_p99": round(_percentile(distances, 0.99), 6),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stride", type=int, default=6)
    parser.add_argument("--max-episodes", type=int)
    parser.add_argument("--trees", type=int, default=28)
    parser.add_argument("--depth", type=int, default=9)
    parser.add_argument("--min-leaf", type=int, default=36)
    parser.add_argument("--seed", type=int, default=20260824)
    parser.add_argument("--output", type=Path, default=Path("agents/v8/expert_policy_model.json"))
    parser.add_argument("--dataset", type=Path, default=Path("data/training/v8_expert_policy.npz"))
    parser.add_argument("--report", type=Path, default=Path("data/analysis/v8_expert_policy_validation.json"))
    args = parser.parse_args()

    arrays, profile_rows, source = collect_dataset(stride=args.stride, max_episodes=args.max_episodes)
    if not len(arrays["x"]):
        raise SystemExit("no expert examples collected")
    validation = arrays["validation"]
    if not np.any(validation) or np.all(validation):
        validation = np.arange(len(arrays["x"])) % 5 == 0
    training = ~validation
    print(
        f"split: train={int(np.sum(training))}, validation={int(np.sum(validation))}, "
        f"episodes={len(np.unique(arrays['episode']))}",
        flush=True,
    )

    report: dict[str, Any] = {
        "objective": "held-out expert trajectory fidelity; no old-agent win-rate selection",
        "source": source,
        "validation_examples": int(np.sum(validation)),
        "validation_episodes": int(len(np.unique(arrays["episode"][validation]))),
        "horizons": {},
    }
    validation_forests: dict[str, list[list[Any]]] = {}
    uncertainty_p90: dict[str, float] = {}
    target_scales = np.maximum(1.0, np.std(arrays["h72"][training], axis=0))
    for horizon_index, horizon_name in enumerate(HORIZONS):
        print(f"validation forest: {horizon_name}", flush=True)
        forest = train_forest(
            arrays["x"][training],
            arrays[horizon_name][training],
            arrays["weight"][training],
            trees=max(12, args.trees // 2),
            depth=args.depth,
            min_leaf=args.min_leaf,
            seed=args.seed + horizon_index * 100,
        )
        validation_forests[horizon_name] = forest
        prediction, deviation = _predict_rows(forest, arrays["x"][validation])
        temporal = _time_baseline(
            arrays["x"][training], arrays[horizon_name][training], arrays["x"][validation]
        )
        actual = arrays[horizon_name][validation]
        normalized_uncertainty = np.mean(deviation / target_scales, axis=1)
        uncertainty_p90[horizon_name] = _percentile(normalized_uncertainty, 0.90)
        report["horizons"][horizon_name] = {
            "model": _metrics(actual, prediction),
            "day_block_median": _metrics(actual, temporal),
            "v7_safe_targets": _metrics(actual, arrays["safe"][validation]),
            "unchanged_state_proxy": None,
            "model_improvement_vs_v7": round(
                1.0
                - _metrics(actual, prediction)["critical_normalized_mae"]
                / max(1e-9, _metrics(actual, arrays["safe"][validation])["critical_normalized_mae"]),
                6,
            ),
            "uncertainty_p90": round(uncertainty_p90[horizon_name], 6),
        }

    forests: dict[str, list[list[Any]]] = {}
    for horizon_index, horizon_name in enumerate(HORIZONS):
        print(f"final forest: {horizon_name}", flush=True)
        forests[horizon_name] = train_forest(
            arrays["x"],
            arrays[horizon_name],
            arrays["weight"],
            trees=args.trees,
            depth=args.depth,
            min_leaf=args.min_leaf,
            seed=args.seed + 500 + horizon_index * 100,
        )

    payload = {
        "format": POLICY_FORMAT,
        "created_at": datetime.now().astimezone().isoformat(),
        "training_seed": args.seed,
        "feature_names": POLICY_FEATURE_NAMES,
        "target_names": TARGET_NAMES,
        "horizons": HORIZONS,
        "source": source,
        "hyperparameters": {
            "trees": args.trees,
            "depth": args.depth,
            "min_leaf": args.min_leaf,
            "stride": args.stride,
        },
        "target_scales": [round(float(value), 6) for value in target_scales],
        "uncertainty_p90": {key: round(value, 6) for key, value in uncertainty_p90.items()},
        "profiles": _build_profiles(profile_rows),
        "validation": report,
        "forests": forests,
    }

    output = args.output if args.output.is_absolute() else ROOT / args.output
    dataset = args.dataset if args.dataset.is_absolute() else ROOT / args.dataset
    report_path = args.report if args.report.is_absolute() else ROOT / args.report
    output.parent.mkdir(parents=True, exist_ok=True)
    dataset.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    np.savez_compressed(
        dataset,
        **arrays,
        feature_names=np.asarray(POLICY_FEATURE_NAMES),
        target_names=np.asarray(TARGET_NAMES),
    )
    print(json.dumps(report["horizons"], ensure_ascii=False, indent=2))
    print(f"model: {output} ({output.stat().st_size} bytes)")
    print(f"dataset: {dataset} ({dataset.stat().st_size} bytes)")
    print(f"report: {report_path}")


if __name__ == "__main__":
    main()
