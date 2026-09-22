# ruff: noqa: E501
from __future__ import annotations

import gzip
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from kaggle_environments.envs.kaggriculture import kaggriculture as engine

from agents.learning_round3_20260921.contracts import (
    actor_identity,
    actor_identity_matches,
    apply_candidate_or_keep,
    normalize_typed,
    rejoin_status,
    validate_joint_action,
)
from agents.learning_round3_20260921.market import MARKET_PARAMS, market_price, simulate_market
from scripts.learning_round3 import replay_task_digest, reusable_replay, sha256

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "experiments/learning_round3_20260921/REGRESSION_CASES"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _contract(obs: dict, actor: int, continuation: list[list[object]], **updates: object) -> dict:
    result = {
        "candidate_id": "generic-test-plan",
        "preconditions": {},
        "actor_identity": actor_identity(obs, actor),
        "reserved_materials": {},
        "reserved_cash": 0,
        "reserved_shed_capacity": 0,
        "deadline_step": int(obs["step"]) + 4,
        "continuation": continuation,
        "safe_rejoin_boundary": None,
        "expected_rejoin": {"position": result_position(obs, actor), "minimum_inventory": {}},
        "primitive_postconditions": ["operation_observed"],
        "economic_postconditions": ["paired_margin_nonnegative"],
        "abort_policy": "KEEP",
        "replanning_policy": "STATE_BASED_ACTOR_REPLAN",
    }
    result.update(updates)
    return result


def result_position(obs: dict, actor: int) -> list[int]:
    farm = obs["farms"][obs["player"]]
    return list([farm["farmer"], *farm.get("hands", [])][actor])


def test_required_wheat_pickup_cannot_be_erased() -> None:
    case = _fixture("wheat_pickup_removed.json")
    obs, control = case["observation"], case["control"]
    contract = _contract(
        obs,
        1,
        case["candidate"]["continuation"],
        preconditions={"remaining_wheat_uses": case["candidate"]["remaining_wheat_uses"]},
    )
    output, reasons = apply_candidate_or_keep(obs, control, contract)
    assert output == control
    assert "REQUIRED_PICKUP_REMOVED:WHEAT" in reasons


def test_feed_reservation_and_drop_are_enforced_on_final_joint_action() -> None:
    case = _fixture("resource_conflicts.json")
    obs = {
        "player": 0, "step": 100, "day": 4, "hour": 4,
        "farms": [{"farmer": [4, 4], "hands": [[4, 4], [4, 4]], "money": 3000}, {"farmer": [0, 0], "hands": [], "money": 3000}],
        "private": {"shed": case["shed"], "inventories": case["inventories"]},
        "configuration": {"shedCapacity": 100, "maxMarketOrdersPerTurn": 10},
    }
    contract = _contract(
        obs, 1, [["FEED"]],
        reserved_materials={"shed:WHEAT": 2, "actor:1:WHEAT": 2},
        reserved_shed_capacity=1,
    )
    reasons = validate_joint_action(obs, case["joint_action"], [contract])
    assert any(reason.startswith("DROP_VIOLATES_FUTURE_RESERVATION") for reason in reasons)
    assert any(reason.startswith("SHED_MATERIAL_DOUBLE_USE") for reason in reasons)
    assert any(reason.startswith("SHED_CAPACITY_OVERBOOKED") for reason in reasons)


def test_missing_movement_requires_state_based_replan_not_stale_resume() -> None:
    case = _fixture("movement_rejoin_failure.json")
    obs = {
        "player": 0, "step": 201, "day": 8, "hour": 9,
        "farms": [{"farmer": case["actual_after_replacement"]["position"], "hands": [], "money": 1}, {"farmer": [0, 0], "hands": [], "money": 1}],
        "private": {"shed": {}, "inventories": [{}]},
        "configuration": {},
    }
    contract = _contract(
        obs, 0, case["replacement"],
        expected_rejoin=case["expected_rejoin"],
        safe_rejoin_boundary={"after": "NORTH", "proof": "position-and-inventory"},
    )
    status, reasons = rejoin_status(obs, contract)
    assert status == case["required_result"]
    assert "REJOIN_POSITION_MISMATCH" in reasons


def test_hand_identity_expires_at_day_boundary_and_index_reuse() -> None:
    obs = {
        "player": 0, "step": 23, "day": 0, "hour": 23,
        "farms": [{"farmer": [4, 4], "hands": [[3, 3]], "money": 1}, {"farmer": [0, 0], "hands": [], "money": 1}],
        "private": {"shed": {}, "inventories": [{}, {}]},
    }
    identity = actor_identity(obs, 1)
    next_day = deepcopy(obs)
    next_day.update({"step": 24, "day": 1, "hour": 0})
    next_day["farms"][0]["hands"] = [[3, 3]]
    assert not actor_identity_matches(next_day, identity)


def test_typed_normalization_rejects_unseen_constant_without_extreme_z() -> None:
    case = _fixture("unknown_support.json")
    values, reasons = normalize_typed(case["values"], case["schema"])
    assert values[0] == 0.0
    assert max(abs(value) for value in values) < 10
    assert any(reason.startswith(case["required_reason"]) for reason in reasons)


@pytest.mark.parametrize("item", MARKET_PARAMS)
@pytest.mark.parametrize("inventory", [9500, 9900, 10000, 10100, 11000, 50000])
def test_market_price_matches_pinned_engine(item: str, inventory: int) -> None:
    assert market_price(item, inventory) == engine.market_price(item, inventory)


def _engine_market(players: list[dict], queues: list[list[list[object]]], inventory: dict[str, int]):
    farms = [engine._new_farm(10, row["money"]) for row in players]
    market = engine._new_market()
    market["inventory"].update(inventory)
    privates = []
    state = []
    for index, row in enumerate(players):
        private = {
            "shed": {**{key: 0 for key in [*engine.PRODUCTS, *engine.ANIMALS]}, **row.get("shed", {})},
            "seeds": {**{key: 0 for key in engine.CROPS}, **row.get("seeds", {})},
            "inventories": [{}],
        }
        farms[index]["hires_today"] = row.get("hires_today", 0)
        privates.append(private)
        state.append(SimpleNamespace(observation=SimpleNamespace(private=private), action={"farmer": ["PASS"], "hands": [], "market": queues[index]}))
    for row in state:
        row.observation.market = market
        row.observation.farms = farms
        row.observation.town = engine._new_town()
    env = SimpleNamespace(configuration=SimpleNamespace(boardSize=10, maxMarketOrdersPerTurn=10, farmHandCostMult=1, shedCapacity=100))
    engine._process_market(state, env)
    return market, farms, privates


@pytest.mark.parametrize(
    "queues",
    [
        [[["SELL", "MELON", 12], ["SELL", "FERTILIZER", 13]], [["SELL", "MELON", 12], ["SELL", "FERTILIZER", 13]]],
        [[["BUY_PRODUCT", "WHEAT", 3], ["SELL", "WHEAT", 2]], [["SELL", "WHEAT", 4], ["BUY_PRODUCT", "FERTILIZER", 2]]],
        [[["SELL", "FERTILIZER", 5], ["HIRE"], ["BUY_LAND"]], [["SELL", "MELON", 2], ["HIRE"]]],
    ],
)
def test_lockstep_evaluator_matches_pinned_engine(queues: list[list[list[object]]]) -> None:
    players = [
        {"money": 3000, "shed": {"MELON": 20, "FERTILIZER": 20, "WHEAT": 5}, "seeds": {}, "hires_today": 0, "hands": 0, "unlocked_land": 1},
        {"money": 3000, "shed": {"MELON": 20, "FERTILIZER": 20, "WHEAT": 5}, "seeds": {}, "hires_today": 0, "hands": 0, "unlocked_land": 1},
    ]
    inventory = {item: 10000 for item in engine.PRODUCTS}
    expected_market, expected_farms, expected_privates = _engine_market(players, queues, inventory)
    actual = simulate_market(inventory, players, queues)
    assert actual["market_inventory"] == dict(expected_market["inventory"])
    for index in range(2):
        assert actual["players"][index]["money"] == expected_farms[index]["money"]
        assert actual["players"][index]["shed"] == expected_privates[index]["shed"]
        assert actual["players"][index]["seeds"] == expected_privates[index]["seeds"]
        assert actual["players"][index]["hires_today"] == expected_farms[index]["hires_today"]


def test_step264_ordered_oracle_rejects_round2_reversal() -> None:
    case = _fixture("step264_market.json")
    left = simulate_market(case["market_inventory"], case["players"], [case["c0_orders"], case["opponent_orders"]])
    right = simulate_market(case["market_inventory"], case["players"], [case["reversed_orders"], case["opponent_orders"]])
    assert [row["money"] for row in left["players"]] == [16721, 15917]
    assert [row["money"] for row in right["players"]] == [16549, 16057]
    left_margin = left["players"][0]["money"] - left["players"][1]["money"]
    right_margin = right["players"][0]["money"] - right["players"][1]["money"]
    assert left_margin > right_margin
    assert case["round2_prediction"]["MELON"]["quantity_regression"] < 0.5


def _replay_task() -> dict:
    return {
        "agent_archive_sha256": "a" * 64,
        "agent_source_tree_sha256": "b" * 64,
        "model_hashes": {},
        "configuration": {"episodeSteps": 2},
        "feature_schema_sha256": "c" * 64,
        "executor_version": "test-v1",
        "engine_sha256": "d" * 64,
        "opponent_tree_sha256": "e" * 64,
        "seed": 123,
        "seat": 1,
    }


def _valid_replay_pair(tmp_path: Path) -> tuple[dict, Path, Path, dict]:
    task = _replay_task()
    replay = tmp_path / "replay.json.gz"
    with gzip.open(replay, "wt", encoding="utf-8") as stream:
        json.dump({"steps": [[], []]}, stream)
    sidecar = replay.with_suffix(replay.suffix + ".sidecar.json")
    metadata = {
        "task_digest": replay_task_digest(task),
        "replay_sha256": sha256(replay),
        "seed": 123,
        "seat": 1,
        "terminal_statuses": ["DONE", "DONE"],
        "stored_states": 2,
    }
    sidecar.write_text(json.dumps(metadata), encoding="utf-8")
    return task, replay, sidecar, metadata


def test_replay_reuse_requires_matching_sidecar_and_hash(tmp_path: Path) -> None:
    task, replay, sidecar, metadata = _valid_replay_pair(tmp_path)
    assert reusable_replay(task, replay, sidecar) == (True, "VALID")
    metadata["replay_sha256"] = "0" * 64
    sidecar.write_text(json.dumps(metadata), encoding="utf-8")
    assert reusable_replay(task, replay, sidecar) == (False, "REPLAY_HASH_MISMATCH")


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("seed", 124, "SEED_OR_SEAT_MISMATCH"),
        ("seat", 0, "SEED_OR_SEAT_MISMATCH"),
        ("terminal_statuses", ["ERROR", "DONE"], "TERMINAL_STATUS_INVALID"),
        ("stored_states", 1, "STATE_COUNT_INVALID"),
    ],
)
def test_replay_reuse_rejects_identity_or_completion_mismatch(tmp_path: Path, field: str, value: object, reason: str) -> None:
    task, replay, sidecar, metadata = _valid_replay_pair(tmp_path)
    metadata[field] = value
    sidecar.write_text(json.dumps(metadata), encoding="utf-8")
    assert reusable_replay(task, replay, sidecar) == (False, reason)


def test_replay_reuse_rejects_missing_sidecar(tmp_path: Path) -> None:
    task, replay, sidecar, _metadata = _valid_replay_pair(tmp_path)
    sidecar.unlink()
    assert reusable_replay(task, replay, sidecar) == (False, "SIDECAR_MISSING")
