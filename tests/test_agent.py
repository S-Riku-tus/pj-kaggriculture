from __future__ import annotations

from copy import deepcopy

from agents.v1.main import agent

PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER")
ANIMALS = ("GOOSE", "COW", "SHEEP")


def make_obs(*, day: int = 0, hour: int = 0, hands: int = 0) -> dict:
    def farm() -> dict:
        return {
            "money": 3000.0,
            "tiles": [[None if x < 5 and y < 5 else "LOCKED" for x in range(10)] for y in range(10)],
            "farmer": [4, 4],
            "hands": [[4, 4] for _ in range(hands)],
            "unlocked_quadrants": ["NW"],
            "hires_today": hands,
        }

    return {
        "player": 0,
        "step": day * 24 + hour,
        "day": day,
        "hour": hour,
        "farms": [farm(), farm()],
        "private": {
            "shed": {item: 0 for item in (*PRODUCTS, *ANIMALS)},
            "seeds": {crop: 0 for crop in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")},
            "inventories": [{} for _ in range(hands + 1)],
        },
        "market": {
            "inventory": {item: 10000 for item in PRODUCTS},
            "prices": {
                "WHEAT": 25,
                "CARROT": 35,
                "TOMATO": 60,
                "STRAWBERRY": 120,
                "MELON": 250,
                "EGG": 50,
                "MILK": 160,
                "WOOL": 200,
                "FERTILIZER": 100,
            },
        },
        "town": {"unlocked_shops": []},
    }


def assert_shape(action: dict, hand_count: int) -> None:
    assert set(action) == {"farmer", "hands", "market"}
    assert isinstance(action["farmer"], list) and action["farmer"]
    assert len(action["hands"]) == hand_count
    assert all(isinstance(item, list) and item for item in action["hands"])
    assert len(action["market"]) <= 10


def test_day_zero_buys_cash_crop_seeds_and_hires() -> None:
    obs = make_obs()
    action = agent(obs)
    assert ["BUY_SEED", "WHEAT", 10] in action["market"]
    assert ["BUY_SEED", "CARROT", 8] in action["market"]
    assert action["market"].count(["HIRE"]) == 8
    assert_shape(action, 0)


def test_emergency_feed_is_selected_on_tile() -> None:
    obs = make_obs(day=7, hour=8)
    obs["farms"][0]["tiles"][4][4] = {
        "kind": "PASTURE",
        "animal": "COW",
        "placed_day": 4,
        "yield_units": 0,
        "fed_today": False,
        "consecutive_unfed": 1,
        "cared_today": False,
        "fertilizer_available": False,
        "pending_care_bonus": 0,
    }
    obs["private"]["inventories"][0]["WHEAT"] = 1
    assert agent(obs)["farmer"] == ["FEED"]


def test_unfed_animal_causes_wheat_pickup_at_shed() -> None:
    obs = make_obs(day=7, hour=8)
    obs["farms"][0]["tiles"][2][2] = {
        "kind": "PASTURE",
        "animal": "COW",
        "placed_day": 4,
        "yield_units": 0,
        "fed_today": False,
        "consecutive_unfed": 1,
        "cared_today": False,
        "fertilizer_available": False,
        "pending_care_bonus": 0,
    }
    obs["private"]["shed"]["WHEAT"] = 3
    assert agent(obs)["farmer"][:2] == ["PICKUP", "WHEAT"]


def test_emergency_water_beats_optional_work() -> None:
    obs = make_obs(day=2, hour=10)
    obs["farms"][0]["tiles"][4][4] = {
        "kind": "PLANT",
        "crop": "WHEAT",
        "planted_day": 0,
        "watered_today": False,
        "consecutive_unwatered": 1,
        "yield_units": 1,
        "max_lifespan_step": 120,
        "fertilized_until_day": -1,
    }
    assert agent(obs)["farmer"] == ["WATER"]


def test_plant_requests_never_exceed_seed_count() -> None:
    obs = make_obs(day=1, hour=4, hands=3)
    obs["private"]["seeds"]["WHEAT"] = 1
    action = agent(obs)
    unit_actions = [action["farmer"], *action["hands"]]
    assert sum(item[:2] == ["PLANT", "WHEAT"] for item in unit_actions) <= 1
    assert_shape(action, 3)


def test_agent_does_not_mutate_observation() -> None:
    obs = make_obs(day=5, hour=12, hands=2)
    before = deepcopy(obs)
    action = agent(obs)
    assert obs == before
    assert_shape(action, 2)


def test_missing_observation_fails_closed() -> None:
    assert agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}
