from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _summary(module):
    return {
        "crops": {crop: 0 for crop in module.base.CROP_DATA},
        "animals": {animal: 0 for animal in module.base.ANIMAL_DATA},
    }


def _observation(tile, *, day=10, shops=None):
    tiles = [[None] * 10 for _ in range(10)]
    if tile is not None:
        tiles[0][0] = tile
    farm = {
        "farmer": [4, 4],
        "hands": [],
        "money": 3000,
        "tiles": tiles,
        "unlocked_quadrants": ["NW"],
    }
    return {
        "day": day,
        "hour": 0,
        "step": 24 * day,
        "player": 0,
        "farms": [farm, farm],
        "private": {"inventories": [{}], "seeds": {}, "shed": {}},
        "market": {
            "inventory": {
                item: 10_000
                for item in (
                    "WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
                    "EGG", "MILK", "WOOL", "FERTILIZER",
                )
            },
            "prices": {
                "WHEAT": 25, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120,
                "MELON": 250, "EGG": 50, "MILK": 160, "WOOL": 200, "FERTILIZER": 100,
            },
        },
        "town": {"unlocked_shops": shops or []},
    }


def test_candidate_a_schedule_is_early_strawberry_three_land_rotation():
    module = _load("test_v125_base_schedule", "agents/v125_base/main.py")
    d2 = module.plan_targets(2, _summary(module))
    d11 = module.plan_targets(11, _summary(module))
    d18 = module.plan_targets(18, _summary(module))
    assert d2["animals"] == {"COW": 2, "SHEEP": 3, "GOOSE": 0}
    assert d2["crops"]["STRAWBERRY"] == 2
    assert d11["land"] == 3 and d11["crops"]["TOMATO"] == 2
    assert d18["land"] == 3 and d18["crops"]["CARROT"] == 4


def test_asset_ledger_stops_production_at_final_day_and_tracks_care():
    module = _load("test_v125_base_ledger", "agents/v125_base/main.py")
    tile = {
        "kind": "PASTURE",
        "animal": "SHEEP",
        "placed_day": 0,
        "yield_units": 2,
        "pending_care_bonus": 3,
        "fertilizer_available": False,
    }
    obs = _observation(tile, day=28)
    row = module.asset_ledger(obs)[0]
    assert row["yield_waiting"] == 2
    assert row["pending_care"] == 3
    assert all(day <= 29 for day in module._future_production_days("animal", "SHEEP", tile, 28))


def test_duplicate_shops_contribute_independent_demand():
    module = _load("test_v125_base_forecast", "agents/v125_base/main.py")
    one = module.observed_supply_forecast(_observation(None, shops=["YARN_STORE"]))
    two = module.observed_supply_forecast(_observation(None, shops=["YARN_STORE", "YARN_STORE"]))
    assert two["items"]["WOOL"]["town_drain"] - one["items"]["WOOL"]["town_drain"] == 36


def test_forbidden_metadata_does_not_change_targets_or_supply_forecast():
    module = _load("test_v125_base_boundary", "agents/v125_base/main.py")
    left = _observation(None)
    right = dict(left)
    right.update({"seed": 999, "submission_id": 123, "opponent_rating": 3200, "winner": 1})
    assert module.plan_targets(10, _summary(module)) == module.plan_targets(10, _summary(module))
    assert module.observed_supply_forecast(left) == module.observed_supply_forecast(right)


def test_adaptive_arm_is_a_separate_entry_point():
    module = _load("test_v125_adaptive_entry", "agents/v125_adaptive/main.py")
    assert callable(module.agent)
    assert module.base.PLAN_NAME == "top1_three_quadrant_rotation_v1"
