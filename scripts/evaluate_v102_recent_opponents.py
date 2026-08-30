"""Evaluate the V102 gate on recent opponents that defeated V14/V18.

These episodes were not used to select the V102 thresholds.  They are a
current-pool external confirmation set, not a globally pristine dataset: the
attached user report already inspected the same submissions at an aggregate
level.  Evaluation remains future-goal fidelity, never a counterfactual score
claim.
"""

from __future__ import annotations

import csv
import json
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
from scripts.train_v12_relative_policy import _observation, _portfolio  # noqa: E402
from scripts.train_v14_winner_policy import TARGET_IMPORTANCE, TARGET_SCALES  # noqa: E402

FORMAT = "kaggriculture-v102-recent-opponent-confirmation-v1"
SOURCES = {
    "v14_recent_opponent": ROOT / "data/submissions/rank1_v14_submission_55815097",
    "v18_recent_opponent": ROOT
    / "data/submissions/rank2_v18_intraday_gate_submission_55815102",
}
PORTFOLIO = tuple(v14.PORTFOLIO)


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


def _error(actual: dict[str, float], target: dict[str, float]) -> float:
    return mean(
        abs(float(actual[item]) - float(target[item]))
        / float(TARGET_SCALES[index])
        * float(TARGET_IMPORTANCE[index])
        for index, item in enumerate(PORTFOLIO)
    )


def _percentile(values: list[float], probability: float) -> float:
    return float(np.quantile(np.asarray(values, dtype=np.float64), probability)) if values else 0.0


def _summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    episode: dict[str, list[float]] = defaultdict(list)
    for record in records:
        episode[str(record["episode_id"])].append(float(record["improvement"]))
    values = [mean(rows) for rows in episode.values()]
    return {
        "triggered_rows": len(records),
        "triggered_episodes": len(values),
        "row_mean_improvement": round(mean(float(row["improvement"]) for row in records), 6)
        if records
        else 0.0,
        "episode_improvement": {
            "mean": round(mean(values), 6) if values else 0.0,
            "p10": round(_percentile(values, 0.10), 6),
            "minimum": round(min(values), 6) if values else 0.0,
        },
    }


def main() -> None:
    selection_path = ROOT / "data/analysis/v102_recovery_gate_screen.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))["selection"]
    reference = float(v14.WINNER_MODEL["uncertainty_p90"]["h72"])
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    episode_counts: dict[str, int] = defaultdict(int)
    winning_opponents: dict[str, int] = defaultdict(int)

    for source, directory in SOURCES.items():
        for manifest in _manifest(directory):
            episode_id = str(manifest["episode_id"])
            submitted_seat = int(manifest["submission_seat"])
            opponent_seat = 1 - submitted_seat
            key = (episode_id, opponent_seat)
            if key in seen:
                continue
            seen.add(key)
            episode_counts[source] += 1
            replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
            rewards = [float(value or 0) for value in replay.get("rewards") or (0, 0)]
            if rewards[opponent_seat] <= rewards[submitted_seat]:
                continue
            winning_opponents[source] += 1
            for day in range(6, 28):
                current = _observation(replay, day * 24, opponent_seat)
                future = _observation(replay, min(day * 24 + 72, 719), opponent_seat)
                if current is None or future is None:
                    continue
                safe = v14.base._safe_observation(current)
                if safe is None:
                    continue
                farm, opponent_farm, private = safe
                player = int(current.get("player", opponent_seat))
                future_farms = future.get("farms") or []
                if not 0 <= player < len(future_farms):
                    continue
                prediction = v14._winner_prediction(current, farm, opponent_farm)
                if not prediction.get("active"):
                    continue
                baseline = v14.v11._strategy_targets(current, farm, opponent_farm, private)
                candidate = v14._strategy_targets(current, farm, opponent_farm, private)
                baseline_target = {**baseline[1], "COW": baseline[0]["COW"], "SHEEP": baseline[0]["SHEEP"]}
                candidate_target = {
                    **candidate[1],
                    "COW": candidate[0]["COW"],
                    "SHEEP": candidate[0]["SHEEP"],
                }
                change = mean(
                    abs(float(candidate_target[item]) - float(baseline_target[item]))
                    / float(TARGET_SCALES[index])
                    for index, item in enumerate(PORTFOLIO)
                )
                phase = v14._phase(day)
                if not (
                    phase in selection["phases"]
                    and float(prediction["confidence"]) >= float(selection["min_confidence"])
                    and float(prediction["uncertainty"]) / reference
                    <= float(selection["max_uncertainty_ratio"])
                    and change >= float(selection["min_change"])
                    and float(prediction["money_gap_ratio"])
                    <= float(selection["max_money_gap_ratio"])
                ):
                    continue
                actual = _portfolio(future_farms[player])
                records.append(
                    {
                        "source": source,
                        "episode_id": episode_id,
                        "day": day,
                        "phase": phase,
                        "confidence": float(prediction["confidence"]),
                        "uncertainty_ratio": float(prediction["uncertainty"]) / reference,
                        "change": change,
                        "money_gap_ratio": float(prediction["money_gap_ratio"]),
                        "improvement": _error(actual, baseline_target)
                        - _error(actual, candidate_target),
                    }
                )

    result = {
        "format": FORMAT,
        "selection_source": str(selection_path.relative_to(ROOT)),
        "selection": selection,
        "available_complete_episodes": dict(episode_counts),
        "winning_opponent_episodes": dict(winning_opponents),
        "overall": _summary(records),
        "by_source": {
            source: _summary([record for record in records if record["source"] == source])
            for source in SOURCES
        },
        "triggered_records": records,
        "interpretation": {
            "fact": "thresholds were frozen before these recent opponent trajectories were evaluated",
            "scope": "opponents that beat the submitted V14 or V18 agent",
            "limit": "future-goal fidelity is not a counterfactual score or rating estimate",
        },
    }
    output = ROOT / "data/analysis/v102_recent_opponent_confirmation.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    printable = {key: value for key, value in result.items() if key != "triggered_records"}
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
