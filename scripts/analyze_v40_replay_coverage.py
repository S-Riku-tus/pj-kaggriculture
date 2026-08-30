"""Measure whether V40 changes decisions on submitted V11 late-Cow states."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v40 import main as v40  # noqa: E402
from scripts.analyze_v33_asset_labor import _actions  # noqa: E402
from scripts.analyze_v34_labor_value import SOURCES  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    _manifest,
    _observation,
    _replay_path,
    _split,
)

FORMAT = "kaggriculture-v40-replay-coverage-v1"


def _field_actions(result: dict[str, Any]) -> list[list[Any]]:
    return [list(result.get("farmer") or ["PASS"]), *(result.get("hands") or [])]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=Path("data/analysis/v40_replay_coverage.json")
    )
    args = parser.parse_args()
    rows = []
    seen: set[tuple[str, int]] = set()
    for manifest in _manifest(SOURCES["v11"]):
        episode_id = str(manifest["episode_id"])
        seat = int(manifest["submission_seat"])
        key = (episode_id, seat)
        if key in seen:
            continue
        seen.add(key)
        replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
        for day in sorted(v40.COMPLETION_DAYS):
            for hour in range(v40.COMPLETION_START_HOUR, 24):
                step = day * 24 + hour
                obs = _observation(replay, step, seat)
                if obs is None:
                    continue
                v40.ENABLE_LATE_COW_COMPLETION = False
                safe = v40.agent(obs)
                v40.ENABLE_LATE_COW_COMPLETION = True
                candidate = v40.agent(obs)
                safe_actions = _field_actions(safe)
                candidate_actions = _field_actions(candidate)
                actual_actions = _actions(replay, step, seat)
                transitions = Counter()
                for before, after in zip(safe_actions, candidate_actions, strict=True):
                    if before != after:
                        transitions[f"{before[0]}->{after[0]}"] += 1
                rows.append(
                    {
                        "episode_id": episode_id,
                        "split": _split(episode_id),
                        "day": day,
                        "hour": hour,
                        "safe_matches_submitted": safe_actions == actual_actions,
                        "changed": safe_actions != candidate_actions,
                        "changed_actions": sum(transitions.values()),
                        "transitions": dict(transitions),
                    }
                )
    v40.ENABLE_LATE_COW_COMPLETION = False
    payload = {
        "format": FORMAT,
        "runtime_policy_enabled": False,
        "objective": "test V40 decision coverage on submitted V11 states without claiming causal value",
        "states": len(rows),
        "episodes": len({row["episode_id"] for row in rows}),
        "safe_submitted_match_rate": sum(row["safe_matches_submitted"] for row in rows)
        / max(1, len(rows)),
        "changed_states": sum(row["changed"] for row in rows),
        "changed_actions": sum(row["changed_actions"] for row in rows),
        "transitions": dict(
            sum((Counter(row["transitions"]) for row in rows), Counter())
        ),
        "changed_examples": [row for row in rows if row["changed"]],
        "by_split": {
            split: {
                "states": len(selected),
                "changed_states": sum(row["changed"] for row in selected),
                "changed_actions": sum(row["changed_actions"] for row in selected),
            }
            for split in ("train", "validation", "test")
            for selected in [[row for row in rows if row["split"] == split]]
        },
        "interpretation_limits": [
            "candidate actions are evaluated on fixed V11 states and do not include downstream feedback",
            "a decision change is coverage evidence rather than final-score value",
            "V14 safe-core equality with submitted V11 is checked rather than assumed",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
