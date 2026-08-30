"""Screen a narrower V14 recovery gate above V11's public safe core.

The V14 crop forest is refit on complete training episodes only.  Gate
thresholds and eligible phases are selected on validation episodes.  The
historical test split is reported once as confirmation, but is explicitly not
called pristine because earlier V14/V101 work has already inspected it.

The target is 72-hour winner portfolio error, not immediate action matching or
local reward.  Runtime promotion still requires independent recent-submission
logs and clean closed-loop safety diagnostics.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v14 import main as v14  # noqa: E402
from scripts.train_v3_strategy import train_forest  # noqa: E402
from scripts.train_v14_winner_policy import (  # noqa: E402
    TARGET_IMPORTANCE,
    TARGET_SCALES,
    _phase,
    _predict_rows,
)

FORMAT = "kaggriculture-v102-recovery-gate-screen-v1"
PHASES = ("6-9", "10-11", "12-13", "14-17", "18-21", "22-24", "25-27")
CROPS = tuple(v14.CROPS)
PORTFOLIO = tuple(v14.PORTFOLIO)


def _percentile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    return float(np.quantile(np.asarray(values, dtype=np.float64), probability))


def _project(
    row: dict[str, Any], means: np.ndarray, confidence: float
) -> dict[str, float]:
    """Approximate V14's deterministic projection from cached public counts."""
    baseline = {item: int(round(float(row["baseline"][item]))) for item in PORTFOLIO}
    current = {item: int(round(float(row["current"][item]))) for item in PORTFOLIO}
    goal = {item: float(means[index]) for index, item in enumerate(PORTFOLIO)}
    blend = min(v14.MAX_BLEND, 0.15 + 0.20 * confidence)
    selected = dict(baseline)
    for crop in CROPS:
        mixed = round((1.0 - blend) * baseline[crop] + blend * goal[crop])
        limit = int(v14.CROP_CHANGE_LIMIT[crop])
        limited = min(baseline[crop] + limit, max(baseline[crop] - limit, mixed))
        selected[crop] = max(current[crop], limited)

    feed_floor = math.ceil((baseline["COW"] + baseline["SHEEP"]) * 1.2)
    selected["WHEAT"] = max(selected["WHEAT"], feed_floor)
    floors = dict(current)
    floors["WHEAT"] = max(floors["WHEAT"], feed_floor)
    baseline_mass = sum(baseline.values())
    budget = max(baseline_mass, sum(floors.values()))
    features = row["features"]
    demand = {
        item: float(features[v14.v3.FEATURE_NAMES.index(f"demand_{v14.ITEM_DEMAND[item]}")])
        for item in CROPS
    }
    while sum(selected.values()) > budget:
        reducible = [item for item in CROPS if selected[item] > floors[item]]
        if not reducible:
            break
        item = min(
            reducible,
            key=lambda value: (
                demand[value],
                int(v14.base.BASE_PRICE[v14.ITEM_DEMAND[value]]),
                -int(selected[value] - floors[value]),
                PORTFOLIO.index(value),
            ),
        )
        selected[item] -= 1
    if sum(selected.values()) < budget:
        selected["WHEAT"] += budget - sum(selected.values())
    return {item: float(selected[item]) for item in PORTFOLIO}


def _row_error(row: dict[str, Any], target: dict[str, float]) -> float:
    actual = row["h72"]
    values = [
        abs(float(actual[item]) - float(target[item]))
        / float(TARGET_SCALES[index])
        * float(TARGET_IMPORTANCE[index])
        for index, item in enumerate(PORTFOLIO)
    ]
    return mean(values)


def _summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    triggered = [record for record in records if record["trigger"]]
    episode_values: dict[str, list[float]] = defaultdict(list)
    for record in triggered:
        episode_values[str(record["episode_id"])].append(float(record["improvement"]))
    episode_means = [mean(values) for values in episode_values.values()]
    source = {
        name: {
            "rows": sum(record["source"] == name for record in triggered),
            "mean_improvement": round(
                mean(
                    float(record["improvement"])
                    for record in triggered
                    if record["source"] == name
                ),
                6,
            ),
        }
        for name in ("rank1", "rank2", "rank3", "opponent")
        if any(record["source"] == name for record in triggered)
    }
    return {
        "rows": len(records),
        "triggered_rows": len(triggered),
        "triggered_episodes": len(episode_means),
        "mean_row_improvement": round(
            mean(float(record["improvement"]) for record in triggered), 6
        )
        if triggered
        else 0.0,
        "episode_improvement": {
            "mean": round(mean(episode_means), 6) if episode_means else 0.0,
            "p10": round(_percentile(episode_means, 0.10), 6),
            "minimum": round(min(episode_means), 6) if episode_means else 0.0,
        },
        "source": source,
    }


def _gate(record: dict[str, Any], params: dict[str, Any]) -> bool:
    return bool(
        record["base_active"]
        and record["phase"] in params["phases"]
        and record["confidence"] >= params["min_confidence"]
        and record["uncertainty_ratio"] <= params["max_uncertainty_ratio"]
        and record["change"] >= params["min_change"]
        and record["money_gap_ratio"] <= params["max_money_gap_ratio"]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=Path, default=Path("data/training/v12_relative_rows.json"))
    parser.add_argument(
        "--output", type=Path, default=Path("data/analysis/v102_recovery_gate_screen.json")
    )
    args = parser.parse_args()
    path = args.rows if args.rows.is_absolute() else ROOT / args.rows
    cached = json.loads(path.read_text(encoding="utf-8"))
    rows = [row for row in cached["rows"] if row["winner"]]
    x = np.asarray([row["features"] for row in rows], dtype=np.float64)
    y = np.asarray(
        [[float(row["h72"][item]) for item in PORTFOLIO] for row in rows], dtype=np.float64
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
        seed=20260828 + 100,
    )
    means, deviations = _predict_rows(forest, x)
    uncertainty = np.mean(deviations / TARGET_SCALES, axis=1)
    reference = float(np.quantile(uncertainty[split == "validation"], 0.90))

    records: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        manifold, distance = v14._distance_confidence(row["features"], int(row["day"]))
        model_confidence = min(1.0, max(0.0, 1.15 - 0.50 * uncertainty[index] / max(0.05, reference)))
        confidence = float(manifold * model_confidence)
        candidate = _project(row, means[index], confidence)
        baseline_error = _row_error(row, row["baseline"])
        candidate_error = _row_error(row, candidate)
        change = mean(
            abs(float(candidate[item]) - float(row["baseline"][item]))
            / float(TARGET_SCALES[item_index])
            for item_index, item in enumerate(PORTFOLIO)
        )
        records.append(
            {
                "episode_id": str(row["episode_id"]),
                "split": str(row["split"]),
                "source": str(row["source"]),
                "phase": _phase(int(row["day"])),
                "day": int(row["day"]),
                "money_gap_ratio": float(row["money_gap_ratio"]),
                "confidence": confidence,
                "distance": float(distance),
                "uncertainty_ratio": float(uncertainty[index] / max(0.05, reference)),
                "change": float(change),
                "base_active": bool(
                    float(row["money_gap_ratio"]) < 0
                    and uncertainty[index] <= reference
                    and confidence >= v14.MIN_CONFIDENCE
                ),
                "improvement": float(baseline_error - candidate_error),
            }
        )

    validation = [record for record in records if record["split"] == "validation"]
    candidates: list[dict[str, Any]] = []
    for min_confidence, max_uncertainty_ratio, min_change, max_money_gap_ratio in itertools.product(
        (0.35, 0.45, 0.55, 0.65, 0.75),
        (0.50, 0.65, 0.80, 1.00),
        (0.0, 0.02, 0.04, 0.06, 0.08),
        (0.0, -0.02, -0.05, -0.10),
    ):
        phase_reports: dict[str, Any] = {}
        selected_phases: list[str] = []
        for phase in PHASES:
            phase_records = [
                {**record, "trigger": _gate(record, {
                    "phases": [phase],
                    "min_confidence": min_confidence,
                    "max_uncertainty_ratio": max_uncertainty_ratio,
                    "min_change": min_change,
                    "max_money_gap_ratio": max_money_gap_ratio,
                })}
                for record in validation
            ]
            report = _summary(phase_records)
            phase_reports[phase] = report
            if (
                report["triggered_rows"] >= 20
                and report["triggered_episodes"] >= 8
                and report["episode_improvement"]["mean"] > 0
            ):
                selected_phases.append(phase)
        if not selected_phases:
            continue
        params = {
            "phases": selected_phases,
            "min_confidence": min_confidence,
            "max_uncertainty_ratio": max_uncertainty_ratio,
            "min_change": min_change,
            "max_money_gap_ratio": max_money_gap_ratio,
        }
        report = _summary([{**record, "trigger": _gate(record, params)} for record in validation])
        if report["triggered_episodes"] < 20:
            continue
        score = report["episode_improvement"]["mean"] + min(
            0.0, report["episode_improvement"]["p10"]
        )
        candidates.append({"params": params, "validation": report, "score": score})
    if not candidates:
        raise RuntimeError("no recovery meta-gate passed validation support")
    selected = max(
        candidates,
        key=lambda item: (
            float(item["score"]),
            float(item["validation"]["episode_improvement"]["p10"]),
            int(item["validation"]["triggered_episodes"]),
        ),
    )
    params = selected["params"]
    reports = {
        name: _summary(
            [
                {**record, "trigger": _gate(record, params)}
                for record in records
                if record["split"] == split_name
            ]
        )
        for name, split_name in (
            ("train_diagnostic", "train"),
            ("validation_selection", "validation"),
            ("historical_test_confirmation", "test"),
        )
    }
    result = {
        "format": FORMAT,
        "objective": "gate V14 72-hour crop recovery only where it improves V11 future-goal fidelity",
        "episode_split": {
            name: len({record["episode_id"] for record in records if record["split"] == name})
            for name in ("train", "validation", "test")
        },
        "base_forest": {
            "fit": "train episodes only",
            "trees": 18,
            "depth": 9,
            "min_leaf": 48,
            "uncertainty_reference_validation_p90": reference,
        },
        "selection": params,
        "reports": reports,
        "candidate_count": len(candidates),
        "limitations": {
            "historical_test": "confirmation only; inspected by prior V14/V101 work",
            "projection": "cached public counts omit rare unplaced animal inventory",
            "causal": "future-goal fidelity is not a reward or rating estimate",
            "remaining": "independent recent-submission opponent trajectories and closed-loop safety",
        },
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
