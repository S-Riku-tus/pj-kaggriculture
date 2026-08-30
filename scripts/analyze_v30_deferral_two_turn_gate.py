"""Evaluate the V29 two-turn supply model on V27 deferral candidates."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from statistics import mean, median
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_v28_deferral_supply_gate import _paths_and_seats  # noqa: E402
from scripts.build_v22_opponent_supply_rows import _history_values, _public_values  # noqa: E402
from scripts.train_v12_relative_policy import _observation  # noqa: E402
from scripts.train_v22_opponent_supply import _predict_forest, _raw_predictions  # noqa: E402
from scripts.train_v29_two_turn_supply import MODEL_FORMAT  # noqa: E402

FORMAT = "kaggriculture-v30-deferral-two-turn-gate-v1"


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * quantile
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - position) + ordered[high] * (position - low)


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "median": 0.0, "p10": 0.0, "p90": 0.0}
    return {
        "mean": mean(values),
        "median": median(values),
        "p10": _percentile(values, 0.10),
        "p90": _percentile(values, 0.90),
    }


def _metrics(rows: list[dict[str, Any]], event_limit: float, quantity_limit: float) -> dict[str, Any]:
    selected = [
        row
        for row in rows
        if row["supply_event_score"] <= event_limit
        and row["supply_quantity"] <= quantity_limit
        and row["confident"]
    ]
    safe = [row for row in selected if row["safe"]]
    all_safe = sum(row["safe"] for row in rows)
    return {
        "rows": len(rows),
        "safe_prevalence": sum(row["safe"] for row in rows) / max(1, len(rows)),
        "selected": len(selected),
        "selection_rate": len(selected) / max(1, len(rows)),
        "safe_precision": len(safe) / max(1, len(selected)),
        "safe_recall": len(safe) / max(1, all_safe),
        "logged_revenue_gain_lower_bound": _stats(
            [float(row["revenue_gain_lower_bound"]) for row in selected]
        ),
        "opponent_two_turn_requested_sale": _stats(
            [float(row["opponent_two_turn_requested_sale"]) for row in selected]
        ),
    }


def _select_gate(validation: list[dict[str, Any]]) -> dict[str, Any]:
    event_values = np.asarray([float(row["supply_event_score"]) for row in validation])
    quantity_values = np.asarray([float(row["supply_quantity"]) for row in validation])
    event_candidates = sorted({0.0, *np.quantile(event_values, np.linspace(0.02, 1.0, 30)).tolist()})
    quantity_candidates = sorted(
        {0.0, *np.quantile(quantity_values, np.linspace(0.02, 1.0, 30)).tolist()}
    )
    candidates: list[dict[str, Any]] = []
    for event_limit in event_candidates:
        for quantity_limit in quantity_candidates:
            report = _metrics(validation, event_limit, quantity_limit)
            candidates.append(
                {
                    "event_limit": float(event_limit),
                    "quantity_limit": float(quantity_limit),
                    **report,
                }
            )
    supported = [
        row
        for row in candidates
        if row["selected"] >= 30
        and row["safe_precision"] >= 0.75
        and row["logged_revenue_gain_lower_bound"]["p10"] >= 0
    ]
    pool = supported or candidates
    winner = max(
        pool,
        key=lambda row: (
            bool(row in supported),
            row["safe_recall"],
            row["safe_precision"],
            row["selection_rate"],
        ),
    )
    return {
        "supported_on_validation": bool(supported),
        "event_limit": float(winner["event_limit"]),
        "quantity_limit": float(winner["quantity_limit"]),
        "validation_selected": int(winner["selected"]),
        "validation_safe_precision": float(winner["safe_precision"]),
        "validation_safe_recall": float(winner["safe_recall"]),
        "validation_gain_p10": float(winner["logged_revenue_gain_lower_bound"]["p10"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--counterfactual",
        type=Path,
        default=Path("data/analysis/v27_town_deferral_counterfactual.json"),
    )
    parser.add_argument(
        "--model", type=Path, default=Path("data/models/v29_two_turn_supply_model.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("data/analysis/v30_deferral_two_turn_gate.json")
    )
    args = parser.parse_args()
    counterfactual_path = (
        args.counterfactual if args.counterfactual.is_absolute() else ROOT / args.counterfactual
    )
    model_path = args.model if args.model.is_absolute() else ROOT / args.model
    source = json.loads(counterfactual_path.read_text(encoding="utf-8"))
    model = json.loads(model_path.read_text(encoding="utf-8"))
    if model.get("format") != MODEL_FORMAT:
        raise ValueError("a frozen V29 two-turn supply model is required")
    candidates = source["runtime_candidates"]
    paths, seats = _paths_and_seats()
    replay_cache: dict[tuple[str, str], dict[str, Any]] = {}
    feature_rows: list[list[float]] = []
    kept: list[dict[str, Any]] = []
    feature_names = list(model["feature_names"])
    for index, candidate in enumerate(candidates, start=1):
        if index == 1 or index % 250 == 0:
            print(f"features [{index}/{len(candidates)}]", flush=True)
        key = (str(candidate["source"]), str(candidate["episode_id"]))
        if key not in replay_cache:
            replay_cache[key] = json.loads(paths[key].read_text(encoding="utf-8"))
        replay = replay_cache[key]
        seat = seats[key]
        step = int(candidate["day"]) * 24 + int(candidate["hour"])
        obs = _observation(replay, step, seat)
        if obs is None:
            continue
        values = _public_values(obs, seat)
        values.update(_history_values(replay, step, seat, obs))
        feature_rows.append([float(values[name]) for name in feature_names])
        opponent_two_turn = (
            float(candidate["counterfactual_next_inventory"])
            + float(candidate["town_consumption"])
            - float(candidate["current_inventory"])
            + float(candidate["opponent_next_requested_sale"])
        )
        kept.append(
            {
                **candidate,
                "safe": float(candidate["revenue_gain_lower_bound"]) > 0,
                "opponent_two_turn_requested_sale": max(0.0, opponent_two_turn),
            }
        )
    x = np.asarray(feature_rows, dtype=np.float64)
    print(f"predicting {len(x)} rows", flush=True)
    raw, deviation = _predict_forest(model["forest"], x)
    output_names = list(model["output_names"])
    event, quantity = _raw_predictions(raw, len(output_names))
    uncertainty = np.mean(deviation, axis=1)
    uncertainty_limit = float(model["uncertainty_limit"])
    rows = []
    for row_index, candidate in enumerate(kept):
        output_index = output_names.index(f"h2_{candidate['item']}")
        rows.append(
            {
                **candidate,
                "supply_event_score": float(event[row_index, output_index]),
                "supply_quantity": float(quantity[row_index, output_index]),
                "uncertainty": float(uncertainty[row_index]),
                "confident": float(uncertainty[row_index]) <= uncertainty_limit,
            }
        )
    top_validation = [
        row for row in rows if row["source"] != "v11" and row["split"] == "validation"
    ]
    gate = _select_gate(top_validation)
    event_limit = float(gate["event_limit"])
    quantity_limit = float(gate["quantity_limit"])
    groups = {
        "top_train": [row for row in rows if row["source"] != "v11" and row["split"] == "train"],
        "top_validation": top_validation,
        "top_test": [row for row in rows if row["source"] != "v11" and row["split"] == "test"],
        "v11_external": [row for row in rows if row["source"] == "v11"],
        **{
            f"v11_external_{split}": [
                row for row in rows if row["source"] == "v11" and row["split"] == split
            ]
            for split in ("train", "validation", "test")
        },
    }
    reports = {
        name: _metrics(group, event_limit, quantity_limit) for name, group in groups.items()
    }
    support = {
        "validation": bool(gate["supported_on_validation"]),
        "top_test": reports["top_test"]["safe_precision"] >= 0.70
        and reports["top_test"]["logged_revenue_gain_lower_bound"]["p10"] >= 0,
        "v11_external": reports["v11_external"]["safe_precision"] >= 0.70
        and reports["v11_external"]["logged_revenue_gain_lower_bound"]["p10"] >= 0,
    }
    payload = {
        "format": FORMAT,
        "objective": "two-turn opponent-sale gate for public Town-deferral candidates",
        "model": str(model_path.relative_to(ROOT)),
        "gate_selection": gate,
        "reports": reports,
        "support": support,
        "interpretation": {
            "fact": "model and hyperparameters are frozen before this candidate-gate evaluation",
            "limit": "gate thresholds use Top-3 validation candidates; V11 remains external",
            "runtime": "disabled unless validation, untouched Top-3 test, and external V11 all pass",
        },
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"gate": gate, "reports": reports, "support": support}, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
