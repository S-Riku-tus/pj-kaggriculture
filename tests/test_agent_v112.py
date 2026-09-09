from __future__ import annotations

import ast
import copy
import hashlib
from pathlib import Path

from agents.v112 import main as v112

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SHA256 = "f48c21166eac68d1b05a401f04f94a2eb6154e65415af64893672365ff33c7b8"


def _farm(hands: int = 4) -> dict:
    return {
        "farmer": [0, 0],
        "hands": [[0, 0] for _ in range(hands)],
        "tiles": [["EMPTY" for _ in range(10)] for _ in range(10)],
        "money": 3000,
    }


def _observation(step: int, player: int = 0, hands: int = 4) -> dict:
    return {
        "step": step,
        "day": step // 24,
        "hour": step % 24,
        "player": player,
        "farms": [_farm(hands), _farm(hands)],
        "private": {"shed": {}, "inventories": [{} for _ in range(hands + 1)]},
        "market": {
            "inventory": {item: 10000 for item in v112._MARKET_PARAMS},
            "prices": {item: values[0] for item, values in v112._MARKET_PARAMS.items()},
        },
        "town": {"unlocked_shops": []},
    }


def test_v112_is_exact_public_v27_artifact() -> None:
    source = ROOT / "agents/v112/main.py"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == EXPECTED_SHA256
    assert len(v112._LEGACY_ACTIONS) == 719
    assert v112._REBALANCE_ACTIONS is v112._LEGACY_ACTIONS


def test_v112_submission_has_only_standard_library_imports() -> None:
    tree = ast.parse((ROOT / "agents/v112/main.py").read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert imported <= {"base64", "copy", "json", "math", "zlib"}


def test_four_hire_opening_and_step_progression() -> None:
    v112._WEED_STATE = {0: {}, 1: {}}
    first = v112.agent(_observation(0))
    second = v112.agent(_observation(1))
    assert sum(order == ["HIRE"] for order in first["market"]) == 4
    assert ["BUY_ANIMAL", "COW", 1] in first["market"]
    assert ["BUY_ANIMAL", "SHEEP", 4] in first["market"]
    assert second["farmer"] == ["PICKUP", "COW", 1]
    assert first != second


def test_agent_does_not_mutate_frozen_route() -> None:
    v112._WEED_STATE = {0: {}, 1: {}}
    frozen = copy.deepcopy(v112._LEGACY_ACTIONS[0])
    action = v112.agent(_observation(0))
    action["market"][0][0] = "CORRUPTED"
    assert v112._LEGACY_ACTIONS[0] == frozen


def test_sell_ranker_only_permutes_existing_sell_slots() -> None:
    obs = _observation(300)
    obs["town"]["unlocked_shops"] = ["YARN_STORE", "ICE_CREAM_SHOP"]
    action = {
        "farmer": ["PASS"],
        "hands": [["PASS"] for _ in range(4)],
        "market": [
            ["SELL", "WHEAT", 4],
            ["HIRE"],
            ["SELL", "WOOL", 3],
            ["SELL", "MILK", 2],
        ],
    }
    ranked = v112._rank_sell_slots(obs, action, {"townCenterSellInterval": 24})
    assert ranked["market"][1] == ["HIRE"]
    assert sorted(tuple(order) for order in ranked["market"] if order[0] == "SELL") == sorted(
        tuple(order) for order in action["market"] if order[0] == "SELL"
    )
    assert action["market"][0] == ["SELL", "WHEAT", 4]


def test_failure_path_returns_hand_aligned_pass() -> None:
    broken = {"step": object(), "player": 1, "farms": [_farm(1), _farm(3)]}
    action = v112.agent(broken)
    assert action == {
        "farmer": ["PASS"],
        "hands": [["PASS"], ["PASS"], ["PASS"]],
        "market": [],
    }
