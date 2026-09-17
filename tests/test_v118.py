from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "agents" / "v118" / "main.py"


def load_module():
    spec = importlib.util.spec_from_file_location("test_v118_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def observation(step: int = 595, carrot: int = 50, wheat: int = 25):
    tiles = [[None for _ in range(10)] for _ in range(10)]
    locked = [["LOCKED" for _ in range(10)] for _ in range(10)]
    return {
        "step": step,
        "player": 0,
        "farms": [
            {
                "money": 2000,
                "tiles": tiles,
                "farmer": [4, 4],
                "hands": [],
                "unlocked_quadrants": ["NW"],
            },
            {
                "money": 2000,
                "tiles": locked,
                "farmer": [4, 4],
                "hands": [],
                "unlocked_quadrants": ["NW"],
            },
        ],
        "private": {"seeds": {"CARROT": 0}, "inventories": [{}], "shed": {}},
        "market": {"prices": {"CARROT": carrot, "WHEAT": wheat}},
        "town": {"unlocked_shops": []},
    }


def test_price_gate_requires_conservative_edge():
    module = load_module()
    assert module._rotation_has_edge(observation(carrot=50, wheat=25))
    assert not module._rotation_has_edge(observation(carrot=46, wheat=25))
    assert not module._rotation_has_edge(observation(carrot=50, wheat=31))


def test_seed_buy_preserves_reserve_and_avoids_inherited_spend():
    module = load_module()
    state = module._new_state(595)
    action = {"farmer": ["PASS"], "hands": [], "market": []}
    result = module._buy_carrot_seeds(observation(), copy.deepcopy(action), state)
    assert result["market"] == [["BUY_SEED", "CARROT", 45]]
    blocked = {"farmer": ["PASS"], "hands": [], "market": [["BUY_LAND"]]}
    result = module._buy_carrot_seeds(observation(), copy.deepcopy(blocked), state)
    assert result == blocked


def test_swap_is_atomic_for_all_actors():
    module = load_module()
    obs = observation(step=610)
    obs["private"]["seeds"]["CARROT"] = 2
    state = module._new_state(610)
    action = {
        "farmer": ["PLANT", "WHEAT"],
        "hands": [["PLANT", "WHEAT"]],
        "market": [],
    }
    result = module._swap_late_wheat(obs, copy.deepcopy(action), state)
    assert result["farmer"] == ["PLANT", "CARROT"]
    assert result["hands"] == [["PLANT", "CARROT"]]
    obs["private"]["seeds"]["CARROT"] = 1
    assert module._swap_late_wheat(obs, copy.deepcopy(action), state) == action


def test_weed_repair_only_reuses_certain_noop():
    module = load_module()
    obs = observation(step=100)
    obs["farms"][0]["tiles"][4][4] = {"kind": "WEED"}
    state = module._new_state(100)
    idle = {"farmer": ["PASS"], "hands": [], "market": []}
    repaired = module._repair_weeds(obs, copy.deepcopy(idle), state)
    assert repaired["farmer"] == ["DIG"]
    moving = {"farmer": ["NORTH"], "hands": [], "market": []}
    assert module._repair_weeds(obs, copy.deepcopy(moving), state) == moving
