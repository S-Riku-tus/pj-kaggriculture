"""Scan held-out closed-loop replays for effective V17 herd-gate states."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v17 import main as v17  # noqa: E402

SEAT_PATTERN = re.compile(r"_seat_([01])\.json$")


def _paths(replay_root: Path, limit: int) -> list[Path]:
    paths = [
        path
        for path in replay_root.glob("*safe-core*/*.json")
        if any(token in path.parent.name for token in ("v14_", "v15_", "v16_", "v17_"))
    ]
    paths.sort(key=lambda path: (path.stat().st_mtime_ns, str(path)), reverse=True)
    return paths[:limit] if limit > 0 else paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-root", type=Path, default=Path("data/replays"))
    parser.add_argument("--max-files", type=int, default=80)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v17_gate_replay_coverage.json"),
    )
    args = parser.parse_args()
    replay_root = args.replay_root if args.replay_root.is_absolute() else ROOT / args.replay_root
    paths = _paths(replay_root, args.max_files)
    reasons: Counter[str] = Counter()
    decisions: Counter[str] = Counter()
    effective_files: set[str] = set()
    effective_days: set[tuple[str, int]] = set()
    effective_steps = 0
    evaluated_steps = 0
    examples: list[dict[str, Any]] = []
    for file_index, path in enumerate(paths, start=1):
        print(f"[{file_index}/{len(paths)}] {path.parent.name}/{path.name}", flush=True)
        match = SEAT_PATTERN.search(path.name)
        if match is None:
            continue
        seat = int(match.group(1))
        replay = json.loads(path.read_text(encoding="utf-8"))
        for states in replay.get("steps") or []:
            observation = states[seat].get("observation") or {}
            day = int(observation.get("day", 0) or 0)
            if not 6 <= day <= 19:
                continue
            farms = observation.get("farms") or []
            player = int(observation.get("player", seat))
            if len(farms) < 2 or not 0 <= player < len(farms):
                continue
            farm, opponent = farms[player], farms[1 - player]
            gate = v17._herd_gate_prediction(observation, farm, opponent)
            evaluated_steps += 1
            reasons[str(gate.get("reason") or "missing")] += 1
            decisions[str(gate.get("decision") or "fallback")] += 1
            if not gate.get("active") or gate.get("decision") != "freeze-owned":
                continue
            private = observation.get("private") or {}
            baseline = v17._SAFE_STRATEGY_TARGETS(observation, farm, opponent, private)[0]
            owned = {animal: v17.v4._owned_animals(farm, private, animal) for animal in ("COW", "SHEEP")}
            if all(owned[animal] >= baseline[animal] for animal in owned):
                continue
            effective_steps += 1
            relative = str(path.relative_to(ROOT))
            effective_files.add(relative)
            effective_days.add((relative, day))
            if len(examples) < 30:
                examples.append(
                    {
                        "replay": relative,
                        "seat": seat,
                        "day": day,
                        "hour": int(observation.get("hour", 0) or 0),
                        "baseline": {animal: int(baseline[animal]) for animal in owned},
                        "owned": owned,
                        "money_gap_ratio": gate.get("money_gap_ratio"),
                        "advantage": gate.get("advantage"),
                        "uncertainty": gate.get("uncertainty"),
                    }
                )
    payload = {
        "agent": "agents/v17/main.py",
        "source": "saved V14-V17 safe-core closed-loop replays",
        "files": len(paths),
        "evaluated_steps": evaluated_steps,
        "reason_counts": dict(reasons),
        "decision_counts": dict(decisions),
        "effective_change_steps": effective_steps,
        "effective_change_days": len(effective_days),
        "effective_change_files": len(effective_files),
        "examples": examples,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
