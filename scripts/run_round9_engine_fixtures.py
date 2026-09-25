"""Fixed-engine differential fixtures for the Round9 A2 prefix resolver."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kaggle_environments import make

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agents" / "round9_teacher_reproduction_and_closed_loop_bc_20260923" / "a2"
EXPERIMENT = ROOT / "experiments" / "round9_teacher_reproduction_and_closed_loop_bc_20260923"
OUTPUT = EXPERIMENT / "fixed_engine_fixtures_v1.json"
REPLAY_PATH = ROOT / "data" / "replays" / "submission_56216119" / "episode_109118332.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_round9_economy import apply_actors, process_market  # noqa: E402
from run_round9_contract_controls import core_state, isolated_step, recorded_action  # noqa: E402

sys.path.pop(0)


def load_runtime():
    for name in ("common", "spatial", "spatial_policy", "runtime", "model_compat", "round9_fixture_main"):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location("round9_fixture_main", AGENT / "main.py")
    assert spec is not None and spec.loader is not None
    sys.path.insert(0, str(AGENT))
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return sys.modules["runtime"]
    finally:
        sys.path.pop(0)


def observation(*, day: int = 0, hour: int = 0, hands: int = 0) -> dict[str, Any]:
    environment = make("kaggriculture", configuration={"episodeSteps": 720, "seed": 20260923, "weedSpawnChance": 0.0})
    value = copy.deepcopy(environment.toJSON()["steps"][0][0]["observation"])
    value["player"] = 0
    value["step"] = day * 24 + hour
    value["day"] = day
    value["hour"] = hour
    value["farms"][0]["farmer"] = [1, 1]
    value["farms"][0]["hands"] = [[1, 1] for _ in range(hands)]
    value["private"]["inventories"] = [{} for _ in range(hands + 1)]
    return value


def plant(crop: str, planted_day: int, yield_units: int, *, watered: bool = False) -> dict[str, Any]:
    return {
        "kind": "PLANT",
        "crop": crop,
        "planted_day": planted_day,
        "watered_today": watered,
        "consecutive_unwatered": 1,
        "yield_units": yield_units,
        "max_lifespan_step": 720,
        "fertilized_until_day": -1,
    }


def animal(kind: str) -> dict[str, Any]:
    return {
        "kind": "COOP" if kind == "GOOSE" else "PASTURE",
        "animal": kind,
        "placed_day": 0,
        "yield_units": 0,
        "consecutive_unfed": 0,
        "fed_today": False,
        "cared_today": False,
        "fertilizer_available": False,
        "pending_care_bonus": 0,
    }


def canonical(value: Any) -> Any:
    return json.loads(json.dumps(value))


def engine_actor_result(source: dict[str, Any], requested: list[list[Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    farms = copy.deepcopy(source["farms"])
    privates = [copy.deepcopy(source["private"]), observation()["private"]]
    actor_action = {"farmer": requested[0], "hands": requested[1:], "market": []}
    apply_actors(farms, privates, [actor_action, {"farmer": ["PASS"], "hands": [], "market": []}], int(source["step"]))
    return farms[0], privates[0]


def shadow_actor_result(
    runtime: Any, source: dict[str, Any], requested: list[list[Any]]
) -> tuple[list[list[Any]], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    shadow = copy.deepcopy(source)
    remaining = {str(key): int(value) for key, value in shadow["private"]["seeds"].items()}
    final, trace = [], []
    for index, action in enumerate(requested):
        resolved, record = runtime._resolve_actor(shadow, index, copy.deepcopy(action), remaining)
        final.append(resolved)
        trace.append(record)
    return final, shadow["farms"][0], shadow["private"], trace


def actor_fixture(
    runtime: Any, name: str, source: dict[str, Any], requested: list[list[Any]], expected: list[list[Any]]
) -> dict[str, Any]:
    final, shadow_farm, shadow_private, trace = shadow_actor_result(runtime, source, requested)
    engine_farm, engine_private = engine_actor_result(source, final)
    passed = (
        final == expected
        and canonical(shadow_farm) == canonical(engine_farm)
        and canonical(shadow_private) == canonical(engine_private)
    )
    if not passed:
        raise AssertionError({"fixture": name, "requested": requested, "final": final, "expected": expected})
    return {
        "name": name,
        "requested": requested,
        "final": final,
        "expected": expected,
        "full_farm_private_engine_exact": True,
        "trace": trace,
        "final_position": engine_farm["farmer"],
        "final_money": engine_farm["money"],
        "final_tile": engine_farm["tiles"][1][1],
        "final_inventories": engine_private["inventories"],
        "final_shed": engine_private["shed"],
    }


def market_fixture(
    runtime: Any,
    name: str,
    source: dict[str, Any],
    actor_requests: list[list[Any]],
    orders: list[list[Any]],
    expected_orders: list[list[Any]],
) -> dict[str, Any]:
    final_actor, shadow_farm, shadow_private, actor_trace = shadow_actor_result(runtime, source, actor_requests)
    shadow = copy.deepcopy(source)
    shadow["farms"][0], shadow["private"] = copy.deepcopy(shadow_farm), copy.deepcopy(shadow_private)
    final_market, market_trace = runtime._resolve_market(shadow, copy.deepcopy(orders))
    farms = copy.deepcopy(source["farms"])
    privates = [copy.deepcopy(source["private"]), observation()["private"]]
    actions = [
        {"farmer": final_actor[0], "hands": final_actor[1:], "market": final_market},
        {"farmer": ["PASS"], "hands": [], "market": []},
    ]
    apply_actors(farms, privates, actions, int(source["step"]))
    market = copy.deepcopy(source["market"])
    process_market(
        farms, privates, market, actions, {"maxMarketOrdersPerTurn": 10, "farmHandCostMult": 1, "shedCapacity": 100}
    )
    passed = (
        final_market == expected_orders
        and canonical(shadow["farms"][0]) == canonical(farms[0])
        and canonical(shadow["private"]) == canonical(privates[0])
        and canonical(shadow["market"]) == canonical(market)
    )
    if not passed:
        raise AssertionError(
            {
                "fixture": name,
                "final_market": final_market,
                "expected": expected_orders,
                "shadow_money": shadow["farms"][0]["money"],
                "engine_money": farms[0]["money"],
            }
        )
    return {
        "name": name,
        "actor_requested": actor_requests,
        "actor_final": final_actor,
        "market_requested": orders,
        "market_final": final_market,
        "full_money_inventory_seed_market_engine_exact": True,
        "actor_trace": actor_trace,
        "market_trace": market_trace,
        "final_money": farms[0]["money"],
        "final_shed": privates[0]["shed"],
        "final_seeds": privates[0]["seeds"],
    }


def main() -> None:
    if OUTPUT.exists():
        raise FileExistsError(f"refusing to overwrite {OUTPUT}")
    runtime = load_runtime()
    results = []

    value = observation(hands=1)
    value["private"]["seeds"]["WHEAT"] = 1
    results.append(
        actor_fixture(
            runtime, "PLANT_WHEAT_then_WATER", value, [["PLANT", "WHEAT"], ["WATER"]], [["PLANT", "WHEAT"], ["WATER"]]
        )
    )

    value = observation(day=4, hands=1)
    value["farms"][0]["tiles"][1][1] = plant("WHEAT", 0, 4)
    value["private"]["seeds"]["CARROT"] = 1
    results.append(
        actor_fixture(
            runtime,
            "HARVEST_then_PLANT_CARROT",
            value,
            [["HARVEST"], ["PLANT", "CARROT"]],
            [["HARVEST"], ["PLANT", "CARROT"]],
        )
    )

    value = observation(hands=1)
    value["private"]["inventories"][1]["COW"] = 1
    results.append(
        actor_fixture(
            runtime,
            "BUILD_PASTURE_then_PLACE_COW",
            value,
            [["BUILD_PASTURE"], ["PLACE", "COW", 1]],
            [["BUILD_PASTURE"], ["PLACE", "COW", 1]],
        )
    )

    value = observation(hands=1)
    value["farms"][0]["farmer"] = [4, 4]
    value["farms"][0]["hands"] = [[4, 4]]
    value["private"]["inventories"][0]["WHEAT"] = 5
    results.append(
        actor_fixture(
            runtime,
            "PLACE_WHEAT5_then_PICKUP_WHEAT5",
            value,
            [["PLACE", "WHEAT", 5], ["PICKUP", "WHEAT", 5]],
            [["PLACE", "WHEAT", 5], ["PICKUP", "WHEAT", 5]],
        )
    )

    value = observation(hands=2)
    value["farms"][0]["tiles"][1][1] = animal("COW")
    value["private"]["inventories"][0]["WHEAT"] = 1
    value["private"]["inventories"][1]["WHEAT"] = 1
    results.append(
        actor_fixture(
            runtime,
            "duplicate_FEED_then_valid_CARE",
            value,
            [["FEED"], ["FEED"], ["CARE"]],
            [["FEED"], ["PASS"], ["CARE"]],
        )
    )

    value = observation(day=4, hands=1)
    value["farms"][0]["tiles"][1][1] = plant("WHEAT", 0, 3)
    results.append(
        actor_fixture(runtime, "WATER_then_HARVEST", value, [["WATER"], ["HARVEST"]], [["WATER"], ["HARVEST"]])
    )

    value = observation(day=4, hands=2)
    value["farms"][0]["tiles"][1][1] = plant("WHEAT", 0, 3)
    value["private"]["inventories"][0]["FERTILIZER"] = 1
    results.append(
        actor_fixture(
            runtime,
            "FERTILIZE_WATER_HARVEST",
            value,
            [["FERTILIZE"], ["WATER"], ["HARVEST"]],
            [["FERTILIZE"], ["WATER"], ["HARVEST"]],
        )
    )

    value = observation(hands=1)
    value["farms"][0]["hands"] = [[2, 1]]
    value["private"]["seeds"]["WHEAT"] = 1
    results.append(
        actor_fixture(
            runtime,
            "same_turn_seed_shortage",
            value,
            [["PLANT", "WHEAT"], ["PLANT", "WHEAT"]],
            [["PLANT", "WHEAT"], ["PASS"]],
        )
    )

    value = observation()
    value["farms"][0]["farmer"] = [4, 4]
    value["private"]["shed"]["WHEAT"] = 3
    results.append(actor_fixture(runtime, "partial_PICKUP", value, [["PICKUP", "WHEAT", 5]], [["PICKUP", "WHEAT", 3]]))

    value = observation()
    value["farms"][0]["farmer"] = [4, 4]
    value["private"]["shed"]["CARROT"] = 100
    value["private"]["inventories"][0]["WHEAT"] = 5
    results.append(actor_fixture(runtime, "full_shed_DROP_discards_overflow", value, [["DROP"]], [["DROP"]]))

    value = observation()
    value["farms"][0]["money"] = 55
    results.append(
        market_fixture(
            runtime,
            "partial_BUY_PRODUCT",
            value,
            [["PASS"]],
            [["BUY_PRODUCT", "WHEAT", 20]],
            [["BUY_PRODUCT", "WHEAT", 2]],
        )
    )

    value = observation()
    value["farms"][0]["money"] = 0
    value["private"]["shed"]["WHEAT"] = 2
    results.append(
        market_fixture(
            runtime,
            "SELL_then_BUY",
            value,
            [["PASS"]],
            [["SELL", "WHEAT", 2], ["BUY_PRODUCT", "WHEAT", 1]],
            [["SELL", "WHEAT", 2], ["BUY_PRODUCT", "WHEAT", 1]],
        )
    )

    value = observation()
    value["farms"][0]["farmer"] = [4, 4]
    value["private"]["inventories"][0]["WHEAT"] = 5
    results.append(
        market_fixture(
            runtime, "actor_DROP_then_SELL", value, [["DROP"]], [["SELL", "WHEAT", 5]], [["SELL", "WHEAT", 5]]
        )
    )

    replay = json.loads(REPLAY_PATH.read_text(encoding="utf-8"))
    for step, name in (
        (23, "day_boundary_actor_regeneration_and_market_order"),
        (718, "terminal_last_executable_decision"),
    ):
        teacher = recorded_action(replay, step, 0)
        actual = isolated_step(replay, step, teacher)
        expected = core_state(replay["steps"][step + 1])
        exact = actual == expected
        if not exact:
            raise AssertionError(name)
        results.append(
            {
                "name": name,
                "source_episode": 109118332,
                "observation_step": step,
                "record_index": step + 1,
                "action": teacher,
                "complete_official_next_state_exact": exact,
                "status": actual[0]["status"],
                "next_day": actual[0]["observation"]["day"],
                "next_hour": actual[0]["observation"]["hour"],
            }
        )
    payload = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "engine": "kaggle-environments 1.32.7",
        "fixture_count": len(results),
        "passed": len(results),
        "failed": 0,
        "full_state_fields": [
            "position",
            "money",
            "tile kind/resource/generation/yield",
            "inventory",
            "shed",
            "seeds",
            "market",
        ],
        "fixtures": results,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
