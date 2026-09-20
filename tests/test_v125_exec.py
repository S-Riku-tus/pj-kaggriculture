from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = ROOT / "agents" / "v125_exec" / "main.py"
    spec = importlib.util.spec_from_file_location("test_v125_exec_agent", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _observation(*, seeds=None, shed=None, inventories=None, positions=None, prices=None):
    positions = positions or [(4, 4)]
    farm = {
        "farmer": list(positions[0]),
        "hands": [list(pos) for pos in positions[1:]],
        "tiles": [[None] * 10 for _ in range(10)],
    }
    return {
        "player": 0,
        "farms": [farm, farm],
        "private": {
            "seeds": seeds or {},
            "shed": shed or {},
            "inventories": inventories or [{} for _ in positions],
        },
        "market": {"prices": prices or {}},
    }


def test_caps_plant_requests_to_start_of_turn_seed_stock():
    module = _load()
    obs = _observation(seeds={"WHEAT": 2}, positions=[(0, 0), (1, 0), (2, 0)])
    action = {
        "farmer": ["PLANT", "WHEAT"],
        "hands": [["PLANT", "WHEAT"], ["PLANT", "WHEAT"]],
        "market": [["BUY_SEED", "WHEAT", 10]],
    }
    repaired, diagnostics = module.repair_action(obs, action)
    assert repaired["farmer"] == ["PLANT", "WHEAT"]
    assert repaired["hands"] == [["PLANT", "WHEAT"], ["PASS"]]
    assert diagnostics["plant_requests_removed"] == 1


def test_quantity_place_preserves_overflow_with_worker():
    module = _load()
    obs = _observation(
        shed={"WHEAT": 98},
        inventories=[{"WOOL": 3, "WHEAT": 2}],
        prices={"WOOL": 200, "WHEAT": 25},
    )
    repaired, diagnostics = module.repair_action(
        obs, {"farmer": ["DROP"], "hands": [], "market": []}
    )
    assert repaired["farmer"] == ["PLACE", "WOOL", 2]
    assert diagnostics["drop_actions_bounded"] == 1
    assert diagnostics["drop_units_preserved"] == 3


def test_drop_is_unchanged_when_everything_fits():
    module = _load()
    obs = _observation(shed={"WHEAT": 90}, inventories=[{"WOOL": 3}])
    repaired, diagnostics = module.repair_action(
        obs, {"farmer": ["DROP"], "hands": [], "market": []}
    )
    assert repaired["farmer"] == ["DROP"]
    assert diagnostics["drop_actions_bounded"] == 0
