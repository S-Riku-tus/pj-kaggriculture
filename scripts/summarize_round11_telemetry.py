"""Aggregate per-game diagnostics emitted by Round11 experimental arms."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def numeric_totals(value: object, prefix: str = "") -> dict[str, float]:
    totals: dict[str, float] = {}
    if not isinstance(value, dict):
        return totals
    for key, child in value.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(child, dict):
            totals.update(numeric_totals(child, name))
        elif isinstance(child, (int, float)) and not isinstance(child, bool):
            totals[name] = float(child)
    return totals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("panel", type=Path, help="Panel directory containing games.csv")
    args = parser.parse_args()
    panel = args.panel if args.panel.is_absolute() else ROOT / args.panel
    with (panel / "games.csv").open(encoding="utf-8-sig", newline="") as handle:
        games = list(csv.DictReader(handle))

    aggregate: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    game_counts: dict[str, int] = defaultdict(int)
    games_with_changes: dict[str, int] = defaultdict(int)
    for row in games:
        arm = row["arm"]
        raw = row.get("diagnostics_json") or "{}"
        diagnostics = json.loads(raw)
        flattened = numeric_totals(diagnostics)
        game_counts[arm] += 1
        for key, value in flattened.items():
            aggregate[arm][key] += value
        if flattened.get("changes", 0) > 0 or flattened.get("parent.forecast.frontier_fires", 0) > 0:
            games_with_changes[arm] += 1

    fieldnames = ["arm", "games", "games_with_reported_changes", "metric", "total", "per_game"]
    rows = []
    structured = {"schema": "round11-telemetry-summary-v1", "arms": {}}
    for arm in sorted(game_counts):
        metrics = aggregate[arm]
        structured["arms"][arm] = {
            "games": game_counts[arm],
            "games_with_reported_changes": games_with_changes[arm],
            "totals": dict(sorted(metrics.items())),
        }
        for metric, total in sorted(metrics.items()):
            rows.append(
                {
                    "arm": arm,
                    "games": game_counts[arm],
                    "games_with_reported_changes": games_with_changes[arm],
                    "metric": metric,
                    "total": total,
                    "per_game": total / game_counts[arm],
                }
            )

    with (panel / "telemetry_summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    (panel / "telemetry_summary.json").write_text(
        json.dumps(structured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(structured, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
