"""Aggregate plan telemetry without treating proposal rejection as engine illegality."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


ROUND13 = Path(__file__).resolve().parents[1]
GAMES = ROUND13 / "metrics/development/games.csv"
SUMS = ROUND13 / "metrics/development/paired_summary.json"


def main() -> None:
    with GAMES.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    failures = json.loads((GAMES.parent / "failures.json").read_text(encoding="utf-8"))
    paired = json.loads(SUMS.read_text(encoding="utf-8"))
    paired_by_arm = {entry["arm"]: entry for entry in paired["summaries"]}
    output = {}
    for arm in ("M1_deadline_market", "P_EARLY4", "P_ROTATE2"):
        selected = [row for row in rows if row["arm"] == arm]
        telemetry_sums = Counter()
        status = Counter()
        first_plant = defaultdict(list)
        harvested = Counter()
        sold = Counter()
        revenue = Counter()
        expenses = Counter()
        terminal_animals = Counter()
        for row in selected:
            telemetry = json.loads(row["telemetry_json"])
            route = json.loads(row["route_metrics_json"])
            status[row["completion_status"]] += 1
            for key, value in telemetry.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    telemetry_sums[key] += value
            for item, day in (route.get("first_plant_day") or {}).items():
                first_plant[item].append(int(day))
            harvested.update(route.get("harvest_units") or {})
            sold.update(route.get("sold_units") or {})
            revenue.update(route.get("sales_revenue") or {})
            expenses.update(route.get("expenses") or {})
            terminal_animals.update(route.get("terminal_animals") or {})
        output[arm] = {
            "games": len(selected),
            "engine_failures": sum(entry.get("arm") == arm for entry in failures),
            "completion_statuses_raw_runner": dict(sorted(status.items())),
            "telemetry_totals": dict(sorted(telemetry_sums.items())),
            "first_plant_day_range": {item: [min(values), max(values)] for item, values in sorted(first_plant.items())},
            "harvested_units_total": dict(sorted(harvested.items())),
            "sold_units_total": dict(sorted(sold.items())),
            "sales_revenue_total": dict(sorted(revenue.items())),
            "expenses_total": dict(sorted(expenses.items())),
            "terminal_animals_total": dict(sorted(terminal_animals.items())),
            "paired_outcome": paired_by_arm[arm],
            "proposal_rejection_note": "invalid_candidates counts rejected internal proposals followed by KEEP_B1; no invalid action was sent to the engine.",
        }
    target = ROUND13 / "analysis/candidate_realization_summary.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
