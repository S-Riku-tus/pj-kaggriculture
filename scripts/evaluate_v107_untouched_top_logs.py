"""Evaluate the frozen V107 runtime gate on untouched strong-submission logs.

The two source submissions and 24-log caps were fixed from opponent rating
before inspecting whether V107 triggers.  The observations are never used to
change V107 here.  This measures agreement with the strong policy's 24/72-hour
future portfolio, not a counterfactual score or a rating estimate.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v107 import main as v107  # noqa: E402
from scripts.train_v12_relative_policy import _observation, _portfolio  # noqa: E402
from scripts.train_v14_winner_policy import TARGET_IMPORTANCE, TARGET_SCALES  # noqa: E402

OUTPUT = ROOT / "data/analysis/v107_untouched_top_log_confirmation.json"
FORMAT = "kaggriculture-v107-untouched-top-log-confirmation-v1"
SOURCES = {
    "untouched_top_1_55832857": ROOT / "data/submissions/untouched_top_1_submission_55832857",
    "untouched_top_2_55815118": ROOT / "data/submissions/untouched_top_2_submission_55815118",
}
PORTFOLIO = tuple(v107.v14.PORTFOLIO)
BASE_GATE_ATTRIBUTE = "_SAFE_GATE_DECISION"
BASE_ACTIVE_LABEL = "v102_base_active_rows"
REJECTION_LABEL = "v107_rejection_reasons"
SELECTION_PROVENANCE = {
    "rule": "two highest opponent updated ratings in the submitted V14/V18 manifests",
    "selected_before_v107_trigger_inspection": True,
    "sources": {
        "untouched_top_1_55832857": {
            "selection_rating": 1267.5,
            "fetched_episodes": 24,
            "excluded_known_encounter": "101410775 was outside the fetched newest-24 window",
        },
        "untouched_top_2_55815118": {
            "selection_rating": 1231.3,
            "fetched_episodes": 24,
            "excluded_known_encounter": "100786533 was outside the fetched newest-24 window",
        },
    },
}
INTERPRETATION = {
    "fact": "V107 code and thresholds were frozen before these 48 trajectories were evaluated",
    "scope": "future-portfolio fidelity to two strong submitted policies on episode-disjoint logs",
    "limit": "this is observational teacher agreement, not a counterfactual reward or rating estimate",
}


def _manifest(directory: Path) -> list[dict[str, str]]:
    with (directory / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        return [
            row
            for row in csv.DictReader(handle)
            if row.get("replay_status") in {"downloaded", "skipped_existing"}
            and int(float(row.get("step_count") or 0)) >= 719
        ]


def _replay_path(row: dict[str, str]) -> Path:
    direct = ROOT / row["replay_path"]
    return direct if direct.is_file() else ROOT / "data" / row["replay_path"]


def _target(portfolio: tuple[dict[str, int], dict[str, int], Any, Any, Any, Any]) -> dict[str, float]:
    return {
        **{crop: float(portfolio[1][crop]) for crop in v107.v14.CROPS},
        "COW": float(portfolio[0]["COW"]),
        "SHEEP": float(portfolio[0]["SHEEP"]),
    }


def _candidate(decision: dict[str, Any]) -> dict[str, float]:
    return {
        **{crop: float(decision["candidate_crops"][crop]) for crop in v107.v14.CROPS},
        "COW": float(decision["candidate_animals"]["COW"]),
        "SHEEP": float(decision["candidate_animals"]["SHEEP"]),
    }


def _error(actual: dict[str, float], target: dict[str, float]) -> float:
    return mean(
        abs(float(actual[item]) - float(target[item]))
        / float(TARGET_SCALES[index])
        * float(TARGET_IMPORTANCE[index])
        for index, item in enumerate(PORTFOLIO)
    )


def _percentile(values: list[float], probability: float) -> float:
    return float(np.quantile(np.asarray(values, dtype=np.float64), probability)) if values else 0.0


def _metric(values: list[float]) -> dict[str, float]:
    return {
        "mean": round(mean(values), 6) if values else 0.0,
        "p10": round(_percentile(values, 0.10), 6),
        "minimum": round(min(values), 6) if values else 0.0,
    }


def _summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_episode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_episode[str(record["episode_id"])].append(record)
    result: dict[str, Any] = {
        "triggered_rows": len(records),
        "triggered_episodes": len(by_episode),
    }
    for horizon in (24, 72):
        row_values = [float(record[f"h{horizon}_improvement"]) for record in records]
        episode_values = [
            mean(float(record[f"h{horizon}_improvement"]) for record in episode_records)
            for episode_records in by_episode.values()
        ]
        result[f"h{horizon}"] = {
            "row_improvement": _metric(row_values),
            "episode_improvement": _metric(episode_values),
            "positive_rows": sum(value > 0 for value in row_values),
            "negative_rows": sum(value < 0 for value in row_values),
        }
    return result


def main() -> None:
    records: list[dict[str, Any]] = []
    available: Counter[str] = Counter()
    results: dict[str, Counter[str]] = defaultdict(Counter)
    base_active: Counter[str] = Counter()
    rejection_reasons: Counter[str] = Counter()
    seen: set[tuple[str, int]] = set()

    for source, directory in SOURCES.items():
        for manifest in _manifest(directory):
            episode_id = str(manifest["episode_id"])
            seat = int(manifest["submission_seat"])
            key = (episode_id, seat)
            if key in seen:
                continue
            seen.add(key)
            available[source] += 1
            results[source][str(manifest.get("result") or "unknown")] += 1
            replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
            for day in range(6, 28):
                current = _observation(replay, day * 24, seat)
                if current is None:
                    continue
                safe = v107.base._safe_observation(current)
                if safe is None:
                    continue
                farm, opponent_farm, private = safe
                original_decision = getattr(v107, BASE_GATE_ATTRIBUTE)(
                    current, farm, opponent_farm, private
                )
                if not original_decision.get("active"):
                    continue
                base_active[source] += 1
                decision = v107._gate_decision(current, farm, opponent_farm, private)
                if not decision.get("active"):
                    rejection_reasons[str(decision.get("reason", "unknown"))] += 1
                    continue
                baseline = _target(decision["baseline"])
                candidate = _candidate(decision)
                future_values: dict[int, dict[str, float]] = {}
                for horizon in (24, 72):
                    future = _observation(replay, min(day * 24 + horizon, 719), seat)
                    if future is None:
                        break
                    future_farms = future.get("farms") or []
                    player = int(future.get("player", seat))
                    if not 0 <= player < len(future_farms):
                        break
                    future_values[horizon] = _portfolio(future_farms[player])
                if len(future_values) != 2:
                    continue
                record: dict[str, Any] = {
                    "source": source,
                    "episode_id": episode_id,
                    "teacher_result": str(manifest.get("result") or "unknown"),
                    "day": day,
                    "phase": str(decision["phase"]),
                    "current_money": float(decision["v107_current_money"]),
                    "money_gap_ratio": float(decision["prediction"]["money_gap_ratio"]),
                    "confidence": float(decision["confidence"]),
                    "uncertainty_ratio": float(decision["uncertainty_ratio"]),
                    "normalized_change": float(decision["normalized_change"]),
                    "demand_alignment": float(decision["v107_demand_alignment"]),
                    "baseline": baseline,
                    "candidate": candidate,
                }
                for horizon, actual in future_values.items():
                    record[f"h{horizon}_actual"] = actual
                    record[f"h{horizon}_baseline_error"] = _error(actual, baseline)
                    record[f"h{horizon}_candidate_error"] = _error(actual, candidate)
                    record[f"h{horizon}_improvement"] = (
                        record[f"h{horizon}_baseline_error"]
                        - record[f"h{horizon}_candidate_error"]
                    )
                records.append(record)

    result = {
        "format": FORMAT,
        "selection_provenance": SELECTION_PROVENANCE,
        "available_complete_episodes": dict(available),
        "teacher_results": {source: dict(counts) for source, counts in results.items()},
        BASE_ACTIVE_LABEL: dict(base_active),
        REJECTION_LABEL: dict(rejection_reasons),
        "overall": _summary(records),
        "by_source": {
            source: _summary([record for record in records if record["source"] == source])
            for source in SOURCES
        },
        "by_day": {
            str(day): _summary([record for record in records if record["day"] == day])
            for day in sorted({int(record["day"]) for record in records})
        },
        "by_teacher_result": {
            teacher_result: _summary(
                [record for record in records if record["teacher_result"] == teacher_result]
            )
            for teacher_result in sorted({str(record["teacher_result"]) for record in records})
        },
        "triggered_records": records,
        "interpretation": INTERPRETATION,
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "format": FORMAT,
                "available_complete_episodes": result["available_complete_episodes"],
                BASE_ACTIVE_LABEL: result[BASE_ACTIVE_LABEL],
                REJECTION_LABEL: result[REJECTION_LABEL],
                "overall": result["overall"],
                "by_source": result["by_source"],
                "by_day": result["by_day"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"result: {OUTPUT}")


if __name__ == "__main__":
    main()
