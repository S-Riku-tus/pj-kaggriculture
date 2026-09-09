from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from agents.v111 import main as v111
from scripts import train_v111_strategy as trainer

ROOT = Path(__file__).resolve().parents[1]


def _farm(money: float = 3000.0, hands: int = 1) -> dict:
    return {
        "money": money,
        "hands": [[0, 0] for _ in range(hands)],
        "farmer": [0, 0],
        "unlocked_quadrants": ["SW"],
        "tiles": [[None for _ in range(10)] for _ in range(10)],
    }


def _obs(step: int, shops: list[str], money: float = 3000.0) -> dict:
    return {
        "step": step,
        "day": step // 24,
        "hour": step % 24,
        "player": 0,
        "farms": [_farm(money), _farm(3000.0)],
        "town": {"unlocked_shops": shops},
        "market": {"prices": {}, "inventory": {}},
        "private": {"shed": {}, "inventories": [{}, {}]},
    }


def test_runtime_features_match_training_encoder_on_replay() -> None:
    source = ROOT / "data/submissions/v110_submission_55903573"
    with (source / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        manifest = next(csv.DictReader(handle))
    replay_path = ROOT / manifest["replay_path"]
    if not replay_path.is_file():
        replay_path = ROOT / "data" / manifest["replay_path"]
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    seat = int(manifest["submission_seat"])
    observation = trainer._observation(replay, 216, seat)
    assert observation is not None
    expected = trainer._features(observation, seat, 216)
    actual = v111._features(observation)
    assert actual == pytest.approx(expected)


def test_third_yarn_goal_is_set_only_inside_support(monkeypatch: pytest.MonkeyPatch) -> None:
    observation = _obs(216, ["BAKERY", "PET_CAFE", "YARN_STORE"])
    state = v111._new_state(216)
    monkeypatch.setattr(v111, "_predict_72", lambda _obs: ([0, 0, 0, 0, 0, 0, 2.1], 2.0))
    v111._update_strategy_goal(observation, state)
    assert state["late_goal"]["reason"] == "heldout-72h-third-yarn-wool-goal"

    state = v111._new_state(216)
    monkeypatch.setattr(v111, "_predict_72", lambda _obs: ([0, 0, 0, 0, 0, 0, 9], 4.1))
    v111._update_strategy_goal(observation, state)
    assert state["late_goal"] is None
    assert state["last_fallback_reason"] == "strategy-model-ood"


def test_rejected_second_yarn_veto_stays_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    observation = _obs(153, ["BAKERY", "YARN_STORE"])
    state = v111._new_state(153)
    monkeypatch.setattr(v111, "_predict_72", lambda _obs: ([0, 0, 0, 0, 0, 3, 0], 1.0))
    v111._update_strategy_goal(observation, state)
    assert v111.ENABLE_SECOND_YARN_VETO is False
    assert state["route_override"] is None


def test_late_animal_transaction_rewrites_purchase_pickup_and_placements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(v111, "_fallback_latched", lambda _obs: False)
    state = v111._new_state(216)
    state["late_goal"] = {"step": 216, "animal_tilt": 2.2}

    purchase_obs = _obs(248, ["BAKERY", "PET_CAFE", "YARN_STORE"], money=1500.0)
    purchase = {
        "farmer": ["PASS"],
        "hands": [["PASS"]],
        "market": [["SELL", "MELON", 6], ["BUY_ANIMAL", "COW", 2]],
    }
    rewritten = v111._rewrite_late_animals(purchase_obs, purchase, state)
    assert rewritten["market"][1] == ["BUY_ANIMAL", "SHEEP", 2]
    assert purchase["market"][1] == ["BUY_ANIMAL", "COW", 2]

    pickup_obs = _obs(249, ["BAKERY", "PET_CAFE", "YARN_STORE"])
    pickup_obs["private"]["shed"] = {"SHEEP": 2}
    pickup = {"farmer": ["PASS"], "hands": [["PICKUP", "COW", 2]], "market": []}
    rewritten = v111._rewrite_late_animals(pickup_obs, pickup, state)
    assert rewritten["hands"][0] == ["PICKUP", "SHEEP", 2]

    for expected in (1, 2):
        place_obs = _obs(255 + expected, ["BAKERY", "PET_CAFE", "YARN_STORE"])
        place_obs["private"]["inventories"] = [{}, {"SHEEP": 3 - expected}]
        place = {"farmer": ["PASS"], "hands": [["PLACE", "COW"]], "market": []}
        rewritten = v111._rewrite_late_animals(place_obs, place, state)
        assert rewritten["hands"][0] == ["PLACE", "SHEEP"]
        assert state["conversion"]["placed"] == expected


def test_late_purchase_falls_back_to_v110_when_cash_reserve_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(v111, "_fallback_latched", lambda _obs: False)
    state = v111._new_state(216)
    state["late_goal"] = {"step": 216, "animal_tilt": 3.0}
    observation = _obs(248, ["BAKERY", "PET_CAFE", "YARN_STORE"], money=1499.0)
    action = {
        "farmer": ["PASS"],
        "hands": [["PASS"]],
        "market": [["BUY_ANIMAL", "COW", 2]],
    }
    assert v111._rewrite_late_animals(observation, action, state) is action
    assert state["conversion"] is None
    assert state["last_fallback_reason"] == "late-sheep-cash-reserve"
