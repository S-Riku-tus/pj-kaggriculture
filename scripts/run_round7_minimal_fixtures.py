"""Execute and save Round7 engine-contract fixtures with before/after state."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from kaggle_environments import make
from kaggle_environments.envs.kaggriculture import kaggriculture as engine

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "experiments" / "learning_round7_20260922" / "minimal_fixtures" / "engine_contracts.json"
PASS = {"farmer": ["PASS"], "hands": [], "market": []}


def private(**shed: int) -> dict[str, Any]:
    stock = {item: 0 for item in [*engine.PRODUCTS, *engine.ANIMALS]}
    stock.update(shed)
    return {
        "shed": stock,
        "seeds": {crop: 0 for crop in engine.CROPS},
        "inventories": [{}],
    }


def market_state(
    left: dict[str, Any],
    left_action: dict[str, Any],
    *,
    left_money: int = 3000,
) -> tuple[Any, list[Any], Any]:
    farms = [engine._new_farm(10, left_money), engine._new_farm(10, 3000)]
    observation = SimpleNamespace(market=engine._new_market(), farms=farms, town=engine._new_town())
    right = private()
    state = [
        SimpleNamespace(observation=SimpleNamespace(private=left), action=left_action),
        SimpleNamespace(observation=SimpleNamespace(private=right), action=PASS),
    ]
    state[0].observation.market = observation.market
    state[0].observation.farms = farms
    state[0].observation.town = observation.town
    env = SimpleNamespace(
        configuration=SimpleNamespace(
            boardSize=10,
            maxMarketOrdersPerTurn=10,
            farmHandCostMult=1,
            shedCapacity=100,
        )
    )
    return observation, state, env


def snapshot(farm: dict[str, Any], own: dict[str, Any], market: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "farm": copy.deepcopy(farm),
        "private": copy.deepcopy(own),
        "market": copy.deepcopy(market),
    }


def unit_event(
    events: list[dict[str, Any]],
    name: str,
    farm: dict[str, Any],
    own: dict[str, Any],
    action: list[Any],
    *,
    day: int,
) -> None:
    before = snapshot(farm, own)
    engine._apply_unit_action(farm, own, 0, action, 10, day, 24, 100)
    events.append(
        {
            "name": name,
            "requested_action": action,
            "before": before,
            "after": snapshot(farm, own),
            "state_changed": before != snapshot(farm, own),
        }
    )


def fixture_livestock_lifecycle() -> dict[str, Any]:
    own = private()
    farm = engine._new_farm(10, 3000)
    farm["farmer"] = [4, 3]
    events: list[dict[str, Any]] = []
    unit_event(events, "build_pasture", farm, own, ["BUILD_PASTURE"], day=0)
    unit_event(events, "move_to_shed", farm, own, ["SOUTH"], day=0)

    action = {
        **PASS,
        "market": [["BUY_ANIMAL", "COW", 1], ["BUY_PRODUCT", "WHEAT", 10]],
    }
    observation, state, env = market_state(own, action, left_money=farm["money"])
    observation.farms[0] = farm
    before = snapshot(farm, own, observation.market)
    engine._process_market(state, env)
    events.append(
        {
            "name": "buy_cow_and_feed_stock",
            "requested_action": action,
            "before": before,
            "after": snapshot(farm, own, observation.market),
            "state_changed": before != snapshot(farm, own, observation.market),
        }
    )
    unit_event(events, "pickup_cow", farm, own, ["PICKUP", "COW", 1], day=0)
    unit_event(events, "pickup_wheat", farm, own, ["PICKUP", "WHEAT", 10], day=0)
    unit_event(events, "return_to_pasture", farm, own, ["NORTH"], day=0)
    unit_event(events, "place_cow", farm, own, ["PLACE", "COW", 1], day=0)
    for day in range(8):
        unit_event(events, f"feed_day_{day}", farm, own, ["FEED"], day=day)
        unit_event(events, f"care_day_{day}", farm, own, ["CARE"], day=day)
        before = snapshot(farm, own)
        engine._daily_refresh_animals(farm, day)
        events.append(
            {
                "name": f"end_of_day_{day}",
                "requested_action": "ENGINE_REFRESH",
                "before": before,
                "after": snapshot(farm, own),
                "state_changed": before != snapshot(farm, own),
            }
        )
    produced = farm["tiles"][3][4].get("yield_units", 0)
    unit_event(events, "collect_milk", farm, own, ["HARVEST"], day=8)
    unit_event(events, "return_product_to_shed", farm, own, ["SOUTH"], day=8)
    milk_carried = own["inventories"][0].get("MILK", 0)
    unit_event(events, "store_milk", farm, own, ["PLACE", "MILK", milk_carried], day=8)
    action = {**PASS, "market": [["SELL", "MILK", own["shed"].get("MILK", 0)]]}
    observation, state, env = market_state(own, action, left_money=farm["money"])
    observation.farms[0] = farm
    before_money = farm["money"]
    before = snapshot(farm, own, observation.market)
    engine._process_market(state, env)
    events.append(
        {
            "name": "sell_milk",
            "requested_action": action,
            "before": before,
            "after": snapshot(farm, own, observation.market),
            "state_changed": before != snapshot(farm, own, observation.market),
        }
    )
    return {
        "name": "cow_buy_pickup_place_feed_care_first_collect_sell",
        "events": events,
        "success_conditions": {
            "cow_survived_to_first_production": produced > 0,
            "milk_was_collected": milk_carried > 0,
            "milk_left_shed_after_sale": own["shed"].get("MILK", 0) == 0,
            "sale_increased_cash": farm["money"] > before_money,
        },
    }


def fixture_resource_collisions() -> dict[str, Any]:
    farm = engine._new_farm(10, 3000)
    own = private()
    farm["farmer"] = [4, 3]
    farm["hands"] = [[4, 3]]
    own["inventories"] = [{"WHEAT": 1}, {"WHEAT": 1}]
    farm["tiles"][3][4] = engine._new_animal("COW", 0)
    before = snapshot(farm, own)
    engine._apply_unit_action(farm, own, 0, ["FEED"], 10, 0, 24, 100)
    middle = snapshot(farm, own)
    engine._apply_unit_action(farm, own, 1, ["FEED"], 10, 0, 24, 100)
    after = snapshot(farm, own)

    distinct = engine._new_farm(10, 3000)
    distinct_private = private()
    distinct["farmer"] = [4, 3]
    distinct["hands"] = [[5, 3]]
    distinct_private["inventories"] = [{"WHEAT": 1}, {"WHEAT": 1}]
    distinct["tiles"][3][4] = engine._new_animal("COW", 0)
    distinct["tiles"][3][5] = engine._new_animal("COW", 0)
    engine._apply_unit_action(distinct, distinct_private, 0, ["FEED"], 10, 0, 24, 100)
    engine._apply_unit_action(distinct, distinct_private, 1, ["FEED"], 10, 0, 24, 100)
    return {
        "name": "same_target_collision_and_distinct_allocation",
        "same_target": {"before": before, "after_first": middle, "after_second": after},
        "distinct_targets_after": snapshot(distinct, distinct_private),
        "success_conditions": {
            "duplicate_second_feed_had_no_effect": middle == after,
            "distinct_cows_both_fed": distinct["tiles"][3][4]["fed_today"] and distinct["tiles"][3][5]["fed_today"],
        },
    }


def fixture_atomic_plant() -> dict[str, Any]:
    env = make(
        "kaggriculture",
        configuration={"episodeSteps": 2, "seed": 20260922, "weedSpawnChance": 0.0},
        debug=True,
    )
    env.reset(2)
    farm = env.state[0].observation.farms[0]
    own = env.state[0].observation.private
    farm.farmer = [3, 4]
    farm.hands = [[4, 4]]
    own.inventories = [{}, {}]
    own.seeds.WHEAT = 1
    before = env.toJSON()["steps"][-1][0]["observation"]
    action = {"farmer": ["PLANT", "WHEAT"], "hands": [["PLANT", "WHEAT"]], "market": []}
    env.step([action, PASS])
    after = env.toJSON()["steps"][-1][0]["observation"]
    crop_count = sum(
        isinstance(tile, dict) and tile.get("crop") == "WHEAT" for row in after["farms"][0]["tiles"] for tile in row
    )
    return {
        "name": "atomic_multi_actor_plant_shortage",
        "requested_action": action,
        "before": before,
        "after": after,
        "success_conditions": {
            "all_requests_cancelled": crop_count == 0,
            "seed_preserved": after["private"]["seeds"]["WHEAT"] == 1,
        },
    }


def fixture_actor_market_order() -> dict[str, Any]:
    env = make(
        "kaggriculture",
        configuration={"episodeSteps": 2, "seed": 20260922, "weedSpawnChance": 0.0},
        debug=True,
    )
    env.reset(2)
    farm = env.state[0].observation.farms[0]
    own = env.state[0].observation.private
    farm.tiles[4][4] = engine._new_animal("COW", 0)
    farm.farmer = [4, 4]
    own.inventories = [{}]
    action = {"farmer": ["FEED"], "hands": [], "market": [["BUY_PRODUCT", "WHEAT", 1]]}
    before = env.toJSON()["steps"][-1][0]["observation"]
    env.step([action, PASS])
    after = env.toJSON()["steps"][-1][0]["observation"]

    own2 = private(CARROT=1)
    sale_then_buy = {**PASS, "market": [["SELL", "CARROT", 1], ["BUY_SEED", "WHEAT", 1]]}
    observation, state, market_env = market_state(own2, sale_then_buy, left_money=0)
    sale_before = snapshot(observation.farms[0], own2, observation.market)
    engine._process_market(state, market_env)
    sale_after = snapshot(observation.farms[0], own2, observation.market)
    return {
        "name": "actor_before_market_and_ordered_market_funding",
        "same_turn_purchase": {"requested_action": action, "before": before, "after": after},
        "sale_then_buy": {"requested_action": sale_then_buy, "before": sale_before, "after": sale_after},
        "success_conditions": {
            "same_turn_bought_wheat_cannot_feed": not after["farms"][0]["tiles"][4][4]["fed_today"],
            "bought_wheat_lands_in_shed": after["private"]["shed"]["WHEAT"] == 1,
            "sale_funds_later_seed_buy": sale_after["private"]["seeds"]["WHEAT"] == 1,
        },
    }


def fixture_land_followthrough() -> dict[str, Any]:
    farm = engine._new_farm(10, 3000)
    own = private()
    before = snapshot(farm, own)
    engine._do_buy_land(farm, 10)
    own["seeds"]["WHEAT"] = 1
    farm["farmer"] = [5, 0]
    engine._apply_unit_action(farm, own, 0, ["PLANT", "WHEAT"], 10, 0, 24, 100)
    engine._apply_unit_action(farm, own, 0, ["WATER"], 10, 0, 24, 100)
    after = snapshot(farm, own)
    tile = farm["tiles"][0][5]
    return {
        "name": "buy_land_then_plant_and_maintain",
        "before": before,
        "after": after,
        "success_conditions": {
            "land_unlocked": "NE" in farm["unlocked_quadrants"],
            "crop_planted": tile.get("crop") == "WHEAT",
            "crop_watered": tile.get("watered_today") is True,
        },
    }


def main() -> None:
    fixtures = [
        fixture_livestock_lifecycle(),
        fixture_resource_collisions(),
        fixture_atomic_plant(),
        fixture_actor_market_order(),
        fixture_land_followthrough(),
    ]
    payload = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "engine_sha256": hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest(),
        "success_definition": "requested -> accepted -> observed state change -> workflow completion are distinct",
        "fixtures": fixtures,
        "all_success_conditions_passed": all(all(case["success_conditions"].values()) for case in fixtures),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "all_passed": payload["all_success_conditions_passed"]}, indent=2))


if __name__ == "__main__":
    main()
