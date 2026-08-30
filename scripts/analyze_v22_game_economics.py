"""Derive first-principles Kaggriculture economics from the installed engine.

This is not a policy scorer.  It establishes invariant mechanics and simple
upper/lower economic envelopes that can be compared with replay behaviour.
Travel, congestion, opponent supply, inventory overflow, and action deadlines
are deliberately reported as omitted costs rather than hidden in a single ROI.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from kaggle_environments.envs.kaggriculture import kaggriculture as game

ROOT = Path(__file__).resolve().parents[1]
FORMAT = "kaggriculture-v22-first-principles-v1"
SEASON_DAYS = 30
TURNS_PER_DAY = 24
EPISODE_STEPS = SEASON_DAYS * TURNS_PER_DAY
SHOP_UNLOCK_DAYS = tuple(range(3, 25, 3))


def _market_curves() -> dict[str, Any]:
    curves: dict[str, Any] = {}
    for item, params in game.MARKET_PARAMS.items():
        scale = int(params["T"])
        points = {}
        for ratio in (-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0):
            inventory = int(params["I0"] + ratio * scale)
            points[str(ratio)] = {
                "inventory": inventory,
                "price": game.market_price(item, inventory),
            }
        i0 = int(params["I0"])
        curves[item] = {
            "parameters": dict(params),
            "points_by_T_delta": points,
            "one_unit_price_impact_at_I0": {
                "scarcity": game.market_price(item, i0 - 1) - game.market_price(item, i0),
                "glut": game.market_price(item, i0 + 1) - game.market_price(item, i0),
            },
            "price_at_positive_T_glut": game.market_price(item, i0 + scale),
            "price_at_negative_T_scarcity": game.market_price(item, i0 - scale),
        }
    return curves


def _shop_consumption_events(unlock_day: int) -> int:
    first_step = unlock_day * TURNS_PER_DAY
    last_processed_step = EPISODE_STEPS - 4
    return (last_processed_step - first_step) // 4 + 1


def _town_demand() -> dict[str, Any]:
    events = {str(day): _shop_consumption_events(day) for day in SHOP_UNLOCK_DAYS}
    event_sum = sum(events.values())
    weighted_shop_incidence: Counter[str] = Counter()
    for products in game.SHOPS.values():
        multiplier = 2 if len(products) == 1 else 1
        for product in products:
            weighted_shop_incidence[product] += multiplier
    center_events = len(range(0, EPISODE_STEPS - 1, 24))
    expected: dict[str, Any] = {}
    for item in game.PRODUCTS:
        if item == "FERTILIZER":
            center = 0.0
        else:
            center = float(center_events)
        shop = event_sum * weighted_shop_incidence[item] / len(game.SHOPS)
        expected[item] = {
            "center_units": center,
            "expected_shop_units": shop,
            "expected_total_units": center + shop,
            "weighted_shop_incidence_of_8": weighted_shop_incidence[item],
        }
    return {
        "unlock_days": list(SHOP_UNLOCK_DAYS),
        "consumption_events_per_unlock": events,
        "events_summed_across_eight_draws": event_sum,
        "shops_drawn_with_replacement": True,
        "expected_season_units": expected,
    }


def _crop_output(crop: str, fertilized: bool) -> int:
    spec = game.CROPS[crop]
    if spec["ongoing"]:
        per_event = 2 if fertilized else 1
        return int(spec["max_yield"] * per_event)
    window_start = (int(spec["max_yield_day"]) + 1) // 2
    water_days = int(spec["max_yield_day"]) - window_start + 1
    # One-time crops start with one stored unit before any production-window
    # WATER.  This differs from ongoing crops, whose stored yield starts at 0.
    return min(int(spec["max_yield"]), 1 + water_days * (2 if fertilized else 1))


def _cover_with_three_day_windows(days: list[int]) -> int:
    remaining = sorted(days)
    count = 0
    while remaining:
        start = remaining[0]
        remaining = [day for day in remaining if day > start + 2]
        count += 1
    return count


def _minimum_survival_waters(lifespan: int, mandatory: set[int]) -> int:
    # state: previous consecutive-unwatered count -> minimum WATER actions.
    costs = {1: 0}
    for day in range(lifespan + 1):
        next_costs: dict[int, int] = {}
        for consecutive, cost in costs.items():
            if day not in mandatory and consecutive + 1 < 2:
                next_costs[consecutive + 1] = min(next_costs.get(consecutive + 1, 10**9), cost)
            next_costs[0] = min(next_costs.get(0, 10**9), cost + 1)
        costs = next_costs
    return min(costs.values())


def _minimum_one_time_plan(crop: str, fertilized: bool) -> tuple[int, int]:
    """Return exact WATER/FERTILIZE counts for maximum one-time output.

    The enumeration includes the planting-day consecutive-unwatered value of
    one, permits harvest as soon as the maximum is reached, and counts a
    three-day fertilizer window only when its bonus is needed.
    """
    spec = game.CROPS[crop]
    first = int(spec["first_yield_day"])
    last = int(spec["max_yield_day"])
    window_start = (last + 1) // 2
    target = _crop_output(crop, fertilized)
    best: tuple[int, int, int, int] | None = None
    for harvest_day in range(first, last + 1):
        days = range(harvest_day + 1)
        for mask in range(1 << (harvest_day + 1)):
            watered = {day for day in days if mask & (1 << day)}
            consecutive = 1
            alive = True
            for day in days:
                consecutive = 0 if day in watered else consecutive + 1
                if consecutive >= 2:
                    alive = False
                    break
            if not alive:
                continue
            production = sorted(day for day in watered if window_start <= day <= harvest_day)
            base_output = min(int(spec["max_yield"]), 1 + len(production))
            fertilizer_actions = 0
            if fertilized:
                bonus_needed = max(0, target - base_output)
                if bonus_needed > len(production):
                    continue
                if bonus_needed:
                    fertilizer_actions = min(
                        _cover_with_three_day_windows(list(selected))
                        for selected in itertools.combinations(production, bonus_needed)
                    )
            elif base_output < target:
                continue
            key = (len(watered) + fertilizer_actions, harvest_day, len(watered), fertilizer_actions)
            if best is None or key < best:
                best = key
    if best is None:
        raise RuntimeError(f"no service plan found for {crop}, fertilized={fertilized}")
    return best[2], best[3]


def _crop_actions(crop: str, fertilized: bool) -> dict[str, int]:
    """Return tile-operation lower bounds; routing and market orders are extra."""
    spec = game.CROPS[crop]
    lifespan = (
        int(spec["first_yield_day"]) + int(spec["interval"]) * (int(spec["max_yield"]) - 1)
        if spec["ongoing"]
        else int(spec["max_yield_day"])
    )
    if spec["ongoing"]:
        production_days = [
            int(spec["first_yield_day"]) + int(spec["interval"]) * index
            for index in range(int(spec["max_yield"]))
        ]
        mandatory_waters = {0, *production_days} if fertilized else {0}
        harvests = math.ceil(_crop_output(crop, fertilized) / int(spec["max_yield"]))
        fertilizes = _cover_with_three_day_windows(production_days) if fertilized else 0
        waters = _minimum_survival_waters(lifespan, mandatory_waters)
    else:
        harvests = 1
        waters, fertilizes = _minimum_one_time_plan(crop, fertilized)
    return {
        "plant": 1,
        "water_lower_bound": waters,
        "harvest_lower_bound": harvests,
        "fertilize_lower_bound": fertilizes,
        "tile_actions_lower_bound": 1 + waters + harvests + fertilizes,
    }


def _crop_economics(curves: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for crop, spec in game.CROPS.items():
        scenarios: dict[str, Any] = {}
        for fertilized in (False, True):
            output = _crop_output(crop, fertilized)
            prices = {
                "floor": game.PRICE_FLOOR,
                "T_glut": curves[crop]["price_at_positive_T_glut"],
                "base": int(game.MARKET_PARAMS[crop]["base"]),
                "T_scarcity": curves[crop]["price_at_negative_T_scarcity"],
            }
            scenarios["fertilized" if fertilized else "unfertilized"] = {
                "maximum_units_if_serviced": output,
                "cash_margin_before_actions": {
                    name: output * price - int(spec["seed"]) for name, price in prices.items()
                },
                "price_scenarios": prices,
                "field_action_lower_bounds": _crop_actions(crop, fertilized),
            }
        first_yield = int(spec["first_yield_day"])
        if spec["ongoing"]:
            full_cycle_day = first_yield + int(spec["interval"]) * (int(spec["max_yield"]) - 1)
        else:
            full_cycle_day = int(spec["max_yield_day"])
        result[crop] = {
            "seed_cost": int(spec["seed"]),
            "first_yield_day": first_yield,
            "latest_plant_day_for_one_harvest": 29 - first_yield,
            "latest_plant_day_for_full_cycle": 29 - full_cycle_day,
            "scenarios": scenarios,
            "omitted_costs": [
                "travel",
                "market order capacity",
                "fertilizer acquisition/opportunity cost",
                "shed overflow",
                "opponent price impact",
                "deadline congestion",
            ],
        }
    return result


def _animal_horizons() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for animal, spec in game.ANIMALS.items():
        first = int(spec["first_yield_day"])
        result[animal] = {
            "purchase_cost": int(spec["cost"]),
            "product": spec["product"],
            "first_yield_day": first,
            "latest_place_day_for_one_harvest": 29 - first,
            "base_price": int(game.MARKET_PARAMS[spec["product"]]["base"]),
            "mandatory_constraints": [
                f"matching {spec['structure']}",
                "PICKUP and PLACE transaction",
                "no two consecutive missed-feed refreshes",
                "WHEAT logistics",
            ],
            "care_note": (
                "CARE adds one pending unit only when that day is also fed; "
                "bonus pays on a later fed production day"
            ),
        }
    return result


def _hand_costs() -> dict[str, Any]:
    rows = []
    total = 0
    for count in range(1, 15):
        marginal = int(game._hire_cost(count - 1))
        total += marginal
        rows.append({"hand_count": count, "marginal_cost": marginal, "cumulative_daily_cost": total})
    return {
        "schedule": rows,
        "resets_daily": True,
        "decision_rule": (
            "hire only if expected marginal value of the added worker-turns "
            "exceeds marginal cost and routing congestion"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/analysis/v22_game_economics.json"))
    args = parser.parse_args()
    curves = _market_curves()
    payload = {
        "format": FORMAT,
        "engine": {
            "module": str(Path(game.__file__).resolve()),
            "episode_steps": EPISODE_STEPS,
            "official_terminal_reward": "own farm money",
            "competition_objective_inference": (
                "rating rewards head-to-head wins, so expected money is not "
                "a sufficient policy objective"
            ),
        },
        "turn_order": [
            "both players' field actions",
            "market orders",
            "Town consumption",
            "plant decay",
            "end-of-day refresh when hour 23 completes",
        ],
        "turn_order_implications": [
            "A sale on a Town-consumption step receives the pre-consumption quote.",
            (
                "Waiting until the next observation receives the post-consumption quote, "
                "if capital, overflow, and opponent timing permit."
            ),
            "Both players selling the same unit index are quoted from the same pre-commit inventory.",
            (
                "At price 1, a sale pays 1 but does not increase market inventory; "
                "public-flow sell labels are right-censored there."
            ),
        ],
        "market_curves": curves,
        "town_demand": _town_demand(),
        "crop_economics": _crop_economics(curves),
        "animal_horizons": _animal_horizons(),
        "hand_costs": _hand_costs(),
        "land_costs": list(game.LAND_PRICES),
        "strategy_invariants": [
            "Preserve survival and transaction legality in a deterministic executor.",
            "Value a product from projected joint supply and Town demand, not its base price alone.",
            "Treat action capacity and routing as scarce resources alongside money and land.",
            "Reject new assets whose first useful cash flow falls outside the remaining horizon.",
            "Condition irreversible portfolio choices on observable opponent supply and uncertainty.",
            "Condition risk on relative margin because leaderboard strength is head-to-head, not raw coin alone.",
        ],
        "bounded_dominance_claim": {
            "claim": (
                "On the same current tile, preventive WATER weakly dominates PASS when no output, "
                "inventory, or future-position task is displaced."
            ),
            "limits": (
                "It does not dominate moving toward future work, and routing to a preventive tile "
                "has non-zero opportunity cost."
            ),
        },
        "status": {
            "facts": "mechanics and numeric tables are derived from the installed engine",
            "inferences": "strategy invariants and dominance claim",
            "unverified": "rating improvement, causal replay effects, and opponent-predictor usefulness",
        },
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "format": FORMAT,
                "output": str(output),
                "expected_town_units": {
                    item: values["expected_total_units"]
                    for item, values in payload["town_demand"]["expected_season_units"].items()
                },
                "hand_12": payload["hand_costs"]["schedule"][11],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
