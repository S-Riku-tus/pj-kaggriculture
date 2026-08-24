"""Distill Rank 1's high-consensus Day 1-3 choreography for V8.

Replay actions are stored one step after the observation that produced them.
The output therefore pairs observation ``steps[t]`` with action
``steps[t + 1]``.  Only the interval whose exact-action consensus remains
high across public opponents is emitted; later play is handled by the learned
state policy rather than a brittle fixed script.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "submissions" / "leaderboard_rank1_submission_55614463"


def _rows() -> list[dict[str, str]]:
    with (SOURCE / "manifest.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [
        row
        for row in rows
        if row.get("replay_status") in {"downloaded", "skipped_existing"}
        and row.get("opponent_team_name") != row.get("team_name")
    ]


def _replay_path(row: dict[str, str]) -> Path:
    relative = Path(row["replay_path"])
    direct = ROOT / relative
    return direct if direct.is_file() else ROOT / "data" / relative


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first-day", type=int, default=1)
    parser.add_argument("--last-day", type=int, default=5)
    parser.add_argument("--minimum-field-consensus", type=float, default=0.75)
    parser.add_argument("--output", type=Path, default=Path("agents/v8/expert_opening_actions.json"))
    args = parser.parse_args()

    rows = _rows()
    start = args.first_day * 24
    stop = (args.last_day + 1) * 24
    action_counts = [Counter() for _ in range(start, stop)]
    field_counts = [Counter() for _ in range(start, stop)]
    market_counts = [Counter() for _ in range(start, stop)]
    position_counts = [Counter() for _ in range(start, stop)]
    for index, row in enumerate(rows, 1):
        with _replay_path(row).open(encoding="utf-8") as handle:
            replay = json.load(handle)
        seat = int(row["submission_seat"])
        for offset, step in enumerate(range(start, stop)):
            observation = replay["steps"][step][seat].get("observation") or {}
            action = replay["steps"][step + 1][seat].get("action") or {
                "farmer": ["PASS"],
                "hands": [],
                "market": [],
            }
            farms = observation.get("farms", [])
            player = int(observation.get("player", seat))
            if not 0 <= player < len(farms):
                continue
            farm = farms[player]
            positions = {
                "farmer": farm.get("farmer", [0, 0]),
                "hands": farm.get("hands", []) or [],
            }
            action_counts[offset][_canonical(action)] += 1
            field_counts[offset][
                _canonical(
                    {
                        "farmer": action.get("farmer", ["PASS"]),
                        "hands": action.get("hands", []) or [],
                    }
                )
            ] += 1
            market_counts[offset][_canonical(action.get("market", []) or [])] += 1
            position_counts[offset][_canonical(positions)] += 1
        if index % 25 == 0 or index == len(rows):
            print(f"loaded {index}/{len(rows)}", flush=True)

    entries = []
    for offset, step in enumerate(range(start, stop)):
        action_json, action_count = action_counts[offset].most_common(1)[0]
        field_json, field_count = field_counts[offset].most_common(1)[0]
        market_json, market_count = market_counts[offset].most_common(1)[0]
        positions_json, position_count = position_counts[offset].most_common(1)[0]
        field_agreement = field_count / len(rows)
        if field_agreement < args.minimum_field_consensus:
            raise SystemExit(
                f"step {step} field consensus {field_agreement:.3f} is below "
                f"{args.minimum_field_consensus:.3f}"
            )
        field = json.loads(field_json)
        action = {
            "farmer": field["farmer"],
            "hands": field["hands"],
            "market": json.loads(market_json),
        }
        entries.append(
            {
                "day": step // 24,
                "hour": step % 24,
                "action": action,
                "expected_positions": json.loads(positions_json),
                "action_consensus": round(action_count / len(rows), 6),
                "field_consensus": round(field_agreement, 6),
                "market_consensus": round(market_count / len(rows), 6),
                "position_consensus": round(position_count / len(rows), 6),
            }
        )

    payload = {
        "format": "kaggriculture-v8-rank1-opening-v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "source": str(SOURCE.relative_to(ROOT)),
        "episodes": len(rows),
        "first_day": args.first_day,
        "last_day": args.last_day,
        "minimum_action_consensus": min(entry["action_consensus"] for entry in entries),
        "minimum_field_consensus": min(entry["field_consensus"] for entry in entries),
        "entries": entries,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(f"opening: {output} ({output.stat().st_size} bytes)")
    print(f"minimum action consensus: {payload['minimum_action_consensus']:.3f}")
    print(f"minimum field consensus: {payload['minimum_field_consensus']:.3f}")
    print(f"sha256: {digest}")


if __name__ == "__main__":
    main()
