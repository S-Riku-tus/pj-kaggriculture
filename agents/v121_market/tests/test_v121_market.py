from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("v121_market", ROOT / "agents/v121_market/main.py")
assert SPEC and SPEC.loader
agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent)


def observation(*, step: int = 300, shed: dict | None = None) -> dict:
    farm = {
        "farmer": [4, 4],
        "hands": [],
        "money": 10000,
        "unlocked_quadrants": ["NW"],
        "tiles": [[None for _ in range(10)] for _ in range(10)],
    }
    return {
        "step": step,
        "player": 0,
        "farms": [farm, farm.copy()],
        "private": {"shed": shed or {}, "inventories": [{}], "seeds": {}},
        "market": {
            "inventory": dict.fromkeys(agent.SELLABLE, 10000),
            "prices": {item: agent.MARKET_PARAMS[item][0] for item in agent.SELLABLE},
        },
    }


def test_sanitize_removes_only_provably_dead_sells() -> None:
    obs = observation(shed={"MILK": 3})
    state = {"diagnostics": {}}
    action = {
        "farmer": ["PASS"],
        "hands": [],
        "market": [
            ["SELL", "MILK", 2],
            ["SELL", "WOOL", 4],
            ["SELL", "MILK", 0],
            ["SELL", "BAD", 4],
            ["HIRE"],
        ],
    }
    result = agent._sanitize_market(obs, action, state)
    assert result["market"] == [["SELL", "MILK", 2], ["HIRE"]]
    assert state["diagnostics"]["dead_sells_removed"] == 3


def test_rank_preserves_non_sell_slots() -> None:
    obs = observation(shed={"WHEAT": 20, "MELON": 20})
    state = {"diagnostics": {}}
    action = {
        "farmer": ["PASS"],
        "hands": [],
        "market": [["SELL", "WHEAT", 4], ["HIRE"], ["SELL", "MELON", 8]],
    }
    result = agent._rank_sell_slots(obs, action, state)
    assert result["market"][1] == ["HIRE"]
    assert sorted(tuple(order) for order in result["market"] if order[0] == "SELL") == [
        ("SELL", "MELON", 8),
        ("SELL", "WHEAT", 4),
    ]


def test_terminal_liquidation_appends_only_unplanned_stock() -> None:
    obs = observation(step=718, shed={"MILK": 7, "WOOL": 2})
    state = {"diagnostics": {}}
    action = {"farmer": ["PASS"], "hands": [], "market": [["SELL", "MILK", 3]]}
    result = agent._terminal_liquidation(obs, action, 718, state)
    assert ["SELL", "MILK", 4] in result["market"]
    assert ["SELL", "WOOL", 2] in result["market"]
    assert state["diagnostics"]["terminal_units_appended"] == 6


def test_weed_collision_becomes_dig_then_intended() -> None:
    agent.reset_runtime_state()
    obs = observation(step=100)
    obs["farms"][0]["tiles"][4][4] = {"kind": "WEED"}
    state = agent._state(obs, 100)
    intended = {"farmer": ["PLANT", "WHEAT"], "hands": [], "market": []}
    repaired = agent._weed_repair(obs, intended, 100, state)
    assert repaired["farmer"] == ["DIG"]
    state = agent._state(obs, 101)
    replayed = agent._weed_repair(obs, {"farmer": ["NORTH"], "hands": [], "market": []}, 101, state)
    assert replayed["farmer"] == ["PLANT", "WHEAT"]

