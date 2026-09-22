from __future__ import annotations

import copy
import gzip
import importlib.util
import json
from pathlib import Path

import pytest

from agents.learning_round4_20260921.features import strategy_features as round4_features
from agents.learning_round5_20260921.contracts import attribute_primitive
from agents.learning_round5_20260921.evaluation import evaluate_artifact
from agents.learning_round5_20260921.executor import ExecutionCoordinator, WorkingState, _market_price
from agents.learning_round5_20260921.features import strategy_features as round5_features
from agents.learning_round5_20260921 import rule_main as round5_rule_main
from agents.learning_next_20260921.common import MarketHistory, bc_actor_features

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "experiments/learning_round5_20260921/input_bundle/round4_independent_audit/round5_regression_fixtures.json"
ROUND3_REPLAY = ROOT / "experiments/learning_round3_20260921/p3_paired_development/replays/feed_once_replan/qeinstein_moev2/seed_2026092421_seat_0.json.gz"


def _fixtures() -> dict[str, dict]:
    return {row["case_id"]: row for row in json.loads(FIXTURES.read_text(encoding="utf-8"))}


def _round3_replay() -> dict:
    with gzip.open(ROUND3_REPLAY, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def _replay_observation(replay: dict, step: int) -> dict:
    value = copy.deepcopy(replay["steps"][step][0]["observation"])
    value["step"] = step
    return value


def _replay_action(replay: dict, step: int) -> dict:
    return copy.deepcopy(replay["steps"][step + 1][0]["action"])


def _empty_observation(*, day: int = 0, hour: int = 0, actors: int = 1, money: int = 3000) -> dict:
    tiles = [[None if x < 5 and y < 5 else "LOCKED" for x in range(10)] for y in range(10)]
    hands = [[4, 4] for _ in range(actors - 1)]
    return {
        "player": 0,
        "step": day * 24 + hour,
        "day": day,
        "hour": hour,
        "farms": [
            {
                "money": money,
                "tiles": tiles,
                "farmer": [4, 4],
                "hands": hands,
                "unlocked_quadrants": ["NW"],
                "hires_today": actors - 1,
            },
            {
                "money": 3000,
                "tiles": copy.deepcopy(tiles),
                "farmer": [4, 4],
                "hands": [],
                "unlocked_quadrants": ["NW"],
                "hires_today": 0,
            },
        ],
        "private": {
            "shed": {item: 0 for item in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER", "GOOSE", "COW", "SHEEP")},
            "seeds": {crop: 0 for crop in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")},
            "inventories": [{} for _ in range(actors)],
        },
        "market": {
            "prices": {"WHEAT": 20, "CARROT": 30, "TOMATO": 60, "STRAWBERRY": 100, "MELON": 90, "EGG": 80, "MILK": 160, "WOOL": 180, "FERTILIZER": 10},
            "inventory": {"WHEAT": 100, "CARROT": 100, "TOMATO": 100, "STRAWBERRY": 100, "MELON": 100, "EGG": 100, "MILK": 100, "WOOL": 100, "FERTILIZER": 100},
        },
        "town": {"unlocked_shops": []},
    }


def test_round4_duplicate_harvest_first_is_ordered_and_reassigned() -> None:
    fixture = _fixtures()["duplicate_harvest_first"]
    coordinator = ExecutionCoordinator("test")
    emitted = coordinator.repair(fixture["before"], fixture["joint_action"], {})
    positions = [tuple(fixture["before"]["farms"][0]["farmer"]), *map(tuple, fixture["before"]["farms"][0]["hands"])]
    units = [emitted["farmer"], *emitted["hands"]]
    at_target = [index for index, position in enumerate(positions) if position == (0, 4)]
    assert sum(units[index] == ["HARVEST"] for index in at_target) == 1
    assert coordinator.diagnostics()["duplicate_harvests_blocked"] >= 1
    assert any(units[index] != ["PASS"] for index in at_target[1:])


def test_round4_six_actor_duplicate_harvest_has_one_owner() -> None:
    fixture = _fixtures()["duplicate_harvest_six_actors"]
    coordinator = ExecutionCoordinator("test")
    emitted = coordinator.repair(fixture["before"], fixture["joint_action"], {})
    seat = fixture["before"]["player"]
    positions = [tuple(fixture["before"]["farms"][seat]["farmer"]), *map(tuple, fixture["before"]["farms"][seat]["hands"])]
    units = [emitted["farmer"], *emitted["hands"]]
    at_target = [index for index, position in enumerate(positions) if position == (7, 4)]
    assert len(at_target) == 6
    assert sum(units[index] == ["HARVEST"] for index in at_target) == 1
    assert sum(units[index] != ["PASS"] for index in at_target) >= 2


def test_animal_full_yield_is_typed_and_harvested() -> None:
    fixture = _fixtures()["animal_full_yield_no_harvest"]
    coordinator = ExecutionCoordinator("test")
    emitted = coordinator.repair(fixture["before"], fixture["joint_action"], {})
    assert emitted["farmer"] == ["HARVEST"]
    assert coordinator.diagnostics()["animal_harvest_overrides"] == 1


def test_animal_harvest_attribution_uses_product_not_crop() -> None:
    before = _empty_observation()
    before["farms"][0]["tiles"][4][4] = {
        "kind": "PASTURE", "animal": "COW", "placed_day": 0, "yield_units": 6,
        "fed_today": True, "consecutive_unfed": 0, "cared_today": False,
        "fertilizer_available": True, "pending_care_bonus": 0,
    }
    after = copy.deepcopy(before)
    after["step"] += 1
    after["hour"] += 1
    after["farms"][0]["tiles"][4][4]["yield_units"] = 0
    after["private"]["inventories"][0]["MILK"] = 6
    assert attribute_primitive(before, after, 0, ["HARVEST"], (4, 4)) == ("ESTABLISHED", "HARVEST_ATTRIBUTED:MILK:6")


def test_atomic_plant_shortage_reassigns_all_requests() -> None:
    obs = _empty_observation(actors=2)
    obs["private"]["seeds"]["WHEAT"] = 1
    proposal = {"farmer": ["PLANT", "WHEAT"], "hands": [["PLANT", "WHEAT"]], "market": []}
    coordinator = ExecutionCoordinator("test")
    emitted = coordinator.repair(obs, proposal, {})
    assert emitted["farmer"] != ["PLANT", "WHEAT"]
    assert emitted["hands"][0] != ["PLANT", "WHEAT"]
    assert coordinator.diagnostics()["atomic_plants_blocked"] == 2


def test_ordered_build_consumes_tile_before_later_plant() -> None:
    obs = _empty_observation(actors=2)
    obs["private"]["seeds"]["WHEAT"] = 2
    proposal = {"farmer": ["BUILD_PASTURE"], "hands": [["PLANT", "WHEAT"]], "market": []}
    coordinator = ExecutionCoordinator("test")
    emitted = coordinator.repair(obs, proposal, {})
    assert emitted["farmer"] == ["BUILD_PASTURE"]
    assert emitted["hands"][0] != ["PLANT", "WHEAT"]
    assert any(row.get("reason") == "PLANT_PRECONDITION_FAILED" for row in coordinator.policy_trace())


def test_last_hour_unwatered_plant_is_replanned_and_day_boundary_is_unknown() -> None:
    obs = _empty_observation(day=4, hour=23)
    obs["private"]["seeds"]["STRAWBERRY"] = 1
    coordinator = ExecutionCoordinator("test")
    emitted = coordinator.repair(obs, {"farmer": ["PLANT", "STRAWBERRY"], "hands": [], "market": []}, {})
    assert emitted["farmer"] != ["PLANT", "STRAWBERRY"]
    assert any(row.get("reason") == "PLANT_WOULD_DIE_AT_DAY_BOUNDARY" for row in coordinator.policy_trace())
    before = _empty_observation(day=4, hour=23)
    before["farms"][0]["tiles"][4][4] = {
        "kind": "PLANT", "crop": "WHEAT", "planted_day": 2, "watered_today": False,
        "consecutive_unwatered": 0, "yield_units": 1, "fertilized_until_day": -1,
    }
    after = _empty_observation(day=5, hour=0)
    after["farms"][0]["tiles"][4][4] = copy.deepcopy(before["farms"][0]["tiles"][4][4])
    after["farms"][0]["tiles"][4][4]["watered_today"] = False
    assert attribute_primitive(before, after, 0, ["WATER"], (4, 4)) == ("UNKNOWN", "WATER_DAY_BOUNDARY_RESET")


def test_water_target_consumed_by_later_joint_actor_is_unknown_not_failed() -> None:
    before = _empty_observation(day=4, hour=10)
    before["farms"][0]["tiles"][4][4] = {
        "kind": "PLANT", "crop": "WHEAT", "planted_day": 2, "watered_today": False,
        "consecutive_unwatered": 0, "yield_units": 1, "fertilized_until_day": -1,
    }
    after = copy.deepcopy(before)
    after["step"] += 1
    after["hour"] += 1
    after["farms"][0]["tiles"][4][4] = None
    assert attribute_primitive(before, after, 0, ["WATER"], (4, 4)) == (
        "UNKNOWN", "WATER_TARGET_CHANGED_LATER_IN_JOINT"
    )


def test_opening_wheat_sale_respects_accepted_animal_commitments() -> None:
    fixture = _fixtures()["opening_sell_feed_reserve"]
    coordinator = ExecutionCoordinator("test")
    emitted = coordinator.repair(fixture["before"], fixture["joint_action"], {})
    sold = sum(int(order[2]) for order in emitted["market"] if order[:2] == ["SELL", "WHEAT"])
    assert sold < 4
    assert coordinator.diagnostics()["wheat_sell_units_blocked"] > 0


def test_market_ledger_matches_fixed_price_and_partial_order_semantics() -> None:
    module_path = ROOT / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py"
    spec = importlib.util.spec_from_file_location("fixed_market_probe", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for inventory in (9600, 9999, 10000, 10001, 10400):
        assert _market_price("WHEAT", inventory) == module.market_price("WHEAT", inventory)
    obs = _empty_observation(money=35)
    coordinator = ExecutionCoordinator("market-partial")
    emitted = coordinator.repair(obs, {"farmer": ["PASS"], "hands": [], "market": [["BUY_SEED", "WHEAT", 5]]}, {})
    assert emitted["market"] == [["BUY_SEED", "WHEAT", 3]]


def test_actor_pickup_frees_capacity_before_market_and_sale_funds_reinvestment() -> None:
    obs = _empty_observation(money=0)
    obs["private"]["shed"]["WHEAT"] = 99
    obs["private"]["shed"]["CARROT"] = 1
    coordinator = ExecutionCoordinator("market-order")
    emitted = coordinator.repair(
        obs,
        {
            "farmer": ["PICKUP", "WHEAT", 2],
            "hands": [],
            "market": [["SELL", "CARROT", 1], ["BUY_SEED", "WHEAT", 2]],
        },
        {},
    )
    assert emitted["farmer"] == ["PICKUP", "WHEAT", 2]
    assert emitted["market"] == [["SELL", "CARROT", 1], ["BUY_SEED", "WHEAT", 2]]


def test_round3_wheat_quantity_and_duplicate_feed_regressions_use_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    replay = _round3_replay()
    coordinator = ExecutionCoordinator("regression")
    pickup = coordinator.repair(_replay_observation(replay, 434), _replay_action(replay, 434), {})
    assert pickup["hands"][4] == ["PICKUP", "WHEAT", 2]
    feed_observation = _replay_observation(replay, 435)
    feed_observation["private"]["inventories"][5]["WHEAT"] = 2
    feed = coordinator.repair(feed_observation, _replay_action(replay, 435), {})
    assert feed["hands"][3] == ["FEED"]
    assert feed["hands"][4] != ["FEED"]
    round5_rule_main.reset_runtime_state()
    monkeypatch.setattr(round5_rule_main._runtime.base, "agent", lambda _observation, _configuration=None: _replay_action(replay, 435))
    entrypoint = round5_rule_main.agent(feed_observation)
    units = [entrypoint["farmer"], *entrypoint["hands"]]
    assert sum(units[index] == ["FEED"] for index in (4, 5)) == 1


def test_yield_changes_round4_selector_alias_but_not_round5_or_old_bc() -> None:
    low = _empty_observation()
    low["farms"][0]["tiles"][4][4] = {
        "kind": "PASTURE", "animal": "COW", "placed_day": 0, "yield_units": 0,
        "fed_today": True, "consecutive_unfed": 0, "cared_today": False,
        "fertilizer_available": False, "pending_care_bonus": 0,
    }
    high = copy.deepcopy(low)
    high["farms"][0]["tiles"][4][4]["yield_units"] = 6
    assert round4_features(low) == round4_features(high)
    assert round5_features(low) != round5_features(high)
    assert (bc_actor_features(low, 0, "PASS", MarketHistory()) != bc_actor_features(high, 0, "PASS", MarketHistory())).any()


def test_positive_yield_can_be_held_or_harvested_by_horizon() -> None:
    early = _empty_observation(day=10)
    early["farms"][0]["tiles"][4][4] = {
        "kind": "PASTURE", "animal": "COW", "placed_day": 0, "yield_units": 1,
        "fed_today": True, "consecutive_unfed": 0, "cared_today": False,
        "fertilizer_available": False, "pending_care_bonus": 0,
    }
    proposal = {"farmer": ["WEST"], "hands": [], "market": []}
    assert ExecutionCoordinator("test").repair(early, proposal, {})["farmer"] == ["WEST"]
    late = copy.deepcopy(early)
    late.update({"day": 28, "hour": 0, "step": 672})
    assert ExecutionCoordinator("test").repair(late, proposal, {})["farmer"] == ["HARVEST"]


def test_animal_maintenance_and_retirement_plans_drive_actions_and_reserves() -> None:
    maintain = _empty_observation(day=7, money=500)
    maintain["farms"][0]["tiles"][4][4] = {
        "kind": "PASTURE", "animal": "COW", "placed_day": 0, "yield_units": 0,
        "fed_today": False, "consecutive_unfed": 1, "cared_today": False,
        "fertilizer_available": False, "pending_care_bonus": 0,
    }
    maintainer = ExecutionCoordinator("maintain")
    maintained = maintainer.repair(maintain, {"farmer": ["PASS"], "hands": [], "market": []}, {"ANIMAL_LIFECYCLE_REALIZATION": 1.0})
    assert maintained["market"] and maintained["market"][0][:2] == ["BUY_PRODUCT", "WHEAT"]
    assert maintainer.animal_plans()[0]["state"] == "MAINTAIN"

    retire = copy.deepcopy(maintain)
    retire.update({"day": 29, "hour": 5, "step": 701})
    retire["private"]["inventories"][0]["WHEAT"] = 1
    retiring = ExecutionCoordinator("retire")
    retired = retiring.repair(retire, {"farmer": ["FEED"], "hands": [], "market": []}, {"ANIMAL_LIFECYCLE_REALIZATION": 1.0})
    assert retiring.animal_plans()[0]["state"] == "RETIRE"
    assert retired["farmer"] != ["FEED"]
    assert retiring.diagnostics()["retirement_plans_enforced"] == 1

    capacity_blocked = copy.deepcopy(retire)
    capacity_blocked.update({"hour": 23, "step": 719})
    capacity_blocked["private"]["shed"]["WHEAT"] = 100
    capacity_blocked["private"]["inventories"][0] = {}
    capacity_blocked["farms"][0]["tiles"][4][4]["yield_units"] = 6
    capacity = ExecutionCoordinator("capacity-retire")
    held = capacity.repair(capacity_blocked, {"farmer": ["HARVEST"], "hands": [], "market": []}, {"ANIMAL_LIFECYCLE_REALIZATION": 1.0})
    assert capacity.animal_plans()[0]["state"] == "RETIRE"
    assert capacity.animal_plans()[0]["retirement_reason"] == "TERMINAL_SHED_CAPACITY_BLOCKS_REALIZATION"
    assert held["farmer"] != ["HARVEST"]


def test_evaluator_changes_with_failures_pending_and_model_use() -> None:
    base = {
        "package": {"tested": True, "valid": True, "last_callable": "agent", "full_episodes": 2},
        "execution": {"required_contracts": [{"status": "PASS"}], "scope": "fixtures"},
        "training": {"optimizer_updates": 3, "parameter_change_l2": 1.0, "checkpoint_valid": True},
        "model": {"model_loads": 1, "inference_calls": 10, "invalid_fallbacks": 0, "reloaded": True},
        "skill": {"evaluated": True, "completed": 2, "required": 2, "failed": 0, "unknown": 0},
        "local_economic": {"evaluated": False},
        "external_economic": {"evaluated": False},
        "online": {"evaluated": False},
        "diagnostic_hypothesis": "bounded",
    }
    passed = evaluate_artifact(base, {"version": "x", "required_hashes_current": True}, "learned", {})
    assert passed["axes"]["EXECUTION_CORRECT"]["status"] == "PASS"
    assert passed["axes"]["MODEL_USED"]["status"] == "PASS"
    failed = copy.deepcopy(base)
    failed["execution"]["required_contracts"] = [{"status": "FAIL"}]
    assert evaluate_artifact(failed, {"required_hashes_current": True}, "learned", {})["axes"]["READY_FOR_LIMITED_SUBMISSION"]["status"] == "FAIL"
    pending = copy.deepcopy(base)
    pending["skill"]["unknown"] = 1
    assert evaluate_artifact(pending, {"required_hashes_current": True}, "learned", {})["axes"]["SKILL_COMPLETION"]["status"] == "UNKNOWN"
    loaded_only = copy.deepcopy(base)
    loaded_only["model"]["inference_calls"] = 0
    assert evaluate_artifact(loaded_only, {"required_hashes_current": True}, "learned", {})["axes"]["MODEL_USED"]["status"] == "FAIL"
    deferred = copy.deepcopy(base)
    deferred["limited_submission_decision"] = "DEFER"
    deferred["limited_submission_reason"] = "all proxy games lost"
    assert evaluate_artifact(deferred, {"required_hashes_current": True}, "learned", {})["axes"]["READY_FOR_LIMITED_SUBMISSION"]["status"] == "NOT_APPLICABLE"


class AnimalLifecycleProbe:
    def __init__(self, animal: str) -> None:
        self.animal = animal
        self.product = {"COW": "MILK", "SHEEP": "WOOL"}[animal]
        self.coordinator = ExecutionCoordinator(f"scenario-{animal.lower()}")

    def __call__(self, observation: dict, configuration=None) -> dict:
        del configuration
        if int(observation.get("step", 0)) == 0:
            self.coordinator.reset()
        tile = observation["farms"][observation["player"]]["tiles"][4][4]
        private = observation["private"]
        inventory = private["inventories"][0]
        market = []
        if tile is None:
            unit = ["BUILD_PASTURE"]
            market = [["BUY_ANIMAL", self.animal, 1], ["BUY_PRODUCT", "WHEAT", 20]]
        elif isinstance(tile, dict) and not tile.get("animal"):
            unit = ["PLACE", self.animal] if inventory.get(self.animal, 0) else ["PICKUP", self.animal, 1]
        elif inventory.get(self.product, 0):
            unit = ["DROP"]
        elif private["shed"].get(self.product, 0):
            unit = ["PASS"]
            market = [["SELL", self.product, int(private["shed"][self.product])]]
        elif int(tile.get("yield_units", 0)) > 0:
            unit = ["HARVEST"]
        elif not tile.get("fed_today"):
            unit = ["FEED"] if inventory.get("WHEAT", 0) else ["PICKUP", "WHEAT", 2]
        elif not tile.get("cared_today"):
            unit = ["CARE"]
        else:
            unit = ["PASS"]
        return self.coordinator.repair(observation, {"farmer": unit, "hands": [], "market": market}, {"ANIMAL_LIFECYCLE_REALIZATION": 1.0})


@pytest.mark.parametrize(("animal", "product", "minimum_day"), [("COW", "MILK", 8), ("SHEEP", "WOOL", 6)])
def test_real_engine_animal_investment_reaches_cash_realization(animal: str, product: str, minimum_day: int) -> None:
    from kaggle_environments import make

    probe = AnimalLifecycleProbe(animal)
    env = make("kaggriculture", configuration={"episodeSteps": 300}, debug=True, info={"seed": 20260950 + minimum_day})
    env.run([probe, "pass"])
    actions = [state[0].get("action") or {} for state in env.steps[1:]]
    harvest_records = [index for index, action in enumerate(actions, 1) if action.get("farmer") == ["HARVEST"]]
    sell_records = [index for index, action in enumerate(actions, 1) if any(order[:2] == ["SELL", product] for order in action.get("market", []))]
    assert harvest_records and sell_records and sell_records[0] > harvest_records[0]
    final = env.steps[-1][0]["observation"]
    assert final["farms"][0]["money"] > 0
    assert probe.coordinator.diagnostics()["cash_realization_completed"] >= 1


def test_fixed_engine_two_animal_harvests_do_not_duplicate_yield() -> None:
    module_path = ROOT / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py"
    spec = importlib.util.spec_from_file_location("fixed_kaggriculture", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    farm = {"farmer": [4, 4], "hands": [[4, 4]], "tiles": [[None for _ in range(10)] for _ in range(10)]}
    farm["tiles"][4][4] = {
        "kind": "PASTURE", "animal": "COW", "placed_day": 0, "yield_units": 1,
        "fed_today": True, "consecutive_unfed": 0, "cared_today": False,
        "fertilizer_available": False, "pending_care_bonus": 0,
    }
    private = {"shed": {}, "seeds": {}, "inventories": [{}, {}]}
    module._apply_unit_action(farm, private, 0, ["HARVEST"], 10, 10, 24)
    module._apply_unit_action(farm, private, 1, ["HARVEST"], 10, 10, 24)
    assert private["inventories"][0].get("MILK") == 1
    assert private["inventories"][1].get("MILK", 0) == 0


def test_working_state_pickup_and_fertilizer_are_consumed_in_actor_order() -> None:
    obs = _empty_observation(actors=2)
    obs["private"]["shed"]["WHEAT"] = 1
    obs["farms"][0]["tiles"][4][4] = {
        "kind": "PASTURE", "animal": "COW", "placed_day": 0, "yield_units": 0,
        "fed_today": False, "consecutive_unfed": 0, "cared_today": False,
        "fertilizer_available": True, "pending_care_bonus": 0,
    }
    state = WorkingState(obs)
    assert state.apply(0, ["PICKUP", "WHEAT", 1], set())[0] == ["PICKUP", "WHEAT", 1]
    assert state.apply(1, ["PICKUP", "WHEAT", 1], set())[0] is None
    assert state.apply(0, ["COLLECT_FERTILIZER"], set())[0] == ["COLLECT_FERTILIZER"]
    assert state.apply(1, ["COLLECT_FERTILIZER"], set())[0] is None
