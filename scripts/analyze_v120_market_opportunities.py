"""Measure concrete correctness/market-overlay opportunities in saved replays.

Replay entries store the action selected from the preceding observation, so the
analysis deliberately pairs ``steps[t]`` observations with ``steps[t + 1]``
actions.  The report is descriptive only: it does not claim that every detected
opportunity is profitable.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

SELLABLE = (
    "WHEAT",
    "CARROT",
    "TOMATO",
    "STRAWBERRY",
    "MELON",
    "EGG",
    "MILK",
    "WOOL",
    "FERTILIZER",
)
PREMIUM = ("STRAWBERRY", "MELON", "MILK", "WOOL", "TOMATO")


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _integer(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _tile(farm: dict[str, Any], position: Any) -> Any:
    try:
        x, y = map(int, position)
        return farm["tiles"][y][x]
    except (KeyError, IndexError, TypeError, ValueError):
        return "LOCKED"


def _weed_collisions(observation: dict[str, Any], action: dict[str, Any]) -> int:
    player = _integer(observation.get("player"))
    farms = list(observation.get("farms") or [])
    farm = _mapping(farms[player]) if player < len(farms) else {}
    positions = [farm.get("farmer"), *(farm.get("hands") or [])]
    actions = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
    count = 0
    for position, unit_action in zip(positions, actions, strict=False):
        if not unit_action or unit_action[0] not in {"BUILD_PASTURE", "PLANT"}:
            continue
        if _mapping(_tile(farm, position)).get("kind") == "WEED":
            count += 1
    return count


def _clone_distance(observation: dict[str, Any]) -> int:
    farms = list(observation.get("farms") or [])
    if len(farms) < 2:
        return 10**9

    def signature(farm: dict[str, Any]) -> tuple[int, int, tuple[int, ...]]:
        keys = sorted(
            ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "COW", "SHEEP", "GOOSE", "PASTURE", "COOP", "WEED")
        )
        counts = dict.fromkeys(keys, 0)
        for row in farm.get("tiles") or []:
            for raw in row:
                tile = _mapping(raw)
                for field in ("crop", "animal", "kind"):
                    value = str(tile.get(field, "")).upper()
                    if value in counts:
                        counts[value] += 1
                        break
        return (
            len(farm.get("hands") or []),
            len(farm.get("unlocked_quadrants") or []),
            tuple(counts[key] for key in keys),
        )

    left, right = signature(_mapping(farms[0])), signature(_mapping(farms[1]))
    return abs(left[0] - right[0]) + 3 * abs(left[1] - right[1]) + sum(
        abs(a - b) for a, b in zip(left[2], right[2], strict=True)
    )


def _market(action: dict[str, Any]) -> list[list[Any]]:
    return [list(order) for order in action.get("market") or [] if isinstance(order, list)]


def _sells(action: dict[str, Any]) -> list[list[Any]]:
    return [order for order in _market(action) if len(order) >= 3 and order[0] == "SELL"]


def _available_shed(observation: dict[str, Any]) -> dict[str, int]:
    shed = _mapping(_mapping(observation.get("private")).get("shed"))
    return {item: max(0, _integer(shed.get(item))) for item in SELLABLE}


def analyze(paths: list[Path]) -> dict[str, Any]:
    report: Counter[str] = Counter()
    by_item: Counter[str] = Counter()
    terminal_leftovers: Counter[str] = Counter()
    future_horizons: Counter[str] = Counter()
    seen_files: set[Path] = set()

    files: list[Path] = []
    for path in paths:
        candidates = [path] if path.is_file() else sorted(path.rglob("*.json"))
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved not in seen_files:
                seen_files.add(resolved)
                files.append(candidate)

    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        steps = list(payload.get("steps") or [])
        if len(steps) < 2:
            continue
        report["games"] += 1
        report["seats"] += len(steps[0])
        for seat in range(len(steps[0])):
            observations: list[dict[str, Any]] = []
            actions: list[dict[str, Any]] = []
            for turn in range(len(steps) - 1):
                observation = _mapping(steps[turn][seat].get("observation"))
                action = _mapping(steps[turn + 1][seat].get("action"))
                observations.append(observation)
                actions.append(action)
                report["turns"] += 1

                market = _market(action)
                sells = _sells(action)
                report["market_orders"] += len(market)
                report["sell_orders"] += len(sells)
                report["full_market_turns"] += len(market) >= 10
                report["multi_sell_turns"] += len(sells) >= 2
                report["weed_collisions"] += _weed_collisions(observation, action)
                report["near_clone_turns"] += _clone_distance(observation) <= 6
                if len({str(order[1]) for order in sells}) < len(sells):
                    report["duplicate_sell_turns"] += 1

                shed = _available_shed(observation)
                for order in sells:
                    item, quantity = str(order[1]), max(0, _integer(order[2]))
                    by_item[item] += 1
                    if quantity <= 0:
                        report["zero_quantity_sells"] += 1
                    if shed.get(item, 0) <= 0:
                        report["empty_shed_sells"] += 1

                hour = _integer(observation.get("hour"))
                if hour in {21, 22}:
                    shed_total = sum(_available_shed(observation).values())
                    inventories = list(_mapping(observation.get("private")).get("inventories") or [])
                    carried = sum(
                        max(0, _integer(quantity))
                        for inventory in inventories
                        for item, quantity in _mapping(inventory).items()
                        if item in SELLABLE
                    )
                    report["pre_overflow_checks"] += 1
                    report["pre_overflow_shed_90"] += shed_total >= 90
                    report["pre_overflow_total_100"] += shed_total + carried > 100

            for turn, (observation, action) in enumerate(zip(observations, actions, strict=True)):
                if not (120 <= turn < 680) or _clone_distance(observation) > 6:
                    continue
                shed = _available_shed(observation)
                current_items = {str(order[1]) for order in _sells(action)}
                for horizon in (1, 2, 3):
                    if turn + horizon >= len(actions):
                        continue
                    future = _sells(actions[turn + horizon])
                    eligible = [
                        order
                        for order in future
                        if str(order[1]) in PREMIUM
                        and max(0, _integer(order[2])) >= 4
                        and shed.get(str(order[1]), 0) > 0
                        and str(order[1]) not in current_items
                        and len(_market(action)) < 10
                    ]
                    if eligible:
                        future_horizons[str(horizon)] += 1

            final_observation = observations[-1]
            final_shed = _available_shed(final_observation)
            leftover = sum(final_shed.values())
            report["terminal_leftover_units"] += leftover
            report["terminal_nonempty_seats"] += leftover > 0
            for item, quantity in final_shed.items():
                terminal_leftovers[item] += quantity

    return {
        "counts": dict(sorted(report.items())),
        "sell_orders_by_item": dict(sorted(by_item.items())),
        "future_sell_preemption_opportunities": dict(sorted(future_horizons.items())),
        "terminal_leftovers_by_item": dict(sorted(terminal_leftovers.items())),
        "replay_files": [str(path) for path in files],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = analyze(args.paths)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
