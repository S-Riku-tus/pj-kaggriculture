"""Validate context-conditioned daily role portfolios on held-out top logs."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v14 import main as v14  # noqa: E402
from scripts.analyze_v34_labor_value import SOURCES  # noqa: E402
from scripts.analyze_v56_daily_roles import DAYS, _day_row  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    _manifest,
    _observation,
    _replay_path,
    _split,
)

FORMAT = "kaggriculture-v57-role-portfolio-validation-v1"
MODEL_FORMAT = "kaggriculture-v58-role-portfolio-knn-v1"
TEACHERS = ("rank1", "rank2", "rank3")
FEATURES = (
    "day",
    "hands",
    "own_animals",
    "own_crops",
    "own_productive",
    "own_money",
    "opponent_animals",
    "opponent_crops",
    "opponent_productive",
    "money_gap_ratio",
    "milk_demand",
    "wool_demand",
    "wheat_demand",
    "strawberry_demand",
    "unlocked_shops",
)
LABELS = (
    "animal_worker_fraction",
    "crop_worker_fraction",
    "logistics_worker_fraction",
    "productive_per_hand",
    "move_per_productive",
    "pass_per_hand",
    "same_role_transition_rate",
    "future24_productive",
    "future72_productive",
    "future24_animals",
    "future72_animals",
)


def _context(obs: dict[str, Any], seat: int) -> dict[str, float]:
    farms = obs.get("farms") or []
    farm = farms[seat]
    opponent = farms[1 - seat] if len(farms) > 1 else farm
    own = v14.base._farm_summary(farm)
    other = v14.base._farm_summary(opponent)
    demand = v14.base._demand_profile(obs)
    own_money = float(farm.get("money", 0) or 0)
    other_money = float(opponent.get("money", 0) or 0)
    return {
        "day": float(obs.get("day", 0) or 0),
        "hands": float(len(farm.get("hands") or [])),
        "own_animals": float(own["animal_total"]),
        "own_crops": float(sum(own["crops"].values())),
        "own_productive": float(own["productive"]),
        "own_money": own_money,
        "opponent_animals": float(other["animal_total"]),
        "opponent_crops": float(sum(other["crops"].values())),
        "opponent_productive": float(other["productive"]),
        "money_gap_ratio": (own_money - other_money) / max(1.0, own_money + other_money),
        "milk_demand": float(demand.get("MILK", 0)),
        "wool_demand": float(demand.get("WOOL", 0)),
        "wheat_demand": float(demand.get("WHEAT", 0)),
        "strawberry_demand": float(demand.get("STRAWBERRY", 0)),
        "unlocked_shops": float(len((obs.get("town") or {}).get("unlocked_shops") or [])),
    }


def _future_summary(replay: dict[str, Any], seat: int, day: int) -> tuple[float, float]:
    obs = _observation(replay, min(719, day * 24), seat)
    if obs is None:
        return 0.0, 0.0
    farms = obs.get("farms") or []
    if seat >= len(farms):
        return 0.0, 0.0
    summary = v14.base._farm_summary(farms[seat])
    return float(summary["productive"]), float(summary["animal_total"])


def _row(
    replay: dict[str, Any], manifest: dict[str, str], source: str, day: int
) -> dict[str, Any] | None:
    seat = int(manifest["submission_seat"])
    obs = _observation(replay, day * 24, seat)
    role = _day_row(replay, manifest, source, day)
    if obs is None or role is None:
        return None
    hands = max(1.0, role["metrics"]["hands_peak"])
    future24_productive, future24_animals = _future_summary(replay, seat, day + 1)
    future72_productive, future72_animals = _future_summary(replay, seat, day + 3)
    labels = {
        "animal_worker_fraction": role["metrics"]["animal_workers"] / hands,
        "crop_worker_fraction": role["metrics"]["crop_workers"] / hands,
        "logistics_worker_fraction": role["metrics"]["logistics_workers"] / hands,
        "productive_per_hand": role["metrics"]["productive_per_hand"],
        "move_per_productive": role["metrics"]["move_per_productive"],
        "pass_per_hand": role["metrics"]["pass_per_hand"],
        "same_role_transition_rate": role["metrics"]["same_role_transition_rate"],
        "future24_productive": future24_productive,
        "future72_productive": future72_productive,
        "future24_animals": future24_animals,
        "future72_animals": future72_animals,
    }
    return {
        "source": source,
        "episode_id": str(manifest["episode_id"]),
        "split": _split(str(manifest["episode_id"])),
        "day": day,
        "features": _context(obs, seat),
        "labels": labels,
    }


def _scales(rows: list[dict[str, Any]], names: tuple[str, ...], field: str) -> dict[str, tuple[float, float]]:
    result = {}
    for name in names:
        values = sorted(float(row[field][name]) for row in rows)
        center = median(values)
        q25 = values[round(0.25 * (len(values) - 1))]
        q75 = values[round(0.75 * (len(values) - 1))]
        result[name] = (center, max(1e-6, q75 - q25))
    return result


def _vector(row: dict[str, Any], scales: dict[str, tuple[float, float]]) -> list[float]:
    return [
        (float(row["features"][name]) - scales[name][0]) / scales[name][1]
        for name in FEATURES
    ]


def _distance(left: list[float], right: list[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)) / len(left))


def _median_labels(rows: list[dict[str, Any]]) -> dict[str, float]:
    return {name: median(float(row["labels"][name]) for row in rows) for name in LABELS}


def _predict(
    vector: list[float],
    train: list[tuple[list[float], dict[str, Any]]],
    fallback: dict[str, float],
    threshold: float,
    k: int,
) -> tuple[dict[str, float], float, bool]:
    nearest = sorted(
        ((_distance(vector, train_vector), row) for train_vector, row in train),
        key=lambda value: value[0],
    )
    distance = nearest[0][0]
    if distance > threshold:
        return fallback, distance, True
    neighbors = [row for _distance_value, row in nearest[:k]]
    return _median_labels(neighbors), distance, False


def _evaluate(
    rows: list[dict[str, Any]],
    train_vectors: list[tuple[list[float], dict[str, Any]]],
    feature_scales: dict[str, tuple[float, float]],
    label_scales: dict[str, tuple[float, float]],
    day_fallback: dict[int, dict[str, float]],
    threshold: float,
    k: int,
) -> dict[str, Any]:
    conditional_errors: dict[str, list[float]] = defaultdict(list)
    baseline_errors: dict[str, list[float]] = defaultdict(list)
    ood = 0
    distances = []
    source_counts: Counter[str] = Counter()
    for row in rows:
        fallback = day_fallback[row["day"]]
        prediction, distance, is_ood = _predict(
            _vector(row, feature_scales),
            train_vectors,
            fallback,
            threshold,
            k,
        )
        ood += is_ood
        distances.append(distance)
        source_counts[row["source"]] += 1
        for label in LABELS:
            scale = label_scales[label][1]
            actual = float(row["labels"][label])
            conditional_errors[label].append(abs(actual - prediction[label]) / scale)
            baseline_errors[label].append(abs(actual - fallback[label]) / scale)
    return {
        "rows": len(rows),
        "episodes": len({row["episode_id"] for row in rows}),
        "source_rows": dict(source_counts),
        "ood_rate": ood / max(1, len(rows)),
        "mean_nearest_distance": mean(distances) if distances else 0.0,
        "normalized_mae": {
            label: {
                "conditional": mean(conditional_errors[label]),
                "day_median_baseline": mean(baseline_errors[label]),
                "delta": mean(conditional_errors[label]) - mean(baseline_errors[label]),
            }
            for label in LABELS
        },
        "mean_normalized_mae": {
            "conditional": mean(mean(conditional_errors[label]) for label in LABELS),
            "day_median_baseline": mean(mean(baseline_errors[label]) for label in LABELS),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--neighbors", type=int, default=15)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v57_role_portfolio_validation.json"),
    )
    parser.add_argument(
        "--model-output",
        type=Path,
        default=Path("agents/v58/role_portfolio_model.json"),
    )
    args = parser.parse_args()
    rows = []
    seen: set[tuple[str, str, int]] = set()
    for source in TEACHERS:
        manifests = _manifest(SOURCES[source])
        for index, manifest in enumerate(manifests, start=1):
            if index == 1 or index % 50 == 0:
                print(f"[{source} {index}/{len(manifests)}]", flush=True)
            if str(manifest.get("result") or "").lower() != "win":
                continue
            key = (source, str(manifest["episode_id"]), int(manifest["submission_seat"]))
            if key in seen:
                continue
            seen.add(key)
            replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
            for day in DAYS:
                if row := _row(replay, manifest, source, day):
                    rows.append(row)
    train = [row for row in rows if row["split"] == "train"]
    feature_scales = _scales(train, FEATURES, "features")
    label_scales = _scales(train, LABELS, "labels")
    train_vectors = [(_vector(row, feature_scales), row) for row in train]
    day_fallback = {
        day: _median_labels([row for row in train if row["day"] == day])
        for day in DAYS
    }
    training_nearest = []
    for index, (vector, _row_value) in enumerate(train_vectors):
        training_nearest.append(
            min(
                _distance(vector, other)
                for other_index, (other, _other_row) in enumerate(train_vectors)
                if other_index != index
            )
        )
    threshold = sorted(training_nearest)[round(0.95 * (len(training_nearest) - 1))]
    payload = {
        "format": FORMAT,
        "runtime_policy_enabled": False,
        "objective": "validate state-conditioned day-role goals and 24h/72h futures before runtime use",
        "episode_disjoint_split": True,
        "teachers": list(TEACHERS),
        "winner_only": True,
        "features": list(FEATURES),
        "labels": list(LABELS),
        "model": {
            "kind": "robust-scaled-knn-with-day-median-ood-fallback",
            "neighbors": args.neighbors,
            "ood_threshold_training_p95": threshold,
        },
        "splits": {
            split: _evaluate(
                [row for row in rows if row["split"] == split],
                train_vectors,
                feature_scales,
                label_scales,
                day_fallback,
                threshold,
                args.neighbors,
            )
            for split in ("validation", "test")
        },
        "support": {
            "rows": len(rows),
            "episodes": len({row["episode_id"] for row in rows}),
            "split_rows": dict(Counter(row["split"] for row in rows)),
            "source_rows": dict(Counter(row["source"] for row in rows)),
        },
        "interpretation_limits": [
            "role targets are descriptive teacher goals and do not prove causal reward improvement",
            "future labels cover productive tiles and animals, not hidden inventory value or final leaderboard rating",
            "no runtime override is enabled by this validation",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    model_payload = {
        "format": MODEL_FORMAT,
        "features": list(FEATURES),
        "labels": list(LABELS),
        "neighbors": args.neighbors,
        "ood_threshold": threshold,
        "feature_scales": {
            name: {"center": center, "scale": scale}
            for name, (center, scale) in feature_scales.items()
        },
        "day_fallback": {str(day): day_fallback[day] for day in DAYS},
        "training": [
            {
                "vector": vector,
                "labels": [float(row["labels"][label]) for label in LABELS],
            }
            for vector, row in train_vectors
        ],
        "support": payload["support"],
        "validation_reference": {
            split: payload["splits"][split]["mean_normalized_mae"]
            for split in ("validation", "test")
        },
    }
    model_output = (
        args.model_output
        if args.model_output.is_absolute()
        else ROOT / args.model_output
    )
    model_output.parent.mkdir(parents=True, exist_ok=True)
    model_output.write_text(
        json.dumps(model_payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(json.dumps(payload["support"], ensure_ascii=False, indent=2))
    print(json.dumps(payload["splits"], ensure_ascii=False, indent=2))
    print(f"result: {output}")
    print(f"model: {model_output}")


if __name__ == "__main__":
    main()
