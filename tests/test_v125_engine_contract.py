from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from kaggle_environments import make
from kaggle_environments.envs.kaggriculture import kaggriculture as engine

PASS = {"farmer": ["PASS"], "hands": [], "market": []}


def _private(**shed: int) -> dict:
    stock = {item: 0 for item in [*engine.PRODUCTS, *engine.ANIMALS]}
    stock.update(shed)
    return {
        "shed": stock,
        "seeds": {crop: 0 for crop in engine.CROPS},
        "inventories": [{}],
    }


def _market_state(left: dict, right: dict, left_action: dict, right_action: dict):
    farms = [engine._new_farm(10, 3_000), engine._new_farm(10, 3_000)]
    observation = SimpleNamespace(
        market=engine._new_market(),
        farms=farms,
        town=engine._new_town(),
    )
    state = [
        SimpleNamespace(observation=SimpleNamespace(private=left), action=left_action),
        SimpleNamespace(observation=SimpleNamespace(private=right), action=right_action),
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


def test_recorded_action_is_stored_one_state_after_its_observation() -> None:
    seen: list[tuple[int, int, int]] = []

    def marker(obs, _configuration=None):
        seen.append((int(obs.day), int(obs.hour), int(obs.player)))
        return {"farmer": ["PASS"], "hands": [], "market": [["HIRE"]]}

    env = make(
        "kaggriculture",
        configuration={"episodeSteps": 3, "seed": 20260920, "weedSpawnChance": 0.0},
        debug=True,
    )
    env.run([marker, marker])
    replay = env.toJSON()
    assert seen[:2] == [(0, 0, 0), (0, 0, 1)]
    assert replay["steps"][0][0]["observation"]["hour"] == 0
    assert replay["steps"][1][0]["action"] == {
        "farmer": ["PASS"],
        "hands": [],
        "market": [["HIRE"]],
    }


def test_unit_actions_precede_market_and_cannot_use_same_turn_seed_or_hire() -> None:
    def buyer(obs, _configuration=None):
        if int(obs.hour) == 0:
            return {
                "farmer": ["PLANT", "WHEAT"],
                "hands": [["PLANT", "WHEAT"]],
                "market": [["BUY_SEED", "WHEAT", 1], ["HIRE"]],
            }
        return PASS

    env = make(
        "kaggriculture",
        configuration={"episodeSteps": 3, "seed": 20260921, "weedSpawnChance": 0.0},
        debug=True,
    )
    env.run([buyer, "pass"])
    after = env.toJSON()["steps"][1][0]["observation"]
    farm = after["farms"][0]
    assert sum(
        isinstance(tile, dict) and tile.get("crop") == "WHEAT"
        for row in farm["tiles"]
        for tile in row
    ) == 0
    assert after["private"]["seeds"]["WHEAT"] == 1
    assert len(farm["hands"]) == 1


def test_atomic_seed_shortage_cancels_every_request_for_that_crop() -> None:
    farm = engine._new_farm(10, 3_000)
    private = _private()
    farm["farmer"] = [3, 4]
    farm["hands"] = [[4, 4]]
    private["inventories"] = [{}, {}]
    private["seeds"]["WHEAT"] = 1

    demand = [["PLANT", "WHEAT"], ["PLANT", "WHEAT"]]
    count = sum(action[:2] == ["PLANT", "WHEAT"] for action in demand)
    blocked = count > private["seeds"]["WHEAT"]
    for index, action in enumerate(demand):
        engine._apply_unit_action(
            farm,
            private,
            index,
            ["PASS"] if blocked else action,
            10,
            0,
            24,
            100,
        )

    assert private["seeds"]["WHEAT"] == 1
    assert farm["tiles"][4][3] is None
    assert farm["tiles"][4][4] is None


def test_same_slot_same_product_sales_receive_symmetric_unit_quotes() -> None:
    left = _private(WHEAT=2)
    right = _private(WHEAT=2)
    action = {"farmer": ["PASS"], "hands": [], "market": [["SELL", "WHEAT", 2]]}
    observation, state, env = _market_state(left, right, action, deepcopy(action))

    engine._process_market(state, env)

    assert observation.farms[0]["money"] == observation.farms[1]["money"]
    assert left["shed"]["WHEAT"] == right["shed"]["WHEAT"] == 0
    assert observation.market["inventory"]["WHEAT"] == 10_004


def test_place_preserves_excess_while_drop_discards_overflow() -> None:
    farm = engine._new_farm(10, 3_000)
    farm["farmer"] = [4, 4]

    placed = _private(CARROT=99)
    placed["inventories"][0] = {"WHEAT": 2, "MILK": 2}
    engine._apply_unit_action(farm, placed, 0, ["PLACE", "WHEAT", 2], 10, 0, 24, 100)
    assert placed["shed"]["WHEAT"] == 1
    assert placed["inventories"][0] == {"WHEAT": 1, "MILK": 2}

    dropped = _private(CARROT=99)
    dropped["inventories"][0] = {"WHEAT": 2, "MILK": 2}
    engine._apply_unit_action(farm, dropped, 0, ["DROP"], 10, 0, 24, 100)
    assert sum(dropped["shed"].values()) == 100
    assert dropped["inventories"][0] == {}


def test_care_is_paid_after_old_pending_bonus_and_banks_for_next_cycle() -> None:
    farm = engine._new_farm(10, 3_000)
    farm["tiles"][3][4] = {
        "kind": "PASTURE",
        "animal": "COW",
        "placed_day": 0,
        "yield_units": 0,
        "fed_today": True,
        "consecutive_unfed": 0,
        "cared_today": True,
        "fertilizer_available": False,
        "pending_care_bonus": 5,
    }

    engine._daily_refresh_animals(farm, 7)

    tile = farm["tiles"][3][4]
    assert tile["yield_units"] == 6
    assert tile["pending_care_bonus"] == 1
    assert tile["fed_today"] is False
    assert tile["cared_today"] is False


def test_duplicate_shop_instances_consume_independently() -> None:
    left = _private()
    right = _private()
    observation, state, env = _market_state(left, right, PASS, PASS)
    observation.town["unlocked_shops"] = ["YARN_STORE", "YARN_STORE"]
    env.configuration.townShopSellInterval = 4
    env.configuration.townCenterSellInterval = 24

    engine._town_consume(env, state, 4)

    assert observation.market["inventory"]["WOOL"] == 9_996


def test_final_recorded_turn_does_not_run_a_day_29_end_of_day_refresh() -> None:
    env = make(
        "kaggriculture",
        configuration={"episodeSteps": 720, "seed": 20260922, "weedSpawnChance": 0.0},
        debug=True,
    )
    env.reset()
    for _ in range(718):
        env.step([PASS, PASS])

    farm = env.state[0].observation.farms[0]
    farm["tiles"][0][0] = {
        "kind": "PASTURE",
        "animal": "COW",
        "placed_day": 22,
        "yield_units": 0,
        "fed_today": True,
        "consecutive_unfed": 0,
        "cared_today": True,
        "fertilizer_available": False,
        "pending_care_bonus": 5,
    }
    env.step([PASS, PASS])

    final_tile = env.steps[-1][0].observation.farms[0]["tiles"][0][0]
    assert env.steps[-1][0].status == "DONE"
    assert final_tile["yield_units"] == 0
    assert final_tile["pending_care_bonus"] == 5
    assert final_tile["fed_today"] is True

