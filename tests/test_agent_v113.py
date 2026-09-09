from __future__ import annotations

from collections import Counter

import pytest

from agents.v113 import main as v113


def _farm(money: float = 3000.0) -> dict:
    return {
        "money": money,
        "hands": [],
        "farmer": [0, 0],
        "unlocked_quadrants": ["NW", "NE", "SW"],
        "tiles": [[None for _ in range(10)] for _ in range(10)],
    }


def _obs(step: int = 216, shops: list[str] | None = None) -> dict:
    return {
        "step": step,
        "day": step // 24,
        "hour": step % 24,
        "player": 0,
        "farms": [_farm(), _farm()],
        "town": {"unlocked_shops": shops or ["BAKERY", "PET_CAFE", "SMOOTHIE_SHOP"]},
        "market": {
            "prices": {
                "WHEAT": 25,
                "CARROT": 35,
                "TOMATO": 60,
                "STRAWBERRY": 120,
                "MELON": 250,
                "MILK": 160,
                "WOOL": 200,
            },
            "inventory": {
                "WHEAT": 10000,
                "CARROT": 10000,
                "TOMATO": 10000,
                "STRAWBERRY": 10000,
                "MELON": 10000,
                "MILK": 10000,
                "WOOL": 10000,
            },
        },
        "private": {"shed": {}, "inventories": [{}]},
    }


def test_canonical_clock_uses_public_day_and_hour() -> None:
    observation = _obs(216)
    observation["step"] = 0
    assert v113._canonical_step(observation) == 216
    assert v113._normalize_observation(observation)["step"] == 216


def test_generalized_gate_sets_inherited_goal_without_exact_yarn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observation = _obs(216, ["BAKERY", "PET_CAFE", "SMOOTHIE_SHOP"])
    state = v113._new_state(216)
    inherited = {
        "late_goal": None,
        "decision_counts": Counter(),
    }
    monkeypatch.setattr(v113.base, "_predict_72", lambda _obs: ([0, 0, 0, 0, 0, 0, 2.1], 2.0))
    monkeypatch.setattr(v113.base, "_state_for", lambda _obs: inherited)
    monkeypatch.setattr(v113, "_animal_residual_score", lambda _obs: 0.25)
    v113._prime_generalized_goal(observation, state)
    assert inherited["late_goal"]["reason"] == "v113-development-predictive-animal-tilt"
    assert state["generalized_goal"]["animal_residual_score"] == pytest.approx(0.25)


def test_generalized_gate_rejects_ood_and_weak_tilt(monkeypatch: pytest.MonkeyPatch) -> None:
    observation = _obs()
    state = v113._new_state(216)
    monkeypatch.setattr(v113.base, "_predict_72", lambda _obs: ([0, 0, 0, 0, 0, 0, 9], 4.1))
    v113._prime_generalized_goal(observation, state)
    assert state["generalized_goal"] is None
    assert state["model_rejections"]["out-of-support"] == 1

    state = v113._new_state(216)
    monkeypatch.setattr(v113.base, "_predict_72", lambda _obs: ([0, 0, 0, 0, 0, 0, 1.4], 2.0))
    v113._prime_generalized_goal(observation, state)
    assert state["generalized_goal"] is None
    assert state["model_rejections"]["below-tilt"] == 1


def test_dormant_premium_sells_move_first_without_mutating_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(v113, "ENABLE_PREMIUM_FIRST", True)
    state = v113._new_state(100)
    action = {
        "farmer": ["PASS"],
        "hands": [],
        "market": [
            ["HIRE"],
            ["SELL", "WHEAT", 20],
            ["SELL", "MILK", 8],
            ["BUY_SEED", "WHEAT", 5],
            ["SELL", "WOOL", 6],
        ],
    }
    result = v113._premium_first(action, state)
    assert result["market"] == [
        ["SELL", "MILK", 8],
        ["SELL", "WOOL", 6],
        ["HIRE"],
        ["SELL", "WHEAT", 20],
        ["BUY_SEED", "WHEAT", 5],
    ]
    assert action["market"][0] == ["HIRE"]
    assert state["premium_reorders"] == 1
    assert state["premium_orders_advanced"] == 5


def test_agent_primes_goal_before_inherited_action(monkeypatch: pytest.MonkeyPatch) -> None:
    observation = _obs()
    events: list[str] = []
    monkeypatch.setattr(v113, "_prime_generalized_goal", lambda _obs, _state: events.append("goal"))
    monkeypatch.setattr(
        v113.base,
        "agent",
        lambda _obs, _configuration: events.append("base")
        or {"farmer": ["PASS"], "hands": [], "market": []},
    )
    result = v113.agent(observation)
    assert events == ["goal", "base"]
    assert result["farmer"] == ["PASS"]
