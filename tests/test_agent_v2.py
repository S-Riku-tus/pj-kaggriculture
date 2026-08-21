from __future__ import annotations

from copy import deepcopy

from agents.v2.main import _desired_animals, _farm_summary, agent

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


def test_v2_opening_matches_replay_calibrated_core() -> None:
    action = agent(make_obs())
    assert ["BUY_SEED", "WHEAT", 6] in action["market"]
    assert ["BUY_SEED", "MELON", 11] in action["market"]
    assert ["BUY_ANIMAL", "COW", 2] in action["market"]
    assert ["BUY_ANIMAL", "SHEEP", 2] in action["market"]
    assert ["BUY_PRODUCT", "WHEAT", 4] in action["market"]
    assert action["market"].count(["HIRE"]) == 5
    assert len(action["market"]) == 10


def test_v2_town_demand_increases_mature_cow_target() -> None:
    current = {animal: 0 for animal in ANIMALS}
    opponent = _farm_summary(make_obs()["farms"][1])
    prices = {"MILK": 160, "WOOL": 200}
    low = _desired_animals(12, current, opponent, {}, prices)
    high = _desired_animals(12, current, opponent, {"MILK": 4}, prices)
    assert low["COW"] == 6
    assert high["COW"] == 12


def test_v2_liquidation_sells_every_shed_product_and_stops_investment() -> None:
    obs = make_obs(day=29, hour=5, hands=2)
    obs["farms"][0]["money"] = 5000
    obs["private"]["shed"]["MILK"] = 3
    obs["private"]["shed"]["WHEAT"] = 4
    action = agent(obs)
    assert ["SELL", "MILK", 3] in action["market"]
    assert ["SELL", "WHEAT", 4] in action["market"]
    assert not any(order[0] in {"BUY_SEED", "BUY_ANIMAL", "BUY_LAND"} for order in action["market"])


def test_v2_does_not_mutate_observation_and_returns_one_action_per_hand() -> None:
    obs = make_obs(day=12, hour=8, hands=4)
    before = deepcopy(obs)
    action = agent(obs)
    assert obs == before
    assert len(action["hands"]) == 4
    assert len(action["market"]) <= 10


def test_v2_missing_observation_fails_closed() -> None:
    assert agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}
