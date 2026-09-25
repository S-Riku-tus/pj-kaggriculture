from __future__ import annotations

import copy
import gzip
import hashlib
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
ROUND13 = Path(__file__).resolve().parents[1]
B1_HASH = "b6553c296c556aff5b5e2d12b75618e505fa4d852afb5338414ac6d6e039cb02"
REPLAY = (
    ROOT
    / "experiments/round12_causal_repairs_20260925/metrics/factorial_development/replays"
    / "P0M0/B1/seed_712609243_seat_0.json.gz"
)


def exec_namespace(path: Path):
    namespace: dict = {}
    exec(compile(path.read_text(encoding="utf-8"), "<string>", "exec"), namespace)
    entry = [value for value in namespace.values() if callable(value)][-1]
    return entry, namespace


@pytest.fixture(scope="module")
def runtime():
    return exec_namespace(ROUND13 / "agents/M1_deadline_market/main.py")


def read_replay() -> dict:
    with gzip.open(REPLAY, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def test_frozen_b1_bytes_and_last_callable():
    path = ROUND13 / "agents/D0_B1/main.py"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == B1_HASH
    entry, _namespace = exec_namespace(path)
    assert entry.__name__ == "opening_liquidity_agent"


def test_submission_loader_empty_namespace_selects_explicit_entrypoint():
    from kaggle_environments.agent import get_last_callable

    for name in ("M1_deadline_market", "P_EARLY4", "P_ROTATE2", "C_EARLY4_M1"):
        source = (ROUND13 / "agents" / name / "main.py").read_text(encoding="utf-8")
        entry = get_last_callable(source)
        assert entry.__name__ == "round13_agent"
        assert "numpy" not in source


def test_parent_is_called_once_per_transaction():
    entry, namespace = exec_namespace(ROUND13 / "agents/P_EARLY4/main.py")
    record = read_replay()["decisions"][0]
    observation = record["observations"][0]
    baseline = record["actions"][0]
    calls = []

    def parent(_observation, _configuration=None):
        calls.append(int(_observation["step"]))
        return copy.deepcopy(baseline)

    namespace["_R13_PARENT"] = parent
    result = entry(observation, {"episodeSteps": 720})
    assert isinstance(result, dict)
    assert calls == [0]


def test_cxd_fixed_order_regression_is_retained():
    _entry, namespace = exec_namespace(ROUND13 / "agents/D0_B1/main.py")
    orders = [["SELL", "MILK", 1], ["HIRE"], ["SELL", "WOOL", 1]]
    candidates = list(namespace["_cxd_candidates"](orders, [0, 1, 2], [orders[0], orders[2]], [orders[1]]))
    assert len(candidates) == 6
    assert any(candidate[0] == ["HIRE"] for candidate in candidates)


def test_all_product_ledger_status_and_unknown_propagation(runtime):
    _entry, namespace = runtime
    observation = copy.deepcopy(read_replay()["decisions"][1]["observations"][0])
    previous_inventory = dict(observation["market"]["inventory"])
    draw = namespace["_r13_town_draw"]([], 0)
    for item in namespace["_R13_PRODUCTS"]:
        observation["market"]["inventory"][item] = previous_inventory[item] - int(draw.get(item, 0))
    observation["market"]["inventory"]["MILK"] += 3
    observation["market"]["inventory"]["TOMATO"] -= 5
    state = namespace["_r13_initial_state"]()
    state["ledger_previous"] = {
        "step": 0,
        "inventory": previous_inventory,
        "prices": dict(observation["market"]["prices"]),
        "shops": [],
        "own_lower": {item: 0 for item in namespace["_R13_PRODUCTS"]},
        "own_upper": {item: 0 for item in namespace["_R13_PRODUCTS"]},
        "ambiguous": [],
    }
    namespace["_r13_reconcile_ledger"](observation, state)
    assert set(state["opponent_ledger"]) == set(namespace["_R13_PRODUCTS"])
    assert state["opponent_ledger"]["MILK"]["status"] == "EXACT_POSITIVE"
    assert state["opponent_ledger"]["MILK"]["lower"] == 3
    assert state["opponent_ledger"]["WHEAT"]["status"] == "EXACT_ZERO"
    assert state["opponent_ledger"]["TOMATO"]["status"] == "UNKNOWN"
    signal = namespace["_r13_forecast_signal"](state, "TOMATO")
    assert signal == {"known": False, "event": None, "lower": None, "upper": None}


def test_price_floor_is_interval_not_zero(runtime):
    _entry, namespace = runtime
    observation = copy.deepcopy(read_replay()["decisions"][1]["observations"][0])
    previous_inventory = dict(observation["market"]["inventory"])
    state = namespace["_r13_initial_state"]()
    state["ledger_previous"] = {
        "step": 0,
        "inventory": previous_inventory,
        "prices": dict(observation["market"]["prices"]),
        "shops": [],
        "own_lower": {item: 0 for item in namespace["_R13_PRODUCTS"]},
        "own_upper": {item: 0 for item in namespace["_R13_PRODUCTS"]},
        "ambiguous": [],
    }
    original_price = namespace["_r13_market_price"]
    namespace["_r13_market_price"] = lambda obs, item, inventory: 1 if item == "WOOL" else original_price(obs, item, inventory)
    try:
        draw = namespace["_r13_town_draw"]([], 0)
        for item in namespace["_R13_PRODUCTS"]:
            observation["market"]["inventory"][item] = previous_inventory[item] - int(draw.get(item, 0))
        namespace["_r13_reconcile_ledger"](observation, state)
    finally:
        namespace["_r13_market_price"] = original_price
    assert state["opponent_ledger"]["WOOL"]["status"] == "INTERVAL"
    assert state["opponent_ledger"]["WOOL"]["upper"] == 100


def test_day_boundary_drop_is_not_available_before_market(runtime):
    _entry, namespace = runtime
    observation = copy.deepcopy(read_replay()["decisions"][23]["observations"][0])
    observation["farms"][0]["farmer"] = [0, 0]
    observation["private"]["shed"]["WHEAT"] = 0
    observation["private"]["inventories"][0] = {"WHEAT": 5}
    action = {"farmer": ["DROP"], "hands": [], "market": [["SELL", "WHEAT", 5]]}
    lower, upper, _ambiguous = namespace["_r13_own_fill_bounds"](observation, action)
    assert lower["WHEAT"] == upper["WHEAT"] == 0
    observation["farms"][0]["farmer"] = [4, 4]
    lower, upper, _ambiguous = namespace["_r13_own_fill_bounds"](observation, action)
    assert lower["WHEAT"] == upper["WHEAT"] == 5


def test_deadline_is_fixed_and_due_order_is_committed(runtime):
    _entry, namespace = runtime
    observation = copy.deepcopy(read_replay()["decisions"][300]["observations"][0])
    observation["step"] = 300
    observation["day"] = 12
    baseline = {"farmer": ["PASS"], "hands": [["PASS"] for _ in observation["farms"][0]["hands"]], "market": [["SELL", "MILK", 10]]}
    state = namespace["_r13_initial_state"]()
    original_project = namespace["_r13_projected_shed"]
    original_signal = namespace["_r13_forecast_signal"]
    original_draw = namespace["_r13_future_known_draw"]
    namespace["_r13_projected_shed"] = lambda obs, action: {**{item: 0 for item in namespace["_R13_PRODUCTS"]}, "MILK": 10}
    namespace["_r13_forecast_signal"] = lambda value, item: {"known": True, "event": False, "lower": 0, "upper": 0}
    namespace["_r13_future_known_draw"] = lambda obs, item, horizon=4: 2
    try:
        _action, state, event = namespace["_r13_market_candidate"](observation, baseline, state)
        assert event["type"] == "reservation_created"
        due_step = event["due_step"]
        observation["step"] = 301
        _action, state, _event = namespace["_r13_market_candidate"](observation, baseline, state)
        assert state["reservations"]["MILK"]["due_step"] == due_step
        observation["step"] = due_step
        action, state, event = namespace["_r13_market_candidate"](observation, {**baseline, "market": []}, state)
        assert event["type"] == "reservation_due"
        assert ["SELL", "MILK", 5] in action["market"]
        assert "MILK" not in state["reservations"]
    finally:
        namespace["_r13_projected_shed"] = original_project
        namespace["_r13_forecast_signal"] = original_signal
        namespace["_r13_future_known_draw"] = original_draw


def test_early_funding_does_not_use_same_turn_seed():
    _entry, namespace = exec_namespace(ROUND13 / "agents/P_EARLY4/main.py")
    record = read_replay()["decisions"][1]
    observation = record["observations"][0]
    baseline = record["actions"][0]
    action, state, event = namespace["_r13_early_candidate"](observation, baseline, namespace["_r13_initial_state"]())
    assert event["type"] == "early_started"
    assert ["BUY_SEED", "STRAWBERRY", 4] in action["market"]
    assert all(command != ["PLANT", "STRAWBERRY"] for command in namespace["_r13_units"](action))
    assert state["early"]["planted"] == 0
