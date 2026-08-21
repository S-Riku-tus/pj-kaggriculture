from __future__ import annotations

from copy import deepcopy

from agents.v3.feature_schema import FEATURE_NAMES, OUTPUT_NAMES, encode_observation
from agents.v3.main import MODEL, _assign_tasks, _expert_weights, _strategy_targets, agent

PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER")
ANIMALS = ("GOOSE", "COW", "SHEEP")


def make_obs(*, day: int = 0, hour: int = 0, hands: int = 0, shops: list[str] | None = None) -> dict:
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
        "town": {"unlocked_shops": shops or []},
    }


def test_v3_model_matches_runtime_schema_and_uses_all_top3_corpora() -> None:
    assert MODEL is not None
    assert tuple(MODEL["feature_names"]) == FEATURE_NAMES
    assert tuple(MODEL["output_names"]) == OUTPUT_NAMES
    assert MODEL["sources"]["rank1"]["episodes"] == 134
    assert MODEL["sources"]["rank2"]["episodes"] == 131
    assert MODEL["sources"]["rank3"]["episodes"] == 185


def test_v3_rank1_exact_hour_zero_opening() -> None:
    obs = make_obs()
    before = deepcopy(obs)
    action = agent(obs)
    assert obs == before
    assert action["farmer"] == ["BUILD_PASTURE"]
    assert action["market"][:5] == [["HIRE"]] * 5
    assert ["BUY_ANIMAL", "COW", 2] in action["market"]
    assert ["BUY_SEED", "MELON", 11] in action["market"]
    assert len(action["market"]) == 10


def test_v3_feature_vector_and_learned_targets_are_bounded() -> None:
    obs = make_obs(day=12, shops=["ICE_CREAM_SHOP", "SMOOTHIE_SHOP", "YARN_STORE"])
    assert len(encode_observation(obs)) == len(FEATURE_NAMES)
    animals, crops, hands, land, weights = _strategy_targets(
        obs, obs["farms"][0], obs["farms"][1], obs["private"]
    )
    assert 0 <= animals["COW"] <= 18
    assert 0 <= animals["SHEEP"] <= 11
    assert 6 <= crops["WHEAT"] <= 55
    assert 0 <= crops["STRAWBERRY"] <= 48
    assert 3 <= hands <= 13
    assert 1 <= land <= 3
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_v3_gate_changes_when_market_regime_changes() -> None:
    milk = _expert_weights(make_obs(day=15, shops=["ICE_CREAM_SHOP"] * 4), 15)
    wool = _expert_weights(make_obs(day=15, shops=["YARN_STORE"] * 3), 15)
    assert any(abs(milk[key] - wool[key]) > 1e-4 for key in milk)


def test_v3_equal_priority_assignment_is_global_not_task_greedy() -> None:
    positions = [(0, 0), (4, 0)]
    inventories = [{}, {}]
    tasks = [
        {"pos": (3, 0), "action": ["DIG"], "priority": 100, "required": None, "unit": None, "label": "a"},
        {"pos": (4, 4), "action": ["DIG"], "priority": 100, "required": None, "unit": None, "label": "b"},
    ]
    assert _assign_tasks(positions, inventories, tasks) == [["EAST"], ["SOUTH"]]


def test_v3_missing_observation_fails_closed() -> None:
    assert agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}
