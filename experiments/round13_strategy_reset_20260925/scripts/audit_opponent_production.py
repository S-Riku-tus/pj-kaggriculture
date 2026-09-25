"""Summarize realized opponent production from the frozen development baseline."""

from __future__ import annotations

import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path


ROUND13 = Path(__file__).resolve().parents[1]
ROOT = ROUND13.parents[1]
REPLAYS = ROUND13 / "metrics/development/replays/D0_B1"


def main() -> None:
    report = {}
    for opponent_dir in sorted(path for path in REPLAYS.iterdir() if path.is_dir()):
        action_counts = Counter()
        planted = Counter()
        seed_buys = Counter()
        animal_buys = Counter()
        sell_units = Counter()
        first_plant_days: dict[str, list[int]] = defaultdict(list)
        terminal_animals = Counter()
        terminal_cash = []
        games = 0
        for path in sorted(opponent_dir.glob("*.json.gz")):
            seat = int(path.stem.split("_seat_")[-1].split(".")[0])
            opponent_seat = 1 - seat
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                replay = json.load(stream)
            games += 1
            seen = set()
            for decision in replay["decisions"]:
                observation = decision["observations"][opponent_seat]
                action = decision["actions"][opponent_seat]
                unit_commands = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
                for command in unit_commands:
                    if not command:
                        continue
                    kind = command[0]
                    action_counts[kind] += 1
                    if kind == "PLANT" and len(command) >= 2:
                        crop = command[1]
                        planted[crop] += 1
                        if crop not in seen:
                            first_plant_days[crop].append(int(observation["day"]))
                            seen.add(crop)
                for order in action.get("market") or []:
                    if not order:
                        continue
                    action_counts[order[0]] += 1
                    if order[0] == "BUY_SEED" and len(order) >= 3:
                        seed_buys[order[1]] += int(order[2])
                    elif order[0] == "BUY_ANIMAL" and len(order) >= 3:
                        animal_buys[order[1]] += int(order[2])
                    elif order[0] == "SELL" and len(order) >= 3:
                        sell_units[order[1]] += int(order[2])
            terminal = replay["terminal"]
            terminal_cash.append(float(terminal["rewards"][opponent_seat]))
            farm = terminal["observations"][opponent_seat]["farms"][opponent_seat]
            for row in farm["tiles"]:
                for tile in row:
                    if isinstance(tile, dict) and tile.get("animal"):
                        terminal_animals[tile["animal"]] += 1
        report[opponent_dir.name] = {
            "games": games,
            "actual_reactive_actions": dict(sorted(action_counts.items())),
            "planted_by_crop": dict(sorted(planted.items())),
            "first_plant_day_range": {
                crop: [min(values), max(values)] for crop, values in sorted(first_plant_days.items())
            },
            "seed_units_bought": dict(sorted(seed_buys.items())),
            "animal_units_bought": dict(sorted(animal_buys.items())),
            "sale_units_ordered": dict(sorted(sell_units.items())),
            "terminal_animals_total": dict(sorted(terminal_animals.items())),
            "mean_terminal_cash": sum(terminal_cash) / len(terminal_cash),
        }
    output = ROUND13 / "analysis/opponent_production_audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
