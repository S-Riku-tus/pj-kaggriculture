from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evaluate_round6_imitation.py"
SPEC = importlib.util.spec_from_file_location("round6_imitation", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_importance_can_assign_multiple_simultaneous_decisions() -> None:
    action = {
        "farmer": ["PICKUP", "WHEAT", 5],
        "hands": [["HARVEST"]],
        "market": [["HIRE"], ["BUY_PRODUCT", "WHEAT", 4], ["SELL", "MILK", 2]],
    }
    assert MODULE._importance(action) == {"transport", "collection", "hire", "feed_procurement", "sale"}


def test_context_labels_are_not_identity_conditioned() -> None:
    observation = {
        "player": 0,
        "day": 20,
        "hour": 0,
        "farms": [{"money": 500}, {"money": 1000}],
        "private": {"shed": {"WHEAT": 80}},
        "town": {"unlocked_shops": ["BAKERY"]},
    }
    labels = MODULE._context_labels(observation, [])
    assert "phase:late" in labels
    assert "shop:addition_turn" in labels
    assert "cash:pressured" in labels
    assert "inventory:pressured" in labels
    assert all("episode" not in value and "submission" not in value for value in labels)
