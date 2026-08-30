from __future__ import annotations

from agents.v45 import main as v45


def _farm() -> dict[str, object]:
    return {
        "tiles": [[None for _ in range(10)] for _ in range(10)],
        "unlocked_quadrants": ["NW", "NE"],
    }


def _tasks() -> list[dict[str, object]]:
    protected = sorted(v45._protected_ne_positions(10))
    return [
        {
            "pos": protected[0],
            "action": ["PLANT", "STRAWBERRY"],
            "label": "plant-STRAWBERRY",
            "priority": 9700,
        },
        {
            "pos": protected[1],
            "action": ["PLANT", "WHEAT"],
            "label": "plant-WHEAT",
            "priority": 9000,
        },
    ]


def test_v45_delays_core_plants_through_day6(monkeypatch) -> None:
    monkeypatch.setattr(v45, "ENABLE_STAGED_EXPANSION", True)
    assert v45._stage_core_plants({"day": 6}, _farm(), _tasks(), set()) == []


def test_v45_relocates_catchup_plants_on_day7(monkeypatch) -> None:
    monkeypatch.setattr(v45, "ENABLE_STAGED_EXPANSION", True)
    tasks = _tasks()
    result = v45._stage_core_plants({"day": 7}, _farm(), tasks, set())
    protected = v45._protected_ne_positions(10)
    assert len(result) == len(tasks)
    assert not ({task["pos"] for task in result} & protected)
    assert [task["action"] for task in result] == [task["action"] for task in tasks]


def test_v45_is_inert_when_disabled_or_ne_locked(monkeypatch) -> None:
    tasks = _tasks()
    monkeypatch.setattr(v45, "ENABLE_STAGED_EXPANSION", False)
    assert v45._stage_core_plants({"day": 6}, _farm(), tasks, set()) is tasks
    monkeypatch.setattr(v45, "ENABLE_STAGED_EXPANSION", True)
    farm = _farm()
    farm["unlocked_quadrants"] = ["NW"]
    assert v45._stage_core_plants({"day": 6}, farm, tasks, set()) is tasks


def test_v45_safe_empty_observation() -> None:
    assert v45.agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}

