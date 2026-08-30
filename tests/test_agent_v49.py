from __future__ import annotations

from agents.v49 import main as v49


def _task(position=(3, 1)):
    return {
        "pos": position,
        "action": ["WATER"],
        "priority": 12000,
        "required": None,
        "unit": None,
        "label": "water",
    }


def _call(inventory, *, prediction=(None, None, 1.0)):
    return v49._loaded_preposition(
        {"day": 8},
        {"tiles": [[None] * 10 for _ in range(10)]},
        {},
        {},
        [(0, 0), (1, 1)],
        [{}, inventory],
        [_task()],
        [["PASS"], ["PASS"]],
        prediction,
    )


def test_v49_routes_loaded_idle_worker(monkeypatch) -> None:
    monkeypatch.setattr(v49, "ENABLE_LOADED_PREPOSITION", True)
    monkeypatch.setattr(v49, "_SAFE_PREPOSITION", lambda *args: args[7])
    assert _call({"WHEAT": 2})[1] == ["EAST"]


def test_v49_does_not_expand_to_empty_or_animal_carriers(monkeypatch) -> None:
    monkeypatch.setattr(v49, "ENABLE_LOADED_PREPOSITION", True)
    monkeypatch.setattr(v49, "_SAFE_PREPOSITION", lambda *args: args[7])
    assert _call({})[1] == ["PASS"]
    assert _call({"COW": 1})[1] == ["PASS"]


def test_v49_uses_safe_fallback_when_disabled_or_low_confidence(monkeypatch) -> None:
    monkeypatch.setattr(v49, "_SAFE_PREPOSITION", lambda *args: args[7])
    monkeypatch.setattr(v49, "ENABLE_LOADED_PREPOSITION", False)
    assert _call({"WHEAT": 2})[1] == ["PASS"]
    monkeypatch.setattr(v49, "ENABLE_LOADED_PREPOSITION", True)
    assert _call({"WHEAT": 2}, prediction=(None, None, 0.2))[1] == ["PASS"]


def test_v49_safe_empty_observation() -> None:
    assert v49.agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}

