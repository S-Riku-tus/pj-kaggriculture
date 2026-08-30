"""Compare actual Wheat pickup-to-FEED missions in V11 and Top-3 logs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_v33_asset_labor import _actions, _farm, _positions  # noqa: E402
from scripts.analyze_v34_labor_value import SOURCES, _stats  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    _manifest,
    _observation,
    _replay_path,
    _split,
)

FORMAT = "kaggriculture-v52-feed-missions-v1"
DAYS = tuple(range(6, 13))
MOVES = {"NORTH", "SOUTH", "EAST", "WEST"}


def _count(inventory: Any, item: str) -> int:
    try:
        return max(0, int((inventory or {}).get(item, 0) or 0))
    except (AttributeError, TypeError, ValueError):
        return 0


def _finish(event: dict[str, Any], events: list[dict[str, Any]]) -> None:
    if event.get("finished"):
        return
    event["finished"] = True
    events.append(event)


def _day_row(
    replay: dict[str, Any], manifest: dict[str, str], source: str, day: int
) -> dict[str, Any] | None:
    seat = int(manifest["submission_seat"])
    episode_id = str(manifest["episode_id"])
    active: dict[int, dict[str, Any]] = {}
    events: list[dict[str, Any]] = []
    feeders: set[int] = set()
    feed_actions = 0
    for step in range(day * 24, (day + 1) * 24):
        obs = _observation(replay, step, seat)
        next_obs = _observation(replay, step + 1, seat)
        if obs is None or next_obs is None:
            continue
        private = obs.get("private") or {}
        next_private = next_obs.get("private") or {}
        inventories = list(private.get("inventories") or [])
        next_inventories = list(next_private.get("inventories") or [])
        positions = _positions(_farm(obs, seat))
        actions = _actions(replay, step, seat)
        for unit in range(1, min(len(positions), len(actions), len(inventories))):
            action = actions[unit]
            op = str(action[0]) if action else "PASS"
            before = _count(inventories[unit], "WHEAT")
            after = _count(next_inventories[unit], "WHEAT") if unit < len(next_inventories) else 0
            event = active.get(unit)
            if event is not None and step > event["step"]:
                if op in MOVES:
                    event["moves"] += 1
                elif op == "PASS":
                    event["passes"] += 1
                if op == "FEED" and before > 0:
                    event["feeds"] += 1
                    feeders.add(unit)
                    feed_actions += 1
                    if event["first_feed_lag"] is None:
                        event["first_feed_lag"] = step - event["step"]
                        event["first_route_excess"] = max(
                            0,
                            event["moves"]
                            - (
                                abs(positions[unit][0] - event["pickup_pos"][0])
                                + abs(positions[unit][1] - event["pickup_pos"][1])
                            ),
                        )
            elif op == "FEED" and before > 0:
                feeders.add(unit)
                feed_actions += 1

            if op == "PICKUP" and len(action) >= 2 and str(action[1]) == "WHEAT":
                if event is not None:
                    _finish(event, events)
                gained = max(0, after - before)
                if gained > 0:
                    active[unit] = {
                        "step": step,
                        "pickup_pos": positions[unit],
                        "units": gained,
                        "feeds": 0,
                        "moves": 0,
                        "passes": 0,
                        "first_feed_lag": None,
                        "first_route_excess": None,
                        "finished": False,
                    }
                else:
                    active.pop(unit, None)
            elif event is not None and step > event["step"] and after <= 0:
                _finish(event, events)
                active.pop(unit, None)

    for event in active.values():
        _finish(event, events)
    if not events and feed_actions == 0:
        return None
    fed_events = [event for event in events if event["first_feed_lag"] is not None]
    return {
        "source": source,
        "episode_id": episode_id,
        "split": _split(episode_id),
        "result": str(manifest.get("result") or "unknown").lower(),
        "day": day,
        "metrics": {
            "pickup_events": float(len(events)),
            "pickup_units": float(sum(event["units"] for event in events)),
            "pickup_units_per_event": mean([event["units"] for event in events]) if events else 0.0,
            "no_feed_events": float(sum(event["first_feed_lag"] is None for event in events)),
            "feed_within_3_rate": (
                sum(event["first_feed_lag"] <= 3 for event in fed_events) / len(events) if events else 0.0
            ),
            "feed_within_6_rate": (
                sum(event["first_feed_lag"] <= 6 for event in fed_events) / len(events) if events else 0.0
            ),
            "first_feed_lag": mean([event["first_feed_lag"] for event in fed_events]) if fed_events else 24.0,
            "first_route_excess": mean([event["first_route_excess"] for event in fed_events]) if fed_events else 24.0,
            "feeds_per_pickup": sum(event["feeds"] for event in events) / max(1, len(events)),
            "multi_feed_events": float(sum(event["feeds"] >= 2 for event in events)),
            "passes_before_finish": float(sum(event["passes"] for event in events)),
            "feed_actions": float(feed_actions),
            "unique_feeders": float(len(feeders)),
            "feeds_per_feeder": feed_actions / max(1, len(feeders)),
            "pickup_surplus_units": float(
                max(0, sum(event["units"] for event in events) - feed_actions)
            ),
        },
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"episode_days": 0}
    metrics = tuple(rows[0]["metrics"])
    return {
        "episode_days": len(rows),
        **{metric: _stats([row["metrics"][metric] for row in rows]) for metric in metrics},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v52_feed_missions.json"),
    )
    args = parser.parse_args()
    rows = []
    seen: set[tuple[str, str, int]] = set()
    for source, directory in SOURCES.items():
        manifests = _manifest(directory)
        for index, manifest in enumerate(manifests, start=1):
            if index == 1 or index % 50 == 0:
                print(f"[{source} {index}/{len(manifests)}]", flush=True)
            key = (source, str(manifest["episode_id"]), int(manifest["submission_seat"]))
            if key in seen:
                continue
            seen.add(key)
            replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
            for day in DAYS:
                row = _day_row(replay, manifest, source, day)
                if row is not None:
                    rows.append(row)
    payload = {
        "format": FORMAT,
        "runtime_policy_enabled": False,
        "objective": "identify mission conditions that make low-batch Wheat logistics viable",
        "data": {
            "episode_days": len(rows),
            "episodes": len({row["episode_id"] for row in rows}),
            "episode_disjoint_split": True,
        },
        "source_daily": {
            source: {
                str(day): {
                    "all": _summary([row for row in rows if row["source"] == source and row["day"] == day]),
                    "win": _summary(
                        [
                            row
                            for row in rows
                            if row["source"] == source and row["day"] == day and row["result"] == "win"
                        ]
                    ),
                }
                for day in DAYS
            }
            for source in SOURCES
        },
        "v11_by_split": {
            split: _summary([row for row in rows if row["source"] == "v11" and row["split"] == split])
            for split in ("train", "validation", "test")
        },
        "interpretation_limits": [
            "missions are inferred from observed successful pickup and later actions, not hidden teacher intent",
            "events end when Wheat reaches zero, another Wheat pickup occurs, or the day ends",
            "feed actions by pre-loaded workers without an observed same-day pickup count in daily feed totals only",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["data"], ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
