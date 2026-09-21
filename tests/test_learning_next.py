from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from kaggle_environments.envs.kaggriculture.kaggriculture import market_price as engine_market_price

from agents.learning_next_20260921.common import (
    PRODUCTS,
    MarketHistory,
    SavedMLP,
    canonical_step,
    legal_actor_tokens,
    market_price,
    reserve_actor_token,
    state_feature_names,
    state_features,
)

ROOT = Path(__file__).resolve().parents[1]
REPLAY = ROOT / "data/replays/submission_56216119/episode_111063979.json"
EXPERIMENT = ROOT / "experiments/learning_next_20260921"


@pytest.fixture(scope="module")
def replay() -> dict:
    return json.loads(REPLAY.read_text(encoding="utf-8"))


def _candidate_actions(action: dict) -> list[list]:
    return [action["farmer"], *action["hands"], *action["market"]]


def _first_action(replay: dict, operation: str, seat: int = 0) -> tuple[int, list]:
    for observation_index in range(len(replay["steps"]) - 1):
        stored = replay["steps"][observation_index + 1][seat]["action"]
        for action in _candidate_actions(stored):
            if action and action[0] == operation:
                return observation_index, action
    raise AssertionError(f"missing operation {operation}")


def _first_unit_action(replay: dict, operation: str, seat: int = 0) -> tuple[int, int, list]:
    for observation_index in range(len(replay["steps"]) - 1):
        stored = replay["steps"][observation_index + 1][seat]["action"]
        for actor_index, action in enumerate([stored["farmer"], *stored["hands"]]):
            if action and action[0] == operation:
                return observation_index, actor_index, action
    raise AssertionError(f"missing unit operation {operation}")


@pytest.mark.parametrize("operation", ["NORTH", "BUY_SEED", "PICKUP", "HARVEST"])
def test_replay_label_is_stored_one_row_after_observation(replay: dict, operation: str) -> None:
    observation_index, expected = _first_action(replay, operation)
    before = replay["steps"][observation_index][0]["observation"]
    stored = replay["steps"][observation_index + 1][0]["action"]
    assert expected in _candidate_actions(stored)
    assert canonical_step(before) == observation_index


def test_replay_initial_terminal_and_day_boundary_are_not_actions(replay: dict) -> None:
    steps = replay["steps"]
    assert len(steps) == 720
    assert canonical_step(steps[0][0]["observation"]) == 0
    assert canonical_step(steps[23][0]["observation"]) == 23
    assert canonical_step(steps[24][0]["observation"]) == 24
    assert (steps[24][0]["observation"]["day"], steps[24][0]["observation"]["hour"]) == (1, 0)
    assert len(steps) - 1 == 719


def test_move_buy_pickup_and_harvest_have_expected_next_state_differences(replay: dict) -> None:
    steps = replay["steps"]
    move_step, actor, move = _first_unit_action(replay, "NORTH")
    before = steps[move_step][0]["observation"]
    after = steps[move_step + 1][0]["observation"]
    before_positions = [before["farms"][0]["farmer"], *before["farms"][0]["hands"]]
    after_positions = [after["farms"][0]["farmer"], *after["farms"][0]["hands"]]
    assert after_positions[actor] == [before_positions[actor][0], before_positions[actor][1] - 1]
    assert move == ["NORTH"]

    buy_step, buy = _first_action(replay, "BUY_SEED")
    crop, quantity = buy[1], int(buy[2])
    before = steps[buy_step][0]["observation"]
    after = steps[buy_step + 1][0]["observation"]
    assert after["private"]["seeds"][crop] == before["private"]["seeds"][crop] + quantity

    pickup_step, actor, pickup = _first_unit_action(replay, "PICKUP")
    item = pickup[1]
    before = steps[pickup_step][0]["observation"]
    after = steps[pickup_step + 1][0]["observation"]
    before_inventory = before["private"]["inventories"][actor].get(item, 0)
    after_inventory = after["private"]["inventories"][actor].get(item, 0)
    assert after_inventory > before_inventory

    harvest_step, actor, _harvest = _first_unit_action(replay, "HARVEST")
    before = steps[harvest_step][0]["observation"]
    after = steps[harvest_step + 1][0]["observation"]
    position = [before["farms"][0]["farmer"], *before["farms"][0]["hands"]][actor]
    tile_before = before["farms"][0]["tiles"][position[1]][position[0]]
    product = tile_before.get("crop") or {"GOOSE": "EGG", "COW": "MILK", "SHEEP": "WOOL"}.get(
        tile_before.get("animal")
    )
    before_inventory = before["private"]["inventories"][actor].get(product, 0)
    after_inventory = after["private"]["inventories"][actor].get(product, 0)
    assert after_inventory > before_inventory


def test_both_seats_share_public_state_but_keep_focal_private_state(replay: dict) -> None:
    for index in (0, 127, 511):
        left = replay["steps"][index][0]["observation"]
        right = replay["steps"][index][1]["observation"]
        assert left["farms"] == right["farms"]
        assert left["market"] == right["market"]
        assert left["town"] == right["town"]
        assert left["player"] == 0
        assert right["player"] == 1
        assert "private" in left and "private" in right


def test_forbidden_future_and_identity_fields_do_not_change_features(replay: dict) -> None:
    observation = deepcopy(replay["steps"][127][0]["observation"])
    baseline = state_features(observation, MarketHistory())
    forbidden = deepcopy(observation)
    forbidden.update(
        {
            "episode_id": 999999999,
            "submission_id": 56216119,
            "replay_seed": "future-seed",
            "final_reward": 10**12,
            "future_action": {"market": [["SELL", "MILK", 999999]]},
            "opponent_private": {"shed": {"MILK": 999999}},
        }
    )
    randomized = state_features(forbidden, MarketHistory())
    for key in (
        "episode_id",
        "submission_id",
        "replay_seed",
        "final_reward",
        "future_action",
        "opponent_private",
    ):
        del forbidden[key]
    removed = state_features(forbidden, MarketHistory())
    np.testing.assert_array_equal(baseline, randomized)
    np.testing.assert_array_equal(baseline, removed)


def test_focal_player_and_public_production_are_explicit_features(replay: dict) -> None:
    observation = deepcopy(replay["steps"][127][0]["observation"])
    features = state_features(observation)
    names = state_feature_names()
    assert features[names.index("player")] == 0
    observation["player"] = 1
    assert state_features(observation)[names.index("player")] == 1
    assert any(name.endswith("production_phase:MILK") for name in names)
    assert any(name.endswith("public_yield:WHEAT") for name in names)


def test_actor_seed_reservation_prevents_double_plant(replay: dict) -> None:
    observation = deepcopy(replay["steps"][0][0]["observation"])
    observation["private"]["seeds"]["WHEAT"] = 1
    observation["farms"][0]["hands"] = [[3, 4]]
    observation["private"]["inventories"] = [{}, {}]
    observation["farms"][0]["farmer"] = [2, 4]
    assert "PLANT:WHEAT" in legal_actor_tokens(observation, 0, {})
    reserved: dict[str, int] = {}
    reserve_actor_token(reserved, "PLANT:WHEAT")
    assert "PLANT:WHEAT" not in legal_actor_tokens(observation, 1, reserved)


def test_frozen_market_calculator_matches_imported_engine() -> None:
    for item in PRODUCTS:
        for inventory in (0, 5000, 9500, 9999, 10000, 10001, 10500, 15000, 50000):
            assert market_price(item, inventory) == engine_market_price(item, inventory)


def _pass_action() -> dict:
    return {"farmer": ["PASS"], "hands": [], "market": []}


def test_fixed_engine_market_lockstep_cash_floor_and_order_limit() -> None:
    from kaggle_environments import make

    env = make("kaggriculture", configuration={"episodeSteps": 2, "seed": 20260921}, debug=True)
    env.reset(2)
    buy = {**_pass_action(), "market": [["BUY_PRODUCT", "WHEAT", 1]]}
    env.step([buy, buy])
    state = env.toJSON()["steps"][-1][0]["observation"]
    expected_cost = market_price("WHEAT", 9999)
    assert state["farms"][0]["money"] == state["farms"][1]["money"] == 3000 - expected_cost

    env = make("kaggriculture", configuration={"episodeSteps": 2, "seed": 20260921}, debug=True)
    env.reset(2)
    env.state[0].observation.private.shed["FERTILIZER"] = 1
    env.state[0].observation.market.inventory["FERTILIZER"] = 50000
    sell_at_floor = {**_pass_action(), "market": [["SELL", "FERTILIZER", 1]]}
    env.step([sell_at_floor, _pass_action()])
    state = env.toJSON()["steps"][-1][0]["observation"]
    assert state["farms"][0]["money"] == 3001
    assert state["private"]["shed"]["FERTILIZER"] == 0
    assert state["market"]["inventory"]["FERTILIZER"] == 50000

    env = make("kaggriculture", configuration={"episodeSteps": 2, "seed": 20260921}, debug=True)
    env.reset(2)
    eleven_hires = {**_pass_action(), "market": [["HIRE"] for _ in range(11)]}
    env.step([eleven_hires, _pass_action()])
    state = env.toJSON()["steps"][-1][0]["observation"]
    assert len(state["farms"][0]["hands"]) == 10
    assert state["farms"][0]["money"] == 3000 - sum((1, 1, 2, 3, 5, 8, 13, 21, 34, 55))

    env = make("kaggriculture", configuration={"episodeSteps": 2, "seed": 20260921}, debug=True)
    env.reset(2)
    overbuy = {**_pass_action(), "market": [["BUY_ANIMAL", "SHEEP", 10]]}
    env.step([overbuy, _pass_action()])
    state = env.toJSON()["steps"][-1][0]["observation"]
    assert state["farms"][0]["money"] == 0
    assert state["private"]["shed"]["SHEEP"] == 6


def test_split_is_episode_level_and_duplicate_views_cannot_cross() -> None:
    source = json.loads((EXPERIMENT / "source_manifest.json").read_text(encoding="utf-8"))
    split = json.loads((EXPERIMENT / "split_manifest.json").read_text(encoding="utf-8"))
    seen: dict[int, str] = {}
    for row in source["files"]:
        episode_id = int(row["episode_id"])
        assignment = split["assignments"][str(episode_id)]
        assert assignment in {"train", "validation", "test"}
        assert seen.setdefault(episode_id, assignment) == assignment
    assert set(split["counts"]) == {"train", "validation", "test"}
    assert sum(split["counts"].values()) == source["unique_episodes"]


def test_independent_bc_has_no_c0_or_replay_router_import() -> None:
    source = (ROOT / "agents/learning_next_20260921/bc_agent.py").read_text(encoding="utf-8")
    assert "v125" not in source
    assert "v124" not in source
    assert "v121" not in source
    assert "nearest" not in source.lower()


def test_missing_checkpoint_is_an_explicit_failure(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="required learned model is missing"):
        SavedMLP(tmp_path / "missing.npz")
