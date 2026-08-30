"""Select joint-assignment strength using only nested validation episodes."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_joint_assignment_holdout import _finalize  # noqa: E402

BONUSES = (200, 400, 800, 1200, 1600)
OUTPUT = ROOT / "data/analysis/joint_assignment_bonus_selection.json"


def _path(bonus: int) -> Path:
    if bonus == 1600:
        return ROOT / "data/analysis/joint_assignment_meta_validation_dense.json"
    return ROOT / f"data/analysis/joint_assignment_validation_bonus{bonus}.json"


def _gain(bucket: dict[str, Any]) -> float:
    return round(
        float(bucket["methods"]["joint_blend"]["worker_exact"])
        - float(bucket["methods"]["baseline"]["worker_exact"]),
        5,
    )


def main() -> None:
    reports: list[dict[str, Any]] = []
    for bonus in BONUSES:
        payload = json.loads(_path(bonus).read_text(encoding="utf-8"))
        rows = [row for row in payload["rows"] if row["split"] == "validation"]
        fit = [row for row in rows if int(row["episode_id"]) % 5 <= 2]
        validation = [row for row in rows if int(row["episode_id"]) % 5 >= 3]
        overall = _finalize(validation)
        by_source = {
            source: _finalize([row for row in validation if row["source"] == source])
            for source in ("rank1", "rank2", "rank3")
        }
        by_future = {
            money_bin: _finalize(
                [row for row in validation if row["future72_money_bin"] == money_bin]
            )
            for money_bin in ("lt_-0.25", "-0.25_0", "0_0.25", "ge_0.25")
        }
        reports.append(
            {
                "bonus": bonus,
                "meta_fit": _finalize(fit),
                "meta_validation": overall,
                "worker_exact_gain": _gain(overall),
                "source_gains": {source: _gain(bucket) for source, bucket in by_source.items()},
                "future72_money_gains": {
                    money_bin: _gain(bucket) if bucket.get("states", 0) >= 20 else None
                    for money_bin, bucket in by_future.items()
                },
            }
        )
    eligible = [
        report
        for report in reports
        if report["worker_exact_gain"] > 0
        and report["meta_validation"]["joint_changed_state_rate"] >= 0.005
        and report["meta_validation"]["joint_worse_rate"] <= 0.01
        and all(value >= 0 for value in report["source_gains"].values())
        and all(
            value is None or value >= 0
            for value in report["future72_money_gains"].values()
        )
    ]
    selected = (
        max(
            eligible,
            key=lambda report: (
                report["worker_exact_gain"],
                -report["meta_validation"]["joint_worse_rate"],
                -report["bonus"],
            ),
        )
        if eligible
        else None
    )
    result = {
        "format": "kaggriculture-joint-assignment-bonus-selection-v1",
        "selection_data": "nested meta-validation episodes only",
        "criteria": {
            "positive_episode_balanced_worker_exact_gain": True,
            "minimum_changed_state_rate": 0.005,
            "maximum_worse_state_rate": 0.01,
            "all_teacher_sources_nonnegative": True,
            "all_future72_money_bins_with_at_least_20_states_nonnegative": True,
        },
        "reports": reports,
        "selected_bonus": selected["bonus"] if selected else None,
        "selection_status": "selected-for-untouched-test" if selected else "no-safe-strength",
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"result: {OUTPUT}")


if __name__ == "__main__":
    main()
