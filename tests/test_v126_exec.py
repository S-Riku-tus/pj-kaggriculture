from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = ROOT / "agents" / "v126_exec" / "main.py"
    spec = importlib.util.spec_from_file_location("test_v126_exec_agent", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _observation(
    *,
    step=242,
    positions=((4, 3),),
    inventories=None,
    shed=None,
    tiles=None,
    money=3000,
):
    if tiles is None:
        tiles = [[None] * 10 for _ in range(10)]
    farm = {
        "money": money,
        "farmer": list(positions[0]),
        "hands": [list(position) for position in positions[1:]],
        "tiles": tiles,
        "unlocked_quadrants": ["NW", "NE", "SW", "SE"],
        "hires_today": max(0, len(positions) - 1),
    }
    return {
        "player": 0,
        "day": step // 24,
        "hour": step % 24,
        "farms": [farm, farm],
        "private": {
            "seeds": {},
            "shed": shed or {},
            "inventories": inventories or [{} for _ in positions],
        },
        "market": {
            "prices": {
                "WHEAT": 25,
                "FERTILIZER": 100,
                "MILK": 160,
                "WOOL": 200,
                "EGG": 50,
            }
        },
        "town": {"unlocked_shops": []},
    }


def _action(unit, market=None):
    return {"farmer": unit, "hands": [], "market": market or []}


def test_pickup_outside_shed_becomes_verified_actor_local_job():
    module = _load()
    module.ENABLE_GENERAL_JOB_RECOVERY = True
    coordinator = module.ExecutionCoordinator(0)
    obs = _observation(shed={"WHEAT": 7})

    repaired = coordinator.repair(obs, _action(["PICKUP", "WHEAT", 5]))
    assert repaired["farmer"] == ["SOUTH"]
    assert coordinator.jobs[0]["kind"] == "pickup"

    obs = _observation(step=243, positions=((4, 4),), shed={"WHEAT": 7})
    repaired = coordinator.repair(obs, _action(["FEED"]))
    assert repaired["farmer"] == ["PICKUP", "WHEAT", 5]
    assert coordinator.jobs[0]["awaiting"]["op"] == "PICKUP"

    obs = _observation(
        step=244,
        positions=((4, 4),),
        inventories=[{"WHEAT": 5}],
        shed={"WHEAT": 2},
    )
    coordinator.repair(obs, _action(["CARE"]))
    assert 0 not in coordinator.jobs
    assert coordinator.counts["operation_verified"] == 1


def test_missing_worker_wheat_recovers_then_feeds_and_verifies():
    module = _load()
    module.ENABLE_GENERAL_JOB_RECOVERY = True
    coordinator = module.ExecutionCoordinator(0)
    tiles = [[None] * 10 for _ in range(10)]
    tiles[3][4] = {
        "kind": "PASTURE",
        "animal": "COW",
        "fed_today": False,
        "cared_today": False,
        "consecutive_unfed": 0,
        "yield_units": 0,
        "placed_day": 0,
    }
    obs = _observation(positions=((4, 3),), shed={"WHEAT": 7}, tiles=tiles)
    repaired = coordinator.repair(obs, _action(["FEED"]))
    assert repaired["farmer"] == ["SOUTH"]
    assert coordinator.jobs[0]["kind"] == "feed"

    obs = _observation(step=243, positions=((4, 4),), shed={"WHEAT": 7}, tiles=tiles)
    repaired = coordinator.repair(obs, _action(["CARE"]))
    assert repaired["farmer"] == ["PICKUP", "WHEAT", 1]

    obs = _observation(
        step=244,
        positions=((4, 4),),
        inventories=[{"WHEAT": 1}],
        shed={"WHEAT": 6},
        tiles=tiles,
    )
    repaired = coordinator.repair(obs, _action(["COLLECT_FERTILIZER"]))
    assert repaired["farmer"] == ["NORTH"]

    obs = _observation(
        step=245,
        positions=((4, 3),),
        inventories=[{"WHEAT": 1}],
        shed={"WHEAT": 6},
        tiles=tiles,
    )
    repaired = coordinator.repair(obs, _action(["NORTH"]))
    assert repaired["farmer"] == ["FEED"]
    assert coordinator.jobs[0]["awaiting"]["op"] == "FEED"

    fed_tiles = [[cell for cell in row] for row in tiles]
    fed_tiles[3][4] = dict(tiles[3][4], fed_today=True)
    obs = _observation(
        step=246,
        positions=((4, 3),),
        inventories=[{}],
        shed={"WHEAT": 6},
        tiles=fed_tiles,
    )
    coordinator.repair(obs, _action(["CARE"]))
    assert 0 not in coordinator.jobs
    assert coordinator.counts["job_completed"] == 1


def test_resource_is_never_borrowed_from_another_worker_slot():
    module = _load()
    module.ENABLE_GENERAL_JOB_RECOVERY = True
    coordinator = module.ExecutionCoordinator(0)
    tiles = [[None] * 10 for _ in range(10)]
    tiles[3][4] = {
        "kind": "PASTURE",
        "animal": "SHEEP",
        "fed_today": False,
        "cared_today": False,
        "consecutive_unfed": 0,
        "yield_units": 0,
        "placed_day": 7,
    }
    obs = _observation(
        positions=((4, 4), (4, 3), (5, 4)),
        inventories=[{}, {}, {"WHEAT": 5}],
        shed={"WHEAT": 4},
        tiles=tiles,
    )
    action = {
        "farmer": ["PASS"],
        "hands": [["FEED"], ["PASS"]],
        "market": [],
    }
    repaired = coordinator.repair(obs, action)
    assert repaired["hands"][0] == ["SOUTH"]
    assert coordinator.jobs[1]["kind"] == "feed"
    assert 2 not in coordinator.jobs


def test_animal_build_failure_becomes_build_then_place_job():
    module = _load()
    module.ENABLE_GENERAL_JOB_RECOVERY = True
    coordinator = module.ExecutionCoordinator(0)
    tiles = [[None] * 10 for _ in range(10)]
    tiles[4][2] = {"kind": "PLANT", "crop": "WHEAT"}
    obs = _observation(
        step=258,
        positions=((2, 4),),
        inventories=[{"SHEEP": 1, "WHEAT": 1}],
        tiles=tiles,
    )
    repaired = coordinator.repair(obs, _action(["BUILD_PASTURE"]))
    assert coordinator.jobs[0]["kind"] == "place_animal"
    # The occupied intended tile is rejected; a real empty tile is selected.
    assert repaired["farmer"] in (["NORTH"], ["WEST"], ["EAST"], ["SOUTH"], ["BUILD_PASTURE"])
    assert coordinator.jobs[0]["target"] != [2, 4]


def test_post_opening_purchase_without_capacity_is_blocked():
    module = _load()
    module.ENABLE_ANIMAL_PURCHASE_GUARD = True
    coordinator = module.ExecutionCoordinator(0)
    tiles = [[{"kind": "PLANT", "crop": "WHEAT"}] * 10 for _ in range(10)]
    obs = _observation(step=252, tiles=tiles)
    repaired = coordinator.repair(
        obs, _action(["PASS"], [["BUY_ANIMAL", "SHEEP", 2]])
    )
    assert repaired["market"] == []
    assert coordinator.counts["animal_purchase_blocked"] == 1


def test_jobs_expire_at_day_boundary_before_actor_slots_are_reused():
    module = _load()
    module.ENABLE_GENERAL_JOB_RECOVERY = True
    coordinator = module.ExecutionCoordinator(0)
    obs = _observation(step=263, positions=((4, 3),), shed={"WHEAT": 7})
    coordinator.repair(obs, _action(["PICKUP", "WHEAT", 5]))
    assert coordinator.jobs
    obs = _observation(step=264, positions=((4, 4),), shed={"WHEAT": 7})
    coordinator.repair(obs, _action(["PASS"]))
    assert not coordinator.jobs
    assert coordinator.counts["job_expired_day_boundary"] == 1


def test_default_candidate_swaps_wheat_pickup_before_move_without_position_drift():
    module = _load()
    assert module.ENABLE_GENERAL_JOB_RECOVERY is False
    module.ENABLE_EXECUTION_TRANSACTIONS = True
    module._current_route_source = lambda observation=None: 42
    module._source_actor_action = lambda source, step, actor: {
        243: ["PICKUP", "WHEAT", 1],
        244: ["FEED"],
        245: ["CARE"],
        246: ["HARVEST"],
    }.get(step)
    coordinator = module.ExecutionCoordinator(0)
    tiles = [[None] * 10 for _ in range(10)]
    tiles[3][4] = {
        "kind": "PASTURE",
        "animal": "COW",
        "fed_today": False,
        "cared_today": False,
        "consecutive_unfed": 0,
        "yield_units": 0,
        "placed_day": 0,
    }
    obs = _observation(
        step=242,
        positions=((4, 4),),
        inventories=[{}],
        shed={"WHEAT": 7},
        tiles=tiles,
    )
    repaired = coordinator.repair(obs, _action(["NORTH"]))
    assert repaired["farmer"] == ["PICKUP", "WHEAT", 1]

    obs = _observation(
        step=243,
        positions=((4, 4),),
        inventories=[{"WHEAT": 1}],
        shed={"WHEAT": 6},
        tiles=tiles,
    )
    repaired = coordinator.repair(obs, _action(["PICKUP", "WHEAT", 5]))
    assert repaired["farmer"] == ["NORTH"]

    obs = _observation(
        step=244,
        positions=((4, 3),),
        inventories=[{"WHEAT": 1}],
        shed={"WHEAT": 6},
        tiles=tiles,
    )
    repaired = coordinator.repair(obs, _action(["FEED"]))
    assert repaired["farmer"] == ["FEED"]
    assert coordinator.jobs

    tiles[3][4]["fed_today"] = True
    obs = _observation(
        step=245,
        positions=((4, 3),),
        inventories=[{}],
        shed={"WHEAT": 6},
        tiles=tiles,
    )
    repaired = coordinator.repair(obs, _action(["CARE"]))
    assert repaired["farmer"] == ["CARE"]
    assert coordinator.jobs

    obs = _observation(
        step=246,
        positions=((4, 3),),
        inventories=[{}],
        shed={"WHEAT": 6},
        tiles=tiles,
    )
    repaired = coordinator.repair(obs, _action(["HARVEST"]))
    assert repaired["farmer"] == ["HARVEST"]
    assert not coordinator.jobs


def test_default_candidate_detours_locked_tile_deposit_and_rejoins_route():
    module = _load()
    module.ENABLE_EXECUTION_TRANSACTIONS = True
    module._current_route_source = lambda observation=None: 42
    module._source_actor_action = lambda source, step, actor: {
        251: ["PLACE", "MELON", 6],
        252: ["EAST"],
        253: ["CARE"],
    }.get(step)
    coordinator = module.ExecutionCoordinator(0)
    tiles = [[None] * 10 for _ in range(10)]
    tiles[5][3] = "LOCKED"
    obs = _observation(
        step=250,
        positions=((3, 4),),
        inventories=[{"MELON": 6}],
        shed={},
        tiles=tiles,
    )
    repaired = coordinator.repair(obs, _action(["SOUTH"]))
    assert repaired["farmer"] == ["EAST"]

    obs = _observation(
        step=251,
        positions=((4, 4),),
        inventories=[{"MELON": 6}],
        shed={},
        tiles=tiles,
    )
    repaired = coordinator.repair(obs, _action(["PLACE", "MELON", 6]))
    assert repaired["farmer"] == ["PLACE", "MELON", 6]

    obs = _observation(
        step=252,
        positions=((4, 4),),
        inventories=[{}],
        shed={"MELON": 6},
        tiles=tiles,
    )
    repaired = coordinator.repair(obs, _action(["NORTH"]))
    assert repaired["farmer"] == ["SOUTH"]
    assert coordinator.jobs

    obs = _observation(
        step=253,
        positions=((4, 5),),
        inventories=[{}],
        shed={"MELON": 6},
        tiles=tiles,
    )
    repaired = coordinator.repair(obs, _action(["CARE"]))
    assert repaired["farmer"] == ["CARE"]
    assert not coordinator.jobs


def test_service_policy_skips_only_low_value_safe_feed_and_matching_care():
    module = _load()
    module.ENABLE_SERVICE_POLICY = True
    tiles = [[None] * 10 for _ in range(10)]
    tiles[3][4] = {
        "kind": "PASTURE",
        "animal": "SHEEP",
        "fed_today": False,
        "cared_today": False,
        "consecutive_unfed": 0,
        "yield_units": 0,
        "placed_day": 0,
    }
    obs = _observation(step=10 * 24, positions=((4, 3),), tiles=tiles)
    obs["market"]["prices"]["WOOL"] = 30
    feed, reason = module._service_policy(obs, (4, 3), ["FEED"])
    assert feed == ["PASS"]
    assert reason == "low_value_nonproduction_safe_skip"
    care, reason = module._service_policy(obs, (4, 3), ["CARE"])
    assert care == ["PASS"]
    assert reason == "care_without_feed_has_no_effect"

    tiles[3][4]["consecutive_unfed"] = 1
    feed, reason = module._service_policy(obs, (4, 3), ["FEED"])
    assert feed == ["FEED"]
    assert reason is None
    tiles[3][4]["consecutive_unfed"] = 0
    obs["market"]["prices"]["WOOL"] = 241
    feed, reason = module._service_policy(obs, (4, 3), ["FEED"])
    assert feed == ["FEED"]
    assert reason is None


def test_fertilizer_policy_requires_incremental_crop_value_above_sale_option():
    module = _load()
    module.ENABLE_FERTILIZER_POLICY = True
    tiles = [[None] * 10 for _ in range(10)]
    tiles[3][4] = {
        "kind": "PLANT",
        "crop": "WHEAT",
        "planted_day": 9,
        "yield_units": 1,
        "fertilized_until_day": -1,
    }
    obs = _observation(step=10 * 24, positions=((4, 3),), tiles=tiles)
    action, reason = module._fertilizer_policy(
        obs, (4, 3), ["FERTILIZE"], {"FERTILIZER": 1}
    )
    assert action == ["PASS"]
    assert reason == "fertilizer_value_below_hurdle"

    obs["market"]["prices"]["WHEAT"] = 100
    obs["market"]["prices"]["FERTILIZER"] = 10
    action, reason = module._fertilizer_policy(
        obs, (4, 3), ["PASS"], {"FERTILIZER": 1}
    )
    assert action == ["FERTILIZE"]
    assert reason == "profitable_idle_wheat_fertilizer"
