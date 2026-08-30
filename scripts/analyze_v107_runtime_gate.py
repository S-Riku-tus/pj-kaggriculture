"""Validate V107's path-safe runtime restriction on episode-disjoint teacher rows.

The additional phase/cash restriction was hypothesized from V106 adaptive
fork failures.  It is frozen here, then evaluated on the existing train,
validation, and historical test partitions without threshold search.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v14 import main as v14  # noqa: E402
from scripts.analyze_v102_recovery_gate import (  # noqa: E402
    PORTFOLIO,
    _phase,
    _project,
    _row_error,
    _summary,
)
from scripts.train_v3_strategy import train_forest  # noqa: E402
from scripts.train_v14_winner_policy import TARGET_SCALES, _predict_rows  # noqa: E402

ROWS = ROOT / "data/training/v12_relative_rows.json"
ADAPTIVE = ROOT / "data/analysis/v106_adaptive_fork_diagnosis.json"
OUTPUT = ROOT / "data/analysis/v107_runtime_gate_screen.json"

PHASE = "10-11"
MIN_MONEY = 500.0
MIN_CONFIDENCE = 0.65
MAX_UNCERTAINTY_RATIO = 0.80
MIN_CHANGE = 0.02
MAX_MONEY_GAP_RATIO = -0.05


def _money(features: list[float]) -> float:
    value = float(features[v14.v3.FEATURE_NAMES.index("money_log")])
    return math.expm1(value * 12.0)


def _demand_alignment(delta: dict[str, float], demand: dict[str, float]) -> float:
    positive_mass = sum(max(0.0, value) for value in delta.values())
    negative_mass = sum(max(0.0, -value) for value in delta.values())
    if positive_mass <= 0 or negative_mass <= 0:
        return 0.0
    return (
        sum(max(0.0, delta[crop]) * demand.get(crop, 0.0) for crop in v14.CROPS)
        / positive_mass
        - sum(max(0.0, -delta[crop]) * demand.get(crop, 0.0) for crop in v14.CROPS)
        / negative_mass
    )


def _gate(record: dict[str, Any]) -> bool:
    return bool(
        record["base_active"]
        and record["phase"] == PHASE
        and record["money"] >= MIN_MONEY
        and record["confidence"] >= MIN_CONFIDENCE
        and record["uncertainty_ratio"] <= MAX_UNCERTAINTY_RATIO
        and record["change"] >= MIN_CHANGE
        and record["money_gap_ratio"] <= MAX_MONEY_GAP_RATIO
        and record["demand_alignment"] > 0.0
    )


def main() -> None:
    cached = json.loads(ROWS.read_text(encoding="utf-8"))
    rows = [row for row in cached["rows"] if row["winner"]]
    x = np.asarray([row["features"] for row in rows], dtype=np.float64)
    y = np.asarray(
        [[float(row["h72"][item]) for item in PORTFOLIO] for row in rows],
        dtype=np.float64,
    )
    split = np.asarray([row["split"] for row in rows])
    training = split == "train"
    weights = np.asarray(
        [1.15 if float(row["money_gap_ratio"]) < 0 else 1.0 for row in rows],
        dtype=np.float64,
    )
    forest = train_forest(
        x[training],
        y[training],
        weights[training],
        trees=18,
        depth=9,
        min_leaf=48,
        seed=20260928,
    )
    means, deviations = _predict_rows(forest, x)
    uncertainty = np.mean(deviations / TARGET_SCALES, axis=1)
    reference = float(np.quantile(uncertainty[split == "validation"], 0.90))

    records = []
    for index, row in enumerate(rows):
        manifold, distance = v14._distance_confidence(row["features"], int(row["day"]))
        model_confidence = min(
            1.0,
            max(0.0, 1.15 - 0.50 * uncertainty[index] / max(0.05, reference)),
        )
        confidence = float(manifold * model_confidence)
        candidate = _project(row, means[index], confidence)
        crop_delta = {
            crop: float(candidate[crop]) - float(row["baseline"][crop])
            for crop in v14.CROPS
        }
        demand = {
            crop: float(
                row["features"][
                    v14.v3.FEATURE_NAMES.index(f"demand_{v14.ITEM_DEMAND[crop]}")
                ]
            )
            for crop in v14.CROPS
        }
        demand_alignment = _demand_alignment(crop_delta, demand)
        change = mean(
            abs(float(candidate[item]) - float(row["baseline"][item]))
            / float(TARGET_SCALES[item_index])
            for item_index, item in enumerate(PORTFOLIO)
        )
        record = {
            "episode_id": str(row["episode_id"]),
            "split": str(row["split"]),
            "source": str(row["source"]),
            "phase": _phase(int(row["day"])),
            "day": int(row["day"]),
            "money": _money(row["features"]),
            "money_gap_ratio": float(row["money_gap_ratio"]),
            "confidence": confidence,
            "distance": float(distance),
            "uncertainty_ratio": float(uncertainty[index] / max(0.05, reference)),
            "change": float(change),
            "demand_alignment": float(demand_alignment),
            "base_active": bool(
                float(row["money_gap_ratio"]) < 0
                and uncertainty[index] <= reference
                and confidence >= v14.MIN_CONFIDENCE
            ),
            "improvement": float(_row_error(row, row["baseline"]) - _row_error(row, candidate)),
        }
        record["trigger"] = _gate(record)
        records.append(record)

    reports = {
        name: _summary([record for record in records if record["split"] == name])
        for name in ("train", "validation", "test")
    }
    adaptive_payload = json.loads(ADAPTIVE.read_text(encoding="utf-8"))
    adaptive_selected = [
        record
        for record in adaptive_payload["records"]
        if int(record["fork_day"]) in {10, 11}
        and float(record["entry"]["money"]) >= MIN_MONEY
        and _demand_alignment(
            {
                crop: float(record["entry"]["gate"]["crop_delta"].get(crop, 0))
                for crop in v14.CROPS
            },
            {
                crop: float(record["entry"]["demand"].get(crop, 0))
                for crop in v14.CROPS
            },
        )
        > 0.0
    ]
    result = {
        "format": "kaggriculture-v107-runtime-gate-screen-v1",
        "hypothesis_source": str(ADAPTIVE.relative_to(ROOT)),
        "teacher_rows": str(ROWS.relative_to(ROOT)),
        "frozen_selection": {
            "phase": PHASE,
            "minimum_money": MIN_MONEY,
            "minimum_confidence": MIN_CONFIDENCE,
            "maximum_uncertainty_ratio": MAX_UNCERTAINTY_RATIO,
            "minimum_normalized_change": MIN_CHANGE,
            "maximum_money_gap_ratio": MAX_MONEY_GAP_RATIO,
            "minimum_demand_alignment": "strictly greater than zero",
        },
        "episode_partition": {
            name: len({record["episode_id"] for record in records if record["split"] == name})
            for name in ("train", "validation", "test")
        },
        "teacher_future_goal_reports": reports,
        "adaptive_development_recheck": {
            "selected_episodes": len(adaptive_selected),
            "reward_deltas": [record["reward_delta_context"] for record in adaptive_selected],
            "margin_deltas": [record["margin_delta_context"] for record in adaptive_selected],
            "minimum_reward_delta": min(
                (float(record["reward_delta_context"]) for record in adaptive_selected),
                default=0.0,
            ),
            "minimum_margin_delta": min(
                (float(record["margin_delta_context"]) for record in adaptive_selected),
                default=0.0,
            ),
        },
        "limits": [
            "phase and cash thresholds were derived from the eight adaptive development forks",
            "the historical test partition was inspected in earlier V14/V102 work and is not pristine",
            "teacher future-goal improvement is not a counterfactual reward or rating label",
            "a new untouched top-log confirmation and standalone closed loop remain required",
        ],
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"result: {OUTPUT}")


if __name__ == "__main__":
    main()
