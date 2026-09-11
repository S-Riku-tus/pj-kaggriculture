from copy import deepcopy

from kaggle_environments.envs.kaggriculture import kaggriculture as engine

from agents.v114 import main as candidate


def test_price_projection_matches_engine_across_scarcity_and_floor():
    for item in candidate.PARAMS:
        for inventory in (0, 9500, 9900, 9999, 10000, 10001, 10059, 10076, 10500):
            assert candidate._price(item, inventory) == engine.market_price(item, inventory)


def test_existing_routes_have_exact_common_prefix_and_intended_divergence():
    left, right = candidate.ROUTES["default"], candidate.ROUTES["yarn_second"]
    assert len(left) == len(right) == 719
    assert left[:153] == right[:153]
    assert left[153] != right[153]


def test_value_projection_does_not_read_private_inventory_or_seed():
    farm = {
        "money": 100000,
        "hires_today": 0,
        "hands": [],
        "unlocked_quadrants": ["NW", "NE"],
        "tiles": [[None] * 10 for _ in range(10)],
    }
    obs = {
        "step": 153,
        "day": 6,
        "hour": 9,
        "player": 0,
        "farms": [deepcopy(farm), deepcopy(farm)],
        "market": {"inventory": dict.fromkeys(candidate.PARAMS, 10000)},
        "town": {"unlocked_shops": ["PIZZA_SHOP", "SMOOTHIE_SHOP"]},
    }
    before = candidate._route_relative_value(obs, "default", 1.0)
    obs["private"] = {"opponent_shed": {"MILK": 1000000}, "shed": {"MILK": 123}}
    obs["seed"] = 999
    assert before == candidate._route_relative_value(obs, "default", 1.0)
