from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from kaggle_environments import make

from scripts.evaluation.lifecycle import _apply_fields_and_count_harvest
from scripts.evaluation.runner import _import_module
from scripts.evaluation.safety import _apply_fields, _simulate_market, analyze_safety

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def option():
    return _import_module(ROOT / "agents/v115p_immediate/main.py", "test_option")


def test_projection_handles_ordered_transfer_and_capacity(option):
    env = make("kaggriculture", configuration={"seed": 10091011})
    obs = copy.deepcopy(dict(env.state[0].observation))
    own = obs["farms"][0]
    own["farmer"], own["hands"] = [4, 4], [[4, 4]]
    obs["private"]["shed"] = {"WHEAT": 95, "MILK": 2}
    obs["private"]["inventories"] = [{"MILK": 5}, {}]
    action = {"farmer": ["DROP"], "hands": [["PICKUP", "WHEAT", 5]], "market": []}
    projected = option.base.base._project_shed(obs, action, env.configuration)
    farms = copy.deepcopy(obs["farms"])
    privates = [copy.deepcopy(obs["private"]), copy.deepcopy(dict(env.state[1].observation.private))]
    _apply_fields(farms, privates, [action, {}], 0)
    assert projected == privates[0]["shed"]
    assert projected["MILK"] == 5


def test_option_preserves_procurement_and_remembers_emitted_sale(option, monkeypatch):
    env = make("kaggriculture", configuration={"seed": 10091011})
    obs = copy.deepcopy(dict(env.state[0].observation))
    obs.update(step=361, day=15, hour=1)
    obs["farms"][0]["money"] = 6000
    obs["private"]["shed"]["MILK"] = 8
    original = {"farmer": ["PASS"], "hands": [], "market": [["BUY_SEED", "WHEAT", 2], ["HIRE"]]}
    monkeypatch.setattr(option.base, "agent", lambda *_: copy.deepcopy(original))
    monkeypatch.setattr(option.base, "_fallback_latched", lambda *_: False)
    result = option.agent(obs, env.configuration)
    assert result["farmer"] == original["farmer"] and result["hands"] == original["hands"]
    assert result["market"] == [["SELL", "MILK", 8], *original["market"]]
    state = option.base.base._RUNTIME[0]
    assert state["previous"]["action"] == result
    assert option.base.base._effective_sell(result, state["previous"]["projected_shed"], "MILK") == 8
    assert option.policy_diagnostics(obs)["research_decision"]["first_action_step"] == 361


def test_sale_cap_consumes_stock_once_and_never_removes_purchase(option):
    orders = [["SELL", "MILK", 99], ["BUY_SEED", "WHEAT", 2], ["SELL", "MILK", 2]]
    assert option._cap_orders(orders, {"MILK": 5}, ["MILK"]) == [
        ["SELL", "MILK", 5], ["BUY_SEED", "WHEAT", 2]
    ]


def test_sale_ledger_matches_engine_money_and_dynamic_buy_cost():
    env = make("kaggriculture", configuration={"seed": 10091011})
    farms = copy.deepcopy(env.state[0].observation.farms)
    privates = [copy.deepcopy(s.observation.private) for s in env.state]
    market = copy.deepcopy(env.state[0].observation.market)
    privates[0]["shed"]["MILK"] = 2
    initial = farms[0]["money"]
    events = _simulate_market(farms, privates, market, [
        {"market": [["SELL", "MILK", 99], ["BUY_PRODUCT", "WHEAT", 2]]}, {}
    ])[0]
    assert sum(e["cash_delta"] for e in events) == farms[0]["money"] - initial
    assert events[0]["requested"] == 99 and events[0]["committed"] == 2
    assert events[1]["cash_delta"] < 0


def test_route_and_inherited_transaction_times_are_independent(monkeypatch):
    from scripts.evaluation import safety

    env = make("kaggriculture", configuration={"seed": 10091011})
    states = [dict(s) for s in env.state]
    replay = {"steps": [copy.deepcopy(states) for _ in range(250)]}

    def events(_, step):
        if step == 248:
            return [
                [
                    {
                        "kind": "market_commit",
                        "op": "BUY_ANIMAL",
                        "item": "SHEEP",
                        "requested": 2,
                        "committed": 2,
                    }
                ],
                [],
            ]
        if step == 186:
            return [[{"kind": "silent_field_noop", "action": ["PLANT", "STRAWBERRY"]}], []]
        return [[], []]

    monkeypatch.setattr(safety, "simulate_turn", events)
    trace = {"strategy_counts": {"cow-to-sheep-purchase": 1, "cow-to-sheep-pickup": 2, "cow-to-sheep-place": 2}}
    result = analyze_safety(replay, 0, trace, transaction_step=248, intervention_step=153)
    assert result["transaction"]["complete"]
    assert result["transaction"]["purchase_units_committed"] == 2
    assert result["engine_action_audit"]["post_intervention_silent_field_noop"] == 1


def test_livestock_contract_only_rewrites_purchase_pickup_and_placement(monkeypatch):
    option = _import_module(ROOT / "agents/v115p_livestock/main.py", "test_livestock")
    env = make("kaggriculture", configuration={"seed": 10091011})
    obs = copy.deepcopy(dict(env.state[0].observation))
    obs.update(step=248, day=10, hour=8)
    obs["farms"][0]["money"] = 1800
    monkeypatch.setattr(option.base, "_fallback_latched", lambda *_: False)
    current = {"farmer": ["PASS"], "hands": [], "market": [["SELL", "MELON", 6], ["BUY_ANIMAL", "COW", 2]]}
    monkeypatch.setattr(option.base.base, "agent", lambda *_: copy.deepcopy(current))
    result = option.agent(obs, env.configuration)
    assert result["market"] == [["SELL", "MELON", 6], ["BUY_ANIMAL", "SHEEP", 2]]
    assert option.policy_diagnostics(obs)["research_decision"]["committed"]
    obs.update(step=249, hour=9)
    obs["private"]["shed"]["SHEEP"] = 2
    current.update(farmer=["PICKUP", "COW", 2], market=[])
    assert option.agent(obs, env.configuration)["farmer"] == ["PICKUP", "SHEEP", 2]
    obs.update(step=250, hour=10)
    obs["private"]["inventories"][0]["SHEEP"] = 2
    current.update(farmer=["PLACE", "COW"])
    assert option.agent(obs, env.configuration)["farmer"] == ["PLACE", "SHEEP"]
    obs.update(step=251, hour=11)
    obs["private"]["inventories"][0]["SHEEP"] = 1
    assert option.agent(obs, env.configuration)["farmer"] == ["PLACE", "SHEEP"]
    assert option.base._RUNTIME[0]["conversion"]["placed"] == 2


def test_retain_cow_r1_clears_late_goal_at_declared_action_step(monkeypatch):
    option = _import_module(
        ROOT / "agents/v115p_retain_cow_r1/main.py", "test_retain_cow_r1"
    )
    env = make("kaggriculture", configuration={"seed": 10091011})
    obs = copy.deepcopy(dict(env.state[0].observation))
    obs.update(step=248, day=10, hour=8)
    obs["farms"][0]["money"] = 2000
    state = option.base._state_for(obs)
    state["late_goal"] = {"step": 216, "reason": "test"}
    monkeypatch.setattr(option.base, "_fallback_latched", lambda *_: False)

    def underlying(*_):
        animal = "SHEEP" if state.get("late_goal") else "COW"
        return {"farmer": ["PASS"], "hands": [], "market": [["BUY_ANIMAL", animal, 2]]}

    monkeypatch.setattr(option.base, "agent", underlying)
    result = option.agent(obs, env.configuration)
    assert result["market"] == [["BUY_ANIMAL", "COW", 2]]
    assert state["late_goal"] is None
    assert option.policy_diagnostics(obs)["research_decision"]["committed"]


def test_activation_windows_are_nonempty_half_open_intervals():
    for name in (
        "options_preregistration.json",
        "livestock_preregistration.json",
        "managed_animals_preregistration.json",
        "retain_cow_r1_preregistration.json",
    ):
        prereg = json.loads(
            (ROOT / "experiments/research_20260911_continuations" / name).read_text(
                encoding="utf-8"
            )
        )
        assert all(variant["start"] < variant["end"] for variant in prereg["variants"])


def test_harvest_counter_excludes_feed_and_fertilizer_collection(monkeypatch):
    from scripts.evaluation import lifecycle

    farms = [{"hands": [[], []]}, {"hands": []}]
    privates = [
        {"shed": {"WHEAT": 3}, "seeds": {}, "inventories": [{}, {}, {}]},
        {"shed": {}, "seeds": {}, "inventories": [{}]},
    ]

    def apply(_, private, __, action, *___):
        if action[0] == "HARVEST":
            private["inventories"][0]["MILK"] = 2
        elif action[0] == "FEED":
            private["shed"]["WHEAT"] -= 1
        elif action[0] == "COLLECT_FERTILIZER":
            private["inventories"][2]["FERTILIZER"] = 1

    monkeypatch.setattr(lifecycle.engine, "_apply_unit_action", apply)
    result = _apply_fields_and_count_harvest(
        farms,
        privates,
        [
            {
                "farmer": ["HARVEST"],
                "hands": [["FEED"], ["COLLECT_FERTILIZER"]],
            },
            {},
        ],
        0,
    )
    assert result[0] == {"MILK": 2}
