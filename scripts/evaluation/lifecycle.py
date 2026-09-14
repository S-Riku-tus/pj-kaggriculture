"""Stage attribution of crop losses on the frozen engine; no safety gate relaxation."""

from __future__ import annotations

import copy
from collections import Counter

from .replay import action, decision_count, observation
from .safety import engine


def _private_product_units(private, item):
    return int(private.get("shed", {}).get(item, 0) or 0) + sum(
        int(inventory.get(item, 0) or 0)
        for inventory in private.get("inventories", [])
    )


def _apply_fields_and_count_harvest(farms, privates, actions, day):
    """Apply the standard field phase and return per-player HARVEST commits.

    Measuring immediately around each HARVEST avoids treating FEED consumption,
    COLLECT_FERTILIZER, PICKUP, or DROP in the same turn as harvested output.
    """
    harvested = [Counter(), Counter()]
    for player in (0, 1):
        current = actions[player] if isinstance(actions[player], dict) else {}
        hand_actions = current.get("hands", [])
        unit_actions = [
            current.get("farmer", ["PASS"]),
            *(hand_actions if isinstance(hand_actions, list) else []),
        ]
        demand = Counter(
            str(row[1])
            for row in unit_actions
            if isinstance(row, list) and len(row) >= 2 and row[0] == "PLANT"
        )
        seeds = privates[player].get("seeds", {})
        blocked = {
            crop for crop, count in demand.items() if count > int(seeds.get(crop, 0) or 0)
        }
        for index, requested in enumerate(unit_actions):
            effective = requested
            if (
                isinstance(requested, list)
                and len(requested) >= 2
                and requested[0] == "PLANT"
                and requested[1] in blocked
            ):
                effective = ["PASS"]
            before = {
                item: _private_product_units(privates[player], item)
                for item in engine.PRODUCTS
            }
            engine._apply_unit_action(
                farms[player], privates[player], index, effective, 10, day, 24, 100
            )
            if isinstance(requested, list) and requested and requested[0] == "HARVEST":
                for item in engine.PRODUCTS:
                    delta = _private_product_units(privates[player], item) - before[item]
                    if delta > 0:
                        harvested[player][item] += delta
    return harvested


def analyze_lifecycle(replay, seat, start=0):
    counts = Counter()
    units = Counter()
    terminal_yield = Counter()
    harvested = Counter()
    examples = []
    for step in range(start, decision_count(replay)):
        observations = [observation(replay, step, p) for p in (0, 1)]
        before = observations[seat]["farms"][seat]["tiles"]
        after = observation(replay, step + 1, seat)["farms"][seat]["tiles"]
        farms = copy.deepcopy(observations[0]["farms"])
        privates = [copy.deepcopy(obs["private"]) for obs in observations]
        turn_harvested = _apply_fields_and_count_harvest(
            farms,
            privates,
            [action(replay, step, p) for p in (0, 1)],
            step // 24,
        )
        harvested.update(turn_harvested[seat])
        field = copy.deepcopy(farms[seat]["tiles"])
        engine._decay_plants(farms[seat], step)
        decay = copy.deepcopy(farms[seat]["tiles"])
        if (step + 1) % 24 == 0:
            engine._daily_refresh_plants(farms[seat], step // 24, 24)
        refreshed = farms[seat]["tiles"]
        for y, row in enumerate(before):
            for x, tile in enumerate(row):
                f, d, r, final = field[y][x], decay[y][x], refreshed[y][x], after[y][x]
                if isinstance(f, dict) and f.get("kind") == "PLANT":
                    remaining = max(0, f.get("yield_units", 0))
                    later = max(0, d.get("yield_units", 0)) if isinstance(d, dict) else 0
                    units["lifespan_decay"] += max(0, remaining - later)
                    if d.get("kind") == "WEED":
                        terminal_yield[str(remaining)] += 1
                    elif r.get("kind") == "WEED":
                        units["water_death_current_yield"] += later
                if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                    counts["crop_turn_exposure"] += 1
                    if isinstance(final, dict) and final.get("kind") == "WEED":
                        cause = (
                            "field_action" if isinstance(f, dict) and f.get("kind") == "WEED"
                            else "lifespan_end" if isinstance(d, dict) and d.get("kind") == "WEED"
                            else "water_death" if isinstance(r, dict) and r.get("kind") == "WEED"
                            else "unresolved"
                        )
                        counts[cause] += 1
                        if len(examples) < 20:
                            examples.append(
                                {
                                    "step": step,
                                    "xy": [x, y],
                                    "cause": cause,
                                    "before": tile,
                                    "after_field": f,
                                }
                            )
                elif tile is None and isinstance(final, dict) and final.get("kind") == "WEED":
                    counts["empty_random_weed"] += 1
    return {
        "counts": dict(counts), "lost_current_units": dict(units),
        "lifespan_end_remaining_yield": dict(terminal_yield),
        "successful_harvest_units": dict(harvested), "examples": examples,
        "limits": (
            "Counts and current unharvested units, not lost future production "
            "or a causal coin mediation estimate"
        ),
    }
