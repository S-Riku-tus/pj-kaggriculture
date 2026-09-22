"""Recompute the priority first-96-action Round4 opening diagnosis."""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "experiments/learning_round4_20260921/closed_loop/replays/round4_learned/qeinstein_moev2/seed_2026092421_seat_0.json.gz"
OUTPUT = ROOT / "experiments/learning_round5_20260921/OPENING_96_DIAGNOSIS.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.learning_round5_20260921.action_codec import normalize_action  # noqa: E402
from agents.learning_round5_20260921.executor import ExecutionCoordinator  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def animals(observation: dict[str, Any], seat: int) -> set[tuple[int, int, str, int]]:
    result = set()
    for y, row in enumerate(observation["farms"][seat]["tiles"]):
        for x, tile in enumerate(row):
            if isinstance(tile, dict) and tile.get("animal"):
                result.add((x, y, str(tile["animal"]), int(tile["placed_day"])))
    return result


def main() -> None:
    with gzip.open(SOURCE, "rt", encoding="utf-8") as stream:
        replay = json.load(stream)
    seat = 0
    event_counts = Counter()
    opening_orders = []
    disappearances = []
    cash_zero = []
    repairs = []
    for record in range(1, 97):
        before = copy.deepcopy(replay["steps"][record - 1][seat]["observation"])
        before["player"] = seat
        before["step"] = record - 1
        after = replay["steps"][record][seat]["observation"]
        action = replay["steps"][record][seat].get("action") or {}
        if record <= 8:
            opening_orders.append({"record": record, "decision_step": record - 1, "market": action.get("market", [])})
        for order in action.get("market", []):
            event_counts[f"market:{order[0]}:{order[1] if len(order) > 1 else ''}"] += int(order[2]) if len(order) > 2 else 1
        for unit in [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]:
            event_counts[f"primitive:{unit[0]}"] += 1
        missing = sorted(animals(before, seat) - animals(after, seat))
        if missing:
            disappearances.append({"record": record, "decision_step": record - 1, "animals": [list(value) for value in missing]})
        if int(after["farms"][seat]["money"]) == 0:
            cash_zero.append(record)
        coordinator = ExecutionCoordinator("opening-static-repair-probe")
        repaired = coordinator.repair(before, action, {"ANIMAL_LIFECYCLE_REALIZATION": 1.0})
        if normalize_action(repaired) != normalize_action(action):
            repairs.append({
                "record": record,
                "decision_step": record - 1,
                "before_money": int(before["farms"][seat]["money"]),
                "before_wheat": int(before["private"]["shed"].get("WHEAT", 0)),
                "proposal": action,
                "repaired": repaired,
                "portfolio": coordinator.animal_plans(),
                "diagnostics": coordinator.diagnostics(),
            })
    output = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "source_replay": str(SOURCE.relative_to(ROOT)),
        "source_replay_sha256": sha256(SOURCE),
        "scope": "records 1..96 recomputed from the saved Round4 learned replay",
        "observed_opening_orders_records_1_8": opening_orders,
        "observed_event_counts_first_96": dict(event_counts),
        "first_animal_disappearance": disappearances[0] if disappearances else None,
        "all_animal_disappearances_first_96": disappearances,
        "first_cash_zero_record": cash_zero[0] if cash_zero else None,
        "cash_zero_records": cash_zero,
        "static_round5_repair_probe": {
            "warning": "each saved Round4 state/action is repaired independently; this is not a continued engine counterfactual",
            "changed_records": len(repairs),
            "first_changes": repairs[:20],
        },
    }
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "first_animal_disappearance": output["first_animal_disappearance"],
        "first_cash_zero_record": output["first_cash_zero_record"],
        "changed_records": len(repairs),
        "counts": dict(event_counts),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
